"""`why-now yes-share`, `split-piles`, `repeat-marks` and `agreement`: the numbers and steps
that come after the reviewer has marked the test cases."""

from datetime import UTC, datetime
from typing import Annotated

import typer

from why_now.cli import app
from why_now.cli.testset import ProfileOption, SettingsOption, open_workspace
from why_now.testset.piles import PilesFrozen, split_piles, yes_share
from why_now.testset.repeat import agreement_counts, pick_repeats

SeedOption = Annotated[int, typer.Option(help="Seed for the random choice. It fixes the result.")]


def now() -> datetime:
    return datetime.now(UTC)


@app.command("yes-share")
def yes_share_command(profile_file: ProfileOption, settings_file: SettingsOption = None) -> None:
    """Show how many marked companies are a yes, to see if the piles can hold enough."""
    settings, workspace, _ = open_workspace(profile_file, settings_file)
    marks = workspace.marks("first")
    yes = sum(m.answer == "yes" for m in marks)
    no = sum(m.answer == "no" for m in marks)
    cant = sum(m.answer == "cant_tell" for m in marks)
    typer.echo(f"{len(marks)} marked: {yes} yes, {no} no, {cant} can't tell.")
    if yes + no == 0:
        typer.echo("There are no yes or no answers yet, so there is no share.")
        return
    needed = settings.target_yes_per_pile / settings.check_size
    typer.echo(
        f"Yes share, leaving out can't tell: {yes_share(marks):.0%}. "
        f"About {needed:.0%} is needed for {settings.target_yes_per_pile} yes answers in a "
        f"pile of {settings.check_size}."
    )


@app.command("split-piles")
def split_piles_command(
    profile_file: ProfileOption, seed: SeedOption, settings_file: SettingsOption = None
) -> None:
    """Split the marked companies into the practice, check and final piles."""
    settings, workspace, _ = open_workspace(profile_file, settings_file)
    try:
        report = split_piles(workspace, seed, settings)
    except PilesFrozen as e:
        typer.echo(f"{e} Nothing was changed.")
        raise typer.Exit(1) from e
    for pile, count in report.counts.items():
        typer.echo(f"{pile}: {count} companies, {report.yes_counts[pile]} yes.")
    typer.echo(f"Yes share, leaving out can't tell: {report.yes_share:.0%}. Seed {seed}.")
    if report.short_piles:
        typer.echo(
            f"Short of {settings.target_yes_per_pile} yes answers: "
            f"{', '.join(report.short_piles)}. "
            f"Mark more companies, up to {settings.marking_ceiling} in all, and split again. "
            "If it is still short, lower target_yes_per_pile (never below "
            f"{settings.floor_yes_per_pile}) and say publicly that the numbers are rougher."
        )


@app.command("repeat-marks")
def repeat_marks_command(
    profile_file: ProfileOption, seed: SeedOption, settings_file: SettingsOption = None
) -> None:
    """Pick companies to mark again, once their first mark is old enough."""
    settings, workspace, _ = open_workspace(profile_file, settings_file)
    existing = workspace.repeat_selection()
    if existing is not None:
        typer.echo(f"{len(existing)} companies were already picked. Mark them at /repeat.")
        return
    picked = pick_repeats(
        workspace.marks("first"),
        settings.remark_size,
        seed,
        now().date(),
        settings.remark_after_days,
    )
    if len(picked) < settings.remark_size:
        typer.echo(
            f"Only {len(picked)} companies have a yes or no mark at least "
            f"{settings.remark_after_days} days old, and {settings.remark_size} are needed. "
            "Nothing was picked. Try again later."
        )
        raise typer.Exit(1)
    workspace.save_repeat_selection(seed, picked, now())
    typer.echo(f"Picked {len(picked)} companies with seed {seed}. Mark them at /repeat.")


@app.command("agreement")
def agreement_command(profile_file: ProfileOption, settings_file: SettingsOption = None) -> None:
    """Show how often the reviewer gave the same answer twice."""
    _, workspace, _ = open_workspace(profile_file, settings_file)
    again = workspace.marks("repeat")
    agreed, compared = agreement_counts(workspace.marks("first"), again)
    if compared == 0:
        typer.echo("There is nothing to compare yet. Mark the repeat companies first.")
        raise typer.Exit(1)
    typer.echo(
        f"The two answers matched for {agreed} of {compared} companies "
        f"({agreed / compared:.0%}). This is a rough number from {compared} companies."
    )
    picked = workspace.repeat_selection() or []
    if len(again) < len(picked):
        typer.echo(f"{len(picked) - len(again)} picked companies are not marked again yet.")
