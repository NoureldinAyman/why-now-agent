"""The repeat marking page: the reviewer marks some companies a second time, about a week
later. It shows the evidence pack alone. It never reads the first-round marks for display,
so the first answer and its reason cannot reach the page."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from why_now.domain import CaseRecord, Mark, Profile
from why_now.web.routes_marking import (
    Progress,
    Reviewer,
    _choose_profile,
    _ctx,
    _find_case,
    _page,
    _profile_query,
    _show_case,
    check_form_token,
    form_error,
)
from why_now.workspace import Workspace

router = APIRouter()

ROUND = "repeat"


@router.get("/repeat", response_class=HTMLResponse)
def next_repeat(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        return _page(request, "choose.html", profiles=list(ctx.profiles.values()))
    workspace = Workspace(ctx.store, chosen.id)
    if workspace.repeat_selection() is None:
        return _page(request, "repeat_none.html", profile=chosen)
    waiting = _waiting(workspace)
    if not waiting:
        return _page(request, "repeat_done.html", profile=chosen)
    return _show_repeat(request, workspace, chosen, waiting[0])


@router.post("/repeat/{case_id}", response_class=HTMLResponse)
def save_repeat(
    request: Request,
    case_id: str,
    _: Reviewer,
    answer: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
    form_token: Annotated[str, Form()] = "",
) -> Response:
    check_form_token(request, form_token)
    ctx = _ctx(request)
    found = _find_case(ctx, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such case")
    workspace, profile, case = found
    if case.case_id not in (workspace.repeat_selection() or []):
        raise HTTPException(status_code=404, detail="This case was not picked to be marked again")

    reason = reason.strip()
    error = form_error(answer, reason)
    if error is not None:
        return _show_repeat(request, workspace, profile, case, error, answer, reason, 422)

    mark = Mark.model_validate(
        {
            "case_id": case.case_id,
            "answer": answer,
            "reason": reason,
            "marked_at": ctx.clock(),
            "round": ROUND,
        }
    )
    workspace.save_mark(mark)  # a second copy of the same form changes nothing
    return RedirectResponse("/repeat" + _profile_query(ctx, profile), status_code=303)


def _show_repeat(
    request: Request,
    workspace: Workspace,
    profile: Profile,
    case: CaseRecord,
    error: str | None = None,
    answer: str = "",
    reason: str = "",
    status: int = 200,
) -> Response:
    return _show_case(
        request, workspace, profile, case, error, answer, reason, status,
        progress=_progress(workspace), post_to=f"/repeat/{case.case_id}", repeating=True,
    )  # fmt: skip


def _waiting(workspace: Workspace) -> list[CaseRecord]:
    """Picked cases not yet marked again, in the order of their ids."""
    picked = set(workspace.repeat_selection() or [])
    done = {m.case_id for m in workspace.marks(ROUND)}
    return [c for c in workspace.cases() if c.case_id in picked - done and c.pack_id is not None]


def _progress(workspace: Workspace) -> Progress:
    """Counts of the repeat round only. They are the reviewer's own second answers."""
    marks = workspace.marks(ROUND)
    return Progress(
        yes=sum(m.answer == "yes" for m in marks),
        no=sum(m.answer == "no" for m in marks),
        cant_tell=sum(m.answer == "cant_tell" for m in marks),
        left=len(_waiting(workspace)),
    )
