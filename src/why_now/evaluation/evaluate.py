"""Grade a pile of test cases against the reviewer's marks."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from why_now.ai import Answerer, Models
from why_now.domain import (
    Answer,
    CaseRecord,
    Company,
    EvidencePack,
    FinalOpening,
    Moment,
    Profile,
    RulesFile,
)
from why_now.evaluation.records import (
    CaseRow,
    ComparisonResult,
    ConsistencyResult,
    PileResult,
    QuestionSpread,
)
from why_now.evaluation.score import ScoreResult, score
from why_now.pipeline.judge import (
    CompanyFailed,
    all_questions,
    answer_questions,
    ask_with_one_retry,
    choose_cutoff,
    combine,
)
from why_now.pipeline.quick_look import quick_look
from why_now.settings import Settings
from why_now.tracing import Tracer
from why_now.workspace import Workspace

CATEGORY = "evaluation"  # the budget category every evaluation call is charged to


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class EvalRun:
    """Everything one evaluation needs, bundled so it can be handed around as one thing."""

    workspace: Workspace
    profile: Profile
    models: Models
    settings: Settings
    tracer: Tracer
    clock: Callable[[], datetime] = _now


def evaluate_pile(pile: str, rules: RulesFile, run: EvalRun, category: str) -> PileResult:
    """Score the agent's yes or no against the reviewer's mark on every case in `pile`."""
    _check_readable(pile)
    return _evaluate(pile, rules, run, category)


def _check_readable(pile: str) -> None:
    """Refuse the final pile, which only `open_final_pile` may read, and any unknown name."""
    if pile == "final":
        raise ValueError("the final pile can only be read through open_final_pile")
    if pile not in ("practice", "check"):
        raise ValueError(f"the pile must be practice or check, not {pile!r}")


def open_final_pile(run: EvalRun, moment: Moment, reason: str | None) -> PileResult:
    """The only way to read the final pile. Every opening is logged before it is read."""
    if moment == "extra" and not (reason and reason.strip()):
        raise ValueError("an extra opening of the final pile needs a reason")
    judge_key = run.models.judge.answer_key
    if run.workspace.cutoff(judge_key) is None:
        # Opened with a guessed cut-off, the one reading of the final pile would be wasted.
        raise ValueError(
            f"no cut-off is recorded for {judge_key}: choose one on the practice pile first"
        )
    run.workspace.record_opening(FinalOpening(moment=moment, reason=reason, opened_at=run.clock()))
    return _evaluate("final", run.workspace.load_rules(), run, CATEGORY)


def set_cutoff(run: EvalRun) -> float:
    """Choose the cut-off on the practice pile only, and record it for the judge in use.

    Every marked practice company is judged, whether or not the quick look would let it
    through, so the cut-off describes the judge alone. A company the judge cannot answer
    for is left out. Nothing from the check or final pile is read.
    """
    workspace, judge = run.workspace, run.models.judge
    questions = all_questions(run.profile, workspace.load_rules())
    rows: list[tuple[list[Answer], bool]] = []
    for case, reviewer_yes in _marked_cases(run, "practice"):
        _, pack = _company_and_pack(case, workspace)
        try:
            answers = answer_questions(pack, questions, judge, workspace, CATEGORY)
        except CompanyFailed:
            continue
        rows.append((answers, reviewer_yes))
    cutoff = choose_cutoff(rows, questions, run.settings)
    workspace.save_cutoff(judge.answer_key, cutoff)
    return cutoff


def _marked_cases(run: EvalRun, pile: str) -> list[tuple[CaseRecord, bool]]:
    """The cases in `pile` the reviewer answered yes or no, each with whether it was a yes.

    A case not marked yet, or marked can't tell, is left out: there is no answer to grade by.
    """
    marks = {m.case_id: m.answer for m in run.workspace.marks("first")}
    return [
        (case, marks[case.case_id] == "yes")
        for case in run.workspace.cases()
        if case.pile == pile and marks.get(case.case_id) in ("yes", "no")
    ]


def _company_and_pack(case: CaseRecord, workspace: Workspace) -> tuple[Company, EvidencePack]:
    company = workspace.case_company(case.case_id)
    pack = None if case.pack_id is None else workspace.load_pack(case.pack_id)
    if company is None or pack is None:
        raise ValueError(f"case {case.case_id} has no company or no evidence pack")
    return company, pack


def _evaluate(pile: str, rules: RulesFile, run: EvalRun, category: str) -> PileResult:
    recorded = run.workspace.cutoff(run.models.judge.answer_key)
    cutoff = run.settings.default_cutoff if recorded is None else recorded
    rows: list[CaseRow] = []
    failed_cases: list[str] = []
    for case, reviewer_yes in _marked_cases(run, pile):
        try:
            rows.append(_grade_case(case, reviewer_yes, rules, run, category, cutoff))
        except CompanyFailed:
            failed_cases.append(case.case_id)
    if not rows:
        raise ValueError(
            f"no company in the {pile} pile could be graded: {len(failed_cases)} could not be "
            "answered for, and the rest are not marked yes or no"
        )
    pairs = [(row.agent_yes, row.reviewer_yes) for row in rows]
    return PileResult(
        pile=pile,
        score=score(pairs, run.settings.score_beta),
        rows=rows,
        failed_cases=failed_cases,
        rules_version=rules.version,
        profile_version=run.profile.version,
        models={
            "quick_look": run.models.quick_look.answer_key,
            "judge": run.models.judge.answer_key,
        },
        cutoff=cutoff,
        cutoff_recorded=recorded is not None,
    )


def _grade_case(
    case: CaseRecord,
    reviewer_yes: bool,
    rules: RulesFile,
    run: EvalRun,
    category: str,
    cutoff: float,
) -> CaseRow:
    """What the agent says about one company, as the daily run would: quick look, then judge."""
    workspace, settings = run.workspace, run.settings
    company, pack = _company_and_pack(case, workspace)

    looked = quick_look(
        [company], run.profile, run.models.quick_look, settings, workspace, run.tracer
    )[0]
    if looked.failed:
        raise CompanyFailed(f"{company.name}: the quick look gave no usable answers")
    if not looked.passed:
        # Dropped by the quick look, which counts as a no. The judge is never asked.
        return CaseRow(
            case_id=case.case_id,
            agent_yes=False,
            reviewer_yes=reviewer_yes,
            quick_passed=False,
            answers=[],
        )

    questions = all_questions(run.profile, rules)
    answers = answer_questions(pack, questions, run.models.judge, workspace, category)
    return CaseRow(
        case_id=case.case_id,
        agent_yes=combine(questions, answers, cutoff, settings).yes,
        reviewer_yes=reviewer_yes,
        quick_passed=True,
        answers=answers,
    )


def baselines(pile: str, run: EvalRun) -> dict[str, ScoreResult]:
    """Three simple rivals the agent must beat: yes to all, the quick look alone, empty rules.

    All three are scored on the companies the agent itself could be graded on, so the numbers
    can be put side by side.
    """
    _check_readable(pile)
    empty_rules = RulesFile(profile_id=run.profile.id)
    agent = evaluate_pile(pile, empty_rules, run, CATEGORY)
    graded = {row.case_id for row in agent.rows}
    cases = [(case, yes) for case, yes in _marked_cases(run, pile) if case.case_id in graded]
    return {
        "yes_to_all": score([(True, yes) for _, yes in cases], run.settings.score_beta),
        "quick_look_only": _quick_look_only(cases, run),
        "empty_rules": agent.score,
    }


def _quick_look_only(cases: list[tuple[CaseRecord, bool]], run: EvalRun) -> ScoreResult:
    """Score the quick look's pass or drop alone, as if there were no judge."""
    pairs: list[tuple[bool, bool]] = []
    for case, reviewer_yes in cases:
        company, _ = _company_and_pack(case, run.workspace)
        looked = quick_look(
            [company], run.profile, run.models.quick_look, run.settings, run.workspace, run.tracer
        )[0]
        if looked.failed:
            continue  # no answer: left out, never counted as a no
        pairs.append((looked.passed, reviewer_yes))
    return score(pairs, run.settings.score_beta)


