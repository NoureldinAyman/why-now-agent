"""`why-now draft-profile`: draft a profile file from a few sentences about the product."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from why_now.ai import BadModelOutput, Writer, build_models
from why_now.ai.budget import BudgetExceeded, Meter
from why_now.cli import app
from why_now.deployment import open_store
from why_now.drafting import draft_profile
from why_now.profile import ProfileError, profile_text
from why_now.resolve_profile import upload_profile_file
from why_now.settings import Settings, load_settings

DEFAULT_SETTINGS = Path("settings.toml")


def make_writer(settings: Settings) -> Writer:
    store = open_store(settings)
    meter = Meter(store, settings, lambda: datetime.now(UTC))
    return build_models(settings, meter, os.environ).writer


profile_app = typer.Typer(help="Keep profiles in the workspace.")
app.add_typer(profile_app, name="profile")


@profile_app.command("upload")
def upload_command(
    file: Annotated[Path, typer.Argument(help="The profile file to save in the workspace.")],
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
) -> None:
    """Check a profile file and save it in the workspace. Older versions are kept."""
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    store = open_store(load_settings(settings_file))
    try:
        profile = upload_profile_file(file, store)
    except (ProfileError, ValueError) as e:
        typer.echo(f"Nothing was saved: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(
        f"Saved profile {profile.id}, version {profile.version[:8]}. Older versions are kept."
    )


@app.command("draft-profile")
def draft_profile_command(
    out: Annotated[Path, typer.Option("--out", help="Where to write the drafted profile.")],
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
) -> None:
    """Describe the product in a few sentences, and get a drafted profile to read and edit.
    This makes one paid call."""
    if out.exists():
        raise typer.BadParameter(
            f"{out} already exists, and is never overwritten", param_hint="--out"
        )
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    settings = load_settings(settings_file)
    description = typer.prompt("Describe the product and who uses it, in a few sentences")
    try:
        profile = draft_profile(description, make_writer(settings))
    except (BadModelOutput, BudgetExceeded, ProfileError) as e:
        typer.echo(f"No profile was drafted: {e}", err=True)
        raise typer.Exit(1) from e
    out.write_text(profile_text(profile), encoding="utf-8")
    typer.echo(f"Drafted {out}. Read it and edit it before use, the required questions above all.")
