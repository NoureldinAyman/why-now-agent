"""`why-now serve`: run the review page.

On one's own machine it uses the local workspace and lets in only this machine. On AWS
it uses the AWS store and the Cognito login, and the web adapter in the same container
passes requests to it, so it still listens on this machine's own address only.
"""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from why_now.ai.budget import Meter
from why_now.cli import app
from why_now.cli.profile import make_writer
from why_now.cli.testset import run_prepare
from why_now.deployment import build_auth, open_store
from why_now.drafting import draft_profile
from why_now.profile import ProfileError, load_profile
from why_now.settings import load_settings
from why_now.web.app import AppContext, create_app
from why_now.web.run_now import RunNow

DEFAULT_SETTINGS = Path("settings.toml")
HOST = "127.0.0.1"  # this machine only. Other machines on the network cannot reach the page


def now() -> datetime:
    return datetime.now(UTC)


@app.command("serve")
def serve_command(
    profile_files: Annotated[
        list[Path] | None,
        typer.Option(
            "--profile",
            help="Profile file to mark for. Repeat for more. Defaults to daily_profiles.",
        ),
    ] = None,
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on.")] = None,
) -> None:
    """Run the review page, where the reviewer marks test cases."""
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    settings = load_settings(settings_file, env=dict(os.environ))
    profile_files = profile_files or settings.daily_profiles
    if not profile_files:
        raise typer.BadParameter("give a profile, or list daily_profiles in the settings")
    try:
        loaded = [(load_profile(f), f) for f in profile_files]
    except ProfileError as e:
        raise typer.BadParameter(str(e), param_hint="--profile") from e
    profiles = {p.id: p for p, _ in loaded}
    try:
        store = open_store(settings)
        auth = build_auth(settings, os.environ)
        ctx = AppContext(settings, store, profiles, Meter(store, settings, now), now)
        ctx.profile_files = {p.id: f.resolve() for p, f in loaded}
        if settings.deployment == "local":
            ctx.prepare = lambda profile, n, seed: run_prepare(settings, store, profile, n, seed)
            ctx.draft = lambda description: draft_profile(description, make_writer(settings))
            ctx.runner = RunNow(
                [sys.executable, "-m", "why_now"],
                settings_file.resolve() if settings_file is not None else None,
                settings.workspace_path / "run-now",
                clock=now,
            )
        web_app = create_app(ctx, auth)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    if port is None:
        config = uvicorn.Config(web_app, host=HOST)  # the server's own default port
    else:
        config = uvicorn.Config(web_app, host=HOST, port=port)
    typer.echo(f"Marking page at http://{HOST}:{config.port}/mark")
    uvicorn.Server(config).run()
