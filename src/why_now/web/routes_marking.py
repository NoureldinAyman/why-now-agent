"""The marking pages: the reviewer answers yes, no or can't tell from the evidence pack alone.

Nothing the agent thinks reaches these pages. They read only the case, its frozen evidence
pack and the reviewer's own marks, so there is no agent answer in reach to leak.
"""

import secrets
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Final, Literal, get_args

from fastapi import APIRouter, Depends, Form, HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from why_now.domain import CaseRecord, Mark, Profile, Source
from why_now.testset.packs import SEED_LIMIT, card
from why_now.testset.repeat import can_repeat
from why_now.web.app import AppContext
from why_now.web.auth import SignInPages
from why_now.workspace import Workspace

router = APIRouter()

ROUND: Final = "first"
TOKEN_NAME: Final = "form_token"
ANSWERS: Final = get_args(Mark.model_fields["answer"].annotation)

# Held while companies are being prepared, so a second press, or a second tab, cannot start
# a second run that researches and pays for the same companies. It covers one process, which
# is how the page runs on one's own computer.
_PREPARING = threading.Lock()


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
        return _form_page(
            request,
            "mark_done.html",
            profile=chosen,
            progress=_progress(workspace),
            repeat_nudge=_repeat_nudge(ctx, workspace),
        )
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


@router.post("/prepare", response_class=HTMLResponse)
def prepare_now(
    request: Request,
    _: Reviewer,
    seed: Annotated[int, Form(ge=0, lt=SEED_LIMIT)],
    profile: str | None = None,
    form_token: Annotated[str, Form()] = "",
) -> Response:
    """Prepare companies now, and wait for it. It costs money, so only on one's own computer."""
    check_form_token(request, form_token)
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if not _can_prepare(ctx) or ctx.prepare is None or chosen is None:
        raise HTTPException(status_code=404, detail="Preparing is not available here")
    if not _PREPARING.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Companies are already being prepared")
    # The page offers to finish a stopped run with the same seed, so it carries both along.
    again = {"seed": seed, "form_token": form_token}
    try:
        result = ctx.prepare(chosen, ctx.settings.prepare_batch, seed)
    except Exception as e:  # shown as text, so a missing key or a failed read is not a blank page
        return _page(
            request, "prepared.html", status=500, profile=chosen, result=None,
            problem=f"{type(e).__name__}: {e}", **again,
        )  # fmt: skip
    finally:
        _PREPARING.release()
    return _page(request, "prepared.html", profile=chosen, result=result, problem=None, **again)


