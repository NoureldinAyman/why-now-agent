import itertools
from dataclasses import replace
from datetime import timedelta

import pytest
from eval_world import NOW, ByCompany, add_case, make_run
from improve_world import ByQuestion, RecordingWriter

from why_now.ai.budget import LOOP, BudgetExceeded, Meter
from why_now.improve.run import run_improvement
from why_now.workspace import Workspace

ADD = {
    "action": "add",
    "question_id": None,
    "question": {
        "id": "l1",
        "text": "Is the company hiring several similar roles?",
        "why": "Many similar ads point to a team being built.",
    },
    "based_on": ["practice:Cora"],
}


class Hostile:
    """Stands in for the hidden instruction tests. It keeps the rules version it was given."""

    def __init__(self, passes: bool = True):
        self.passes = passes
        self.calls: list[int] = []

    def __call__(self, rules) -> bool:
        self.calls.append(rules.version)
        return self.passes


def a_world(
    store,
    settings,
    make_profile,
    *,
    practice,
    check,
    judge,
    final=None,
    floor=1,
    reply=ADD,
    answerer=None,
    **setting_changes,
):
    """A pretend world. `practice`, `check` and `final` say, by company name, what the reviewer
    marked. `judge` says what number the pretend judge gives each company, and `answerer` can
    replace that judge. The check pile needs only `floor` yes answers here, so the loop is ready.
    The pretend writer gives `reply`, and each call costs it 40 cents."""
    settings = settings.model_copy(update={"floor_yes_per_pile": floor, **setting_changes})
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    for name, answer in practice.items():
        add_case(workspace, name, "practice", answer)
    for name, answer in check.items():
        add_case(workspace, name, "check", answer)
    for name, answer in (final or {}).items():
        add_case(workspace, name, "final", answer)
    meter = Meter(store, settings, lambda: NOW)
    writer = RecordingWriter(reply, meter=meter, cost=0.4)
    run = make_run(workspace, profile, settings, quick={n: 0.9 for n in judge}, judge=judge)
    models = replace(run.models, writer=writer)
    if answerer is not None:
        models = replace(models, judge=answerer)
    ticks = itertools.count()  # each reading of the clock is a second later than the last
    run = replace(run, models=models, clock=lambda: NOW + timedelta(seconds=next(ticks)))
    return workspace, run, meter, writer


def test_it_does_not_start_before_the_check_pile_has_enough_yes_answers(
    store, settings, make_profile
):
    _, run, meter, writer = a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "no"},
        check={"Beta": "yes"},
        judge={},
        floor=15,  # the real floor: one yes is far too few
    )

    result = run_improvement(run, meter, Hostile())

    assert result.stop_reason == "not_ready"
    assert result.tries == []
    assert writer.calls == []


def test_it_stops_when_the_loops_share_of_the_budget_is_spent(store, settings, make_profile):
    _, run, meter, writer = a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes"},
        check={"Beta": "yes"},
        judge={"Acme": 0.1, "Beta": 0.9},
    )
    meter.charge(LOOP, settings.loop_budget_usd, "spent already")

    result = run_improvement(run, meter, Hostile())

    assert result.stop_reason == "budget"
    assert writer.calls == []


def test_it_stops_when_the_agent_makes_no_mistakes(store, settings, make_profile):
    workspace, run, meter, writer = a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes", "Cora": "no"},
        check={"Beta": "yes"},
        judge={"Acme": 0.9, "Cora": 0.1, "Beta": 0.9},
    )

    result = run_improvement(run, meter, Hostile())

    assert result.stop_reason == "no_mistakes"
    assert result.tries == []
    assert workspace.tries() == []  # no try, so nothing recorded and nothing spent
    assert writer.calls == []


def one_mistake_world(store, settings, make_profile, **kwargs):
    """The agent says yes to every company. The reviewer marked Cora no, so she is its one
    mistake."""
    names = ["Acme", "Cora", "Beta"]
    return a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes", "Cora": "no"},
        check={"Beta": "yes"},
        judge={n: 0.9 for n in names},
        **kwargs,
    )


def test_a_change_that_names_a_company_is_screened_out_and_still_recorded(
    store, settings, make_profile
):
    naming = {**ADD, "question": {**ADD["question"], "text": "Is Acme hiring several roles?"}}
    workspace, run, meter, writer = one_mistake_world(store, settings, make_profile, reply=naming)
    hostile = Hostile()

    result = run_improvement(run, meter, hostile)

    (record,) = result.tries
    assert record.outcome == "screened_out"
    assert record.screen_problem == "names a company"
    assert record.check_after is None  # nothing was measured
    assert record.cost_usd == pytest.approx(0.4)
    assert workspace.tries() == [record]
    assert workspace.load_rules().version == 0
    assert hostile.calls == []
    assert workspace.tried_mistakes(0) == {"practice:Cora"}
    assert len(writer.calls) == 1  # the same mistake is not asked about again
    assert result.stop_reason == "no_mistakes"


