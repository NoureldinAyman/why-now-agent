"""The improvement loop: find the agent's mistakes, try one change, measure it, and keep it
or throw it away.

What the AI is shown comes only from the practice pile and the daily decisions. The check
pile is measured for its score alone, and its companies are never kept in hand. The final
pile is never read here.
"""

from collections.abc import Callable
from typing import Literal

from why_now.ai.budget import LOOP, BudgetExceeded, Meter
from why_now.domain import RulesFile
from why_now.evaluation.evaluate import EvalRun, evaluate_pile
from why_now.evaluation.records import PileResult
from why_now.evaluation.score import ScoreResult
from why_now.improve.keep import KeepResult, decide_keep
from why_now.improve.mistakes import Mistake, find_mistakes, right_yes_reasons
from why_now.improve.proposer import propose_change
from why_now.improve.records import ImproveResult, TryRecord
from why_now.improve.screen import RuleChange, apply_change, screen_change
from why_now.settings import Settings
from why_now.testset.piles import loop_ready, pile_report
from why_now.workspace import Workspace

# Runs the hidden instruction tests with these rules, and says whether every one was resisted.
type HostileCheck = Callable[[RulesFile], bool]


def run_improvement(run: EvalRun, meter: Meter, hostile: HostileCheck) -> ImproveResult:
    workspace, settings = run.workspace, run.settings
    if not loop_ready(pile_report(workspace), settings):
        return ImproveResult(tries=[], stop_reason="not_ready")

    tries: list[TryRecord] = []
    while True:
        if len(tries) >= settings.tries_per_run:
            return ImproveResult(tries=tries, stop_reason="run_limit")
        try:
            meter.ensure(LOOP)
            spent_before = _loop_spent(meter)  # the scoring below is paid for by this round
            rules = workspace.load_rules()
            practice = evaluate_pile("practice", rules, run, LOOP)

            tried = workspace.tried_mistakes(rules.version)
            found = find_mistakes(workspace, practice, rules, settings)
            mistakes = [m for m in found if m.id not in tried]
            if not mistakes:
                return ImproveResult(tries=tries, stop_reason="no_mistakes")

            # Only the score of the check pile is kept. Its companies never leave this line.
            check_before = evaluate_pile("check", rules, run, LOOP).score
            if _check_pile_used_up(workspace, settings, check_before.n):
                return ImproveResult(tries=tries, stop_reason="check_pile_used_up")

            record = _try_one_change(
                run, meter, hostile, rules, mistakes, practice, check_before, spent_before
            )
        except BudgetExceeded:
            # The money ran out part-way through a round. A try cut short is not recorded, and
            # its mistakes are not marked tried, so the next run asks about them again. What was
            # spent stays in the budget book.
            return ImproveResult(tries=tries, stop_reason="budget")
        tries.append(record)


def _try_one_change(
    run: EvalRun,
    meter: Meter,
    hostile: HostileCheck,
    rules: RulesFile,
    mistakes: list[Mistake],
    practice: PileResult,
    check_before: ScoreResult,
    spent_before: float,
) -> TryRecord:
    """Ask for one change, screen it, measure it, and keep it or not. Records the try.

    `spent_before` is what the loop had spent when the round began, so the try's cost includes
    the scoring the round needed.
    """
    workspace = run.workspace
    started = run.clock()
    change = propose_change(
        mistakes,
        run.profile,
        rules,
        _summaries(workspace.tries()),
        run.models.writer,
        yes_reasons=right_yes_reasons(workspace, practice),
    )
    new_rules, problem = _screened_and_applied(workspace, run.settings, rules, change)

    outcome: Literal["kept", "discarded", "screened_out"]
    scores: dict[str, ScoreResult] = {}  # empty when nothing was measured
    if new_rules is None:
        outcome, reasons = "screened_out", [problem or "screened out"]
    else:
        scores = _measure(run, new_rules, practice, check_before)
        verdict = _keep_verdict(run, hostile, new_rules, scores)
        outcome = "kept" if verdict.keep else "discarded"
        reasons = verdict.reasons or ["every condition held"]
        if verdict.keep:
            workspace.save_rules(new_rules)

    record = TryRecord(
        try_id=f"try-{len(workspace.tries()) + 1}",
        started_at=started,
        change=change,
        screen_problem=problem,
        check_before=scores.get("check_before"),
        check_after=scores.get("check_after"),
        practice_before=scores.get("practice_before"),
        practice_after=scores.get("practice_after"),
        outcome=outcome,
        reasons=reasons,
        cost_usd=_loop_spent(meter) - spent_before,
        rules_version_before=rules.version,
        rules_version_after=new_rules.version if outcome == "kept" and new_rules else rules.version,
    )
    workspace.save_try(record)
    # Marked only now that the try is recorded. A try the budget cut short is asked again.
    for mistake_id in _addressed(mistakes, change):
        workspace.mark_mistake_tried(mistake_id, rules.version)
    return record


