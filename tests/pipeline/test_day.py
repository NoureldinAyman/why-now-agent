"""The daily run, tested whole: invented job ads, scripted models, a throwaway profile."""

import re
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
from pydantic import BaseModel

from why_now.ai import BadModelOutput, Models, ResearchStep
from why_now.ai.budget import Meter
from why_now.domain import Answer, Claim, Decision, FitQuestion, JobAd
from why_now.pipeline.brief import BriefDraft
from why_now.pipeline.day import run_day
from why_now.pipeline.reader import PageReader
from why_now.run_context import RunContext
from why_now.sources import BoardFailed
from why_now.sources.boards import BoardList
from why_now.tracing import LocalLogTracer, UnitCounter
from why_now.workspace import Workspace

TODAY = date(2026, 11, 6)
QUOTE = "Sell things at scale"


class Clock:
    """The run's clock. Tests move `day` to pretend time has passed."""

    def __init__(self, day: date = TODAY):
        self.day = day

    def __call__(self) -> datetime:
        return datetime.combine(self.day, time(9), UTC)


def make_ad(board: str, age: int = 1, ad_id: str = "1") -> JobAd:
    published = datetime.combine(TODAY - timedelta(days=age), time(8), UTC)
    return JobAd(
        source="greenhouse",
        board=board,
        ad_id=ad_id,
        company_name=board.title(),
        title="Sales Rep",
        location="Cairo",
        country=None,
        language=None,
        text=f"Join {board}. {QUOTE}.",
        url=f"https://jobs.test/{board}/{ad_id}",
        published_at=published,
        first_seen=TODAY,
    )


class FakeSource:
    """A job source with fixed ads per careers page, which tests may change between days."""

    name = "greenhouse"

    def __init__(self, ads: dict[str, list[JobAd]]):
        self.ads = ads
        self.broken: set[str] = set()

    def fetch_ads(self, board: str, today: date) -> list[JobAd]:
        if board in self.broken:
            raise BoardFailed(f"{board} is down")
        return [a.model_copy(update={"first_seen": today}) for a in self.ads.get(board, [])]


def board_name(state: str) -> str:
    match = re.search(r"Join (\w+)\.", state)
    assert match, state
    return match.group(1)


class FakeAnswerer:
    """Answers each question with a chance of yes that depends on the company and the step."""

    def __init__(self, chance: Callable[[str, str], float]):
        self.model = "fake-answerer"
        self.chance = chance  # (company's board name, category) to probability of yes
        self.calls = 0

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        self.calls += 1
        p = self.chance(board_name(state), category)
        return [Answer(question_id=q.id, probability=p, model=self.model) for q in questions]


def ranked(board: str, category: str) -> float:
    """co0 is the strongest, then co1, and so on, at both the quick look and the judge."""
    number = board.removeprefix("co")
    return 0.95 - 0.005 * int(number) if number.isdigit() else 0.9


class QuoteWriter:
    """Writes a brief that quotes the first job ad in the evidence."""

    model = "fake-writer"

    def __init__(self, quote: str = QUOTE):
        self.quote = quote
        self.calls = 0

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        self.calls += 1
        source = re.search(r"\[(ad-\w+)\]", untrusted)
        assert source
        claim = Claim(text="They are hiring.", quote=self.quote, source_id=source.group(1))
        return schema.model_validate(BriefDraft(why_now=claim, claims=[]).model_dump())


class Crash(BaseException):
    """Stands for the computer stopping. Not an Exception, so no step catches it."""


class CrashingWriter(QuoteWriter):
    def __init__(self, crash_on_call: int):
        super().__init__()
        self.crash_on_call = crash_on_call

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        if self.calls + 1 == self.crash_on_call:
            self.calls += 1
            raise Crash
        return super().structured(
            system=system, untrusted=untrusted, schema=schema, category=category
        )


class CountingResearch:
    """Says it is done at once, counting how many companies were researched."""

    model = "fake-research"

    def __init__(self):
        self.count = 0

    def step(self, conversation: list[dict], category: str) -> ResearchStep:
        self.count += 1
        return ResearchStep(read_urls=[], searches_used=0, done=True)


