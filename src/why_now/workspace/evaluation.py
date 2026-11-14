"""Evaluation records: the log of every time the final pile was opened."""

from why_now.domain import FinalOpening
from why_now.workspace.base import WorkspaceBase

_OPENINGS = "final_openings"


class EvaluationArea(WorkspaceBase):
    def record_opening(self, opening: FinalOpening) -> None:
        """Add an opening to the log. The log only grows: nothing is edited or removed."""
        number = len(self.final_pile_openings()) + 1
        self.put_model(_OPENINGS, f"{self.require_profile()}/{number:04d}", opening)

    def final_pile_openings(self) -> list[FinalOpening]:
        """This profile's openings, oldest first."""
        found = self.list_models(_OPENINGS, FinalOpening, self.require_profile() + "/")
        return sorted(found, key=lambda o: o.opened_at)
