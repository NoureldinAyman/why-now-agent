"""One job source's list of careers pages, and which of them are worth reading today."""

from datetime import date, timedelta

from why_now.domain import BoardHealth
from why_now.settings import Settings
from why_now.workspace import Workspace


class BoardList:
    """The careers pages to read for one job source.

    A page that fails on `dead_after_days` separate days with no good read in
    between is set aside, and tried again every `retry_dead_after_days` days.
    A good read puts it back on the daily list. Health is kept in the workspace
    per source, so a list built from a sample shares it with the full list.
    """

    def __init__(
        self, workspace: Workspace, source: str, names: list[str], settings: Settings | None = None
    ):
        settings = settings or Settings()
        self.workspace = workspace
        self.source = source
        self.names = list(dict.fromkeys(names))
        self.dead_after = settings.dead_after_days
        self.retry_after = timedelta(days=settings.retry_dead_after_days)

    def to_read(self, today: date) -> list[str]:
        """Pages to read today: all but those set aside and not yet due for a retry."""
        health = self.workspace.board_health(self.source)
        return [n for n in self.names if self._due(health.get(n, BoardHealth()), today)]

    def record_results(self, today: date, ok: list[str], failed: list[str]) -> None:
        health = self.workspace.board_health(self.source)
        for name in ok:
            health.pop(name, None)  # a good read clears the record
        for name in failed:
            h = health.setdefault(name, BoardHealth())
            if h.last_failed != today:
                h.failing_days += 1
                h.last_failed = today
            if h.set_aside_on is not None:
                h.last_retry = today
            elif h.failing_days >= self.dead_after:
                h.set_aside_on = today
        self.workspace.save_board_health(self.source, health)

    def health(self, board: str) -> BoardHealth:
        return self.workspace.board_health(self.source).get(board, BoardHealth())

    def _due(self, h: BoardHealth, today: date) -> bool:
        if h.set_aside_on is None:
            return True
        return today >= (h.last_retry or h.set_aside_on) + self.retry_after
