"""`why-now build-list`: build a list of careers page names from Common Crawl."""

import json
from pathlib import Path
from typing import Annotated

import httpx
import typer

from why_now.cli import app
from why_now.settings import Settings, load_settings
from why_now.sources.commoncrawl import HOSTS, ListBuildFailed, build_board_list

DEFAULT_SETTINGS = Path("settings.toml")


def make_http(settings: Settings) -> httpx.Client:
    return httpx.Client(timeout=settings.source_timeout_seconds)


@app.command("build-list")
def build_list(
    source: Annotated[str, typer.Option(help=f"Job source: {' or '.join(HOSTS)}.")],
    out: Annotated[Path, typer.Option(help="List file to write. Names already in it are kept.")],
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
) -> None:
    """Build a list of careers page names from Common Crawl, and merge it into OUT."""
    if source not in HOSTS:
        raise typer.BadParameter(
            f"unknown job source {source}. Known: {', '.join(HOSTS)}", param_hint="--source"
        )
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    settings = load_settings(settings_file)
    existing = _load(out)
    try:
        with make_http(settings) as http:
            merged = build_board_list(
                source,
                http,
                existing,
                delay_seconds=settings.request_delay_seconds,
                attempts=settings.request_attempts,
            )
    except ListBuildFailed as e:
        typer.echo(f"Could not build the {source} list: {e}", err=True)
        typer.echo(f"Nothing was written. You can supply your own {source} list instead.", err=True)
        raise typer.Exit(1) from e
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    typer.echo(
        f"{source}: {len(merged)} careers pages in {out} ({len(merged) - len(existing)} new)."
    )


def _load(path: Path) -> list[str]:
    if not path.is_file():
        return []
    names = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise typer.BadParameter(f"{path} must be a JSON list of careers page names")
    return names
