"""`why-now read`: read careers pages and save their job ads to the workspace."""

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from why_now.cli import app
from why_now.deployment import open_store
from why_now.pipeline.read import BoardProgress, read_all
from why_now.settings import Settings, load_settings
from why_now.sources.boards import BoardList
from why_now.sources.polite import PoliteClient
from why_now.sources.registry import SOURCES
from why_now.workspace import Workspace

DEFAULT_SETTINGS = Path("settings.toml")


def make_http(settings: Settings) -> httpx.Client:
    return httpx.Client(timeout=settings.source_timeout_seconds)


@app.command("read")
def read_ads(
    sample: Annotated[
        int | None, typer.Option(min=1, help="Read only this many careers pages per job source.")
    ] = None,
    seed: Annotated[int | None, typer.Option(help="Seed for picking the sample.")] = None,
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
) -> None:
    """Read careers pages politely and save their job ads to the workspace."""
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    settings = load_settings(settings_file)
    if not settings.board_lists:
        raise typer.BadParameter(
            "no careers page lists are set. Add board_lists to your settings file, for example "
            'board_lists = { greenhouse = "examples/boards.greenhouse.example.json" }',
            param_hint="board_lists",
        )
    unknown = sorted(set(settings.board_lists) - set(SOURCES))
    if unknown:
        raise typer.BadParameter(
            f"unknown job source {', '.join(unknown)}. Known: {', '.join(SOURCES)}",
            param_hint="board_lists",
        )

    workspace = Workspace(open_store(settings))
    today = datetime.now(UTC).date()
    rng = random.Random(seed)
    http = make_http(settings)
    sources, boards = [], {}
    for name, path in settings.board_lists.items():
        client = PoliteClient(
            http,
            settings.request_delay_seconds,
            attempts=settings.request_attempts,
            max_retry_wait_seconds=settings.max_retry_wait_seconds,
        )
        sources.append(SOURCES[name](client))
        names = BoardList(workspace, name, load_names(path), settings).to_read(today)
        if sample is not None and sample < len(names):
            names = rng.sample(names, sample)
        boards[name] = BoardList(workspace, name, names, settings)

    progress: list[BoardProgress] = []

    def on_progress(p: BoardProgress) -> None:
        progress.append(p)
        if not p.ok:
            typer.echo(f"  {p.source}: {p.board} failed: {p.error}")

    with http:
        result = read_all(
            sources, boards, workspace, today, on_progress, outage_share=settings.outage_share
        )

    for name in settings.board_lists:
        done = [p for p in progress if p.source == name]
        ok = [p for p in done if p.ok]
        ads = sum(p.ad_count for p in ok)
        new = sum(p.new_ad_count for p in ok)
        typer.echo(
            f"{name}: read {len(ok)} of {len(done)} careers pages, {ads} job ads ({new} new)."
        )
        if name in result.outage_sources:
            typer.echo(
                f"{name} looks down: {len(done) - len(ok)} of {len(done)} pages failed, "
                "so none of them counts towards being set aside."
            )
    typer.echo(f"Saved in {settings.workspace_path}.")


def load_names(path: Path) -> list[str]:
    """A careers page list: a JSON list of page names."""
    names = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise typer.BadParameter(f"{path} must be a JSON list of careers page names")
    return names
