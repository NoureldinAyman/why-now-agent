"""The marking pages: the reviewer answers yes, no or can't tell from the evidence pack alone.

Nothing the agent thinks reaches these pages. They read only the case, its frozen evidence
pack and the reviewer's own marks, so there is no agent answer in reach to leak.
"""

import secrets
from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Final, get_args

from fastapi import APIRouter, Depends, Form, HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from why_now.domain import CaseRecord, Mark, Profile, Source
from why_now.web.app import AppContext
from why_now.web.auth import SignInPages
from why_now.workspace import Workspace

router = APIRouter()

ROUND: Final = "first"
TOKEN_NAME: Final = "form_token"
ANSWERS: Final = get_args(Mark.model_fields["answer"].annotation)


def signed_in(request: Request) -> str:
    auth = request.app.state.auth
    user = auth.current_user(request)
    if user is None:
        # A page visit goes to the sign-in page. A sent form is refused, not redirected,
        # so its contents are never carried through a sign-in.
        if request.method == "GET" and isinstance(auth, SignInPages):
            raise HTTPException(status_code=303, headers={"Location": auth.login_path})
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


Reviewer = Annotated[str, Depends(signed_in)]


@dataclass
class Progress:
    yes: int
    no: int
    cant_tell: int
    left: int

    @property
    def marked(self) -> int:
        return self.yes + self.no + self.cant_tell


@router.get("/mark", response_class=HTMLResponse)
def next_case(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        return _page(request, "choose.html", profiles=list(ctx.profiles.values()))
    workspace = Workspace(ctx.store, chosen.id)
    waiting = _waiting(workspace)
    if not waiting:
        return _page(request, "mark_done.html", profile=chosen, progress=_progress(workspace))
    return _show_case(request, workspace, chosen, waiting[0])


@router.get("/mark/progress", response_class=HTMLResponse)
def progress(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        return _page(request, "choose.html", profiles=list(ctx.profiles.values()))
    workspace = Workspace(ctx.store, chosen.id)
    return _page(
        request,
        "progress.html",
        profile=chosen,
        progress=_progress(workspace),
        ceiling=ctx.settings.marking_ceiling,
    )


@router.post("/mark/{case_id}", response_class=HTMLResponse)
def save_mark(
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

    reason = reason.strip()
    error = form_error(answer, reason)
    if error is not None:
        return _show_case(request, workspace, profile, case, error, answer, reason, status=422)

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
    return RedirectResponse(_mark_url(ctx, profile), status_code=303)


def check_form_token(request: Request, form_token: str) -> None:
    """Refuse a save whose form token does not match the browser's cookie."""
    expected = request.cookies.get(TOKEN_NAME, "")
    if not expected or not secrets.compare_digest(form_token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="The form has expired. Go back and reload it.")


def form_error(answer: str, reason: str) -> str | None:
    """What is wrong with a submitted answer and reason, or None if both are fine."""
    if answer not in ANSWERS:
        return "Choose yes, no or can't tell."
    if not reason:
        return "Give a reason, even a short one."
    return None


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def _choose_profile(ctx: AppContext, requested: str | None) -> Profile | None:
    """The profile asked for, or the only one. None means the reviewer must choose."""
    if requested is not None:
        if requested not in ctx.profiles:
            raise HTTPException(status_code=404, detail="No such profile")
        return ctx.profiles[requested]
    if len(ctx.profiles) == 1:
        return next(iter(ctx.profiles.values()))
    return None


def _profile_query(ctx: AppContext, profile: Profile) -> str:
    """The part of a link that names the profile. Only needed when there are several."""
    return "" if len(ctx.profiles) == 1 else f"?profile={profile.id}"


def _mark_url(ctx: AppContext, profile: Profile) -> str:
    return "/mark" + _profile_query(ctx, profile)


def _find_case(ctx: AppContext, case_id: str) -> tuple[Workspace, Profile, CaseRecord] | None:
    for profile in ctx.profiles.values():
        workspace = Workspace(ctx.store, profile.id)
        for case in workspace.cases():
            if case.case_id == case_id and case.pack_id is not None:
                return workspace, profile, case
    return None


def _waiting(workspace: Workspace) -> list[CaseRecord]:
    """Cases with a pack and no mark yet. Their order is the order of their ids, which are
    hashes, so it has no pattern the reviewer could be led by."""
    done = {m.case_id for m in workspace.marks(ROUND)}
    return [c for c in workspace.cases() if c.pack_id is not None and c.case_id not in done]


def _progress(workspace: Workspace) -> Progress:
    given = Counter(m.answer for m in workspace.marks(ROUND))
    return Progress(
        yes=given["yes"],
        no=given["no"],
        cant_tell=given["cant_tell"],
        left=len(_waiting(workspace)),
    )


def _show_case(
    request: Request,
    workspace: Workspace,
    profile: Profile,
    case: CaseRecord,
    error: str | None = None,
    answer: str = "",
    reason: str = "",
    status: int = 200,
    progress: Progress | None = None,
    post_to: str | None = None,
    repeating: bool = False,
) -> Response:
    pack = workspace.load_pack(case.pack_id) if case.pack_id else None
    if pack is None:
        raise HTTPException(status_code=404, detail="This case has no evidence pack yet")
    token = request.cookies.get(TOKEN_NAME) or secrets.token_urlsafe()
    response = _page(
        request,
        "mark.html",
        status=status,
        profile=profile,
        case=case,
        pack=pack,
        sources=[_source_view(s) for s in pack.sources],
        progress=progress or _progress(workspace),
        post_to=post_to or f"/mark/{case.case_id}",
        repeating=repeating,
        form_token=token,
        error=error,
        answer=answer,
        reason=reason,
    )
    if token != request.cookies.get(TOKEN_NAME):
        response.set_cookie(
            TOKEN_NAME,
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
    return response


def _source_view(source: Source) -> dict[str, object]:
    """What the page shows of one source. Its address is a link only if it is a web address."""
    is_web = source.url.lower().startswith(("http://", "https://"))
    return {
        "kind": "Job ad" if source.kind == "job_ad" else "Web page",
        "url": source.url,
        "href": source.url if is_web else None,
        "text": source.text,
    }


def _page(
    request: Request,
    template: str,
    status: int = 200,
    profile: Profile | None = None,
    **values: object,
) -> Response:
    suffix = "" if profile is None else _profile_query(_ctx(request), profile)
    links = {
        "mark_link": "/mark" + suffix,
        "progress_link": "/mark/progress" + suffix,
        "repeat_link": "/repeat" + suffix,
    }
    html = request.app.state.templates.get_template(template).render(
        profile=profile, **links, **values
    )
    return HTMLResponse(html, status_code=status)
