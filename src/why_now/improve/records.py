"""What an improvement run records.

Kept apart from the run so the workspace can save these without importing the code that
makes them, which itself imports the workspace.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from why_now.evaluation.score import ScoreResult
from why_now.improve.screen import RuleChange


class TryRecord(BaseModel):
    """One try, kept whichever way it went. The scores are None for a try that was screened
    out, because nothing was measured."""

    try_id: str
    started_at: datetime
    change: RuleChange | None
    screen_problem: str | None
    check_before: ScoreResult | None
    check_after: ScoreResult | None
    practice_before: ScoreResult | None
    practice_after: ScoreResult | None
    outcome: Literal["kept", "discarded", "screened_out"]
    reasons: list[str]
    cost_usd: float
    rules_version_before: int
    rules_version_after: int


class ImproveResult(BaseModel):
    tries: list[TryRecord]
    stop_reason: Literal["no_mistakes", "budget", "check_pile_used_up", "not_ready", "run_limit"]