def _measure(
    run: EvalRun,
    new_rules: RulesFile,
    practice: PileResult,
    check_before: ScoreResult,
) -> dict[str, ScoreResult]:
    """The scores before and after, on the same companies, old rules then new ones."""
    return {
        "check_before": check_before,
        "check_after": evaluate_pile("check", new_rules, run, LOOP).score,
        "practice_before": practice.score,
        "practice_after": evaluate_pile("practice", new_rules, run, LOOP).score,
    }


def _keep_verdict(
    run: EvalRun, hostile: HostileCheck, new_rules: RulesFile, scores: dict[str, ScoreResult]
) -> KeepResult:
    # First ask whether it would be kept if the hidden tests pass. Only then run them, because
    # they cost money and a change that fails on the scores needs no more proof.
    verdict = decide_keep(**scores, hostile_passed=True, settings=run.settings)
    if not verdict.keep:
        return verdict
    return decide_keep(**scores, hostile_passed=hostile(new_rules), settings=run.settings)


def _screened_and_applied(
    workspace: Workspace, settings: Settings, rules: RulesFile, change: RuleChange
) -> tuple[RulesFile | None, str | None]:
    """The rules with the change made, or None and the reason it cannot be used."""
    # The screen is a script. Names and ads from every pile are used to catch a leak, and none
    # of it goes to the AI.
    companies = [c for case in workspace.cases() if (c := workspace.case_company(case.case_id))]
    names = {c.name for c in companies}
    ads = [ad.text for c in companies for ad in c.ads]
    screened = screen_change(change, names, ads, settings)
    if not screened.ok:
        return None, screened.problem
    try:
        return apply_change(rules, change), None
    except ValueError as e:
        return None, f"it cannot be applied: {e}"


def _addressed(mistakes: list[Mistake], change: RuleChange) -> list[str]:
    """The mistakes this try counts as tried: the ones the change names, or all of them when it
    names none that were shown."""
    shown = {m.id for m in mistakes}
    named = [i for i in change.based_on if i in shown]
    return named or sorted(shown)


def _summaries(tries: list[TryRecord]) -> list[str]:
    """One line per earlier try, so the AI does not propose the same thing again."""
    lines = []
    for t in tries:
        c = t.change
        if c is None:
            continue
        what = c.question.text if c.question else f"remove {c.question_id}"
        lines.append(f"{c.action}: {what} ({t.outcome}: {'; '.join(t.reasons)})")
    return lines


def _check_pile_used_up(workspace: Workspace, settings: Settings, check_size: int) -> bool:
    """After every `tries_per_check_pile` measured tries, no more until `new_check_companies`
    new companies have joined the check pile since the last one."""
    sizes = [t.check_before.n for t in workspace.tries() if t.check_before is not None]
    if not sizes or len(sizes) % settings.tries_per_check_pile:
        return False
    return check_size < sizes[-1] + settings.new_check_companies


def _loop_spent(meter: Meter) -> float:
    return meter.status().by_category.get(LOOP, 0.0)
