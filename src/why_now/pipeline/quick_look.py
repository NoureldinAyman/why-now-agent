"""The quick look: a cheap first read of each company's relevant ads.

Clear no's are dropped and the rest are ordered strongest first. A company the
model could not answer for is marked failed, never quietly dropped.
"""

from pydantic import BaseModel

from why_now.ai import Answerer, BadModelOutput
from why_now.domain import Answer, Company, FitQuestion, Profile
from why_now.settings import Settings
from why_now.tracing import Tracer
from why_now.workspace import Workspace

CATEGORY = "quick_look"


class QuickResult(BaseModel):
    company_key: str
    passed: bool
    order: float
    answers: list[Answer]
    failed: bool = False


def quick_look(
    companies: list[Company],
    profile: Profile,
    answerer: Answerer,
    settings: Settings,
    workspace: Workspace,
    tracer: Tracer,
) -> list[QuickResult]:
    """Strongest first. Failed companies come last, so they can be retried."""
    questions = profile.quick_look_questions
    results: list[QuickResult] = []
    # One light trace for the whole run, because the quick look covers many companies.
    with tracer.trace(
        "quick_look",
        profile_id=profile.id,
        rules_version=None,
        models={"quick_look": answerer.model},
        detail="light",
    ) as trace:
        for company in companies:
            state = _state(company, settings.max_ad_chars)
            try:
                answers = _answers(company.key, state, questions, answerer, workspace)
            except BadModelOutput as e:
                # BudgetExceeded is not caught: a spent budget must stop the run.
                result = QuickResult(
                    company_key=company.key, passed=False, order=0, answers=[], failed=True
                )
                trace.step("quick_look_failed", company.key, repr(e))
            else:
                strength = _strength(questions, answers)
                result = QuickResult(
                    company_key=company.key,
                    passed=strength >= settings.quick_look_pass,
                    order=strength,
                    answers=answers,
                )
                trace.step("quick_look", company.key, strength)
            results.append(result)
    return sorted(results, key=lambda r: (r.failed, -r.order))


def _state(company: Company, max_ad_chars: int) -> str:
    # Only the relevant ads, each cut short: the library's documentation warns that
    # irrelevant text costs accuracy, and long ads cost money.
    return "\n\n".join(
        f"{ad.title} ({ad.location})\n{ad.text[:max_ad_chars]}" for ad in company.ads
    )


def _answers(
    company_key: str,
    state: str,
    questions: list[FitQuestion],
    answerer: Answerer,
    workspace: Workspace,
) -> list[Answer]:
    saved: dict[str, float] = {}
    missing: list[FitQuestion] = []
    for q in questions:
        p = workspace.saved_quick_answer(company_key, state, q.text, answerer.model)
        if p is None:
            missing.append(q)
        else:
            saved[q.id] = p
    if missing:
        texts = {q.id: q.text for q in missing}
        for a in _answer_with_retry(answerer, state, missing):
            saved[a.question_id] = a.probability
            workspace.save_quick_answer(
                company_key, state, texts[a.question_id], answerer.model, a.probability
            )
    return [
        Answer(question_id=q.id, probability=saved[q.id], model=answerer.model) for q in questions
    ]


def _strength(questions: list[FitQuestion], answers: list[Answer]) -> float:
    """Mean chance of fit: p for "for" questions, 1 - p for "against". 1 with no questions."""
    p = {a.question_id: a.probability for a in answers}
    values = [p[q.id] if q.direction == "for" else 1 - p[q.id] for q in questions]
    return sum(values) / len(values) if values else 1.0


def _answer_with_retry(
    answerer: Answerer, state: str, questions: list[FitQuestion]
) -> list[Answer]:
    # One retry, as in the judge: a single odd reply should not fail a company.
    try:
        return answerer.answer(state, questions, CATEGORY)
    except BadModelOutput:
        return answerer.answer(state, questions, CATEGORY)
