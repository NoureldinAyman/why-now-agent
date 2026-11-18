"""The control pages, so nobody needs the terminal after entering keys: Runs, setup
status, settings and the profile.

Drafting and editing a profile work only on one's own computer. There the keys, the budget
and the profile files are the person's own. On AWS a profile is shown as a readable view and
uploaded from one's own computer. A run can be started on either: on AWS the page starts the
night run's task, and nothing else.
"""

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, cast, get_args

from fastapi import APIRouter, Form, HTTPException
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from why_now.ai import BadModelOutput
from why_now.ai.budget import BudgetExceeded
from why_now.domain import Profile
from why_now.drafting import Preview, preview
from why_now.profile import ProfileError, parse_profile, profile_text, quick_look_questions
from why_now.settings import Settings
from why_now.setup_check import check_setup
from why_now.web.app import AppContext
from why_now.web.routes_marking import (
    Reviewer,
    _choose_profile,
    _ctx,
    _form_page,
    _page,
    _profile_query,
    check_form_token,
)
from why_now.web.run_now import AlreadyRunning, Mode, RunNotStarted
from why_now.web.runs_view import next_run_at, run_row, shown_time, until
from why_now.workspace import Workspace
from why_now.workspace.settings_doc import EDITABLE, SettingsRefused, save_overrides

router = APIRouter()

IMPROVE_COMMAND = "improve"


def improve_exists() -> bool:
    """Whether the `why-now improve` command has been built yet."""
    from why_now.cli import app

    # A command registered without a name is named after its function, as typer does.
    return any(
        (c.name or getattr(c.callback, "__name__", "").replace("_", "-")) == IMPROVE_COMMAND
        for c in app.registered_commands
    )


def _local(ctx: AppContext) -> bool:
    return ctx.settings.deployment == "local"


def _can_run(ctx: AppContext) -> bool:
    return ctx.runner is not None


def _modes() -> list[str]:
    modes = [m for m in get_args(Mode) if m != "improve"]
    return [*modes, "improve"] if improve_exists() else modes


# Runs


@router.get("/run", response_class=HTMLResponse)
def run_page(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        return _page(request, "choose.html", profiles=list(ctx.profiles.values()), choose_to="/run")
    return _run_page(request, ctx, chosen)


def _run_page(
    request: Request,
    ctx: AppContext,
    chosen: Profile,
    problem: str | None = None,
    status: int = 200,
) -> Response:
    settings = ctx.settings
    now = ctx.clock()
    stale = timedelta(hours=settings.run_stale_hours)
    zone = settings.display_timezone
    workspace = Workspace(ctx.store)
    held = workspace.running(now, stale)
    rows = [
        run_row(n, now, stale, zone) for n in workspace.last_runs(chosen.id, settings.runs_shown)
    ]
    improve_row = next(
        (
            r
            for r in rows
            if r.note.mode in ("improve", "night") and (r.note.summary.tries or r.note.summary.stop)
        ),
        None,
    )
    schedule = None
    if settings.deployment == "aws":
        at = next_run_at(now, settings.aws_run_hour_utc)
        schedule = {"when": shown_time(at, zone), "zone": zone, "wait": until(at - now)}
    return _form_page(
        request,
        "run.html",
        status=status,
        profile=chosen,
        active="run",
        can_run=_can_run(ctx),
        local=_local(ctx),
        modes=_modes(),
        sample_boards=settings.run_now_sample_boards,
        state=ctx.runner.state() if ctx.runner is not None else None,
        going=None if held is None else run_row(held, now, stale, zone),
        rows=rows,
        improve_row=improve_row,
        schedule=schedule,
        night=[
            {"id": p.id, "name": p.product_name, "on": p.id in settings.nightly_profiles}
            for p in ctx.profiles.values()
        ],
        night_off=not settings.nightly_profiles,
        problem=problem,
        post_to="/run" + _profile_query(ctx, chosen),
        nightly_to="/run/nightly" + _profile_query(ctx, chosen),
    )


@router.post("/run", response_class=HTMLResponse)
def run_now(
    request: Request,
    _: Reviewer,
    profile: str | None = None,
    mode: Annotated[str, Form()] = "",
    form_token: Annotated[str, Form()] = "",
) -> Response:
    check_form_token(request, form_token)
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if not _can_run(ctx) or ctx.runner is None or chosen is None:
        raise HTTPException(status_code=404, detail="Starting a run is not set up here")
    if mode not in _modes():
        return _run_page(request, ctx, chosen, "Choose how to run.", status=422)
    stale = timedelta(hours=ctx.settings.run_stale_hours)
    if Workspace(ctx.store).running(ctx.clock(), stale) is not None:
        return _run_page(
            request, ctx, chosen, "A run is still going. Wait for it to finish.", status=409
        )
    try:
        ctx.runner.start(cast(Mode, mode), chosen.id, ctx.settings.run_now_sample_boards)
    except AlreadyRunning:
        return _run_page(
            request, ctx, chosen, "A run is still going. Wait for it to finish.", status=409
        )
    except RunNotStarted as e:
        return _run_page(request, ctx, chosen, str(e), status=502)
    return RedirectResponse("/run" + _profile_query(ctx, chosen), status_code=303)


@router.post("/run/nightly", response_class=HTMLResponse)
async def nightly_save(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    """Switch profiles on or off for the night run. Only the night list is stored here."""
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        raise HTTPException(status_code=404, detail="No such profile")
    problem = await _store_posted(request, ctx, frozenset({"nightly_profiles"}))
    if problem is not None:
        return _run_page(request, ctx, chosen, problem, status=422)
    return RedirectResponse("/run" + _profile_query(ctx, chosen), status_code=303)


# Setup status and settings


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, _: Reviewer) -> Response:
    ctx = _ctx(request)
    env = ctx.env if ctx.env is not None else os.environ
    items = check_setup(ctx.settings, env, list(ctx.profiles))
    return _page(request, "setup.html", active="setup", items=items, local=_local(ctx))


# Form fields that are not settings.
_FORM_ONLY = {"form_token", "nightly_listed"}
_NUMBERS = ("short_list_size", "hide_days", "judged_no_shown", "prepare_batch")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _: Reviewer) -> Response:
    return _settings_page(request, _ctx(request))


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request, _: Reviewer) -> Response:
    """Store the everyday limits in the workspace. Only the names in `EDITABLE` are ever
    stored: anything else posted refuses the whole form, so nothing is half saved."""
    ctx = _ctx(request)
    problem = await _store_posted(request, ctx, EDITABLE)
    if problem is not None:
        return _settings_page(request, ctx, problem, status=422)
    return RedirectResponse("/settings", status_code=303)


