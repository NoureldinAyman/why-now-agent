"""`why-now copy-workspace`: copy the local workspace to the AWS store, once."""

from pathlib import Path
from typing import Annotated

import typer

from why_now.cli import app
from why_now.deployment import open_store
from why_now.settings import load_settings
from why_now.store.local import LocalStore
from why_now.workspace.copy import NOT_COPIED, CopyReport, CopyStopped, copy_workspace

DEFAULT_SETTINGS = Path("settings.toml")


@app.command("copy-workspace")
def copy_workspace_command(
    to: Annotated[
        Path,
        typer.Option(
            "--to",
            help="A settings file that names the AWS store to copy into (deployment = aws).",
        ),
    ],
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
    ] = None,
) -> None:
    """Copy every document in the local workspace into the AWS store, skipping documents
    that are already there. Safe to run twice. Nothing is deleted or overwritten."""
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    if not to.is_file():
        raise typer.BadParameter(f"{to} is not a file", param_hint="--to")
    source_settings = load_settings(settings_file)
    # The target is what its file says and nothing from the environment, so a shell set up for
    # one place cannot quietly change which store is written to.
    target_settings = load_settings(to, env={})
    if source_settings.deployment != "local":
        raise typer.BadParameter(
            "the settings file must name a local workspace to copy from", param_hint="--settings"
        )
    if target_settings.deployment != "aws":
        raise typer.BadParameter(
            "the --to file must say deployment = aws, naming the store to copy into",
            param_hint="--to",
        )
    source = open_store(source_settings)
    assert isinstance(source, LocalStore)
    target = open_store(target_settings)
    report = CopyReport()
    try:
        copy_workspace(source, target, report)
    except CopyStopped as e:
        _say(report)
        typer.echo(f"Stopped: {e}. Run the same command again to finish.", err=True)
        raise typer.Exit(1) from e
    _say(report)


def _say(report: CopyReport) -> None:
    total = sum(report.copied.values())
    by = ", ".join(f"{name}: {n}" for name, n in sorted(report.copied.items()))
    typer.echo(
        f"Copied {total} documents{f' ({by})' if by else ''}. "
        f"{report.already_there} were already there."
    )
    if report.differing:
        typer.echo(
            f"{len(report.differing)} of them differ from the local copy and were left alone, "
            f"as the AWS copy may have moved on: {', '.join(report.differing[:10])}"
            f"{' and more' if len(report.differing) > 10 else ''}."
        )
    if report.not_copied:
        left = ", ".join(f"{name} ({n})" for name, n in report.not_copied.items())
        typer.echo(f"Not copied, because each place keeps its own: {left}.")
        for name in report.not_copied:
            typer.echo(f"  {name}: {NOT_COPIED[name]}")
