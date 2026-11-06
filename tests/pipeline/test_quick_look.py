from contextlib import contextmanager
from datetime import UTC, date, datetime
from itertools import count

import pytest

from why_now.ai import BadModelOutput
from why_now.ai.budget import BudgetExceeded
from why_now.domain import Answer, Company, FitQuestion, JobAd
from why_now.pipeline.quick_look import quick_look
from why_now.workspace import Workspace

_ids = count()


def make_company(key: str, text: str = "Join us.", n_ads: int = 1) -> Company:
    ads = [
        JobAd(
            source="greenhouse",
            board=key,
            ad_id=str(next(_ids)),
            company_name=key.title(),
            title="Sales",
            location="Berlin",
            country=None,
            language=None,
            text=text,
            url="https://example.com/x",
            published_at=datetime(2026, 11, 1, tzinfo=UTC),
            first_seen=date(2026, 11, 2),
        )
        for _ in range(n_ads)
    ]
    return Company(key=key, name=key.title(), ads=ads, total_open_jobs=10)


class Handle:
    def __init__(self):
        self.steps: list[str] = []

    def step(self, name, input, output):
        self.steps.append(name)

    def score(self, name, value):
        pass


class Tracer:
    def __init__(self):
        self.handle = Handle()
        self.traces: list[dict] = []

    @contextmanager
    def trace(self, name, **kwargs):
        self.traces.append({"name": name, **kwargs})
        yield self.handle


class ScriptedAnswerer:
    """Answers with a probability picked from the company's text: the text is the probability."""

    def __init__(self, model: str = "fake-1"):
        self.model = model
        self.states: list[str] = []
        self.asked: list[list[str]] = []

    def answer(self, state, questions, category):
        self.states.append(state)
        self.asked.append([q.id for q in questions])
        p = float(next(w for w in state.split() if w.replace(".", "").isdigit()))
        return [Answer(question_id=q.id, probability=p, model=self.model) for q in questions]


@pytest.fixture
def workspace(store) -> Workspace:
    return Workspace(store)


@pytest.fixture
def profile(make_profile):
    return make_profile()


def run(companies, profile, answerer, settings, workspace, tracer=None):
    return quick_look(companies, profile, answerer, settings, workspace, tracer or Tracer())


def test_passes_generously_and_orders_strongest_first(profile, settings, workspace):
    companies = [make_company("a", "0.4"), make_company("b", "0.9"), make_company("c", "0.1")]
    results = run(companies, profile, ScriptedAnswerer(), settings, workspace)
    passed = [r.company_key for r in results if r.passed]
    assert passed == ["b", "a"]  # 0.4 passes the 0.3 cut-off; 0.1 does not
    assert [r.company_key for r in results] == ["b", "a", "c"]
    assert results[0].order > results[1].order > results[2].order


def test_against_questions_count_the_other_way(make_profile, settings, workspace):
    profile = make_profile(
        quick_look_questions=[FitQuestion(id="q1", text="Is it a bank?", direction="against")]
    )
    results = run([make_company("a", "0.9")], profile, ScriptedAnswerer(), settings, workspace)
    assert results[0].passed is False
    assert results[0].order == pytest.approx(0.1)


def test_answers_are_saved_per_model(profile, settings, workspace):
    company = [make_company("a", "0.8")]
    first = ScriptedAnswerer("fake-1")
    run(company, profile, first, settings, workspace)
    run(company, profile, first, settings, workspace)
    assert len(first.asked) == 1  # second run reused the saved answers
    other = ScriptedAnswerer("fake-2")
    run(company, profile, other, settings, workspace)
    assert len(other.asked) == 1  # a new model version asks again


def test_a_failure_is_marked_failed_not_dropped(profile, settings, workspace):
    class Failing(ScriptedAnswerer):
        def answer(self, state, questions, category):
            if "boom" in state:
                raise BadModelOutput("no answer")
            return super().answer(state, questions, category)

    results = run(
        [make_company("a", "boom"), make_company("b", "0.9")],
        profile,
        Failing(),
        settings,
        workspace,
    )
    by_key = {r.company_key: r for r in results}
    assert by_key["a"].failed is True and by_key["a"].passed is False
    assert by_key["b"].passed is True


def test_a_spent_budget_stops_the_run(profile, settings, workspace):
    class Broke(ScriptedAnswerer):
        def answer(self, state, questions, category):
            raise BudgetExceeded("limit")

    with pytest.raises(BudgetExceeded):
        run([make_company("a", "0.9")], profile, Broke(), settings, workspace)


def test_long_ads_are_cut_before_the_model_sees_them(profile, settings, workspace):
    settings = settings.model_copy(update={"max_ad_chars": 100})
    answerer = ScriptedAnswerer()
    run([make_company("a", "0.9 " + "x" * 5000)], profile, answerer, settings, workspace)
    assert "x" * 101 not in answerer.states[0]
    assert len(answerer.states[0]) < 500


def test_one_trace_per_run_with_light_detail(profile, settings, workspace):
    tracer = Tracer()
    run(
        [make_company("a", "0.9"), make_company("b", "0.9")],
        profile,
        ScriptedAnswerer(),
        settings,
        workspace,
        tracer,
    )
    assert len(tracer.traces) == 1
    assert tracer.traces[0]["detail"] == "light"
