"""Finding the agent's mistakes, for the improvement loop to learn from."""

from typing import Literal

from pydantic import BaseModel

from why_now.domain import Answer, Company, Decision, RulesFile
from why_now.evaluation.records import PileResult
from why_now.settings import Settings
from why_now.workspace import Workspace


class Mistake(BaseModel):
    id: str
    origin: Literal["practice", "decision"]
    company_key: str
    agent_yes: bool
    reviewer_yes: bool
    reason: str
    answers: list[Answer]  # how the judge answered each fit question, empty for a decision
    quotes: list[str] = []  # short excerpts of the company's ads, empty for a decision


def find_mistakes(
    workspace: Workspace, practice: PileResult, rules: RulesFile, settings: Settings
) -> list[Mistake]:
    """Where the agent and the reviewer disagree: on the practice pile, and in daily decisions."""
    cases = workspace.cases()
    company_of = {case.case_id: case.company_key for case in cases}
    marks = {mark.case_id: mark for mark in workspace.marks("first")}
    found = [
        Mistake(
            id=f"practice:{company_of[row.case_id]}",
            origin="practice",
            company_key=company_of[row.case_id],
            agent_yes=row.agent_yes,
            reviewer_yes=row.reviewer_yes,
            reason=_reason(marks[row.case_id].reason, marks[row.case_id].chips),
            answers=row.answers,
            quotes=_quotes(workspace.case_company(row.case_id), settings),
        )
        for row in practice.rows
        if row.agent_yes != row.reviewer_yes
    ]
    return found + _decision_mistakes(_decisions_to_read(workspace))


def right_yes_reasons(workspace: Workspace, practice: PileResult) -> list[str]:
    """The reasons the reviewer gave for companies the agent rightly said yes to.

    They show what makes a company count, so the AI can propose questions that count for a
    company and not only against one. They come from the same places as the mistakes.
    """
    marks = {mark.case_id: mark for mark in workspace.marks("first")}
    reasons = [
        _reason(marks[row.case_id].reason, marks[row.case_id].chips)
        for row in practice.rows
        if row.agent_yes and row.reviewer_yes
    ]
    reasons += [
        _reason(decision.reason, decision.chips)
        for decision in _decisions_to_read(workspace)
        if decision.approved and decision.from_list != "judged_no"
    ]
    return [reason for reason in reasons if reason]


def _decisions_to_read(workspace: Workspace) -> list[Decision]:
    """The latest decision on each company the loop may learn from.

    A later decision replaces an earlier one. A company in any pile but the practice pile is
    held back: its decisions are never read.
    """
    held_back = {case.company_key for case in workspace.cases() if case.pile != "practice"}
    latest: dict[str, Decision] = {}
    for decision in sorted(workspace.decisions(), key=lambda d: d.decided_at):
        latest[decision.company_key] = decision
    return [d for d in latest.values() if d.company_key not in held_back]


def _decision_mistakes(decisions: list[Decision]) -> list[Mistake]:
    """The companies the reviewer's decision disagrees with the list they were on.

    A company on the short or more list is a yes by the agent, one on the judged-no list a no.
    """
    mistakes: list[Mistake] = []
    for decision in decisions:
        agent_yes = decision.from_list != "judged_no"
        if agent_yes == decision.approved:
            continue
        mistakes.append(
            Mistake(
                id=f"decision:{decision.company_key}",
                origin="decision",
                company_key=decision.company_key,
                agent_yes=agent_yes,
                reviewer_yes=decision.approved,
                reason=_reason(decision.reason, decision.chips),
                answers=[],
            )
        )
    return mistakes


def _reason(reason: str, chips: list[str]) -> str:
    """The reviewer's tapped chips and typed words as one text, leaving out what is empty."""
    return "; ".join(part for part in [*chips, reason] if part)


def _quotes(company: Company | None, settings: Settings) -> list[str]:
    """The title and opening of a few of the company's ads, so the AI can see what it hires for."""
    if company is None:
        return []
    return [
        f'{ad.title}: "{ad.text[: settings.mistake_ad_chars]}"'
        for ad in company.ads[: settings.mistake_ads]
    ]