class RecordingTracer:
    def __init__(self):
        self.traces: list[tuple[str, str]] = []

    @contextmanager
    def trace(self, name, *, profile_id, rules_version, models, detail="full"):
        self.traces.append((name, detail))

        class Handle:
            def step(self, name, input, output): ...
            def score(self, name, value): ...

        yield Handle()


def no_pages(settings) -> PageReader:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no page should be read")

    return PageReader(
        httpx.Client(trust_env=False, transport=httpx.MockTransport(refuse)), settings
    )


class World:
    """Everything a daily run needs, with the fakes kept where the tests can reach them."""

    def __init__(self, store, settings, tmp_path, profile, boards: dict[str, list[JobAd]]):
        self.clock = Clock()
        self.source = FakeSource(boards)
        self.research = CountingResearch()
        self.writer: QuoteWriter = QuoteWriter()
        self.quick = FakeAnswerer(ranked)
        self.judge = FakeAnswerer(ranked)
        self.store = store
        self.settings = settings
        self.profile = profile
        self.workspace = Workspace(store, profile.id)
        self.meter = Meter(store, settings, self.clock)
        self.tracer = LocalLogTracer(
            tmp_path / "traces", UnitCounter(store, settings, self.clock), self.clock
        )
        self.boards = boards

    def context(self) -> RunContext:
        board_list = BoardList(self.workspace, "greenhouse", list(self.boards), self.settings)
        return RunContext(
            settings=self.settings,
            store=self.store,
            sources=[self.source],
            boards={"greenhouse": board_list},
            models=Models(
                quick_look=self.quick, judge=self.judge, writer=self.writer, research=self.research
            ),
            reader=no_pages(self.settings),
            meter=self.meter,
            tracer=self.tracer,
            clock=self.clock,
        )

    def day(self, day: date = TODAY, overrides: dict | None = None):
        self.clock.day = day
        return run_day(self.context(), self.profile, day, overrides)


@pytest.fixture
def profile(make_profile):
    return make_profile(
        fit_questions=[
            FitQuestion(id="f1", text="Is it hiring for itself?", kind="required"),
            FitQuestion(id="f2", text="Is it building a team?"),
        ]
    )


@pytest.fixture
def make_world(store, settings, tmp_path, profile):
    def make(n_companies: int = 15, **kwargs) -> World:
        boards = {f"co{i}": [make_ad(f"co{i}")] for i in range(n_companies)}
        return World(store, settings, tmp_path, profile, boards | kwargs.get("extra", {}))

    return make


def test_day_produces_a_short_list_with_checked_briefs_and_a_more_list(make_world):
    world = make_world(15)
    r = world.day()
    assert len(r.short_list) == 10
    assert all(e.brief for e in r.short_list)
    assert len(r.more_list) == 5
    assert all(e.brief is None and e.pack_id is None for e in r.more_list)
    strengths = [e.strength for e in r.short_list]
    assert strengths == sorted(strengths, reverse=True)
    assert [e.company_key for e in r.short_list] == [f"co{i}" for i in range(10)]
    assert world.research.count == 10  # the rest were never researched


def test_a_day_with_no_good_companies_shows_none(make_world):
    world = make_world(3)
    world.judge.chance = lambda board, category: 0.1  # judged no everywhere
    r = world.day()
    assert r.short_list == [] and r.more_list == []


def test_a_day_with_few_good_companies_shows_few(make_world):
    assert len(make_world(3).day().short_list) == 3


def test_company_with_failed_fact_check_is_dropped_and_recorded(make_world):
    world = make_world(3)
    world.writer = QuoteWriter(quote="a sentence that is in no ad")
    r = world.day()
    assert r.short_list == [] and r.more_list == []
    assert len(r.failed) == 3 and "Co0" in r.failed[0]


def test_clear_quick_look_no_goes_on_no_list(make_world):
    world = make_world(3)
    world.quick.chance = lambda board, category: 0.05 if board == "co1" else 0.9
    r = world.day()
    assert "co1" not in {e.company_key for e in r.short_list + r.more_list}
    assert world.research.count == 2


def test_old_ads_are_not_new(make_world):
    world = make_world(0, extra={"old": [make_ad("old", age=20)], "fresh": [make_ad("fresh")]})
    r = world.day()
    assert [e.company_key for e in r.short_list] == ["fresh"]
    r = world.day(overrides={"new_ad_days": 30})  # the window can be widened for one run
    assert {e.company_key for e in r.short_list} == {"fresh", "old"}


