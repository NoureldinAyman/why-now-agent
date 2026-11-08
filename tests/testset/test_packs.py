from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from why_now.ai import BadModelOutput, ResearchStep
from why_now.ai.budget import BudgetExceeded, Meter
from why_now.domain import CaseRecord, Company, JobAd
from why_now.pipeline.reader import PageReader
from why_now.settings import Settings
from why_now.testset.packs import build_packs, new_case
from why_now.tracing import LocalLogTracer, UnitCounter
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def company(key: str) -> Company:
    ad = JobAd(
        source="greenhouse",
        board=key,
        ad_id="1",
        company_name=key.title(),
        title="Sales Rep",
        location="Cairo",
        country="EG",
        language="en",
        text="Sell things.",
        url=f"https://jobs.test/{key}/1",
        published_at=NOW - timedelta(days=1),
        first_seen=date(2026, 11, 5),
    )
    return Company(key=key, name=key.title(), ads=[ad], total_open_jobs=3)


class CountingModel:
    """Says it is done at once, counting each call. Can fail for some companies."""

    model = "counting"

    def __init__(self, fail_for: frozenset[str] = frozenset(), on_step=None):
        self.calls = 0
        self.fail_for = fail_for
        self.on_step = on_step

    def step(self, conversation: list[dict], category: str) -> ResearchStep:
        self.calls += 1
        if self.on_step:
            self.on_step()
        if any(f"company {k.title()} " in conversation[0]["content"] for k in self.fail_for):
            raise BadModelOutput("refused")
        return ResearchStep(read_urls=[], searches_used=0, done=True)


def unused_reader(settings) -> PageReader:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no page should be read")

    return PageReader(
        httpx.Client(trust_env=False, transport=httpx.MockTransport(refuse)), settings
    )


@pytest.fixture
def workspace(store, make_profile):
    return Workspace(store, make_profile().id)


@pytest.fixture
def profile(workspace, make_profile):
    return make_profile(id=workspace.profile_id)


@pytest.fixture
def tracer(store, settings, tmp_path):
    return LocalLogTracer(
        tmp_path / "traces", UnitCounter(store, settings, lambda: NOW), lambda: NOW
    )


def picked(workspace, profile, *keys: str) -> list[CaseRecord]:
    for key in keys:
        workspace.save_case(new_case(profile.id, company(key), 42, Settings()), company(key))
    return workspace.cases()


def build(workspace, profile, model, settings, tracer):
    return build_packs(
        workspace.cases(),
        workspace,
        profile,
        model,
        unused_reader(settings),
        settings,
        tracer,
        clock=lambda: NOW,
    )


def test_each_case_gets_a_saved_pack(workspace, profile, settings, tracer):
    picked(workspace, profile, "acme", "globex")
    result = build(workspace, profile, CountingModel(), settings, tracer)
    assert result.built == 2 and result.stopped is None
    for case in workspace.cases():
        assert case.pack_id is not None
        pack = workspace.load_pack(case.pack_id)
        assert pack is not None and pack.company_key == case.company_key


def test_rerun_resumes_without_paying_twice(workspace, profile, settings, tracer):
    picked(workspace, profile, "acme", "globex")
    model = CountingModel()
    build(workspace, profile, model, settings, tracer)
    packs = {c.case_id: c.pack_id for c in workspace.cases()}
    again = build(workspace, profile, model, settings, tracer)
    assert model.calls == 2
    assert again.built == 0 and again.already_built == 2
    assert {c.case_id: c.pack_id for c in workspace.cases()} == packs


def test_a_saved_pack_is_frozen(workspace, profile, settings, tracer):
    picked(workspace, profile, "acme")
    build(workspace, profile, CountingModel(), settings, tracer)
    pack = workspace.load_pack(workspace.cases()[0].pack_id or "")
    assert pack is not None
    with pytest.raises(ValueError, match="frozen"):
        workspace.save_pack(pack.model_copy(update={"research_steps": 9}))


def test_one_time_flag_is_set_during_and_cleared_after(workspace, profile, settings, tracer):
    seen: list[bool] = []
    picked(workspace, profile, "acme")
    model = CountingModel(on_step=lambda: seen.append(workspace.one_time_research_active()))
    assert not workspace.one_time_research_active()
    build(workspace, profile, model, settings, tracer)
    assert seen == [True]
    assert not workspace.one_time_research_active()


