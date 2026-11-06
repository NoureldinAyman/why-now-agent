"""The score: F0.5 of the agent's yes or no against the reviewer's, with precision and recall.

F0.5 counts precision more heavily than recall, because wasting a person's time
on a wrong yes is worse than missing a company. See docs/decisions/0002.
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
    f05: float


def score(rows: list[tuple[bool, bool]]) -> ScoreResult:
    """Score `(agent_yes, reviewer_yes)` rows.

    With no yes from the agent, precision is 0, so saying no to everything scores 0.
    """
    if not rows:
        raise ValueError("nothing to score")
    tp = sum(agent and reviewer for agent, reviewer in rows)
    fp = sum(agent and not reviewer for agent, reviewer in rows)
    fn = sum(not agent and reviewer for agent, reviewer in rows)
    tn = len(rows) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    # F-beta with beta = 0.5: (1 + b^2) P R / (b^2 P + R).
    f05 = 1.25 * precision * recall / (0.25 * precision + recall) if tp else 0.0
    return ScoreResult(
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        n=len(rows),
        correct=tp + tn,
        precision=precision,
        recall=recall,
        f05=f05,
    )
