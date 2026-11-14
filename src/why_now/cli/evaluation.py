"""`why-now set-cutoff`, `evaluate`, `baselines` and `open-final`: grade the agent by the marks.

These call the real models, so they cost money. Every paid call is charged to the
`evaluation` budget category.
"""

import os
from collections.abc import Mapping
from typing import Annotated, cast

import typer

from why_now.ai import Answerer, Models, build_answerer, build_models
from why_now.ai.budget import BudgetExceeded, Meter
from why_now.cli import app
from why_now.cli.testset import ProfileOption, SettingsOption, now, open_workspace
from why_now.domain import Moment, Profile
from why_now.evaluation.evaluate import (
    CATEGORY,
    EvalRun,
    baselines,
    compare_judges,
    consistency,
    evaluate_pile,
    open_final_pile,
    set_cutoff,
)
from why_now.evaluation.records import PileResult, ScorePoint
from why_now.evaluation.short_list import short_list_precision
from why_now.run_context import metered
from why_now.settings import Settings
from why_now.tracing import UnitCounter, build_tracer
from why_now.workspace import Workspace

MOMENTS = ("first", "after_loop", "publishing", "extra")


def make_models(settings: Settings, meter: Meter) -> Models:
    return build_models(settings, meter, os.environ)


def make_answerers(settings: Settings, meter: Meter, env: Mapping[str, str]) -> list[Answerer]:
    """The two judges to compare, the current one first so it keeps a tie.

    Without a Jev key, a Jev candidate is replaced by the quick look's Claude fallback.
    """
    names = [
        settings.quick_look_fallback_model
        if name.startswith("jev-") and not env.get("TYPESAFE_API_KEY")
        else name
        for name in settings.judge_candidates
    ]
    names.sort(key=lambda name: name != settings.judge_model)  # False sorts first
    return [build_answerer(n, settings.judge_effort, settings, meter, env) for n in names]


def make_eval_run(settings: Settings, workspace: Workspace, profile: Profile) -> EvalRun:
    """An evaluation with the real models, each checking the budget before it is called."""
    store = workspace.store
    meter = Meter(store, settings, now)
    return EvalRun(
        workspace=workspace,
        profile=profile,
        models=metered(make_models(settings, meter), meter),
        settings=settings,
        tracer=build_tracer(
            settings.workspace_path / "traces", UnitCounter(store, settings, now), now, os.environ
        ),
        clock=now,
    )


@app.command("set-cutoff")
def set_cutoff_command(profile_file: ProfileOption, settings_file: SettingsOption = None) -> None:
    """Choose the cut-off on the practice pile and record it for the judge. This costs money."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    run = make_eval_run(settings, workspace, profile)
    try:
        cutoff = set_cutoff(run)
    except BudgetExceeded as e:
        typer.echo(f"Stopped: {e}.")
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(f"Cannot choose a cut-off: {e}")
        raise typer.Exit(1) from e
    typer.echo(
        f"Cut-off for {run.models.judge.answer_key}: {cutoff:g}, chosen on the practice pile only."
    )


@app.command("evaluate")
def evaluate_command(
    profile_file: ProfileOption,
    pile: Annotated[str, typer.Option(help="The pile to score: practice or check.")] = "check",
    settings_file: SettingsOption = None,
) -> None:
    """Score the agent against the reviewer's marks on one pile. This costs money."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    run = make_eval_run(settings, workspace, profile)
    try:
        result = evaluate_pile(pile, workspace.load_rules(), run, CATEGORY)
    except BudgetExceeded as e:
        typer.echo(f"Stopped: {e}.")
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(f"Cannot score: {e}")
        raise typer.Exit(1) from e
    workspace.save_score_point(ScorePoint(at=now(), result=result))
    _show(result)
    # Apart from the scores: these companies were chosen by the agent, not picked at random.
    shown = short_list_precision(workspace.decisions())
    if shown.percent is None:
        typer.echo("Short lists: no decisions yet.")
    else:
        typer.echo(
            f"Short lists, shown apart from the scores above: {shown.approved} of "
            f"{shown.decided} approved ({shown.percent}%)."
        )


