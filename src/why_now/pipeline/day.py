"""The daily run: read, search, find what's new, quick look, then research, judge and brief.

In order:

1. Read the careers pages, search them by the profile's words, and keep the companies
   that are new (`find_new`).
2. Quick look at every new company. Clear no's are dropped, the rest are ranked.
3. Research, judge and brief the strongest first, until the short list is full or
   `research_per_day` companies have been tried. Each company's steps are saved as they
   finish, so a rerun after a crash picks up where it stopped and pays for nothing twice.
4. The short list is the companies already waiting for a decision plus the new ones, so
   it never grows past `short_list_size`. Companies that passed the quick look but were
   not researched go on the more list. The `judged_no_shown` researched companies judged no
   that are closest to a yes go on the judged-no list.

A spent budget does not stop the read. The run stops paying, says what it skipped, and
leaves the companies it did not get to unseen, so the next day tries them again.

The day means the UTC date the caller passes in. See docs/decisions/0004.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from why_now.ai.budget import BudgetExceeded
from why_now.day_result import DayResult, ListEntry
from why_now.domain import Brief, Company, EvidencePack, Profile, Verdict
from why_now.pipeline.brief import write_brief
from why_now.pipeline.find_new import find_new
from why_now.pipeline.judge import all_questions, answer_questions, combine
from why_now.pipeline.quick_look import QuickResult, quick_look
from why_now.pipeline.read import ReadResult, read_all
from why_now.pipeline.research import research_company
from why_now.pipeline.search import company_key, search_ads
from why_now.run_context import RunContext, metered
from why_now.settings import Settings
from why_now.workspace import Workspace
from why_now.workspace.daily import closest_to_yes

RESEARCH = "research"  # the budget category daily research is charged to, and its step name
BRIEF = "brief"  # the step name for a saved brief
JUDGE = "judge"
# The settings one run may change. Everything else, the budget above all, stays as set.
OVERRIDABLE = frozenset({"short_list_size", "new_ad_days"})


def _saved_read(workspace: Workspace) -> ReadResult:
    """The ads saved at the last read of every careers page, as if they were read now."""
    ads = workspace.all_board_ads()
    return ReadResult(
        ads=ads,
        new_ad_count=0,
        failed_boards={},
        outage_sources=[],
        open_job_counts=dict(Counter(company_key(a.board) for a in ads)),
    )


@dataclass
class _Outcome:
    entry: ListEntry | None = None
    judged_no: ListEntry | None = None  # researched, and the judge said no
    failure: str | None = None
    retry: bool = False  # leave the company's ads unseen, so the next day tries again


def run_day(
    ctx: RunContext,
    profile: Profile,
    today: date,
    overrides: dict | None = None,
    *,
    saved_read: bool = False,
) -> DayResult:
    """One day for `profile`. With `saved_read`, no careers page is read: the ads saved at
    the last read are used, because a full read takes hours and a run started on demand
    should not wait for one."""
    settings = _settings_for_run(ctx.settings, overrides or {})
    workspace = Workspace(ctx.store, profile.id)
    models = metered(ctx.models, ctx.meter)
    failed: list[str] = []
    skipped: list[str] = []

    if saved_read:
        read = _saved_read(workspace)
        if not read.ads:
            skipped.append("Reading: there is no saved read yet, so there was nothing to search.")
    else:
        read = read_all(
            ctx.sources, ctx.boards, workspace, today, outage_share=settings.outage_share
        )
    failed += _read_problems(read)
    companies = search_ads(read.ads, profile, read.open_job_counts)
    candidates = find_new(companies, workspace, settings, today)

    # A company already waiting for a decision is not researched again.
    waiting_keys = {e.company_key for e in workspace.short_list()}
    new = [c for c in candidates if c.key not in waiting_keys]
    # Its newest ads are added to the entry, so the reviewer sees what changed.
    newer = {c.key: c for c in candidates if c.key in waiting_keys}
    waiting = [
        e.model_copy(update={"ads": newer[e.company_key].ads}) if e.company_key in newer else e
        for e in workspace.short_list()
    ]
    by_key = {c.key: c for c in new}
    retry: set[str] = set()  # companies whose ads stay unseen

    ranked: list[QuickResult] = []
    unranked: list[Company] = []  # no quick look was done, so they have no strength
    if new:
        try:
            results = quick_look(new, profile, models.quick_look, settings, workspace, ctx.tracer)
        except BudgetExceeded as e:
            skipped.append(f"Quick look and research for {len(new)} companies: {e}")
            unranked, retry = list(new), set(by_key)
        else:
            for r in results:
                if r.failed:
                    failed.append(
                        f"{by_key[r.company_key].name}: the quick look gave no usable answer"
                    )
                    retry.add(r.company_key)
                elif r.passed:
                    ranked.append(r)

    accepted: list[ListEntry] = []
    turned_down: list[ListEntry] = []
    left = list(ranked)  # passed the quick look, not yet tried
    room = settings.short_list_size - len(waiting)
    tried = 0
    rules = workspace.load_rules()
    while left and len(accepted) < room and tried < settings.research_per_day:
        if workspace.one_time_research_active():
            skipped.append(
                f"Research for {len(left)} companies: paused while one-time research runs."
            )
            retry |= {r.company_key for r in left}
            break
        company = by_key[left[0].company_key]
        try:
            outcome = _process(ctx, models, workspace, profile, rules, settings, company, today)
        except BudgetExceeded as e:
            skipped.append(f"Research for {len(left)} companies: {e}")
            retry |= {r.company_key for r in left}
            break
        left.pop(0)
        tried += 1
        if outcome.failure:
            failed.append(outcome.failure)
        if outcome.retry:
            retry.add(company.key)
        if outcome.entry:
            accepted.append(outcome.entry)
        if outcome.judged_no:
            turned_down.append(outcome.judged_no)

    short, pushed_down = _short_list(waiting + accepted, settings.short_list_size)
    more = _more_list(
        [_unresearched(by_key[r.company_key], r.order, today) for r in left]
        + [_unresearched(c, None, today) for c in unranked]
        + pushed_down,
        workspace.more_list(),
        {e.company_key for e in short},
        # Looked at again today and not put forward, so an older entry must go too.
        {c.key for c in new if c.key not in retry},
        settings,
        today,
    )

    judged_no = _judged_no_list(
        turned_down,
        workspace.judged_no_list(),
        {e.company_key for e in short},
        {c.key for c in new if c.key not in retry},
        settings,
        today,
    )

    # Finished companies are marked seen, so they are not new tomorrow.
    waiting_now = [c for c in candidates if c.key in waiting_keys]
    workspace.mark_ads_seen([a for c in [*new, *waiting_now] if c.key not in retry for a in c.ads])
    result = DayResult(
        day=today,
        short_list=short,
        more_list=more,
        judged_no=judged_no,
        failed=failed,
        skipped=skipped,
        costs=ctx.meter.status(),
    )
    workspace.save_day(result)
    return result


def _settings_for_run(settings: Settings, overrides: dict) -> Settings:
    refused = sorted(set(overrides) - OVERRIDABLE)
    if refused:
        raise ValueError(
            f"{', '.join(refused)} cannot be changed for one run; "
            f"only {', '.join(sorted(OVERRIDABLE))} can"
        )
    return Settings.model_validate(settings.model_dump() | overrides)


def _read_problems(read: ReadResult) -> list[str]:
    problems = [
        f"{source}: {len(boards)} careers pages could not be read"
        for source, boards in read.failed_boards.items()
    ]
    problems += [
        f"{source} looks down, so its pages were not blamed" for source in read.outage_sources
    ]
    return problems


def _process(
    ctx: RunContext,
    models,
    workspace: Workspace,
    profile: Profile,
    rules,
    settings: Settings,
    company: Company,
    today: date,
) -> _Outcome:
    """Research, judge and brief one company. Budget errors go up; any other failure is recorded."""
    run = today.isoformat()
    try:
        pack = _research(ctx, models, workspace, profile, settings, company, run)
        verdict = _judge(ctx, models, workspace, profile, rules, settings, company, pack)
        if not verdict.yes:
            return _Outcome(judged_no=_entry(company, verdict.strength, None, pack, today))
        brief = _brief(ctx, models, workspace, profile, settings, pack, verdict, run)
    except BudgetExceeded:
        raise
    except Exception as e:
        return _Outcome(failure=f"{company.name}: {type(e).__name__}: {e}", retry=True)
    if brief is None:
        return _Outcome(
            failure=f"{company.name}: the brief failed the fact check twice, so it was dropped"
        )
    return _Outcome(entry=_entry(company, verdict.strength, brief, pack, today))


def _entry(
    company: Company, strength: float, brief: Brief | None, pack: EvidencePack, today: date
) -> ListEntry:
    return ListEntry(
        company_key=company.key,
        company_name=company.name,
        strength=strength,
        brief=brief,
        ads=company.ads,
        pack_id=pack.pack_id,
        first_listed=today,
    )


def _research(ctx, models, workspace, profile, settings, company, run) -> EvidencePack:
    saved = workspace.step_result(run, RESEARCH, company.key)
    if saved is not None:
        pack = workspace.load_pack(saved["pack_id"])
        if pack is not None:
            return pack
    pack = research_company(
        company,
        profile,
        models.research,
        ctx.reader,
        settings,
        ctx.tracer,
        category=RESEARCH,
        now=ctx.clock(),
    )
    workspace.save_pack(pack)
    workspace.save_step_result(run, RESEARCH, company.key, {"pack_id": pack.pack_id})
    return pack


def _judge(ctx, models, workspace, profile, rules, settings, company, pack) -> Verdict:
    questions = all_questions(profile, rules)
    cutoff = workspace.cutoff(models.judge.answer_key)
    with ctx.tracer.trace(
        "judge",
        profile_id=profile.id,
        rules_version=rules.version,
        models={"judge": models.judge.answer_key},
    ) as trace:
        answers = answer_questions(pack, questions, models.judge, workspace, JUDGE)
        verdict = combine(
            questions, answers, settings.default_cutoff if cutoff is None else cutoff, settings
        )
        trace.step("verdict", company.key, verdict.model_dump())
    return verdict


def _brief(ctx, models, workspace, profile, settings, pack, verdict, run) -> Brief | None:
    saved = workspace.step_result(run, BRIEF, pack.company_key)
    if saved is not None:
        return None if saved["brief"] is None else Brief.model_validate(saved["brief"])
    brief = write_brief(pack, verdict, profile, models.writer, settings, ctx.tracer)
    doc = {"brief": None if brief is None else brief.model_dump(mode="json")}
    workspace.save_step_result(run, BRIEF, pack.company_key, doc)
    return brief


def _unresearched(company: Company, strength: float | None, today: date) -> ListEntry:
    return ListEntry(
        company_key=company.key,
        company_name=company.name,
        strength=strength,
        brief=None,
        ads=company.ads,
        pack_id=None,
        first_listed=today,
    )


def _short_list(entries: list[ListEntry], size: int) -> tuple[list[ListEntry], list[ListEntry]]:
    """The strongest `size` entries, and the rest without their briefs for the more list."""
    ordered = sorted(entries, key=lambda e: (-(e.strength or 0), e.company_key))
    pushed = [e.model_copy(update={"brief": None}) for e in ordered[size:]]
    return ordered[:size], pushed


def _judged_no_list(
    fresh: list[ListEntry],
    carried: list[ListEntry],
    on_short_list: set[str],
    looked_at_again: set[str],
    settings: Settings,
    today: date,
) -> list[ListEntry]:
    """The `judged_no_shown` companies judged no that are closest to a yes, from today's and
    those still waiting from earlier days, strongest first.

    An older entry stays only while one of its ads is inside the new-ad window, and not once
    the company was judged again today. On equal strength the company key decides the order.
    """
    oldest = today - timedelta(days=settings.new_ad_days - 1)
    kept = {e.company_key: e for e in fresh}
    for entry in carried:
        if entry.company_key in looked_at_again:
            continue
        if any(a.published_at.date() >= oldest for a in entry.ads):
            kept.setdefault(entry.company_key, entry)
    entries = [e for key, e in kept.items() if key not in on_short_list]
    return closest_to_yes(entries)[: settings.judged_no_shown]


def _more_list(
    fresh: list[ListEntry],
    carried: list[ListEntry],
    on_short_list: set[str],
    looked_at_again: set[str],
    settings: Settings,
    today: date,
) -> list[ListEntry]:
    """Today's more list entries, then older ones still waiting, each company once.

    An older entry stays only while one of its ads is inside the new-ad window.
    """
    oldest = today - timedelta(days=settings.new_ad_days - 1)
    kept: dict[str, ListEntry] = {}
    for entry in fresh:
        old = next((c for c in carried if c.company_key == entry.company_key), None)
        kept[entry.company_key] = (
            entry if old is None else entry.model_copy(update={"first_listed": old.first_listed})
        )
    for entry in carried:
        if entry.company_key in looked_at_again:
            continue  # it was judged again today, and what is in `fresh` is the answer
        if any(a.published_at.date() >= oldest for a in entry.ads):
            kept.setdefault(entry.company_key, entry)
    entries = [e for key, e in kept.items() if key not in on_short_list]
    return sorted(entries, key=lambda e: (e.strength is None, -(e.strength or 0), e.company_key))
