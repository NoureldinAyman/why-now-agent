"""Evaluation records: the log of final pile openings, and every score taken."""

from why_now.domain import FinalOpening
from why_now.evaluation.records import ScorePoint
from why_now.workspace.base import WorkspaceBase

_OPENINGS = "final_openings"
_SCORES = "score_points"


class EvaluationArea(WorkspaceBase):
    def record_opening(self, opening: FinalOpening) -> None:
        """Add an opening to the log. The log only grows: nothing is edited or removed."""
        number = len(self.final_pile_openings()) + 1
        self.put_model(_OPENINGS, f"{self.require_profile()}/{number:04d}", opening)

    def final_pile_openings(self) -> list[FinalOpening]:
        """This profile's openings, oldest first."""
        found = self.list_models(_OPENINGS, FinalOpening, self.require_profile() + "/")
        return sorted(found, key=lambda o: o.opened_at)

    def save_score_point(self, point: ScorePoint) -> None:
        """Keep a score. Like the openings, scores are only added, never edited or removed."""
        number = len(self.score_points()) + 1
        self.put_model(_SCORES, f"{self.require_profile()}/{number:04d}", point)

    def score_points(self) -> list[ScorePoint]:
        """This profile's scores, oldest first."""
        found = self.list_models(_SCORES, ScorePoint, self.require_profile() + "/")
        return sorted(found, key=lambda p: p.at)
