"""The read step: fetch every careers page politely and save its job ads."""

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel

from why_now.domain import JobAd, company_key
from why_now.sources import BoardFailed, JobSource
from why_now.sources.boards import BoardList
from why_now.workspace import Workspace


class ReadResult(BaseModel):
    ads: list[JobAd]
    new_ad_count: int
    failed_boards: dict[str, list[str]]
    outage_sources: list[str]
    open_job_counts: dict[str, int]  # company key to total open jobs


@dataclass(frozen=True)
class BoardProgress:
    source: str
    board: str
    ok: bool
    ad_count: int = 0
    new_ad_count: int = 0  # ads not seen at any earlier read
    error: str = ""


@dataclass
class _SourceResult:
    ads: list[JobAd]
    new: int
    failed: list[str]
    outage: bool


def read_all(
    sources: list[JobSource],
    boards: dict[str, BoardList],
    workspace: Workspace,
    today: date,
    on_progress: Callable[[BoardProgress], None] | None = None,
    *,
    outage_share: float,
) -> ReadResult:
    """Read every source side by side, one thread each, so each stays polite on its own.

    One failing page never stops the read. If at least `outage_share` of a source's
    pages fail, the source is counted as down for the day, and no page moves
    towards being set aside.
    """
    report = on_progress or (lambda progress: None)
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as pool:
        futures = [
            pool.submit(_read_source, s, boards[s.name], workspace, today, report, outage_share)
            for s in sources
        ]
        results = {s.name: f.result() for s, f in zip(sources, futures, strict=True)}

    ads = [a for r in results.values() for a in r.ads]
    return ReadResult(
        ads=ads,
        new_ad_count=sum(r.new for r in results.values()),
        failed_boards={name: r.failed for name, r in results.items() if r.failed},
        outage_sources=[name for name, r in results.items() if r.outage],
        open_job_counts=dict(Counter(company_key(a.board) for a in ads)),
    )


def _read_source(
    source: JobSource,
    boards: BoardList,
    workspace: Workspace,
    today: date,
    report: Callable[[BoardProgress], None],
    outage_share: float,
) -> _SourceResult:
    ads: list[JobAd] = []
    new = 0
    ok: list[str] = []
    failed: list[str] = []
    for board in boards.to_read(today):
        try:
            board_ads, board_new = _read_board(source, board, workspace, today)
        except (BoardFailed, ValueError) as e:  # ValueError: a name the workspace refuses
            failed.append(board)
            report(BoardProgress(source.name, board, ok=False, error=str(e)))
            continue
        ok.append(board)
        ads += board_ads
        new += board_new
        report(BoardProgress(source.name, board, True, len(board_ads), board_new))

    tried = len(ok) + len(failed)
    outage = tried > 0 and len(failed) >= outage_share * tried
    # On an outage only the good reads are recorded, so no page is punished for it.
    boards.record_results(today, ok=ok, failed=[] if outage else failed)
    return _SourceResult(ads, new, failed, outage)


def _read_board(
    source: JobSource, board: str, workspace: Workspace, today: date
) -> tuple[list[JobAd], int]:
    """Fetch one page, keep each known ad's first-seen date, and save only if anything changed."""
    seen = {a.ad_id: a.first_seen for a in workspace.load_board_ads(source.name, board) or []}
    ads = [
        a.model_copy(update={"first_seen": seen[a.ad_id]}) if a.ad_id in seen else a
        for a in source.fetch_ads(board, today)
    ]
    workspace.save_board_ads(source.name, board, ads)
    return ads, sum(a.ad_id not in seen for a in ads)
