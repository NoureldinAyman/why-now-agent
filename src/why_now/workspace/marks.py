"""The reviewer's marks: yes, no or can't tell, one per case and round."""

import threading
from typing import Literal

from why_now.domain import Mark
from why_now.workspace.base import WorkspaceBase

_COLLECTION = "marks"

# Held while a mark is checked and saved, so two copies of one form sent at the same moment
# cannot both pass the check. It covers one process, which is how the review page runs.
_SAVE = threading.Lock()


class MarksArea(WorkspaceBase):
    def save_mark(self, mark: Mark) -> bool:
        """Save a mark. Returns False, and changes nothing, if that case and round has one."""
        key = self._mark_key(mark.round, mark.case_id)
        with _SAVE:
            if self.store.get(_COLLECTION, key) is not None:
                return False
            self.put_model(_COLLECTION, key, mark)
        return True

    def marks(self, round: Literal["first", "repeat"]) -> list[Mark]:
        """This profile's marks for a round, in the order the cases were marked."""
        found = self.list_models(_COLLECTION, Mark, f"{self.require_profile()}/{round}/")
        return sorted(found, key=lambda m: (m.marked_at, m.case_id))

    def _mark_key(self, round: str, case_id: str) -> str:
        return f"{self.require_profile()}/{round}/{case_id}"