@app.command("baselines")
def baselines_command(
    profile_file: ProfileOption,
    pile: Annotated[str, typer.Option(help="The pile to score: practice or check.")] = "check",
    settings_file: SettingsOption = None,
) -> None:
    """Score three simple rivals the agent must beat. This costs a little money."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    run = make_eval_run(settings, workspace, profile)
    try:
        scores = baselines(pile, run)
    except BudgetExceeded as e:
        typer.echo(f"Stopped: {e}.")
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(f"Cannot score: {e}")
        raise typer.Exit(1) from e
    for name, s in scores.items():
        typer.echo(
            f"{name.replace('_', ' ')}: {s.n} companies, precision {s.precision:.2f}, "
            f"recall {s.recall:.2f}, F-beta {s.f:.2f} (beta {s.beta:g})."
        )


@app.command("compare-models")
def compare_models_command(
    profile_file: ProfileOption, settings_file: SettingsOption = None
) -> None:
    """Compare two judges on the same check pile companies. This costs money."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    run = make_eval_run(settings, workspace, profile)
    meter = Meter(workspace.store, settings, now)
    try:
        answerers = make_answerers(settings, meter, os.environ)
        result = compare_judges(run, answerers)
    except BudgetExceeded as e:
        typer.echo(f"Stopped: {e}.")
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(f"Cannot compare: {e}")
        raise typer.Exit(1) from e
    for key, s in result.scores.items():
        typer.echo(
            f"{key}: {s.n} companies, precision {s.precision:.2f}, recall {s.recall:.2f}, "
            f"F-beta {s.f:.2f} (beta {s.beta:g})."
        )
    if result.dropped_cases:
        typer.echo(
            f"{len(result.dropped_cases)} companies were left out for both, because a judge "
            "could not answer for them."
        )
    typer.echo("Each judge's cut-off was chosen again on the practice pile and recorded.")
    typer.echo(f"Winner: {result.winner}. Set judge_model to it. The result is recorded.")


@app.command("consistency")
def consistency_command(profile_file: ProfileOption, settings_file: SettingsOption = None) -> None:
    """Ask the same questions again and again on practice packs and show how far the answers
    move, for each of the two judges. Saved answers are not used. This costs money."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    run = make_eval_run(settings, workspace, profile)
    meter = Meter(workspace.store, settings, now)
    # Practice cases only, in a fixed order, so no check or final pile company is read.
    cases = sorted(
        (c for c in workspace.cases() if c.pile == "practice" and c.pack_id is not None),
        key=lambda c: c.case_id,
    )[: settings.consistency_packs]
    packs = [p for c in cases if c.pack_id and (p := workspace.load_pack(c.pack_id)) is not None]
    if not packs:
        typer.echo("There are no practice packs yet. Build packs for practice companies first.")
        raise typer.Exit(1)
    try:
        for answerer in make_answerers(settings, meter, os.environ):
            result = consistency(run, answerer, packs, settings.consistency_asks)
            workspace.save_consistency(result)
            typer.echo(
                f"{result.answer_key}: {result.asks} asks on {result.companies} companies "
                "(a rough number from this few)."
            )
            for question_id, spread in result.spread.items():
                typer.echo(
                    f"  {question_id}: answers moved {spread.average:.2f} on average, "
                    f"{spread.worst:.2f} at worst."
                )
            if result.failed:
                typer.echo(f"  {len(result.failed)} packs left out: no usable answers.")
    except BudgetExceeded as e:
        typer.echo(f"Stopped: {e}.")
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(f"Cannot check consistency: {e}")
        raise typer.Exit(1) from e


@app.command("open-final")
def open_final_command(
    profile_file: ProfileOption,
    moment: Annotated[
        str, typer.Option(help="Why it is opened: first, after_loop, publishing or extra.")
    ],
    reason: Annotated[
        str | None, typer.Option(help="Required for an extra opening. It is logged.")
    ] = None,
    settings_file: SettingsOption = None,
) -> None:
    """Open the final pile. Every opening is logged, and this costs money."""
    if moment not in MOMENTS:
        raise typer.BadParameter(f"must be one of {', '.join(MOMENTS)}", param_hint="--moment")
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    run = make_eval_run(settings, workspace, profile)
    try:
        result = open_final_pile(run, cast(Moment, moment), reason)
    except BudgetExceeded as e:
        typer.echo(f"Stopped: {e}. The opening is already logged.")
        raise typer.Exit(1) from e
    except ValueError as e:
        typer.echo(f"Cannot open the final pile: {e}")
        raise typer.Exit(1) from e
    workspace.save_score_point(ScorePoint(at=now(), result=result))
    typer.echo(f"Opened the final pile ({moment}). The opening is logged.")
    _show(result)


def _show(result: PileResult) -> None:
    s = result.score
    typer.echo(
        f"{result.pile} pile, {s.n} companies: {s.tp} right yes, {s.fp} wrong yes, "
        f"{s.fn} missed, {s.tn} right no."
    )
    typer.echo(
        f"Precision {s.precision:.2f}, recall {s.recall:.2f}, F-beta {s.f:.2f} "
        f"(beta {s.beta:g}). Rules version {result.rules_version}."
    )
    if not result.cutoff_recorded:
        typer.echo(
            f"No cut-off is recorded for {result.models['judge']}, so the default cut-off "
            f"{result.cutoff:g} was used. Run set-cutoff first for a score that means more."
        )
    if result.failed_cases:
        typer.echo(
            f"{len(result.failed_cases)} companies could not be answered for and are left out, "
            f"not counted as a no: {', '.join(result.failed_cases)}."
        )
