"""`why-now sample-run`: try the whole daily flow on invented data, free and with no keys."""

import tempfile
from pathlib import Path
from typing import Annotated

import typer

from why_now.cli import app
from why_now.cli.daily import describe, now
from why_now.sample.data import run_sample

SIMULATED = "Simulated data"


@app.command("sample-run")
def sample_run(
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", help="Folder for what the run saves. Defaults to a new one."),
    ] = None,
) -> None:
    """Run one day on invented companies. Nothing is real, nothing is paid for, no keys are used."""
    folder = workspace or Path(tempfile.mkdtemp(prefix="why-now-sample-"))
    typer.echo(f"{SIMULATED}: every company, job ad and brief below is invented.")
    result = run_sample(folder, now())
    for line in describe(result, label=f"{SIMULATED}. "):
        typer.echo(line)
    typer.echo(f"{SIMULATED}. Saved in {folder}. Nothing was spent and no keys were used.")
