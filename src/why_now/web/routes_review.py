"""The review pages: the short list, the more list, decisions and spending.

Approving only records a decision. Nothing is sent to anyone from here.
"""

import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Final, Literal, TypedDict
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from why_now.ai.budget import LOOP
from why_now.day_result import ListEntry
from why_now.domain import Claim, Decision, Profile, Source
from why_now.evaluation.short_list import ShortListPrecision, short_list_precision
from why_now.web.app import AppContext
from why_now.web.routes_marking import (
    Reviewer,
    _choose_profile,
    _ctx,
    _form_page,
    _page,
    _profile_query,
    _web_href,
    check_form_token,
    reason_error,
    tidy_reason,
)
from why_now.workspace import Workspace

router = APIRouter()

Which = Literal["short", "more"]
CHOICES: Final = {"approve": True, "reject": False}

# Held while a decision is checked and saved, so two copies of one form sent at the same
# moment cannot both pass the check. It covers one process, which is how the page runs.
_DECIDING = threading.Lock()


@dataclass
class Attempt:
    """A decision form that was sent back with a problem, so the page can show it again."""

    company_key: str
    error: str
    reason: str
    chips: list[str] = field(default_factory=list)


@router.get("/", response_class=HTMLResponse)
def short_list(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    return _show_list(request, "short", profile)


@router.get("/more", response_class=HTMLResponse)
def more_list(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    return _show_list(request, "more", profile)


@router.get("/spending", response_class=HTMLResponse)
def spending(request: Request, _: Reviewer, profile: str | None = None) -> Response:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        return _page(
            request, "choose.html", profiles=list(ctx.profiles.values()), choose_to="/spending"
        )
    workspace = Workspace(ctx.store, chosen.id)
    return _page(request, "spending.html", profile=chosen, **_status(ctx, workspace))


@router.post("/decide/{company_key}", response_class=HTMLResponse)
def decide(
    request: Request,
    company_key: str,
    _: Reviewer,
    profile: str | None = None,
    decision: Annotated[str, Form()] = "",
    from_list: Annotated[str, Form()] = "short",
    reason: Annotated[str, Form()] = "",
    chips: Annotated[list[str] | None, Form()] = None,
    form_token: Annotated[str, Form()] = "",
) -> Response:
    check_form_token(request, form_token)
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, profile)
    if chosen is None:
        raise HTTPException(status_code=404, detail="No such profile")
    workspace = Workspace(ctx.store, chosen.id)
    reason, picked = tidy_reason(reason, chips)
    with _DECIDING:
        found = _waiting(workspace, company_key, "more" if from_list == "more" else "short")
        if found is None:
            if workspace.hidden_until(company_key, ctx.settings.hide_days) is None:
                raise HTTPException(status_code=404, detail="That company is not on a list")
            # The company has been decided already, so this is the same form sent again.
            return RedirectResponse("/" + _profile_query(ctx, chosen), status_code=303)
        which, entry = found
        error = (
            "Choose approve or reject."
            if decision not in CHOICES
            else reason_error(reason, picked, ctx.settings.reason_chips)
        )
        if error is not None:
            attempt = Attempt(company_key, error, reason, picked)
            return _show_list(request, which, chosen.id, attempt, status=422)
        workspace.save_decision(
            Decision(
                profile_id=chosen.id,
                company_key=entry.company_key,
                approved=CHOICES[decision],
                reason=reason,
                chips=picked,
                decided_at=ctx.clock(),
                from_list=which,
            )
        )
    return RedirectResponse(_path(which) + _profile_query(ctx, chosen), status_code=303)


def _waiting(
    workspace: Workspace, company_key: str, preferred: Which
) -> tuple[Which, ListEntry] | None:
    """The company on the list the form came from or, failing that, the other list, if it
    awaits a decision. A company can be on both lists, and the page it was decided on says
    which list the decision counts for."""
    lists: list[tuple[Which, list[ListEntry]]] = [
        ("short", workspace.short_list()),
        ("more", workspace.more_list()),
    ]
    lists.sort(key=lambda pair: pair[0] != preferred)
    for which, entries in lists:
        for entry in entries:
            if entry.company_key == company_key:
                return which, entry
    return None


def _show_list(
    request: Request,
    which: Which,
    requested: str | None,
    attempt: Attempt | None = None,
    status: int = 200,
) -> Response:
    ctx = _ctx(request)
    chosen = _choose_profile(ctx, requested)
    if chosen is None:
        return _page(
            request, "choose.html", profiles=list(ctx.profiles.values()), choose_to=_path(which)
        )
    workspace = Workspace(ctx.store, chosen.id)
    entries = workspace.short_list() if which == "short" else workspace.more_list()
    return _form_page(
        request,
        "review.html",
        status=status,
        profile=chosen,
        which=which,
        entries=[_entry_view(ctx, workspace, chosen, e, attempt) for e in entries],
        all_chips=ctx.settings.reason_chips,
        **_status(ctx, workspace),
    )


def _path(which: Which) -> str:
    return "/" if which == "short" else "/more"


def _day(day: date) -> str:
    return f"{day.day} {day:%b} {day.year}"


def _entry_view(
    ctx: AppContext,
    workspace: Workspace,
    profile: Profile,
    entry: ListEntry,
    attempt: Attempt | None,
) -> dict[str, object]:
    """What the page shows of one listed company. A quote links to the ad it came from."""
    pack = workspace.load_pack(entry.pack_id) if entry.pack_id else None
    sources = {s.id: s for s in pack.sources} if pack else {}
    brief = entry.brief
    claims = [] if brief is None else [brief.why_now, *brief.claims]
    mine = attempt if attempt is not None and attempt.company_key == entry.company_key else None
    return {
        "key": entry.company_key,
        "name": entry.company_name,
        "listed": _day(entry.first_listed),
        "post_to": f"/decide/{quote(entry.company_key, safe='')}" + _profile_query(ctx, profile),
        "ads": [
            {"title": ad.title, "location": ad.location, "href": _web_href(ad.url), "url": ad.url}
            for ad in entry.ads
        ],
        "claims": [_claim_view(c, sources.get(c.source_id)) for c in claims],
        "error": mine.error if mine else None,
        "reason": mine.reason if mine else "",
        "chips": mine.chips if mine else [],
    }


def _claim_view(claim: Claim, source: Source | None) -> dict[str, object]:
    """A claim with its quote, and a link to the source the quote came from, if there is one."""
    page = source is not None and source.kind == "page"
    return {
        "text": claim.text,
        "quote": claim.quote,
        "href": _web_href(source.url) if source else None,
        "link_text": "Open the company page" if page else "Open the job ad",
    }


class Status(TypedDict):
    spend: dict[str, object]
    precision: ShortListPrecision
    run: dict[str, object] | None


def _status(ctx: AppContext, workspace: Workspace) -> Status:
    """What the top of the review pages shows: this month's spending, short-list precision
    and how the last daily run went."""
    return Status(
        spend=_spend_view(ctx),
        precision=short_list_precision(workspace.decisions()),
        run=_run_view(ctx, workspace),
    )


def _spend_view(ctx: AppContext) -> dict[str, object]:
    settings = ctx.settings
    status = ctx.meter.status()
    limit = settings.budget_limit_usd
    month = datetime.strptime(status.month, "%Y-%m")
    return {
        "month": f"{month:%B} {month.year}",
        "spent": f"{status.spent_usd:.2f}",
        "limit": f"{limit:g}",
        "warn_at": f"{settings.budget_warning_usd:g}",
        # Where the bar is filled to, and where its warning mark sits, as shares of the limit.
        "fill": round(min(100.0, 100 * status.spent_usd / limit), 1),
        "mark": round(min(100.0, 100 * settings.budget_warning_usd / limit), 1),
        "warning": status.warning,
        "stopped": status.stopped,
        "loop_stopped": status.loop_stopped and not status.stopped,
        "loop_share": f"{settings.loop_budget_usd:g}",
        "loop_spent": f"{status.by_category.get(LOOP, 0.0):.2f}",
        "fixed": settings.fixed_monthly_costs_usd or None,
        "parts": [
            (name.replace("_", " ").capitalize(), f"{usd:.2f}")
            for name, usd in sorted(status.by_category.items(), key=lambda p: -p[1])
        ],
    }


def _run_view(ctx: AppContext, workspace: Workspace) -> dict[str, object] | None:
    """The latest saved daily run, with what it skipped and what failed. None if there is none."""
    day = workspace.latest_day()
    if day is None:
        return None
    return {
        "day": _day(day.day),
        "today": day.day == ctx.clock().date(),
        "skipped": day.skipped,
        "failed": day.failed,
    }
