"""Run notes: a note when a run starts and another when it finishes, wherever it was started.

Only one run goes at a time, because two runs at once could lose spending records or tries.
The one that is going holds a lock document, taken with one atomic step in the store, so the
schedule, the page and a person's computer cannot all start at once. A run that dies leaves
its start with no finish. That shows as a run that stopped, once it is older than the stale
time, and from then on it no longer blocks the next run.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from why_now.settings import Settings
from why_now.workspace.base import WorkspaceBase
from why_now.workspace.profiles import is_safe_id

RunMode = Literal["daily", "improve", "night"]
RunState = Literal["running", "finished", "failed", "stopped"]

_NOTES = "runs"
_LOCK = "run_lock"
_LOCK_KEY = "current"
_REQUESTS = "run_requests"


class RunSummary(BaseModel):
    """What a run did, short enough to read on the Runs page."""

    short_list: int | None = None
    more_list: int | None = None
    failed: list[str] = []  # one plain sentence for each company or careers page that failed
    skipped: list[str] = []
    cost_usd: float = 0.0
    # An improvement run: what each try did, then why it stopped, in plain words.
    tries: list[str] = []
    stop: str | None = None
    problem: str | None = None  # why a run that failed failed


class RunNote(BaseModel):
    run_id: str
    profile_id: str
    mode: RunMode
    started_at: datetime
    finished_at: datetime | None = None
    ended: Literal["finished", "failed"] | None = None
    summary: RunSummary = RunSummary()


class RunAlreadyGoing(Exception):
    """Another run started and has not finished, and is not stale yet."""

    def __init__(self, holder: RunNote):
        super().__init__(
            f"a {holder.mode} run for {holder.profile_id} is still going, "
            f"started {holder.started_at:%d %b %H:%M} UTC"
        )
        self.holder = holder


def stale_after(settings: Settings) -> timedelta:
    """How long a start with no finish may block the next run."""
    return timedelta(hours=settings.run_stale_hours)


def is_stale(note: RunNote, now: datetime, stale_after: timedelta) -> bool:
    return note.finished_at is None and now - note.started_at >= stale_after


def run_state(note: RunNote, now: datetime, stale_after: timedelta) -> RunState:
    """How a note reads now. A start with no finish is running until it is stale, then it
    shows as stopped, so a crash in the night is seen in the morning."""
    if note.finished_at is not None:
        return note.ended or "finished"
    return "stopped" if is_stale(note, now, stale_after) else "running"


class RunsArea(WorkspaceBase):
    def start_run(
        self, profile_id: str, mode: RunMode, now: datetime, stale_after: timedelta
    ) -> RunNote:
        """Write the start note and take the lock, or raise `RunAlreadyGoing`. A holder older
        than `stale_after` is taken over, and its note stays with no finish."""
        if not is_safe_id(profile_id):
            raise ValueError(f"profile id {profile_id!r} must be a single safe name")
        stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%f")
        note = RunNote(
            run_id=f"{profile_id}/{stamp}-{mode}", profile_id=profile_id, mode=mode, started_at=now
        )
        mine = note.model_dump(mode="json")
        if not self.store.swap(_LOCK, _LOCK_KEY, None, mine):
            held = self._held()
            if held is None or not is_stale(RunNote.model_validate(held), now, stale_after):
                # Held by a live run, or released a moment ago. Either way, not this time.
                raise RunAlreadyGoing(RunNote.model_validate(held) if held else note)
            if not self.store.swap(_LOCK, _LOCK_KEY, held, mine):
                raise RunAlreadyGoing(RunNote.model_validate(self._held() or held))
        self.put_model(_NOTES, note.run_id, note)
        return note

    def finish_run(
        self,
        note: RunNote,
        now: datetime,
        summary: RunSummary,
        ended: Literal["finished", "failed"] = "finished",
    ) -> RunNote:
        """Write the finish note and let go of the lock, if this run still holds it. A run that
        was taken over as stale does not let go of the new run's lock."""
        done = note.model_copy(update={"finished_at": now, "ended": ended, "summary": summary})
        self.put_model(_NOTES, done.run_id, done)
        held = self._held()
        if held is not None and held["run_id"] == note.run_id:
            self.store.swap(_LOCK, _LOCK_KEY, held, None)
        return done

    def running(self, now: datetime, stale_after: timedelta) -> RunNote | None:
        """The run that is going, or None. A stale one is not going."""
        held = self._held()
        if held is None:
            return None
        note = RunNote.model_validate(held)
        return None if is_stale(note, now, stale_after) else note

    def last_runs(self, profile_id: str, limit: int) -> list[RunNote]:
        """This profile's notes, newest first."""
        if not is_safe_id(profile_id):
            return []
        notes = self.list_models(_NOTES, RunNote, f"{profile_id}/")
        return sorted(notes, key=lambda n: n.started_at, reverse=True)[:limit]

    def request_run(self, now: datetime) -> None:
        """Note that a run was just asked for. The task takes a while to start and take the
        lock, and until it does, `run_requested` is what tells a second press to wait."""
        self.store.put(_REQUESTS, "current", {"requested_at": now.isoformat()})

    def run_requested(self, now: datetime, wait: timedelta) -> bool:
        """Whether a run was asked for less than `wait` ago."""
        doc = self.store.get(_REQUESTS, "current")
        return doc is not None and now - datetime.fromisoformat(doc["requested_at"]) < wait

    def _held(self) -> dict | None:
        return self.store.get(_LOCK, _LOCK_KEY)