async def _store_posted(request: Request, ctx: AppContext, allowed: frozenset[str]) -> str | None:
    """Store the posted settings, which must all be in `allowed`. None when it worked, else
    what to tell the person, with nothing stored."""
    form = await request.form()
    check_form_token(request, str(form.get("form_token", "")))
    base: Settings = request.app.state.ctx.settings
    foreign = sorted(set(form.keys()) - allowed - _FORM_ONLY)
    if foreign:
        return f"{', '.join(foreign)} cannot be changed here. Nothing was saved."
    try:
        wanted = _posted_values(form, ctx)
        # Only what differs from the file is stored, so a later change to the file shows.
        stored = {name: value for name, value in wanted.items() if value != getattr(base, name)}
        save_overrides(ctx.store, base, stored)
    except SettingsRefused as e:
        return f"Nothing was saved. {e}."
    return None


def _posted_values(form: FormData, ctx: AppContext) -> dict[str, Any]:
    """The editable settings as posted, with the current value for any that was not posted."""
    values: dict[str, Any] = {name: getattr(ctx.settings, name) for name in EDITABLE}
    for name in _NUMBERS:
        if name in form:
            try:
                values[name] = int(str(form[name]).strip())
            except ValueError as e:
                raise SettingsRefused(f"{name} must be a whole number") from e
    if "reason_chips" in form:
        lines = (line.strip() for line in str(form["reason_chips"]).splitlines())
        values["reason_chips"] = [line for line in lines if line]
    if "nightly_listed" in form:
        ids = [str(i) for i in form.getlist("nightly_profiles")]
        unknown = [i for i in ids if i not in ctx.profiles]
        if unknown:
            raise SettingsRefused(f"no profile named {', '.join(unknown)} is in the workspace")
        values["nightly_profiles"] = ids
    return values


def _settings_page(
    request: Request, ctx: AppContext, problem: str | None = None, status: int = 200
) -> Response:
    settings = ctx.settings
    fields = Settings.model_fields
    limits = settings.editable_limits
    return _form_page(
        request,
        "settings.html",
        status=status,
        active="settings",
        problem=problem,
        numbers=[
            {
                "name": name,
                "value": getattr(settings, name),
                "low": limits[name][0] if name in limits else None,
                "high": limits[name][1] if name in limits else None,
                "why": fields[name].description or "",
            }
            for name in _NUMBERS
        ],
        chips_text="\n".join(settings.reason_chips),
        chips_why=fields["reason_chips"].description or "",
        chips_range=limits.get("reason_chips"),
        chip_chars=settings.reason_chip_max_chars,
        night_why=fields["nightly_profiles"].description or "",
        night=[
            {"id": p.id, "name": p.product_name, "on": p.id in settings.nightly_profiles}
            for p in ctx.profiles.values()
        ],
        rows=settings_rows(settings),
    )


def settings_rows(settings: Settings) -> list[dict[str, str]]:
    """Each read-only setting's name, value and reason, in the order they are written. The
    settings the page can change are in its form instead."""
    values = settings.model_dump(mode="json")
    return [
        {
            "name": name,
            "value": values[name] if isinstance(values[name], str) else json.dumps(values[name]),
            "why": field.description or "",
        }
        for name, field in Settings.model_fields.items()
        if name not in EDITABLE
    ]


