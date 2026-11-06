from datetime import UTC, datetime

import pytest

from why_now.ai import BadModelOutput
from why_now.domain import Answer, EvidencePack, FitQuestion, LearnedQuestion, RulesFile, Source
from why_now.pipeline.judge import (
    CompanyFailed,
    all_questions,
    answer_questions,
    choose_cutoff,
    combine,
)
from why_now.workspace import Workspace

REQUIRED = FitQuestion(id="r", text="Does it sell to businesses?", kind="required")
SUPPORTING = FitQuestion(id="s", text="Is the sales team growing?")
AGAINST = FitQuestion(id="a", text="Does it already use a tool like this?", direction="against")


def answers(**probabilities: float) -> list[Answer]:
    ids = {"required": "r", "supporting": "s", "against": "a"}
    return [Answer(question_id=ids[k], probability=p, model="m") for k, p in probabilities.items()]


@pytest.fixture
def questions() -> list[FitQuestion]:
    return [REQUIRED, SUPPORTING]


def test_failed_required_question_is_always_a_no(questions, settings):
    v = combine(questions, answers(required=0.2, supporting=0.99), 0.5, settings)
    assert v.yes is False


def test_supporting_answer_can_move_a_company_to_yes(questions, settings):
    assert combine(questions, answers(required=0.9, supporting=0.8), 0.5, settings).yes is True
    assert combine(questions, answers(required=0.9, supporting=0.3), 0.5, settings).yes is False


def test_strength_is_the_mean_of_supporting_answers(settings):
    qs = [REQUIRED, SUPPORTING, FitQuestion(id="s2", text="Is it hiring its first salesperson?")]
    given = answers(required=0.9, supporting=0.8) + [
        Answer(question_id="s2", probability=0.4, model="m")
    ]
    v = combine(qs, given, 0.5, settings)
    assert v.strength == pytest.approx(0.6)
    assert v.yes is True


def test_against_question_counts_the_other_way(settings):
    qs = [REQUIRED, AGAINST]
    assert combine(qs, answers(required=0.9, against=0.1), 0.5, settings).strength == 0.9
    assert combine(qs, answers(required=0.9, against=0.9), 0.5, settings).yes is False


def test_required_against_question_must_be_a_no(settings):
    deal_breaker = FitQuestion(
        id="r", text="Is it a public body?", kind="required", direction="against"
    )
    assert combine([deal_breaker], answers(required=0.1), 0.5, settings).yes is True
    assert combine([deal_breaker], answers(required=0.9), 0.5, settings).yes is False


def test_no_supporting_questions_means_required_decides(settings):
    v = combine([REQUIRED], answers(required=0.6), 0.99, settings)
    assert v.strength == 1
    assert v.yes is True


def test_required_question_passes_at_the_setting(settings):
    strict = settings.model_copy(update={"required_pass": 0.7})
    assert combine([REQUIRED], answers(required=0.6), 0.5, strict).yes is False
    assert combine([REQUIRED], answers(required=0.7), 0.5, strict).yes is True


def test_a_missing_answer_is_never_counted_as_a_no(questions, settings):
    with pytest.raises(ValueError):
        combine(questions, answers(required=0.9), 0.5, settings)


Q1 = FitQuestion(id="q1", text="Does it sell to businesses?")
Q2 = FitQuestion(id="q2", text="Is the sales team growing?")
Q3 = FitQuestion(id="q3", text="Is it hiring its first salesperson?")


class CountingAnswerer:
    """Answers every question with 0.7 and records which question ids each call asked."""

    def __init__(self, model: str = "model-a"):
        self.model = model
        self.asked: list[list[str]] = []
        self.states: list[str] = []

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        self.asked.append([q.id for q in questions])
        self.states.append(state)
        return [Answer(question_id=q.id, probability=0.7, model=self.model) for q in questions]