def test_seen_ads_are_not_new(make_world):
    world = make_world(3)
    world.day()
    first = world.research.count
    # The same ads on the second day: nothing is new, so nothing more is paid for.
    r = world.day(TODAY + timedelta(days=1))
    assert world.research.count == first
    assert len(r.short_list) == 3  # still waiting for a decision


def decide(world: World, company_key: str, day: date) -> None:
    saved = world.workspace.save_decision(
        Decision(
            profile_id=world.profile.id,
            company_key=company_key,
            approved=False,
            reason="not for us",
            decided_at=datetime.combine(day, time(10), UTC),
            from_list="short",
        )
    )
    assert saved


def test_a_decided_company_with_a_new_ad_stays_hidden(make_world):
    world = make_world(1)
    world.day()
    decide(world, "co0", TODAY)
    world.boards["co0"].append(make_ad("co0", age=0, ad_id="2"))
    assert world.day(TODAY + timedelta(days=1)).short_list == []


def test_decided_company_stays_hidden_for_90_days(make_world):
    world = make_world(1)
    world.day()
    decide(world, "co0", TODAY)
    for days, listed in [(1, False), (30, False), (89, False), (90, True)]:
        day = TODAY + timedelta(days=days)
        # A new ad each day, as the company keeps hiring.
        world.boards["co0"] = [make_ad("co0", age=0, ad_id=f"new-{days}")]
        world.boards["co0"][0] = world.boards["co0"][0].model_copy(
            update={"published_at": datetime.combine(day, time(8), UTC)}
        )
        r = world.day(day)
        assert bool(r.short_list) is listed, days


def test_marks_do_not_hide_a_company(make_world):
    world = make_world(1)
    # A test case was picked and marked for this company. Marks only record a judgement.
    world.store.put("marks", f"{world.profile.id}/case-1", {"case_id": "case-1", "answer": "no"})
    assert [e.company_key for e in world.day().short_list] == ["co0"]


def test_only_top_12_are_researched(make_world):
    world = make_world(30)
    world.writer = QuoteWriter(quote="nothing in any ad")  # nobody is ever listed
    world.day()
    assert world.research.count == 12


def test_rerun_after_a_crash_does_not_pay_twice(make_world):
    world = make_world(5)
    world.writer = CrashingWriter(crash_on_call=3)
    with pytest.raises(Crash):
        world.day()
    assert world.research.count == 3  # the third company was researched, then the writer stopped
    judged = world.judge.calls
    world.writer = QuoteWriter()
    r = world.day()
    assert world.research.count == 5  # only the two not yet researched were paid for
    assert world.judge.calls == judged + 2
    assert len(r.short_list) == 5


def test_budget_stop_still_reads_and_says_what_was_skipped(make_world):
    world = make_world(4)
    world.meter.charge("brief", world.settings.budget_limit_usd, "already spent")
    r = world.day()
    assert r.skipped
    assert r.costs.stopped
    assert world.research.count == 0
    # The read still ran, so the companies are there for the reviewer to look at.
    assert {e.company_key for e in r.more_list} == {f"co{i}" for i in range(4)}
    assert all(e.strength is None and e.brief is None for e in r.more_list)
    # Nothing was marked seen, so the next day with money tries them again.
    assert world.workspace.seen_ads() == set()


def test_budget_running_out_part_way_keeps_what_was_done(make_world):
    world = make_world(5)
    spend = world.settings.budget_limit_usd

    class SpendingResearch(CountingResearch):
        def step(self, conversation, category):
            if self.count == 3:  # the fourth company's research spends the rest of the money
                world.meter.charge("research", spend, "big")
            return super().step(conversation, category)

    world.research = SpendingResearch()
    r = world.day()
    assert [e.company_key for e in r.short_list] == ["co0", "co1", "co2"]
    assert r.skipped and {e.company_key for e in r.more_list} == {"co3", "co4"}


def test_one_time_research_pauses_daily_research(make_world):
    world = make_world(3)
    world.workspace.set_one_time_research(True)
    r = world.day()
    assert world.research.count == 0
    assert r.skipped and len(r.more_list) == 3


