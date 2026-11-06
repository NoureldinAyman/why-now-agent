"""The judge: answer the fit questions from an evidence pack, then combine them in code.

The model only gives a probability of yes for each question. Code decides yes or
no, the same way for every model:

- Every required question must pass. A required question can only turn a yes into a no.
- Strength is the mean over supporting questions of `p` for "for" questions and
  `1 - p` for "against" ones, or 1 when there are none. It must reach the cut-off.

Answers are saved per evidence pack, question and model, so a try only pays for
a new or edited question, and a run on the same pack can be repeated for free.

See docs/decisions/0002.
"""

import math

from why_now.ai import Answerer, BadModelOutput, check_answers
from why_now.domain import Answer, EvidencePack, FitQuestion, Profile, RulesFile, Verdict
from why_now.evaluation.score import score
from why_now.settings import Settings
from why_now.workspace import Workspace


def all_questions(profile: Profile, rules: RulesFile) -> list[FitQuestion]:
    """The profile's fit questions, then the learned ones from its rules file."""
    if rules.profile_id != profile.id:
        raise ValueError(f"rules file for {rules.profile_id!r}, not {profile.id!r}")
    questions = [*profile.fit_questions, *rules.questions]
    ids = [q.id for q in questions]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise ValueError(f"fit question ids used twice: {repeated}")
    return questions


def choose_cutoff(
    rows: list[tuple[list[Answer], bool]], questions: list[FitQuestion], settings: Settings
) -> float:
    """The cut-off with the best F0.5 on `rows`, each a company's answers and the reviewer's yes.

    Tried on a grid from 0 to 1 in `cutoff_step` steps. On a tie the lowest wins.
    Callers pass practice pile rows only, so the cut-off never sees the check or final pile.
    """
    if not rows:
        raise ValueError("no rows to choose a cut-off from")
    # Rounded, so 0.05 steps land on 0.65 and not 0.6500000000000001. The last point
    # is 1 even when the step does not divide 1 evenly.
    steps = math.ceil(round(1 / settings.cutoff_step, 10))
    grid = [min(1.0, round(i * settings.cutoff_step, 10)) for i in range(steps + 1)]
    best, best_f05 = grid[0], -1.0
    for cutoff in grid:
        f05 = score(
            [(combine(questions, answers, cutoff, settings).yes, yes) for answers, yes in rows]
        ).f05
        if f05 > best_f05:
            best, best_f05 = cutoff, f05
    return best


class CompanyFailed(Exception):
    """The model gave no usable answers, even on a retry. The company is recorded as failed."""


def answer_questions(
    pack: EvidencePack,
    questions: list[FitQuestion],
    answerer: Answerer,
    workspace: Workspace,
    category: str,
) -> list[Answer]:
    """One answer per question, in question order, asking the model only for unsaved ones.

    A missing, out-of-range or refused answer gets one retry. If that fails too,
    `CompanyFailed` is raised and nothing from the failed calls is saved.
    """
    probabilities: dict[str, float] = {}
    unasked: dict[str, FitQuestion] = {}
    for q in questions:
        p = workspace.saved_answer(pack.pack_id, q, answerer.model)
        if p is None:
            unasked[q.id] = q
        else:
            probabilities[q.id] = p
    if unasked:
        for answer in ask_with_one_retry(pack, list(unasked.values()), answerer, category):
            question = unasked[answer.question_id]
            workspace.save_answer(pack.pack_id, question, answerer.model, answer.probability)
            probabilities[question.id] = answer.probability
    return [
        Answer(question_id=q.id, probability=probabilities[q.id], model=answerer.model)
        for q in questions
    ]


def ask_with_one_retry(
    pack: EvidencePack, questions: list[FitQuestion], answerer: Answerer, category: str
) -> list[Answer]:
    problem: BadModelOutput | None = None
    for _ in range(2):
        try:
            got = answerer.answer(pack_state(pack), questions, category)
            # Checked here too, so the guarantee does not depend on each model's own checks.
            return check_answers(
                [(a.question_id, a.probability) for a in got], questions, answerer.model
            )
        except BadModelOutput as e:
            problem = e
    raise CompanyFailed(f"{pack.company_name}: no usable answers after a retry: {problem}")


def pack_state(pack: EvidencePack) -> str:
    """The evidence pack as the text the model reads. Only the pack, so the state stays small."""
    parts = [
        f"Company: {pack.company_name}",
        f"Relevant job ads: {pack.relevant_ad_count} of {pack.total_open_jobs} open jobs",
    ]
    parts += [f"[{s.id}] {s.url}\n{s.text}" for s in pack.sources]
    return "\n\n".join(parts)


def combine(
    questions: list[FitQuestion], answers: list[Answer], cutoff: float, settings: Settings
) -> Verdict:
    """Yes or no and a strength, from one answer per question."""
    by_id = {a.question_id: a.probability for a in answers}
    missing = [q.id for q in questions if q.id not in by_id]
    if missing:
        # A missing answer must never quietly count as a no.
        raise ValueError(f"no answer for {missing}")

    def leaning_yes(q: FitQuestion) -> float:
        p = by_id[q.id]
        return p if q.direction == "for" else 1 - p

    required = [leaning_yes(q) for q in questions if q.kind == "required"]
    supporting = [leaning_yes(q) for q in questions if q.kind == "supporting"]
    strength = sum(supporting) / len(supporting) if supporting else 1.0
    passed = all(p >= settings.required_pass for p in required)
    return Verdict(yes=passed and strength >= cutoff, strength=strength, answers=answers)
