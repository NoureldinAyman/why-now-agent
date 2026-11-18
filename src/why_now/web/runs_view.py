"""What the Runs page says about time and about each run, written on the server.

The page runs no script, so the next run and the time until it are worked out here.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from why_now.workspace.runs import RunNote, RunState, run_state

MODE_NAMES = {"daily": "Daily list", "improve": "Improvement run", "night": "Night run"}
STATE_NAMES: dict[RunState, str] = {
    "running": "Running",
    "finished": "Finished",
    "failed": "Failed",
    "stopped": "Stopped without finishing",
}


def next_run_at(now: datetime, hour_utc: int) -> datetime:
    """The next time the schedule starts the night run: `hour_utc` o'clock UTC, strictly after
    `now`."""
    now = now.astimezone(UTC)
    at = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def until(wait: timedelta) -> str:
    """A wait in plain words, such as "in 5 hours 12 minutes"."""
    minutes = int(wait.total_seconds() // 60)
    if minutes < 1:
        return "in under a minute"
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return "in " + " ".join(parts)


def shown_time(when: datetime, zone: str) -> str:
    return when.astimezone(ZoneInfo(zone)).strftime("%d %b %Y %H:%M")


@dataclass
class RunRow:
    """One run as the page shows it."""

    note: RunNote
    mode: str
    state: RunState
    state_name: str
    started: str
    finished: str | None


def run_row(note: RunNote, now: datetime, stale_after: timedelta, zone: str) -> RunRow:
    state = run_state(note, now, stale_after)
    return RunRow(
        note=note,
        mode=MODE_NAMES[note.mode],
        state=state,
        state_name=STATE_NAMES[state],
        started=shown_time(note.started_at, zone),
        finished=None if note.finished_at is None else shown_time(note.finished_at, zone),
    )
