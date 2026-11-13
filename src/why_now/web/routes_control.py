"""The control pages, so nobody needs the terminal after entering keys: Run now, setup
status, settings and the profile.

Running, drafting and saving a profile work only on one's own computer. There the keys,
the budget and the profile files are the person's own. On AWS the scheduled run does the
work, and a profile is changed in its file and deployed.
"""

import json
import os
from pathlib import Path
from typing import Annotated, get_args

from fastapi import APIRouter, Form, HTTPException
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
from why_now.web.run_now import AlreadyRunning, Mode
from why_now.workspace import Workspace

router = APIRouter()

IMPROVE_COMMAND = "improve"


def improve_exists() -> bool:
    """Whether the `why-now improve` command has been built yet."""
    from why_now.cli import app

    return any(c.name == IMPROVE_COMMAND for c in app.registered_commands)


def _local(ctx: AppContext) -> bool:
    return ctx.settings.deployment == "local"


def _can_run(ctx: AppContext) -> bool:
    return _local(ctx) and ctx.runner is not None


def _modes() -> list[str]:
    modes = [m for m in get_args(Mode) if m != "improve"]
    return [*modes, "improve"] if improve_exists() else modes


# Run now


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
    state = ctx.runner.state() if ctx.runner is not None else None
    return _form_page(
        request,
        "run.html",
        status=status,
        profile=chosen,
        active="run",
        can_run=_can_run(ctx) and chosen.id in ctx.profile_files,
        modes=_modes(),
        sample_boards=ctx.settings.run_now_sample_boards,
        state=state,
        problem=problem,
        post_to="/run" + _profile_query(ctx, chosen),
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
        raise HTTPException(status_code=404, detail="Run now is only on one's own computer")
    profile_file = ctx.profile_files.get(chosen.id)
    if profile_file is None:
        raise HTTPException(status_code=404, detail="This profile has no file to run")
    if mode not in _modes():
        return _run_page(request, ctx, chosen, "Choose how to run.", status=422)
    try:
        ctx.runner.start(mode, profile_file, ctx.settings.run_now_sample_boards)  # type: ignore[arg-type]
    except AlreadyRunning:
        return _run_page(
            request, ctx, chosen, "A run is still going. Wait for it to finish.", status=409
        )
    return RedirectResponse("/run" + _profile_query(ctx, chosen), status_code=303)


# Setup status and settings


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, _: Reviewer) -> Response:
    ctx = _ctx(request)
    env = ctx.env if ctx.env is not None else os.environ
    items = check_setup(ctx.settings, env)
    return _page(request, "setup.html", active="setup", items=items, local=_local(ctx))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _: Reviewer) -> Response:
    settings = _ctx(request).settings
    return _page(request, "settings.html", active="settings", rows=settings_rows(settings))


def settings_rows(settings: Settings) -> list[dict[str, str]]:
    """Each setting's name, value and reason, in the order they are written."""
    values = settings.model_dump(mode="json")
    return [
        {
            "name": name,
            "value": values[name] if isinstance(values[name], str) else json.dumps(values[name]),
            "why": field.description or "",
        }
        for name, field in Settings.model_fields.items()
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
    path = ctx.profile_files.get(chosen.id)
    text = path.read_text(encoding="utf-8") if path is not None else profile_text(chosen)
    return _profile_page(request, ctx, chosen, text)


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
    shown = preview(Workspace(ctx.store), edited, ctx.settings)
    return _profile_page(request, ctx, chosen, text, shown=shown, checked=edited)


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
    """Save the box to the profile file, once the loader accepts it. Saving is the person's
    approval of what it says, the required questions above all."""
    check_form_token(request, form_token)
    ctx, chosen = _profile_for_form(request, profile)
    path = ctx.profile_files.get(chosen.id)
    if not _local(ctx) or path is None:
        raise HTTPException(status_code=404, detail="Profiles are edited on one's own computer")
    try:
        edited = parse_profile(text, str(path))
    except ProfileError as e:
        return _profile_page(request, ctx, chosen, text, problem=str(e), status=422)
    if edited.id != chosen.id:
        problem = (
            f"The id must stay {chosen.id}: it names where this profile's marks are kept. "
            "For a new product, make a new profile file."
        )
        return _profile_page(request, ctx, chosen, text, problem=problem, status=422)
    _write(path, text)
    ctx.profiles[chosen.id] = edited
    return RedirectResponse("/profile" + _profile_query(ctx, edited), status_code=303)


def _profile_for_form(request: Request, requested: str | None) -> tuple[AppContext, Profile]:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, requested)
    if chosen is None:
        raise HTTPException(status_code=404, detail="No such profile")
    return ctx, chosen


def _current_text(ctx: AppContext, chosen: Profile) -> str:
    path = ctx.profile_files.get(chosen.id)
    return path.read_text(encoding="utf-8") if path is not None else profile_text(chosen)


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
    shown: Preview | None = None,
    checked: Profile | None = None,
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
        preview=shown,
        quick_look=quick_look_questions(checked) if checked is not None else None,
        own_quick_look=bool(checked and checked.quick_look_questions),
        version=chosen.version,
        new_version=checked is not None and checked.version != chosen.version,
        drafted=drafted,
        description=description,
        can_save=local and chosen.id in ctx.profile_files,
        can_draft=local and ctx.draft is not None,
        marked=marked,
        query=_profile_query(ctx, chosen),
        path=str(ctx.profile_files.get(chosen.id, "")),
    )
