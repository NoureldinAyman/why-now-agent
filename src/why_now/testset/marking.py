"""The checks every mark and decision goes through, wherever it is made.

The marking page, the repeat page, the review page and the `mark` and `decide` commands all
come here, so they accept and refuse exactly the same things.
"""

from datetime import datetime
from typing import Final, Literal, get_args

from why_now.domain import CaseRecord, Mark
from why_now.workspace import Workspace

ANSWERS: Final = get_args(Mark.model_fields["answer"].annotation)
CHOICES: Final = {"approve": True, "reject": False}


def read_form(
    answer: str, reason: str, chips: list[str] | None, allowed: list[str]
) -> tuple[str, list[str], str | None]:
    """The reason and chips of a sent mark, tidied, and what is wrong with it if anything."""
    reason, picked = tidy_reason(reason, chips)
    return reason, picked, form_error(answer, reason, picked, allowed)


def tidy_reason(reason: str, chips: list[str] | None) -> tuple[str, list[str]]:
    """The sentence without stray spacing, and each chip once, in the order sent."""
    return reason.strip(), list(dict.fromkeys(chips or []))


def form_error(answer: str, reason: str, chips: list[str], allowed: list[str]) -> str | None:
    """What is wrong with a submitted answer and reason, or None if all is fine."""
    if answer not in ANSWERS:
        return "Choose yes, no or can't tell."
    return reason_error(reason, chips, allowed)


def decision_error(decision: str, reason: str, chips: list[str], allowed: list[str]) -> str | None:
    """What is wrong with a submitted decision and reason, or None if all is fine."""
    if decision not in CHOICES:
        return "Choose approve or reject."
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
    workspace: Workspace,
    case: CaseRecord,
    answer: str,
    reason: str,
    chips: list[str],
    round: Literal["first", "repeat"],
    *,
    now: datetime,
    profile_version: str | None,
) -> Mark:
    """The mark for a checked answer, noting whether the company was on a daily list before."""
    return Mark.model_validate(
        {
            "case_id": case.case_id,
            "answer": answer,
            "reason": reason,
            "chips": chips,
            "seen_on_list": workspace.was_listed(case.company_key, now),
            "marked_at": now,
            "round": round,
            "profile_version": profile_version,
        }
    )
