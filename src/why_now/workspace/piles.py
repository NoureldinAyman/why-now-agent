"""Whether the improvement loop has started. Once it has, the piles are frozen."""

from why_now.workspace.base import WorkspaceBase

_COLLECTION = "loop_state"


class PilesArea(WorkspaceBase):
    def loop_started(self) -> bool:
        doc = self.store.get(_COLLECTION, self.require_profile())
        return bool(doc and doc["started"])

    def set_loop_started(self) -> None:
        """Freeze this profile's piles. The split is refused from now on."""
        self.store.put(_COLLECTION, self.require_profile(), {"started": True})
