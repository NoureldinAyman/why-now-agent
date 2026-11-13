"""`why-now daily`: one whole daily run for a profile, with the lists printed at the end."""

import os
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from why_now.ai import Models, build_models
from why_now.ai.budget import Meter
from why_now.cli import app
from why_now.cli import read as read_command
from why_now.cli.testset import make_reader
from why_now.day_result import DayResult
from why_now.deployment import open_store
from why_now.pipeline.day import run_day
from why_now.profile import ProfileError, load_profile
from why_now.run_context import RunContext
from why_now.settings import Settings, load_settings
from why_now.sources.boards import BoardList
from why_now.sources.polite import PoliteClient
from why_now.sources.registry import SOURCES
from why_now.tracing import UnitCounter, build_tracer
from why_now.workspace import Workspace

DEFAULT_SETTINGS = Path("settings.toml")


def now() -> datetime:
    return datetime.now(UTC)


def make_models(settings: Settings, meter: Meter) -> Models:
    return build_models(settings, meter, os.environ)


@app.command("daily")
def daily(
    profile_file: Annotated[Path, typer.Option("--profile", help="The profile to run for.")],
    short_list_size: Annotated[
        int | None,
        typer.Option(
            min=1,
            help="Short list size for this run only. Daily research is still limited.",
        ),
    ] = None,
    new_ad_days: Annotated[
        int | None, typer.Option(min=1, help="Days an ad counts as new, for this run only.")
    ] = None,
    saved_read: Annotated[
        bool,
        typer.Option(
            "--saved-read", help="Read no careers page. Use the ads saved at the last read."
        ),
    ] = False,
    sample_boards: Annotated[
        int | None,
        typer.Option(min=1, help="Read only this many careers pages per job source, at random."),
    ] = None,
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
) -> None:
    """Read, search, judge and write briefs for one profile, then print the two lists."""
    if saved_read and sample_boards is not None:
        raise typer.BadParameter("choose either --saved-read or --sample-boards, not both")
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    settings = load_settings(settings_file)
    try:
        profile = load_profile(profile_file)
    except ProfileError as e:
        raise typer.BadParameter(str(e), param_hint="--profile") from e
    unknown = sorted(set(settings.board_lists) - set(SOURCES))
    if not settings.board_lists or unknown:
        raise typer.BadParameter(
            "set board_lists in your settings file with a list for each job source "
            f"({', '.join(SOURCES)})",
            param_hint="board_lists",
        )

    overrides = {
        name: value
        for name, value in (("short_list_size", short_list_size), ("new_ad_days", new_ad_days))
        if value is not None
    }
    store = open_store(settings)
    meter = Meter(store, settings, now)
    http = read_command.make_http(settings)
    today = now().date()
    reader = make_reader(settings)
    with http, reader.http:
        sources, boards = [], {}
        for name, path in settings.board_lists.items():
            client = PoliteClient(
                http,
                settings.request_delay_seconds,
                attempts=settings.request_attempts,
                max_retry_wait_seconds=settings.max_retry_wait_seconds,
            )
            sources.append(SOURCES[name](client))
            names = read_command.load_names(path)
            if sample_boards is not None:
                ready = BoardList(Workspace(store), name, names, settings).to_read(today)
                names = random.sample(ready, min(sample_boards, len(ready)))
            boards[name] = BoardList(Workspace(store), name, names, settings)
        ctx = RunContext(
            settings=settings,
            store=store,
            sources=sources,
            boards=boards,
            models=make_models(settings, meter),
            reader=reader,
            meter=meter,
            tracer=build_tracer(
                settings.workspace_path / "traces",
                UnitCounter(store, settings, now),
                now,
                os.environ,
            ),
            clock=now,
        )
        result = run_day(ctx, profile, today, overrides, saved_read=saved_read)
    for line in describe(result):
        typer.echo(line)


def describe(result: DayResult, label: str = "") -> list[str]:
    """The two lists, and what failed or was skipped, in plain words."""
    lines = [f"{label}Short list for {result.day}: {len(result.short_list)} companies"]
    for i, e in enumerate(result.short_list, 1):
        lines.append(f"  {i}. {e.company_name} (strength {e.strength:.2f})")
        if e.brief is not None:
            lines.append(f'     Why now: {e.brief.why_now.text} "{e.brief.why_now.quote}"')
    lines.append(f"{label}More list: {len(result.more_list)} companies, not researched")
    for e in result.more_list:
        strength = "not looked at" if e.strength is None else f"strength {e.strength:.2f}"
        lines.append(f"  - {e.company_name} ({strength})")
    for problem in result.failed:
        lines.append(f"Failed: {problem}")
    for what in result.skipped:
        lines.append(f"Skipped: {what}")
    lines.append(
        f"Spent ${result.costs.spent_usd:.2f} of the monthly limit in {result.costs.month}."
    )
    return lines
