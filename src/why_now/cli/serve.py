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
from why_now.deployment import aws_clients, build_auth, open_store
from why_now.drafting import draft_profile
from why_now.profile import ProfileError
from why_now.resolve_profile import resolve_profile, upload_profile_file
from why_now.settings import Settings, load_settings
from why_now.store import Store
from why_now.store.aws import ClientFactory
from why_now.testset.ads_only import prepare_ads_only
from why_now.web.app import AppContext, create_app
from why_now.web.run_now import AwsRunNow, RunNow

DEFAULT_SETTINGS = Path("settings.toml")
HOST = "127.0.0.1"  # this machine only. Other machines on the network cannot reach the page


def now() -> datetime:
    return datetime.now(UTC)


def _upload_given(refs: list[str], store: Store) -> dict[str, Path]:
    """Save each given profile file in the workspace, and return the file of each by profile
    id. A ref that is not a file must be the id of a profile already in the workspace."""
    files: dict[str, Path] = {}
    for ref in refs:
        path = Path(ref)
        try:
            if path.is_file():
                profile = upload_profile_file(path, store)
                files[profile.id] = path.resolve()
                typer.echo(f"Uploaded profile {profile.id}, version {profile.version[:8]}.")
            else:
                resolve_profile(ref, store)
        except (ProfileError, ValueError) as e:
            raise typer.BadParameter(str(e), param_hint="--profile") from e
    return files


def attach_actions(
    ctx: AppContext,
    settings: Settings,
    settings_file: Path | None,
    clients: ClientFactory | None = None,
) -> None:
    """Give the page the things it may do for where it runs.

    On one's own computer, where the keys and the budget are the person's own: prepare, draft
    a profile and start a run as a separate process. On AWS: start the night run's task, if
    the AWS setup named it, and prepare while that makes no paid call. Drafting stays off,
    because it is a paid call that needs the person's own keys.
    """
    store = ctx.store
    if settings.deployment == "local":
        ctx.prepare = lambda profile, n, seed: run_prepare(settings, store, profile, n, seed)
        ctx.draft = lambda description: draft_profile(description, make_writer(settings))
        ctx.runner = RunNow(
            [sys.executable, "-m", "why_now"],
            settings_file.resolve() if settings_file is not None else None,
            settings.workspace_path / "run-now",
            clock=now,
        )
        return
    if settings.aws_run_cluster and settings.aws_run_task:
        ctx.runner = AwsRunNow(settings, (clients or aws_clients(settings))("ecs"), store, now)
    if not settings.test_case_web_research:
        ctx.prepare = lambda profile, n, seed: prepare_ads_only(
            settings, store, profile, n, seed, clock=now
        )


@app.command("serve")
def serve_command(
    profile_refs: Annotated[
        list[str] | None,
        typer.Option(
            "--profile",
            help=(
                "A profile file to upload to the workspace before starting, which saving the "
                "profile page then also writes. Repeat for more. Optional: the page shows "
                "the profiles in the workspace."
            ),
        ),
    ] = None,
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on.")] = None,
) -> None:
    """Run the review page. It reads profiles from the workspace on each visit."""
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    settings = load_settings(settings_file, env=dict(os.environ))
    try:
        store = open_store(settings)
        auth = build_auth(settings, os.environ)
        ctx = AppContext(settings, store, Meter(store, settings, now), now)
        ctx.profile_files = _upload_given(profile_refs or [], store)
        attach_actions(ctx, settings, settings_file)
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
