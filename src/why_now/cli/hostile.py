"""`why-now hostile-test`: run the hidden instruction tests against the real models."""

import os

import typer

from why_now.ai import Models, build_models
from why_now.ai.budget import BudgetExceeded, Meter
from why_now.cli import app
from why_now.cli.testset import ProfileOption, SettingsOption, make_reader, now, open_workspace
from why_now.hostile.attacks import load_attacks
from why_now.hostile.runner import run_attacks
from why_now.pipeline.judge import all_questions
from why_now.settings import Settings
from why_now.tracing import UnitCounter, build_tracer

CATEGORY = "hostile"  # the budget category the tests are charged to


def make_models(settings: Settings, meter: Meter) -> Models:
    return build_models(settings, meter, os.environ)


@app.command("hostile-test")
def hostile_test(profile_file: ProfileOption, settings_file: SettingsOption = None) -> None:
    """Run the invented hostile ads and pages against the models. This costs money."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    store = workspace.store
    models = make_models(settings, Meter(store, settings, now))
    cutoff = workspace.cutoff(models.judge.answer_key)
    if cutoff is None:
        typer.echo(
            f"No cut-off is recorded for {models.judge.answer_key}, so decisions can't be "
            "compared. Choose one on the practice pile first."
        )
        raise typer.Exit(1)
    questions = all_questions(profile, workspace.load_rules())
    tracer = build_tracer(
        settings.workspace_path / "traces", UnitCounter(store, settings, now), now, os.environ
    )
    attacks = load_attacks()
    reader = make_reader(settings)
    try:
        with reader.http:
            results = run_attacks(
                attacks,
                models,
                questions,
                reader,
                settings,
                CATEGORY,
                profile=profile,
                cutoff=cutoff,
                tracer=tracer,
                now=now(),
            )
    except BudgetExceeded as e:
        typer.echo(f"Stopped: {e}. Results so far are in the traces.")
        raise typer.Exit(1) from e
    kinds = {a.id: a.kind for a in attacks}
    for r in results:
        verdict = "resisted" if r.passed else "WORKED"
        line = f"  {verdict}  {r.attack_id} ({kinds[r.attack_id]})"
        typer.echo(line + (f": {r.problem}" if r.problem else ""))
    worked = [r for r in results if not r.passed]
    typer.echo(f"{len(results) - len(worked)} of {len(results)} attacks were resisted.")
    if worked:
        raise typer.Exit(1)
