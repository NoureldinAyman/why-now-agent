from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from why_now.ai import Models, ResearchStep
from why_now.ai.budget import TEST_CASES, Meter
from why_now.domain import JobAd
from why_now.pipeline.reader import PageReader
from why_now.run_context import RunContext
from why_now.testset.packs import prepare
from why_now.testset.piles import pile_for
from why_now.tracing import LocalLogTracer, UnitCounter
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def ad(board: str, days_ago: int, title: str = "Sales Rep") -> JobAd:
    return JobAd(
        source="greenhouse", board=board, ad_id="1", company_name=board.title(), title=title,
        location="Cairo", country=None, language=None, text="Sell things.",
        url=f"https://jobs.test/{board}/1", published_at=NOW - timedelta(days=days_ago),
        first_seen=date(2026, 11, 1),
    )  # fmt: skip


class CountingResearch:
    model = "counting"
    answer_key = model

    def __init__(self):
        self.calls = 0

    def step(self, conversation: list[dict], category: str) -> ResearchStep:
        self.calls += 1
        return ResearchStep(read_urls=[], searches_used=0, done=True)


class Idle:
    """A model the prepare step must never use."""

    model = answer_key = "idle"

    def answer(self, state, questions, category):
        raise AssertionError("not used")

    def structured(self, *, system, untrusted, schema, category):
        raise AssertionError("not used")

    def step(self, conversation, category):
        raise AssertionError("not used")


@pytest.fixture
def research() -> CountingResearch:
    return CountingResearch()


@pytest.fixture
def workspace(store, make_profile) -> Workspace:
    return Workspace(store, make_profile().id)


@pytest.fixture
def profile(workspace, make_profile):
    return make_profile(id=workspace.profile_id)


@pytest.fixture
def ctx(store, settings, research, tmp_path) -> RunContext:
    refuse = httpx.MockTransport(lambda r: pytest.fail("no page should be read"))
    meter = Meter(store, settings, lambda: NOW)
    return RunContext(
        settings=settings, store=store, sources=[], boards={},
        models=Models(quick_look=Idle(), judge=Idle(), writer=Idle(), research=research),
        reader=PageReader(httpx.Client(trust_env=False, transport=refuse), settings),
        meter=meter,
        tracer=LocalLogTracer(
            tmp_path / "traces", UnitCounter(store, settings, lambda: NOW), lambda: NOW
        ),
        clock=lambda: NOW,
    )  # fmt: skip


@pytest.fixture
def six_companies(workspace):
    for board in ("acme", "globex", "initech", "hooli", "umbrella", "stark"):
        workspace.save_board_ads("greenhouse", board, [ad(board, 1)])
    workspace.save_board_ads("greenhouse", "old", [ad("old", 30)])  # no ad in the window
    workspace.save_board_ads("greenhouse", "eng", [ad("eng", 1, "Engineer")])  # not relevant


def test_prepare_picks_decides_the_pile_and_researches_each_company(
    ctx, workspace, profile, research, six_companies, settings
):
    result = prepare(ctx, profile, 4, seed=7)
    assert (result.picked, result.eligible, result.built) == (4, 6, 4)
    cases = workspace.cases()
    assert len(cases) == 4 and research.calls == 4
    assert all(c.pack_id and workspace.load_pack(c.pack_id) for c in cases)
    assert {c.company_key: c.pile for c in cases} == {
        c.company_key: pile_for(7, c.company_key, settings) for c in cases
    }
    assert [(p.seed, p.n) for p in workspace.picks()] == [(7, 4)]
    assert not workspace.one_time_research_active()


def test_a_rerun_with_the_same_seed_pays_for_nothing_twice(
    ctx, workspace, profile, research, six_companies
):
    prepare(ctx, profile, 3, seed=5)
    keys = sorted(c.company_key for c in workspace.cases())
    again = prepare(ctx, profile, 3, seed=5)
    assert research.calls == 3
    assert (again.picked, again.built) == (0, 0)
    assert sorted(c.company_key for c in workspace.cases()) == keys
    assert len(workspace.picks()) == 1


def test_a_new_seed_picks_more_companies_never_one_picked_before(
    ctx, workspace, profile, research, six_companies
):
    prepare(ctx, profile, 4, seed=1)
    result = prepare(ctx, profile, 4, seed=2)
    assert result.picked == 2  # only 6 are eligible
    assert len(workspace.cases()) == 6 and research.calls == 6


def test_prepare_stops_cleanly_at_the_budget_and_a_rerun_finishes_without_paying_twice(
    ctx, workspace, profile, research, six_companies, settings
):
    ctx.meter.charge(TEST_CASES, settings.budget_limit_usd, "already spent")
    stopped = prepare(ctx, profile, 3, seed=9)
    assert stopped.built == 0 and stopped.stopped is not None and stopped.left == 3
    assert research.calls == 0
    assert len(workspace.cases()) == 3  # picked and kept, waiting for money
    assert not workspace.one_time_research_active()

    settings_more = settings.model_copy(update={"budget_limit_usd": settings.budget_limit_usd * 2})
    ctx.meter.settings = ctx.settings = settings_more
    resumed = prepare(ctx, profile, 3, seed=9)
    assert (resumed.picked, resumed.built, resumed.stopped) == (0, 3, None)
    assert research.calls == 3 and len(workspace.cases()) == 3


def test_prepare_with_nothing_to_pick_from_says_so(ctx, workspace, profile, research):
    result = prepare(ctx, profile, 3, seed=1)
    assert (result.picked, result.eligible, result.built) == (0, 0, 0)
    assert research.calls == 0