class FlakyAnswerer:
    """Gives `bad` unusable replies first, then good ones."""

    model = "model-a"

    def __init__(self, bad: int, reply: str = "missing"):
        self.bad = bad
        self.reply = reply
        self.calls = 0

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        self.calls += 1
        if self.calls <= self.bad:
            if self.reply == "raise":
                raise BadModelOutput("refused")
            if self.reply == "out_of_range":
                return [
                    Answer(question_id=q.id, probability=1.5, model=self.model) for q in questions
                ]
            return []
        return [Answer(question_id=q.id, probability=0.4, model=self.model) for q in questions]


@pytest.fixture
def pack() -> EvidencePack:
    return EvidencePack(
        pack_id="pack-1",
        profile_id="p",
        company_key="acme",
        company_name="Acme",
        created_at=datetime(2026, 11, 5, tzinfo=UTC),
        sources=[
            Source(
                id="ad-1",
                kind="job_ad",
                url="https://example.com/1",
                text="We are hiring our first account executive.",
                fetched_at=datetime(2026, 11, 5, tzinfo=UTC),
            )
        ],
        relevant_ad_count=1,
        total_open_jobs=12,
        research_steps=0,
    )


@pytest.fixture
def workspace(store) -> Workspace:
    return Workspace(store, profile_id="p")


def test_saved_answers_are_reused_so_only_a_new_question_is_paid_for(workspace, pack):
    counting = CountingAnswerer()
    answer_questions(pack, [Q1, Q2], counting, workspace, "judge")
    got = answer_questions(pack, [Q1, Q2, Q3], counting, workspace, "judge")
    assert counting.asked == [["q1", "q2"], ["q3"]]
    assert [(a.question_id, a.probability) for a in got] == [("q1", 0.7), ("q2", 0.7), ("q3", 0.7)]


def test_nothing_is_asked_when_every_answer_is_saved(workspace, pack):
    counting = CountingAnswerer()
    answer_questions(pack, [Q1], counting, workspace, "judge")
    answer_questions(pack, [Q1], counting, workspace, "judge")
    assert counting.asked == [["q1"]]


def test_editing_a_question_asks_again(workspace, pack):
    counting = CountingAnswerer()
    answer_questions(pack, [Q1], counting, workspace, "judge")
    edited = Q1.model_copy(update={"text": "Does it sell mostly to businesses?"})
    answer_questions(pack, [edited], counting, workspace, "judge")
    new_meaning = Q1.model_copy(update={"yes_means": "Most of its customers are businesses."})
    answer_questions(pack, [new_meaning], counting, workspace, "judge")
    # The model is shown the id as the question's label, so a new id is a new question.
    renamed = Q1.model_copy(update={"id": "sells_to_businesses"})
    answer_questions(pack, [renamed], counting, workspace, "judge")
    assert counting.asked == [["q1"], ["q1"], ["q1"], ["sells_to_businesses"]]


def test_kind_and_direction_can_change_without_asking_again(workspace, pack):
    counting = CountingAnswerer()
    answer_questions(pack, [Q1], counting, workspace, "judge")
    moved = Q1.model_copy(update={"kind": "required", "direction": "against"})
    got = answer_questions(pack, [moved], counting, workspace, "judge")
    assert counting.asked == [["q1"]]
    assert [a.probability for a in got] == [0.7]


def test_changing_the_model_asks_again(workspace, pack):
    answer_questions(pack, [Q1], CountingAnswerer("model-a"), workspace, "judge")
    other = CountingAnswerer("model-b")
    answer_questions(pack, [Q1], other, workspace, "judge")
    assert other.asked == [["q1"]]


def test_the_model_sees_the_evidence_pack(workspace, pack):
    counting = CountingAnswerer()
    answer_questions(pack, [Q1], counting, workspace, "judge")
    assert "We are hiring our first account executive." in counting.states[0]
    assert "Acme" in counting.states[0]


@pytest.mark.parametrize("reply", ["missing", "out_of_range", "raise"])
def test_missing_answer_gets_a_retry_then_raises_company_failed(workspace, pack, reply):
    flaky = FlakyAnswerer(bad=2, reply=reply)
    with pytest.raises(CompanyFailed):
        answer_questions(pack, [Q1], flaky, workspace, "judge")
    assert flaky.calls == 2