def test_the_flag_is_cleared_even_when_the_build_breaks(workspace, profile, settings, tracer):
    def boom():
        raise KeyboardInterrupt

    picked(workspace, profile, "acme")
    with pytest.raises(KeyboardInterrupt):
        build(workspace, profile, CountingModel(on_step=boom), settings, tracer)
    assert not workspace.one_time_research_active()


def test_budget_stop_saves_progress_and_says_so(workspace, profile, settings, tracer, store):
    meter = Meter(store, settings, lambda: NOW)

    def spend():
        meter.ensure("test_cases")
        meter.charge("test_cases", settings.budget_limit_usd, "one costly call")

    picked(workspace, profile, "acme", "globex", "initech")
    result = build(workspace, profile, CountingModel(on_step=spend), settings, tracer)
    assert result.built == 1
    assert result.stopped is not None and "limit" in result.stopped
    assert result.left == 2
    assert sum(c.pack_id is not None for c in workspace.cases()) == 1
    assert workspace.pack_failures() == {}


def test_case_with_a_failed_research_is_recorded_not_lost(workspace, profile, settings, tracer):
    picked(workspace, profile, "acme", "globex")
    result = build(
        workspace, profile, CountingModel(fail_for=frozenset({"acme"})), settings, tracer
    )
    assert result.built == 1 and list(result.failed) == [_case_id(workspace, "acme")]
    assert "refused" in workspace.pack_failures()[_case_id(workspace, "acme")]
    assert sorted(c.company_key for c in workspace.cases()) == ["acme", "globex"]

    # The next run tries it again, and a success clears the failure.
    retry = build(workspace, profile, CountingModel(), settings, tracer)
    assert retry.built == 1 and retry.already_built == 1
    assert workspace.pack_failures() == {}


def _case_id(workspace, key: str) -> str:
    return next(c.case_id for c in workspace.cases() if c.company_key == key)


def test_a_case_keeps_the_seed_and_the_company_it_was_picked_with(workspace, profile):
    picked(workspace, profile, "acme")
    case = workspace.cases()[0]
    assert case.seed == 42 and case.pack_id is None and case.profile_id == profile.id
    assert workspace.case_company(case.case_id) == company("acme")


def test_picks_are_recorded_with_their_seed(workspace):
    workspace.record_pick(seed=42, n=10, picked=["acme"], at=NOW)
    workspace.record_pick(seed=7, n=5, picked=[], at=NOW)
    assert [(p.seed, p.n) for p in workspace.picks()] == [(42, 10), (7, 5)]


def test_cases_and_packs_are_kept_per_profile(store, workspace, profile):
    picked(workspace, profile, "acme")
    assert Workspace(store, "other").cases() == []


def test_budget_exceeded_before_the_first_case_builds_nothing(workspace, profile, settings, tracer):
    def stop():
        raise BudgetExceeded("monthly limit of $70 reached")

    picked(workspace, profile, "acme")
    result = build(workspace, profile, CountingModel(on_step=stop), settings, tracer)
    assert result.built == 0 and result.left == 1 and result.stopped is not None


def test_cases_left_counts_only_those_still_without_a_pack(workspace, profile, settings, tracer):
    def stop():
        raise BudgetExceeded("monthly limit of $70 reached")

    picked(workspace, profile, "acme")
    build(workspace, profile, CountingModel(), settings, tracer)
    picked(workspace, profile, "globex")
    by_key = {c.company_key: c for c in workspace.cases()}
    result = build_packs(
        [by_key["globex"], by_key["acme"]],
        workspace,
        profile,
        CountingModel(on_step=stop),
        unused_reader(settings),
        settings,
        tracer,
        clock=lambda: NOW,
    )
    assert result.left == 1


def test_one_profile_finishing_does_not_end_another_profiles_pause(store):
    first, second = Workspace(store, "first"), Workspace(store, "second")
    first.set_one_time_research(True)
    second.set_one_time_research(True)
    first.set_one_time_research(False)
    assert first.one_time_research_active() and second.one_time_research_active()
    second.set_one_time_research(False)
    assert not first.one_time_research_active()