def test_research_judge_and_brief_are_traced_and_quick_look_lightly(make_world):
    world = make_world(1)
    world.tracer = RecordingTracer()
    world.day()
    assert ("research", "full") in world.tracer.traces
    assert ("judge", "full") in world.tracer.traces
    assert ("brief", "full") in world.tracer.traces
    assert ("quick_look", "light") in world.tracer.traces


def test_undecided_companies_carry_over_at_no_cost(make_world):  # Review Focus 2
    world = make_world(15)
    world.day()
    first = world.research.count
    r = world.day(TODAY + timedelta(days=1))
    assert len(r.short_list) <= 10
    assert world.research.count == first  # list is full, so nothing new is paid for


def test_a_decision_frees_a_place_for_a_new_company(make_world):
    world = make_world(10)
    world.day()
    decide(world, "co0", TODAY)
    world.boards["co40"] = [make_ad("co40", age=0)]
    r = world.day(TODAY + timedelta(days=1))
    assert "co0" not in {e.company_key for e in r.short_list}
    assert "co40" in {e.company_key for e in r.short_list}
    assert len(r.short_list) == 10


def test_two_weeks_away_keeps_the_list_within_its_limit(make_world):  # Review Focus 2
    world = make_world(15)
    r = world.day()
    for i in range(1, 14):
        # Each day brings a company with a new ad, and nobody decides anything.
        board = f"co{20 + i}"
        world.boards[board] = [make_ad(board, age=0)]
        world.boards[board][0] = world.boards[board][0].model_copy(
            update={"published_at": datetime.combine(TODAY + timedelta(days=i), time(8), UTC)}
        )
        r = world.day(TODAY + timedelta(days=i))
        assert len(r.short_list) <= 10
    assert len(r.short_list) == 10


def test_short_list_size_can_be_overridden_for_one_run(make_world):
    world = make_world(25)
    r = world.day(overrides={"short_list_size": 5, "new_ad_days": 7})
    assert len(r.short_list) == 5
    assert world.settings.short_list_size == 10  # the setting itself is untouched


def test_a_longer_short_list_is_still_limited_by_daily_research(make_world):
    r = make_world(25).day(overrides={"short_list_size": 20})
    assert len(r.short_list) == 12


def test_only_list_size_and_window_can_be_overridden(make_world):
    with pytest.raises(ValueError, match="research_per_day"):
        make_world(1).day(overrides={"research_per_day": 100})


def test_a_failing_careers_page_is_reported_and_the_day_goes_on(make_world):
    world = make_world(2)
    world.source.broken = {"co1"}
    r = world.day()
    assert [e.company_key for e in r.short_list] == ["co0"]
    assert any("greenhouse" in f for f in r.failed)


def test_a_bad_model_answer_fails_one_company_not_the_day(make_world):
    world = make_world(3)

    class Flaky(FakeAnswerer):
        def answer(self, state, questions, category):
            if board_name(state) == "co1":
                raise BadModelOutput("garbled")
            return super().answer(state, questions, category)

    world.judge = Flaky(ranked)
    r = world.day()
    assert [e.company_key for e in r.short_list] == ["co0", "co2"]
    assert any("Co1" in f for f in r.failed)


def test_costs_come_from_the_meter(make_world):
    world = make_world(1)
    world.meter.charge("research", 3.5, "x")
    assert world.day().costs.spent_usd == 3.5


def test_a_more_list_company_judged_no_later_leaves_the_more_list(make_world):
    world = make_world(15)
    world.day()
    assert "co12" in {e.company_key for e in world.workspace.more_list()}
    decide(world, "co0", TODAY)  # frees a place, so the next company is researched
    world.boards["co12"].append(make_ad("co12", age=0, ad_id="2"))
    world.judge.chance = lambda board, category: 0.1 if board == "co12" else ranked(board, category)
    r = world.day(TODAY + timedelta(days=1))
    assert "co12" not in {e.company_key for e in r.short_list + r.more_list}


def test_a_waiting_company_with_a_new_ad_shows_the_new_ad(make_world):
    world = make_world(3)
    world.day()
    world.boards["co0"].append(make_ad("co0", age=0, ad_id="2"))
    r = world.day(TODAY + timedelta(days=1))
    entry = next(e for e in r.short_list if e.company_key == "co0")
    assert {a.ad_id for a in entry.ads} == {"1", "2"}
    assert world.research.count == 3  # and it was not researched again