def compare_judges(run: EvalRun, answerers: list[Answerer]) -> ComparisonResult:
    """Score judges on the same check pile companies, each with its own cut-off.

    Each judge's cut-off is chosen again on the practice pile and recorded, replacing the one
    kept for that judge before. The result is kept whichever judge wins. On a tie the first
    judge listed wins, so the caller lists the current judge first and a tie changes nothing.
    """
    rules = run.workspace.load_rules()
    results: dict[str, PileResult] = {}
    for answerer in answerers:
        judge_run = replace(run, models=replace(run.models, judge=answerer))
        set_cutoff(judge_run)
        results[answerer.answer_key] = _evaluate("check", rules, judge_run, CATEGORY)

    answered = [{row.case_id for row in r.rows} for r in results.values()]
    shared = set.intersection(*answered)
    if not shared:
        raise ValueError("the judges answered no company in common, so they cannot be compared")
    seen = set().union(*answered, *(r.failed_cases for r in results.values()))
    scores = {
        key: score(
            [(row.agent_yes, row.reviewer_yes) for row in r.rows if row.case_id in shared],
            run.settings.score_beta,
        )
        for key, r in results.items()
    }

    winner = max(scores, key=lambda key: scores[key].f)
    comparison = ComparisonResult(
        scores=scores,
        winner=winner,
        day=run.clock().date(),
        dropped_cases=sorted(seen - shared),
        rules_version=rules.version,
        profile_version=run.profile.version,
    )
    run.workspace.save_comparison(comparison)
    return comparison


def consistency(
    run: EvalRun, answerer: Answerer, packs: list[EvidencePack], asks: int
) -> ConsistencyResult:
    """Ask every question about each pack `asks` times, with no saved answers, and report
    how far each question's answers move."""
    questions = all_questions(run.profile, run.workspace.load_rules())
    spreads: dict[str, list[float]] = {q.id: [] for q in questions}
    failed: list[str] = []
    for pack in packs:
        try:
            rounds = [ask_with_one_retry(pack, questions, answerer, CATEGORY) for _ in range(asks)]
        except CompanyFailed:
            failed.append(pack.pack_id)
            continue
        for position, question in enumerate(questions):
            given = [answers[position].probability for answers in rounds]
            spreads[question.id].append(max(given) - min(given))

    spread = {
        question_id: QuestionSpread(average=sum(values) / len(values), worst=max(values))
        for question_id, values in spreads.items()
        if values
    }
    return ConsistencyResult(
        answer_key=answerer.answer_key,
        asks=asks,
        companies=len(packs) - len(failed),
        failed=failed,
        spread=spread,
    )
