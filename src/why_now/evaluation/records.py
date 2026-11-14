"""What an evaluation returns and what is kept of it.

Kept apart from `evaluate.py` so the workspace can save these without importing the code
that makes them, which itself imports the workspace.
"""

from datetime import date, datetime

from pydantic import BaseModel

from why_now.domain import Answer
from why_now.evaluation.score import ScoreResult


class CaseRow(BaseModel):
    """One graded company: what the agent said, what the reviewer said, and how it got there."""

    case_id: str
    agent_yes: bool
    reviewer_yes: bool
    quick_passed: bool
    answers: list[Answer]  # the judge's answers, empty when the quick look dropped the company


class PileResult(BaseModel):
    pile: str
    score: ScoreResult
    rows: list[CaseRow]
    failed_cases: list[str]  # companies the models could not answer for, never counted as a no
    rules_version: int
    profile_version: str
    models: dict[str, str]  # the answer key of the quick look and judge that gave these answers


class ScorePoint(BaseModel):
    """One score, kept with when it was taken. Scores are joined into a line only when their
    pile, rules version, profile version and models all match."""

    at: datetime
    result: PileResult


class ComparisonResult(BaseModel):
    """Two judges scored on the same check pile companies. Kept whichever way it goes."""

    scores: dict[str, ScoreResult]  # by the judge's answer key
    winner: str  # the answer key of the judge with the higher score
    day: date


class QuestionSpread(BaseModel):
    """How far one question's answers moved when it was asked again and again.

    On one company the spread is the highest answer minus the lowest. `average` is the mean
    of that over the companies asked about, and `worst` is the largest.
    """

    average: float
    worst: float


class ConsistencyResult(BaseModel):
    answer_key: str
    asks: int
    companies: int  # how many companies were asked about
    failed: list[str]  # packs left out because the model could not answer one of the asks
    spread: dict[str, QuestionSpread]  # by question id