def test_a_change_that_cannot_be_made_is_screened_out(store, settings, make_profile):
    unknown = {**ADD, "action": "edit", "question_id": "nope", "question": {**ADD["question"]}}
    unknown["question"]["id"] = "nope"
    workspace, run, meter, _ = one_mistake_world(store, settings, make_profile, reply=unknown)

    result = run_improvement(run, meter, Hostile())

    (record,) = result.tries
    assert record.outcome == "screened_out"
    assert record.screen_problem is not None
    assert record.screen_problem.startswith("it cannot be applied")


def team_world(store, settings, make_profile, *, learned, **kwargs):
    """The agent says yes to every company, and the new question `l1` fixes the ones the
    reviewer marked no. `learned` gives each company's number on `l1`."""
    names = ["Acme", "Cora", "Beta", "Dina", "Eli"]
    return a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes", "Cora": "no"},
        check={"Beta": "yes", "Dina": "no", "Eli": "no"},
        judge={n: 0.9 for n in names},
        answerer=ByQuestion({"l1": learned}, names),
        **kwargs,
    )


HELPS = {"Acme": 0.9, "Cora": 0.1, "Beta": 0.9, "Dina": 0.1, "Eli": 0.1}


def test_a_change_that_helps_is_kept_and_the_rules_are_saved(store, settings, make_profile):
    workspace, run, meter, _ = team_world(store, settings, make_profile, learned=HELPS)
    hostile = Hostile(passes=True)

    result = run_improvement(run, meter, hostile)

    (record,) = result.tries
    assert record.outcome == "kept"
    assert record.check_before is not None and record.check_after is not None
    assert (record.check_before.correct, record.check_after.correct) == (1, 3)
    assert record.cost_usd == pytest.approx(0.4)
    assert (record.rules_version_before, record.rules_version_after) == (0, 1)
    rules = workspace.load_rules()
    assert rules.version == 1 and [q.id for q in rules.questions] == ["l1"]
    assert hostile.calls == [1]  # run once, with the new rules
    assert result.stop_reason == "no_mistakes"  # the new rules fixed the one mistake


def test_a_change_that_makes_no_difference_is_a_tie_and_is_discarded(store, settings, make_profile):
    same = {name: 0.9 for name in HELPS}
    workspace, run, meter, _ = team_world(store, settings, make_profile, learned=same)
    hostile = Hostile()

    result = run_improvement(run, meter, hostile)

    (record,) = result.tries
    assert record.outcome == "discarded"
    assert "check pile score did not rise" in record.reasons
    assert workspace.load_rules().version == 0
    assert hostile.calls == []  # a change that fails on the scores costs no hidden tests


def test_a_change_that_makes_the_practice_pile_worse_is_discarded(store, settings, make_profile):
    hurts_practice = {**HELPS, "Acme": 0.1}  # Acme is a yes the new question would lose
    workspace, run, meter, _ = team_world(store, settings, make_profile, learned=hurts_practice)
    hostile = Hostile()

    result = run_improvement(run, meter, hostile)

    (record,) = result.tries
    assert record.outcome == "discarded"
    assert "practice pile got worse" in record.reasons
    assert hostile.calls == []


def test_a_change_that_fails_the_hidden_tests_is_discarded(store, settings, make_profile):
    workspace, run, meter, _ = team_world(store, settings, make_profile, learned=HELPS)
    hostile = Hostile(passes=False)

    result = run_improvement(run, meter, hostile)

    (record,) = result.tries
    assert record.outcome == "discarded"
    assert record.reasons == ["hostile tests failed"]
    assert hostile.calls == [1]
    assert workspace.load_rules().version == 0


def many_mistakes(store, settings, make_profile, **setting_changes):
    """Five practice mistakes, and a writer that blames a different one each time. The new
    questions change nothing, so every try is discarded."""
    names = ["Acme", "Cora", "Dora", "Fay", "Gus", "Kit", "Beta", "Hal", "Ivy", "Jon"]
    replies = [
        {
            **ADD,
            "question": {**ADD["question"], "id": f"l{i}"},
            "based_on": [f"practice:{who}"],
        }
        for i, who in enumerate(["Cora", "Dora", "Fay", "Gus", "Kit"], start=1)
    ]
    return a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes", "Cora": "no", "Dora": "no", "Fay": "no", "Gus": "no", "Kit": "no"},
        check={"Beta": "yes", "Hal": "yes"},
        judge={n: 0.9 for n in names},
        reply=replies,
        **setting_changes,
    )


def test_a_run_stops_after_three_tries(store, settings, make_profile):
    workspace, run, meter, writer = many_mistakes(store, settings, make_profile)

    result = run_improvement(run, meter, Hostile())

    assert len(result.tries) == 3
    assert result.stop_reason == "run_limit"
    assert len(writer.calls) == 3


