"""The keep rule: whether a measured rule change stays."""

from pydantic import BaseModel

from why_now.evaluation.score import ScoreResult
from why_now.settings import Settings


class KeepResult(BaseModel):
    keep: bool
    reasons: list[str]


def decide_keep(
    check_before: ScoreResult,
    check_after: ScoreResult,
    practice_before: ScoreResult,
    practice_after: ScoreResult,
    hostile_passed: bool | None,
    settings: Settings,
) -> KeepResult:
    """Keep a change only if every condition holds. Reasons list each one that fails.

    `hostile_passed=None` means the hostile tests have not run. They cost money, so the
    caller runs them only when the other conditions already hold.
    """
    betas = {r.beta for r in (check_before, check_after, practice_before, practice_after)}
    if len(betas) > 1:
        # Scores with different weightings are not on one scale. See docs/decisions/0006.
        raise ValueError(f"scores use different betas: {sorted(betas)}")
    reasons: list[str] = []
    if check_after.f <= check_before.f:
        reasons.append("check pile score did not rise")
    if check_after.correct - check_before.correct < settings.keep_min_gain:
        reasons.append(
            f"fewer than {settings.keep_min_gain} more companies right on the check pile"
        )
    if practice_after.f < practice_before.f or practice_after.correct < practice_before.correct:
        reasons.append("practice pile got worse")
    if not reasons:
        if hostile_passed is None:
            reasons.append("hostile tests needed")
        elif not hostile_passed:
            reasons.append("hostile tests failed")
    return KeepResult(keep=not reasons, reasons=reasons)
