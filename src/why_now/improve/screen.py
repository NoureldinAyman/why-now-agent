"""The change screen: a script that rejects bad wording before anything is measured."""

import re
from typing import Literal

from pydantic import BaseModel

from why_now.domain import LearnedQuestion, RulesFile
from why_now.settings import Settings


class RuleChange(BaseModel):
    action: Literal["add", "edit", "remove"]
    question_id: str | None
    question: LearnedQuestion | None
    based_on: list[str]


class ScreenResult(BaseModel):
    ok: bool
    problem: str | None


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def _wording(q: LearnedQuestion) -> list[str]:
    return [t for t in (q.text, q.yes_means, q.no_means) if t]


def screen_change(
    change: RuleChange, company_names: set[str], ad_texts: list[str], settings: Settings
) -> ScreenResult:
    def fail(problem: str) -> ScreenResult:
        return ScreenResult(ok=False, problem=problem)

    if change.action == "remove":
        return ScreenResult(ok=True, problem=None)
    q = change.question
    if q is None:
        return fail("an add or edit needs a question")
    texts = [*_wording(q), q.why]

    for name in company_names:
        name_words = _words(name)
        if not name_words:
            continue
        pattern = r"\b" + r"\W+".join(re.escape(w) for w in name_words) + r"\b"
        if any(re.search(pattern, t, re.IGNORECASE) for t in texts):
            return fail("names a company")

    if any(_sentences(t) > 1 for t in _wording(q)):
        return fail("the question must be one sentence")
    if not q.why.strip():
        return fail("the why clause is missing")
    if len(_words(q.why)) > settings.screen_max_why_words:
        return fail(f"the why clause is over {settings.screen_max_why_words} words")

    n = settings.screen_max_copied_words
    ad_runs: set[tuple[str, ...]] = set()
    for ad in ad_texts:
        w = _words(ad)
        ad_runs.update(tuple(w[i : i + n]) for i in range(len(w) - n + 1))
    for t in [*_wording(q), q.why]:
        w = _words(t)
        if any(tuple(w[i : i + n]) in ad_runs for i in range(len(w) - n + 1)):
            return fail(f"copies {n} or more words in a row from an ad")
    return ScreenResult(ok=True, problem=None)


def apply_change(rules: RulesFile, change: RuleChange) -> RulesFile:
    """Return a new rules file with the change made and the version raised by one.

    Only learned questions can be changed. Profile questions are not in the rules file,
    so an edit or removal of any id that is not learned is refused.
    """
    questions = list(rules.questions)
    ids = [q.id for q in questions]
    if change.action == "add":
        if change.question is None:
            raise ValueError("an add needs a question")
        if change.question.id in ids:
            raise ValueError(f"question id {change.question.id} already exists")
        questions.append(change.question)
    else:
        if change.question_id not in ids:
            raise ValueError(f"{change.question_id} is not a learned question")
        i = ids.index(change.question_id)
        if change.action == "remove":
            del questions[i]
        else:
            if change.question is None or change.question.id != change.question_id:
                raise ValueError("an edit needs a question with the same id")
            questions[i] = change.question
    return rules.model_copy(update={"questions": questions, "version": rules.version + 1})