# Profile


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        return _page(
            request, "choose.html", profiles=list(ctx.profiles.values()), choose_to="/profile"
        )
    return _profile_page(request, ctx, chosen, _current_text(ctx, chosen))


@router.post("/profile/preview", response_class=HTMLResponse)
def profile_preview(
    request: Request,
    _: Reviewer,
    profile: str | None = None,
    text: Annotated[str, Form()] = "",
    form_token: Annotated[str, Form()] = "",
) -> Response:
    """Check the text and show what it would find. Nothing is saved and nothing is paid for."""
    check_form_token(request, form_token)
    ctx, chosen = _profile_for_form(request, profile)
    try:
        edited = parse_profile(text, "in the box")
    except ProfileError as e:
        return _profile_page(request, ctx, chosen, text, problem=str(e), status=422)
    found = preview(Workspace(ctx.store), edited, ctx.settings)
    return _profile_page(request, ctx, chosen, text, found=found, edited=edited)


@router.post("/profile/draft", response_class=HTMLResponse)
def profile_draft(
    request: Request,
    _: Reviewer,
    profile: str | None = None,
    description: Annotated[str, Form()] = "",
    form_token: Annotated[str, Form()] = "",
) -> Response:
    """Draft a profile from a description into the box. One paid call. Nothing is saved."""
    check_form_token(request, form_token)
    ctx, chosen = _profile_for_form(request, profile)
    if not _local(ctx) or ctx.draft is None:
        raise HTTPException(status_code=404, detail="Drafting is not available here")
    current = _current_text(ctx, chosen)
    if not description.strip():
        return _profile_page(
            request, ctx, chosen, current, problem="Describe the product first.", status=422
        )
    try:
        drafted = ctx.draft(description.strip())
    except (BadModelOutput, BudgetExceeded, ProfileError) as e:
        return _profile_page(
            request, ctx, chosen, current, problem=f"No profile was drafted: {e}", status=500,
            description=description,
        )  # fmt: skip
    # The id names where this profile's marks are kept, so the draft keeps it.
    drafted = drafted.model_copy(update={"id": chosen.id})
    return _profile_page(
        request, ctx, chosen, profile_text(drafted), drafted=True, description=description
    )


@router.post("/profile/save", response_class=HTMLResponse)
def profile_save(
    request: Request,
    _: Reviewer,
    profile: str | None = None,
    text: Annotated[str, Form()] = "",
    form_token: Annotated[str, Form()] = "",
) -> Response:
    """Save the box to the workspace, once the loader accepts it, and to the profile file too
    when the profile came from one. Saving is the person's approval of what it says, the
    required questions above all."""
    check_form_token(request, form_token)
    ctx, chosen = _profile_for_form(request, profile)
    if not _local(ctx):
        raise HTTPException(status_code=404, detail="Profiles are edited on one's own computer")
    try:
        edited = parse_profile(text, "in the box")
    except ProfileError as e:
        return _profile_page(request, ctx, chosen, text, problem=str(e), status=422)
    if edited.id != chosen.id:
        problem = (
            f"The id must stay {chosen.id}: it names where this profile's marks are kept. "
            "For a new product, make a new profile file."
        )
        return _profile_page(request, ctx, chosen, text, problem=problem, status=422)
    Workspace(ctx.store).save_profile(edited, text)
    path = ctx.profile_files.get(chosen.id)
    if path is not None:
        _write(path, text)
    return RedirectResponse("/profile" + _profile_query(ctx, edited), status_code=303)


def _profile_for_form(request: Request, requested: str | None) -> tuple[AppContext, Profile]:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, requested)
    if chosen is None:
        raise HTTPException(status_code=404, detail="No such profile")
    return ctx, chosen


def _current_text(ctx: AppContext, chosen: Profile) -> str:
    return Workspace(ctx.store).profile_text(chosen.id) or profile_text(chosen)


def _write(path: Path, text: str) -> None:
    """Write the whole file or nothing, so a crash part way cannot leave half a profile."""
    swap = path.with_name(path.name + ".saving")
    swap.write_text(text, encoding="utf-8", newline="\n")
    swap.replace(path)


def _profile_page(
    request: Request,
    ctx: AppContext,
    chosen: Profile,
    text: str,
    problem: str | None = None,
    status: int = 200,
    found: Preview | None = None,
    edited: Profile | None = None,
    drafted: bool = False,
    description: str = "",
) -> Response:
    local = _local(ctx)
    marked = any(True for _ in Workspace(ctx.store, chosen.id).marks("first"))
    return _form_page(
        request,
        "profile.html",
        status=status,
        profile=chosen,
        active="profile",
        text=text,
        problem=problem,
        preview=found,
        quick_look=quick_look_questions(edited) if edited is not None else None,
        own_quick_look=bool(edited and edited.quick_look_questions),
        version=chosen.version,
        new_version=edited is not None and edited.version != chosen.version,
        drafted=drafted,
        description=description,
        can_save=local,
        can_draft=local and ctx.draft is not None,
        marked=marked,
        query=_profile_query(ctx, chosen),
        path=str(ctx.profile_files.get(chosen.id, "")),
    )
