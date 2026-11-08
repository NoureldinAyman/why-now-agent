"""The score: F-beta of the agent's yes or no against the reviewer's, with precision and recall.

With beta 1 (F1) a missed company counts as much as a wrong yes. A beta under 1 counts
precision more, a beta over 1 counts recall more. The beta is the `score_beta` setting,
and every score records the one it used. See docs/decisions/0006.
"""

from pydantic import BaseModel


class ScoreResult(BaseModel):
    tp: int
    fp: int
    fn: int
    tn: int
    n: int
    correct: int
    precision: float
    recall: float
    f: float
    beta: float


def score(rows: list[tuple[bool, bool]], beta: float) -> ScoreResult:
    """Score `(agent_yes, reviewer_yes)` rows with F-beta.

    With no right yes from the agent the score is 0, so saying no to everything scores 0.
    """
    if not rows:
        raise ValueError("nothing to score")
    if beta <= 0:
        raise ValueError(f"beta must be above 0, not {beta}")
    tp = sum(agent and reviewer for agent, reviewer in rows)
    fp = sum(agent and not reviewer for agent, reviewer in rows)
    fn = sum(not agent and reviewer for agent, reviewer in rows)
    tn = len(rows) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    # F-beta: (1 + b^2) P R / (b^2 P + R). With a right yes both P and R are above 0.
    b2 = beta * beta
    f = (1 + b2) * precision * recall / (b2 * precision + recall) if tp else 0.0
    return ScoreResult(
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        n=len(rows),
        correct=tp + tn,
        precision=precision,
        recall=recall,
        f=f,
        beta=beta,
    )