def test_a_good_retry_is_used_and_saved(workspace, pack):
    flaky = FlakyAnswerer(bad=1)
    got = answer_questions(pack, [Q1], flaky, workspace, "judge")
    assert [a.probability for a in got] == [0.4]
    assert flaky.calls == 2
    counting = CountingAnswerer()
    answer_questions(pack, [Q1], counting, workspace, "judge")
    assert counting.asked == []


def strength_row(strength: float, reviewer_yes: bool) -> tuple[list[Answer], bool]:
    return [Answer(question_id="s", probability=strength, model="m")], reviewer_yes


def test_cutoff_uses_the_given_rows_and_picks_the_best_score(settings):
    rows = [
        strength_row(0.9, True),
        strength_row(0.8, True),
        strength_row(0.6, False),
        strength_row(0.4, True),
        strength_row(0.2, False),
    ]
    # Worked by hand: any cut-off above 0.6 and up to 0.8 gives 2 right yeses and
    # none wrong (F0.5 0.91), the best. The lowest such point on the grid is 0.65.
    assert choose_cutoff(rows, [SUPPORTING], settings) == 0.65
    # Different rows, different cut-off: without the wrong yes at 0.6, anything
    # above 0.2 and up to 0.4 is right every time, and the lowest such point is 0.25.
    assert choose_cutoff(rows[:2] + rows[3:], [SUPPORTING], settings) == 0.25


def test_cutoff_takes_the_lowest_value_on_a_tie(settings):
    rows = [strength_row(0.9, True), strength_row(0.5, True)]
    assert choose_cutoff(rows, [SUPPORTING], settings) == 0


def test_cutoff_follows_the_step_setting(settings):
    rows = [strength_row(0.9, True), strength_row(0.3, False)]
    assert choose_cutoff(rows, [SUPPORTING], settings) == 0.35
    coarse = settings.model_copy(update={"cutoff_step": 0.25})
    assert choose_cutoff(rows, [SUPPORTING], coarse) == 0.5


def test_cutoff_grid_always_reaches_one(settings):
    # Only a strength of exactly 1 is a right yes, and 0.3 steps stop at 0.9 before 1.
    rows = [strength_row(1.0, True), strength_row(0.95, False)]
    uneven = settings.model_copy(update={"cutoff_step": 0.3})
    assert choose_cutoff(rows, [SUPPORTING], uneven) == 1


def test_cutoff_needs_rows(settings):
    with pytest.raises(ValueError):
        choose_cutoff([], [SUPPORTING], settings)


def test_all_questions_are_the_profile_then_the_rules_file(make_profile):
    profile = make_profile()
    learned = LearnedQuestion(id="l1", text="Does it sell abroad?", why="Wrong yeses sold locally.")
    rules = RulesFile(profile_id=profile.id, version=3, questions=[learned])
    assert [q.id for q in all_questions(profile, rules)] == ["f1", "l1"]


def test_all_questions_refuses_another_profiles_rules(make_profile):
    with pytest.raises(ValueError):
        all_questions(make_profile(), RulesFile(profile_id="someone-else"))


def test_all_questions_refuses_a_repeated_id(make_profile):
    profile = make_profile()
    clash = LearnedQuestion(id="f1", text="Does it sell abroad?", why="A reason.")
    with pytest.raises(ValueError):
        all_questions(profile, RulesFile(profile_id=profile.id, questions=[clash]))


def test_rules_and_cutoff_are_kept_per_profile(store):
    ws = Workspace(store, profile_id="p")
    assert ws.load_rules() == RulesFile(profile_id="p")
    rules = RulesFile(profile_id="p", version=1)
    ws.save_rules(rules)
    assert Workspace(store, profile_id="p").load_rules() == rules
    assert Workspace(store, profile_id="q").load_rules().version == 0
    assert ws.cutoff("model-a") is None
    ws.save_cutoff("model-a", 0.65)
    assert ws.cutoff("model-a") == 0.65
    assert ws.cutoff("model-b") is None
