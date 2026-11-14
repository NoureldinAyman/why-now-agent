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
from why_now.evaluation.records import CaseRow, ComparisonResult, PileResult
from why_now.evaluation.score import ScoreResult, score
from why_now.pipeline.judge import (
    CompanyFailed,
    all_questions,
    answer_questions,
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
    if pile == "final":
        raise ValueError("the final pile can only be read through open_final_pile")
    return _evaluate(pile, rules, run, category)


def open_final_pile(run: EvalRun, moment: Moment, reason: str | None) -> PileResult:
    """The only way to read the final pile. Every opening is logged before it is read."""
    if moment == "extra" and not reason:
        raise ValueError("an extra opening of the final pile needs a reason")
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
    rows: list[CaseRow] = []
    failed_cases: list[str] = []
    for case, reviewer_yes in _marked_cases(run, pile):
        try:
            rows.append(_grade_case(case, reviewer_yes, rules, run, category))
        except CompanyFailed:
            failed_cases.append(case.case_id)
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
    )


def _grade_case(
    case: CaseRecord, reviewer_yes: bool, rules: RulesFile, run: EvalRun, category: str
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
    cutoff = workspace.cutoff(run.models.judge.answer_key)
    cutoff = settings.default_cutoff if cutoff is None else cutoff
    return CaseRow(
        case_id=case.case_id,
        agent_yes=combine(questions, answers, cutoff, settings).yes,
        reviewer_yes=reviewer_yes,
        quick_passed=True,
        answers=answers,
    )


def baselines(pile: str, run: EvalRun) -> dict[str, ScoreResult]:
    """Three simple rivals the agent must beat: yes to all, the quick look alone, empty rules."""
    if pile == "final":
        raise ValueError("the final pile can only be read through open_final_pile")
    cases = _marked_cases(run, pile)
    empty_rules = RulesFile(profile_id=run.profile.id)
    return {
        "yes_to_all": score(
            [(True, reviewer_yes) for _, reviewer_yes in cases], run.settings.score_beta
        ),
        "quick_look_only": _quick_look_only(cases, run),
        "empty_rules": evaluate_pile(pile, empty_rules, run, CATEGORY).score,
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

    The result is kept whichever judge wins. On a tie the first judge listed wins, so the
    caller lists the current judge first and a tie changes nothing.
    """
    rules = run.workspace.load_rules()
    results: dict[str, PileResult] = {}
    for answerer in answerers:
        judge_run = replace(run, models=replace(run.models, judge=answerer))
        set_cutoff(judge_run)
        results[answerer.answer_key] = _evaluate("check", rules, judge_run, CATEGORY)

    shared = set.intersection(*({row.case_id for row in r.rows} for r in results.values()))

    scores = {
        key: score(
            [(row.agent_yes, row.reviewer_yes) for row in r.rows if row.case_id in shared],
            run.settings.score_beta,
        )
        for key, r in results.items()
    }

    winner = max(scores, key=lambda key: scores[key].f)
    comparison = ComparisonResult(scores=scores, winner=winner, day=run.clock().date())
    run.workspace.save_comparison(comparison)
    return comparison
