"""`why-now prepare`, `pick-cases` and `build-packs`: make a profile's test cases."""

import os
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from why_now.ai import Models, ResearchModel, build_models
from why_now.ai.budget import Meter
from why_now.cli import app
from why_now.deployment import open_store
from why_now.domain import Profile
from why_now.pipeline.reader import PageReader
from why_now.pipeline.search import search_ads
from why_now.profile import ProfileError, load_profile
from why_now.run_context import RunContext
from why_now.settings import Settings, load_settings
from why_now.store import Store
from why_now.testset.packs import SEED_LIMIT, BuildResult, build_packs, new_case, prepare
from why_now.testset.picking import eligible_companies, pick_cases
from why_now.testset.piles import pile_sizes
from why_now.tracing import UnitCounter, build_tracer
from why_now.workspace import Workspace

DEFAULT_SETTINGS = Path("settings.toml")

ProfileOption = Annotated[Path, typer.Option("--profile", help="Profile file the cases are for.")]
SettingsOption = Annotated[
    Path | None,
    typer.Option("--settings", help="Settings file. Defaults to settings.toml if present."),
]


def now() -> datetime:
    return datetime.now(UTC)


def make_models(settings: Settings, meter: Meter) -> Models:
    return build_models(settings, meter, os.environ)


def make_research(settings: Settings, meter: Meter) -> ResearchModel:
    return make_models(settings, meter).research


def make_reader(settings: Settings) -> PageReader:
    return PageReader(httpx.Client(trust_env=False), settings)


def run_prepare(
    settings: Settings, store: Store, profile: Profile, n: int, seed: int
) -> BuildResult:
    """Prepare companies with the real models and page reader. The command and the marking
    page's button both come here, so they do the same thing."""
    meter = Meter(store, settings, now)
    reader = make_reader(settings)
    ctx = RunContext(
        settings=settings,
        store=store,
        sources=[],
        boards={},
        models=make_models(settings, meter),
        reader=reader,
        meter=meter,
        tracer=build_tracer(
            settings.workspace_path / "traces", UnitCounter(store, settings, now), now, os.environ
        ),
        clock=now,
    )
    with reader.http:
        return prepare(ctx, profile, n, seed)


@app.command("prepare")
def prepare_command(
    profile_file: ProfileOption,
    n: Annotated[
        int | None,
        typer.Option(
            "--n", min=1, help="How many companies to prepare. Defaults to prepare_batch."
        ),
    ] = None,
    seed: Annotated[
        int | None,
        typer.Option(help="Seed for the random pick. It is recorded. Defaults to a new one."),
    ] = None,
    settings_file: SettingsOption = None,
) -> None:
    """Pick companies at random, decide their piles and research each, ready to mark."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    n = settings.prepare_batch if n is None else n
    # A new seed each time, so asking again prepares more. Say it, so a stop can be finished.
    seed = random.SystemRandom().randrange(SEED_LIMIT) if seed is None else seed
    again = any(p.seed == seed and p.n == n for p in workspace.picks())
    result = run_prepare(settings, workspace.store, profile, n, seed)
    if again:
        typer.echo(f"{n} companies were already picked with seed {seed}. Finishing any left.")
    elif result.eligible == 0:
        typer.echo(
            f"No company has a relevant ad in the last {settings.new_ad_days} days. "
            "Read job ads first with why-now read."
        )
    else:
        typer.echo(
            f"Picked {result.picked} of {result.eligible} companies with a relevant ad in the "
            f"last {settings.new_ad_days} days, with seed {seed}."
        )
        if result.picked < n:
            typer.echo(f"Only {result.picked} could be picked, fewer than the {n} asked for.")
    typer.echo(f"Built {result.built} evidence packs.")
    for case_id, reason in result.failed.items():
        typer.echo(f"  {case_id} failed: {reason}. It is kept and tried again next time.")
    if result.stopped:
        typer.echo(
            f"{result.stopped} {result.left} companies are left. Run again with --n {n} "
            f"--seed {seed} to finish them."
        )
        raise typer.Exit(1)
    if not again and result.eligible == 0 and result.built == 0:
        raise typer.Exit(1)  # nothing was picked and nothing was built


@app.command("pick-cases")
def pick_cases_command(
    profile_file: ProfileOption,
    n: Annotated[int, typer.Option("--n", min=1, help="How many companies to pick.")],
    seed: Annotated[int, typer.Option(help="Seed for the random pick. It is recorded.")],
    settings_file: SettingsOption = None,
) -> None:
    """Pick companies at random from everyone with a relevant ad in the window."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    companies = search_ads(workspace.all_board_ads(), profile, {})
    eligible = eligible_companies(companies, settings, now().date())
    picked_before = {c.company_key for c in workspace.cases()}
    picked = pick_cases(eligible, n, seed, picked_before)
    for company in picked:
        workspace.save_case(new_case(profile.id, company, seed, settings), company)
    workspace.record_pick(seed, n, pile_sizes(settings), [c.key for c in picked], now())
    typer.echo(
        f"Picked {len(picked)} of {len(eligible)} companies with a relevant ad in the last "
        f"{settings.new_ad_days} days, with seed {seed}. {len(picked_before)} were picked before."
    )
    if len(picked) < n:
        typer.echo(f"Only {len(picked)} could be picked, fewer than the {n} asked for.")


@app.command("build-packs")
def build_packs_command(profile_file: ProfileOption, settings_file: SettingsOption = None) -> None:
    """Research each picked company once and save its frozen evidence pack."""
    settings, workspace, profile = open_workspace(profile_file, settings_file)
    store = workspace.store
    cases = workspace.cases()
    if not cases:
        typer.echo("No test cases yet. Run pick-cases first.")
        return
    tracer = build_tracer(
        settings.workspace_path / "traces", UnitCounter(store, settings, now), now, os.environ
    )
    reader = make_reader(settings)
    with reader.http:
        result = build_packs(
            cases,
            workspace,
            profile,
            make_research(settings, Meter(store, settings, now)),
            reader,
            settings,
            tracer,
            clock=now,
        )
    typer.echo(
        f"Built {result.built} evidence packs. {result.already_built} were built before, "
        "and were not paid for again."
    )
    for case_id, reason in result.failed.items():
        typer.echo(f"  {case_id} failed: {reason}. It is kept and tried again next time.")
    if result.stopped:
        typer.echo(f"{result.stopped} {result.left} cases are left. Run build-packs again later.")
        raise typer.Exit(1)


def open_workspace(
    profile_file: Path, settings_file: Path | None
) -> tuple[Settings, Workspace, Profile]:
    if settings_file is None and DEFAULT_SETTINGS.is_file():
        settings_file = DEFAULT_SETTINGS
    settings = load_settings(settings_file)
    try:
        profile = load_profile(profile_file)
    except ProfileError as e:
        raise typer.BadParameter(str(e), param_hint="--profile") from e
    return settings, Workspace(open_store(settings), profile.id), profile
