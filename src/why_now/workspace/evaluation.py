"""Evaluation records: the log of final pile openings, and every score taken."""

from why_now.domain import FinalOpening
from why_now.evaluation.records import ComparisonResult, ConsistencyResult, ScorePoint
from why_now.workspace.base import WorkspaceBase

_OPENINGS = "final_openings"
_SCORES = "score_points"
_COMPARISONS = "judge_comparisons"
_CONSISTENCY = "consistency_results"


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

    def save_comparison(self, result: ComparisonResult) -> None:
        """Keep a judge comparison. Every one is kept, so a result is never quietly replaced."""
        number = len(self.comparisons()) + 1
        self.put_model(_COMPARISONS, f"{self.require_profile()}/{number:04d}", result)

    def comparisons(self) -> list[ComparisonResult]:
        """This profile's judge comparisons, oldest first."""
        found = self.list_models(_COMPARISONS, ComparisonResult, self.require_profile() + "/")
        return sorted(found, key=lambda c: c.day)

    def save_consistency(self, result: ConsistencyResult) -> None:
        """Keep a consistency result. Every one is kept, and a model's results stay apart by key."""
        number = len(self.consistency_results()) + 1
        self.put_model(_CONSISTENCY, f"{self.require_profile()}/{number:04d}", result)

    def consistency_results(self) -> list[ConsistencyResult]:
        """This profile's consistency results, in the order they were taken."""
        found = self.store.list(_CONSISTENCY, self.require_profile() + "/")
        return [ConsistencyResult.model_validate(doc) for _, doc in found]
