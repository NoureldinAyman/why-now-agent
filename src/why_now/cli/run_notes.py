"""Writing a run's notes, for the commands that start runs: `daily`, `improve` and `night-run`.

A command that starts a run holds this around the work. It writes the start note, refuses to
go on while another run is going, and writes the finish note however the work ends, so a run
that raised an error is noted as failed and does not block the next one. A run that dies
without running any code, such as one that is killed, leaves its start with no finish.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

import typer

from why_now.settings import Settings
from why_now.store import Store
from why_now.workspace import Workspace
from why_now.workspace.runs import RunAlreadyGoing, RunMode, RunSummary, stale_after


class RunRecord:
    """What the command fills in as it goes: the summary kept on the finish note."""

    def __init__(self) -> None:
        self.summary = RunSummary()


@contextmanager
def noted_run(
    store: Store,
    settings: Settings,
    profile_id: str,
    mode: RunMode,
    clock: Callable[[], datetime],
) -> Iterator[RunRecord]:
    workspace = Workspace(store)
    try:
        note = workspace.start_run(profile_id, mode, clock(), stale_after(settings))
    except RunAlreadyGoing as e:
        typer.echo(f"Not started: {e}. Wait for it to finish.", err=True)
        raise typer.Exit(1) from e
    record = RunRecord()
    try:
        yield record
    except typer.Exit as e:
        failed = e.exit_code != 0
        if failed and record.summary.problem is None:
            record.summary.problem = f"The run ended with exit code {e.exit_code}."
        workspace.finish_run(note, clock(), record.summary, "failed" if failed else "finished")
        raise
    except BaseException as e:
        record.summary.problem = f"{type(e).__name__}: {e}"
        workspace.finish_run(note, clock(), record.summary, "failed")
        raise
    ended = "failed" if record.summary.problem else "finished"
    workspace.finish_run(note, clock(), record.summary, ended)
