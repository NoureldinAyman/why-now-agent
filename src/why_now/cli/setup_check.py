"""`why-now check-setup`: say what is ready, missing and optional."""

import os
from pathlib import Path
from typing import Annotated

import typer

from why_now.cli import app
from why_now.settings import load_settings
from why_now.setup_check import check_setup

DEFAULT_SETTINGS = Path("settings.toml")

HEADINGS = (("ok", "Ready"), ("missing", "Missing"), ("optional", "Optional"))


@app.command("check-setup")
def check_setup_command(
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
) -> None:
    """List what is ready, missing and optional. Never prints key values."""
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    items = check_setup(load_settings(settings_file), os.environ)
    for status, heading in HEADINGS:
        group = [i for i in items if i.status == status]
        if not group:
            continue
        typer.echo(f"{heading}:")
        for item in group:
            typer.echo(f"  {item.name}" + (f": {item.how_to_fix}" if item.how_to_fix else ""))
    typer.echo("")
    typer.echo("With no keys at all, the sample run can still work: it uses invented data.")
