import threading
from datetime import UTC, date, datetime, timedelta

import pytest

from why_now.domain import JobAd
from why_now.pipeline.read import read_all
from why_now.sources import BoardFailed
from why_now.sources.boards import BoardList
from why_now.store.local import LocalStore
from why_now.workspace import Workspace

TODAY = date(2026, 11, 5)


def ad(board: str, ad_id: str, today: date, source: str = "s") -> JobAd:
    return JobAd(
        source=source, board=board, ad_id=ad_id, company_name=board.title(),
        title="Sales Rep", location="Berlin", country=None, language="en",
        text="Sell things.", url=f"https://example.test/{board}/{ad_id}",
        published_at=datetime(2026, 11, 1, tzinfo=UTC), first_seen=today,
    )  # fmt: skip


class FakeSource:
    """A job source whose pages either answer with fixed ads or fail."""

    def __init__(self, name="s", ads: dict[str, list[str]] | None = None, fail=()):
        self.name = name
        self.ads = ads or {}
        self.fail = set(fail)
        self.threads: set[str] = set()

    def fetch_ads(self, board: str, today: date) -> list[JobAd]:
        self.threads.add(threading.current_thread().name)
        if board in self.fail:
            raise BoardFailed(f"{board} is down")
        return [ad(board, i, today, self.name) for i in self.ads.get(board, [])]


class CountingStore(LocalStore):
    def __init__(self, root):
        super().__init__(root)
        self.writes: dict[str, int] = {}

    def put(self, collection, key, doc):
        self.writes[collection] = self.writes.get(collection, 0) + 1
        super().put(collection, key, doc)


@pytest.fixture
def workspace(store) -> Workspace:
    return Workspace(store)


def read(sources, workspace, today=TODAY, outage_share=0.9, **kw):
    boards = {s.name: BoardList(workspace, s.name, sorted(s.ads.keys() | s.fail)) for s in sources}
    return read_all(sources, boards, workspace, today, outage_share=outage_share, **kw)


def test_ads_are_saved_and_counted_as_new(workspace):
    r = read([FakeSource(ads={"acme": ["1", "2"]})], workspace)
    assert [a.ad_id for a in r.ads] == ["1", "2"]
    assert r.new_ad_count == 2
    assert [a.ad_id for a in workspace.load_board_ads("s", "acme") or []] == ["1", "2"]


def test_first_seen_is_kept_across_reads(workspace):
    read([FakeSource(ads={"acme": ["1"]})], workspace)
    r = read([FakeSource(ads={"acme": ["1", "2"]})], workspace, today=TODAY + timedelta(days=3))
    assert {a.ad_id: a.first_seen for a in r.ads} == {"1": TODAY, "2": TODAY + timedelta(days=3)}
    assert r.new_ad_count == 1


def test_ad_list_is_only_written_when_it_changed(tmp_path):
    store = CountingStore(tmp_path)
    read([FakeSource(ads={"acme": ["1"]})], Workspace(store))
    writes = store.writes["board_ads"]
    read([FakeSource(ads={"acme": ["1"]})], Workspace(store), today=TODAY + timedelta(days=1))
    assert store.writes["board_ads"] == writes


def test_one_failing_board_does_not_stop_the_read(workspace):
    r = read([FakeSource(ads={"a": ["1"]}, fail=["b"])], workspace)
    assert r.failed_boards == {"s": ["b"]}
    assert r.ads
    assert r.outage_sources == []
    assert BoardList(workspace, "s", ["b"]).health("b").failing_days == 1


def test_whole_source_outage_is_reported_and_no_board_is_punished(workspace):
    # Review Focus 1: a job source down for a whole day.
    r = read([FakeSource(fail=["a", "b"])], workspace)
    assert r.outage_sources == ["s"]
    assert BoardList(workspace, "s", ["a", "b"]).health("a").failing_days == 0


def test_a_share_of_failures_counts_as_an_outage(workspace):
    pages = {str(i): ["1"] for i in range(1)}
    r = read([FakeSource(ads=pages, fail=[f"x{i}" for i in range(9)])], workspace)
    assert r.outage_sources == ["s"]
    assert BoardList(workspace, "s", ["x0"]).health("x0").failing_days == 0


def test_below_the_share_failures_count_against_boards(workspace):
    pages = {str(i): ["1"] for i in range(2)}
    r = read([FakeSource(ads=pages, fail=[f"x{i}" for i in range(8)])], workspace)
    assert r.outage_sources == []
    assert BoardList(workspace, "s", ["x0"]).health("x0").failing_days == 1


def test_a_board_name_the_workspace_cannot_store_fails_alone(workspace):
    r = read([FakeSource(ads={"acme": ["1"], "a:b": ["2"]})], workspace)
    assert r.failed_boards == {"s": ["a:b"]}
    assert [a.board for a in r.ads] == ["acme"]


def test_open_jobs_are_counted_per_company_across_sources(workspace):
    r = read(
        [FakeSource("g", ads={"Acme-Inc": ["1", "2"]}), FakeSource("l", ads={"acmeinc": ["3"]})],
        workspace,
    )
    assert r.open_job_counts == {"acmeinc": 3}


def test_sources_are_read_side_by_side(workspace):
    g, lv = FakeSource("g", ads={"a": ["1"]}), FakeSource("l", ads={"b": ["1"]})
    read([g, lv], workspace)
    assert g.threads != lv.threads


def test_progress_is_reported_per_board(workspace):
    seen = []
    read([FakeSource(ads={"a": ["1"]}, fail=["b"])], workspace, on_progress=seen.append)
    assert sorted((p.board, p.ok) for p in seen) == [("a", True), ("b", False)]