def test_the_check_pile_is_used_up_until_new_companies_join(store, settings, make_profile):
    workspace, run, meter, _ = many_mistakes(
        store,
        settings,
        make_profile,
        tries_per_check_pile=2,
        new_check_companies=2,
        tries_per_run=9,
    )
    first = run_improvement(run, meter, Hostile())

    assert len(first.tries) == 2
    assert first.stop_reason == "check_pile_used_up"

    add_case(workspace, "Ivy", "check", "yes")
    add_case(workspace, "Jon", "check", "yes")
    second = run_improvement(run, meter, Hostile())

    assert len(second.tries) == 2  # two more were allowed, once two new companies had joined
    assert second.stop_reason == "check_pile_used_up"
    assert len(workspace.tries()) == 4


def test_the_ai_is_never_shown_a_check_or_final_company(store, settings, make_profile):
    names = ["Acme", "Cora", "Beta", "Checkco", "Finalco"]
    workspace, run, meter, writer = a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes", "Cora": "no"},
        check={"Beta": "yes", "Checkco": "no"},  # the agent is wrong about Checkco
        final={"Finalco": "no"},  # and about Finalco
        judge={n: 0.9 for n in names},
    )

    result = run_improvement(run, meter, Hostile())

    assert len(result.tries) >= 1
    shown = writer.all_prompts()
    assert "Cora" in shown  # a practice mistake is shown
    for hidden in ("Checkco", "Finalco", "Beta"):
        assert hidden not in shown


class WatchedJudge(ByCompany):
    """A pretend judge that remembers every text it was asked about."""

    def __init__(self, by_company):
        super().__init__(by_company)
        self.asked: list[str] = []

    def answer(self, state, questions, category):
        self.asked.append(state)
        return super().answer(state, questions, category)


class PaidJudge:
    """Wraps a pretend judge so each answer is charged to the loop, as a real call would be."""

    def __init__(self, inner, meter, cost):
        self.model = inner.model
        self.answer_key = inner.answer_key
        self.inner, self.meter, self.cost = inner, meter, cost
        self.calls = 0

    def answer(self, state, questions, category):
        self.calls += 1
        self.meter.charge(category, self.cost, "pretend call")
        return self.inner.answer(state, questions, category)


class OutOfMoney:
    """A pretend judge whose money has run out."""

    model = answer_key = "broke"

    def answer(self, state, questions, category):
        raise BudgetExceeded("the loop's share is spent")


def test_with_no_mistakes_the_check_pile_is_not_even_scored(store, settings, make_profile):
    judge = WatchedJudge({"Acme": 0.9, "Cora": 0.1, "Beta": 0.9})
    workspace, run, meter, _ = a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes", "Cora": "no"},
        check={"Beta": "yes"},
        judge={"Acme": 0.9, "Cora": 0.1, "Beta": 0.9},
        answerer=judge,
    )

    result = run_improvement(run, meter, Hostile())

    assert result.stop_reason == "no_mistakes"
    assert judge.asked  # the practice pile was scored, to look for mistakes
    assert not any("Beta" in text for text in judge.asked)  # and the check pile was not


def test_a_try_costs_the_scoring_its_round_needed_as_well_as_the_proposal(
    store, settings, make_profile
):
    workspace, run, meter, _ = team_world(store, settings, make_profile, learned=HELPS)
    paid = PaidJudge(run.models.judge, meter, cost=0.01)
    run = replace(run, models=replace(run.models, judge=paid))

    result = run_improvement(run, meter, Hostile())

    (record,) = result.tries
    assert paid.calls > 0
    assert record.cost_usd == pytest.approx(0.4 + 0.01 * paid.calls)


def test_running_out_of_money_while_scoring_stops_the_run_cleanly(store, settings, make_profile):
    workspace, run, meter, writer = a_world(
        store,
        settings,
        make_profile,
        practice={"Acme": "yes", "Cora": "no"},
        check={"Beta": "yes"},
        judge={"Acme": 0.9, "Cora": 0.9, "Beta": 0.9},
        answerer=OutOfMoney(),
    )

    result = run_improvement(run, meter, Hostile())

    assert result.stop_reason == "budget"
    assert result.tries == []
    assert writer.calls == []


def test_a_try_cut_short_by_the_budget_is_not_recorded_and_is_asked_again(
    store, settings, make_profile
):
    class RunsOutOfMoney:
        """The hidden tests, with the money running out part-way through them."""

        def __call__(self, rules) -> bool:
            raise BudgetExceeded("the loop's share is spent")

    workspace, run, meter, _ = team_world(store, settings, make_profile, learned=HELPS)

    result = run_improvement(run, meter, RunsOutOfMoney())

    assert result.stop_reason == "budget"
    assert result.tries == [] and workspace.tries() == []
    assert workspace.tried_mistakes(0) == set()  # so the next run asks about them again
    assert workspace.load_rules().version == 0
