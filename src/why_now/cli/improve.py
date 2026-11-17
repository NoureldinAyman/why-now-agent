"""`why-now improve` and `why-now night-run`: the improvement loop, alone and after the daily run.

These call the real models, so they cost money. Every paid call is charged to the `loop`
budget category, which has its own share of the month.
"""

from pathlib import Path
from typing import Annotated

import typer

from why_now.ai.budget import LOOP, Meter
from why_now.cli import app
from why_now.cli import daily as daily_command
from why_now.cli.evaluation import make_eval_run
from why_now.cli.testset import ProfileOption, SettingsOption, make_reader, now, open_workspace
from why_now.domain import Profile, RulesFile
from why_now.evaluation.evaluate import EvalRun
from why_now.hostile.attacks import load_attacks
from why_now.hostile.runner import run_attacks
from why_now.improve.records import ImproveResult, TryRecord
from why_now.improve.run import HostileCheck, run_improvement
from why_now.improve.screen import RuleChange
from why_now.pipeline.judge import all_questions
from why_now.pipeline.research import PageSource
from why_now.settings import Settings, load_settings
from why_now.testset.piles import pile_report
from why_now.workspace import Workspace

STOPPED = {
    "no_mistakes": "Stopped: no mistakes are left to learn from.",
    "budget": "Stopped: the loop's share of the budget is spent.",
    "run_limit": "Stopped: this run has made as many tries as one run is allowed.",
    "check_pile_used_up": (
        "Stopped: the check pile has been used for as many tries as it can bear. "
        "Mark more check companies, then run again."
    ),
}


@app.command("improve")
def improve_command(profile_file: ProfileOption, settings_file: SettingsOption = None) -> None:
    """Improve now: look for mistakes, try changes to the rules, keep the ones that help."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    if not improve_profile(settings, workspace, profile):
        raise typer.Exit(1)


@app.command("night-run")
def night_run_command(
    profile_files: Annotated[
        list[Path] | None,
        typer.Option(
            "--profile",
            help="Profile file to run. Repeat for more. Defaults to daily_profiles.",
        ),
    ] = None,
    settings_file: SettingsOption = None,
) -> None:
    """For each profile, the daily list first, then the improvement loop."""
    if settings_file is None and daily_command.DEFAULT_SETTINGS.is_file():
        settings_file = daily_command.DEFAULT_SETTINGS
    files = profile_files or load_settings(settings_file).daily_profiles
    if not files:
        raise typer.BadParameter("give a profile, or list daily_profiles in the settings")
    for file in files:
        typer.echo(f"=== {file}: the daily list")
        daily_command.daily(
            profile_file=file,
            short_list_size=None,
            new_ad_days=None,
            saved_read=False,
            sample_boards=None,
            settings_file=settings_file,
        )
        typer.echo(f"=== {file}: the improvement loop")
        settings, workspace, profile = open_workspace(file, settings_file)
        # The daily list is already made and kept, so a loop that cannot start does not undo it.
        improve_profile(settings, workspace, profile)


def improve_profile(settings: Settings, workspace: Workspace, profile: Profile) -> bool:
    """Run the loop once for one profile and say in plain words what happened.

    False when it could not start, so the caller can fail or carry on.
    """
    run = make_eval_run(settings, workspace, profile)
    judge_key = run.models.judge.answer_key
    cutoff = workspace.cutoff(judge_key)
    if cutoff is None:
        typer.echo(
            f"No cut-off is recorded for {judge_key}, so the hidden tests can't be compared. "
            "Choose one on the practice pile first (why-now set-cutoff)."
        )
        return False
    reader = make_reader(settings)
    meter = Meter(workspace.store, settings, now)
    spent_before = meter.status().by_category.get(LOOP, 0.0)
    try:
        with reader.http:
            result = run_improvement(run, meter, _hidden_tests(run, reader, cutoff))
    except ValueError as e:
        typer.echo(f"Could not improve: {e}")
        return False
    spent = meter.status().by_category.get(LOOP, 0.0) - spent_before
    for line in describe(result, settings, workspace, spent):
        typer.echo(line)
    return True


def _hidden_tests(run: EvalRun, reader: PageSource, cutoff: float) -> HostileCheck:
    """The hidden instruction tests as the loop wants them: rules in, all resisted or not."""
    attacks = load_attacks()

    def check(rules: RulesFile) -> bool:
        results = run_attacks(
            attacks,
            run.models,
            all_questions(run.profile, rules),
            reader,
            run.settings,
            LOOP,
            profile=run.profile,
            cutoff=cutoff,
            tracer=run.tracer,
            now=now(),
        )
        return all(r.passed for r in results)

    return check


def describe(
    result: ImproveResult, settings: Settings, workspace: Workspace, spent: float
) -> list[str]:
    """What the run did, in plain words: each try, then why it stopped and what it cost."""
    lines: list[str] = []
    for number, t in enumerate(result.tries, start=1):
        lines += _try_lines(number, t)
    if result.stop_reason == "not_ready":
        yes = pile_report(workspace).piles["check"].yes
        lines.append(
            f"Not ready: the check pile has {yes} yes answers and needs "
            f"{settings.floor_yes_per_pile}. Keep marking."
        )
    else:
        lines.append(STOPPED[result.stop_reason])
    lines.append(f"Spent ${spent:.2f} on this run, scoring included.")
    return lines


def _try_lines(number: int, t: TryRecord) -> list[str]:
    lines = [f"Try {number}: {t.outcome.replace('_', ' ')}. {_what(t.change)}"]
    if t.check_before and t.check_after:
        lines.append(
            f"  Check pile: {t.check_before.correct} right before, {t.check_after.correct} after, "
            f"out of {t.check_after.n}."
        )
    if t.practice_before and t.practice_after:
        lines.append(
            f"  Practice pile: {t.practice_before.correct} right before, "
            f"{t.practice_after.correct} after, out of {t.practice_after.n}."
        )
    lines.append(f"  Because: {'; '.join(t.reasons)}. Cost ${t.cost_usd:.2f}.")
    return lines


def _what(change: RuleChange | None) -> str:
    if change is None:
        return "No change was proposed."
    if change.question is None:
        return f"Remove {change.question_id}."
    return f'{change.action.capitalize()}: "{change.question.text}"'