@router.post("/mark/{case_id}", response_class=HTMLResponse)
def save_mark(
    request: Request,
    case_id: str,
    _: Reviewer,
    answer: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
    chips: Annotated[list[str] | None, Form()] = None,
    form_token: Annotated[str, Form()] = "",
) -> Response:
    check_form_token(request, form_token)
    ctx = _ctx(request)
    found = _find_case(ctx, case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such case")
    workspace, profile, case = found

    reason, picked, error = read_form(ctx, answer, reason, chips)
    if error is not None:
        return _show_case(request, workspace, profile, case, error, reason, picked, status=422)

    # A second copy of the same form changes nothing.
    workspace.save_mark(new_mark(ctx, workspace, case, answer, reason, picked, ROUND))
    return RedirectResponse(_mark_url(ctx, profile), status_code=303)


def check_form_token(request: Request, form_token: str) -> None:
    """Refuse a save whose form token does not match the browser's cookie."""
    expected = request.cookies.get(TOKEN_NAME, "")
    if not expected or not secrets.compare_digest(form_token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="The form has expired. Go back and reload it.")


def read_form(
    ctx: AppContext, answer: str, reason: str, chips: list[str] | None
) -> tuple[str, list[str], str | None]:
    """The reason and chips of a sent mark form, tidied, and what is wrong with it if anything.
    Both the marking and the repeat page read their form here, so they cannot drift apart."""
    reason, picked = tidy_reason(reason, chips)
    return reason, picked, form_error(answer, reason, picked, ctx.settings.reason_chips)


def tidy_reason(reason: str, chips: list[str] | None) -> tuple[str, list[str]]:
    """The sentence without stray spacing, and each chip once, in the order sent."""
    return reason.strip(), list(dict.fromkeys(chips or []))


def form_error(answer: str, reason: str, chips: list[str], allowed: list[str]) -> str | None:
    """What is wrong with a submitted answer and reason, or None if all is fine."""
    if answer not in ANSWERS:
        return "Choose yes, no or can't tell."
    return reason_error(reason, chips, allowed)


def reason_error(reason: str, chips: list[str], allowed: list[str]) -> str | None:
    """What is wrong with a reason, or None if it is fine. A reason is one or more chips from
    the list, a sentence, or both, and at least one is needed. Marks and decisions share it."""
    if any(chip not in allowed for chip in chips):
        return "One of the reasons is not on the list. Pick from the short choices."
    if not reason and not chips:
        return "Give a reason: tap a short choice or write a sentence."
    return None


def new_mark(
    ctx: AppContext,
    workspace: Workspace,
    case: CaseRecord,
    answer: str,
    reason: str,
    chips: list[str],
    round: Literal["first", "repeat"],
) -> Mark:
    """The mark for a checked answer, noting whether the company was on a daily list before."""
    now = ctx.clock()
    return Mark.model_validate(
        {
            "case_id": case.case_id,
            "answer": answer,
            "reason": reason,
            "chips": chips,
            "seen_on_list": workspace.was_listed(case.company_key, now),
            "marked_at": now,
            "round": round,
        }
    )


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


def _repeat_nudge(ctx: AppContext, workspace: Workspace) -> str | None:
    """A line suggesting a repeat round when one can be picked, and none has been yet."""
    if workspace.repeat_selection() is not None:
        return None
    settings = ctx.settings
    ready = can_repeat(workspace.marks(ROUND), ctx.clock().date(), settings.remark_after_days)
    if len(ready) < settings.remark_size:
        return None
    return (
        f"{len(ready)} companies were marked yes or no at least {settings.remark_after_days} days "
        f"ago and can be marked again, which measures how consistent you are. It is optional. "
        f"Pick {settings.remark_size} with why-now repeat-marks, then mark them again."
    )


def _progress(workspace: Workspace) -> Progress:
    given = Counter(m.answer for m in workspace.marks(ROUND))
    return Progress(
        yes=given["yes"],
        no=given["no"],
        cant_tell=given["cant_tell"],
        left=len(_waiting(workspace)),
    )


def _can_prepare(ctx: AppContext) -> bool:
    return ctx.prepare is not None and ctx.settings.deployment == "local"


def _show_case(
    request: Request,
    workspace: Workspace,
    profile: Profile,
    case: CaseRecord,
    error: str | None = None,
    reason: str = "",
    chips: list[str] | None = None,
    status: int = 200,
    progress: Progress | None = None,
    post_to: str | None = None,
    repeating: bool = False,
) -> Response:
    pack = workspace.load_pack(case.pack_id) if case.pack_id else None
    if pack is None:
        raise HTTPException(status_code=404, detail="This case has no evidence pack yet")
    return _form_page(
        request,
        "mark.html",
        status=status,
        profile=profile,
        case=case,
        card=card(case, pack, _ctx(request).settings),
        sources=[_source_view(s) for s in pack.sources],
        progress=progress or _progress(workspace),
        post_to=post_to or f"/mark/{case.case_id}",
        repeating=repeating,
        error=error,
        reason=reason,
        chips=chips or [],
        repeat_nudge=None if repeating else _repeat_nudge(_ctx(request), workspace),
        all_chips=_ctx(request).settings.reason_chips,
    )


def _form_page(
    request: Request,
    template: str,
    status: int = 200,
    profile: Profile | None = None,
    **values: object,
) -> Response:
    """A page with a form on it: it carries the form token, and the Prepare form when it
    is available. The browser keeps the token in a cookie, which the sent form must match."""
    ctx = _ctx(request)
    token = request.cookies.get(TOKEN_NAME) or secrets.token_urlsafe()
    response = _page(
        request,
        template,
        status,
        profile,
        form_token=token,
        can_prepare=_can_prepare(ctx),
        prepare_batch=ctx.settings.prepare_batch,
        prepare_seed=secrets.randbelow(SEED_LIMIT),  # fixed by the page, so a second press of the
        # same form asks for the same companies and pays for nothing twice
        **values,
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
    return {
        "kind": "Job ad" if source.kind == "job_ad" else "Web page",
        "url": source.url,
        "href": _web_href(source.url),
        "text": source.text,
    }


def _web_href(url: str) -> str | None:
    """The address as a link target, or None unless it is a web address. A page read from the
    internet could hold any text as an address, so nothing else becomes a link."""
    return url if url.lower().startswith(("http://", "https://")) else None


def _page(
    request: Request,
    template: str,
    status: int = 200,
    profile: Profile | None = None,
    **values: object,
) -> Response:
    suffix = "" if profile is None else _profile_query(_ctx(request), profile)
    links = {
        "review_link": "/" + suffix,
        "more_link": "/more" + suffix,
        "spending_link": "/spending" + suffix,
        "mark_link": "/mark" + suffix,
        "progress_link": "/mark/progress" + suffix,
        "prepare_link": "/prepare" + suffix,
        "repeat_link": "/repeat" + suffix,
    }
    html = request.app.state.templates.get_template(template).render(
        profile=profile, **links, **values
    )
    return HTMLResponse(html, status_code=status)
