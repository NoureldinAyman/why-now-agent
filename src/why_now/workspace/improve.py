"""The improvement loop's record: every try, and which mistakes were tried."""

from why_now.improve.records import TryRecord
from why_now.workspace.base import WorkspaceBase

_TRIES = "tries"
_TRIED = "tried_mistakes"


class ImproveArea(WorkspaceBase):
    def save_try(self, record: TryRecord) -> None:
        """Keep a try. Every try is kept, kept or not, so nothing is quietly dropped."""
        number = len(self.tries()) + 1
        self.put_model(_TRIES, f"{self.require_profile()}/{number:04d}", record)

    def tries(self) -> list[TryRecord]:
        """This profile's tries, oldest first."""
        found = self.list_models(_TRIES, TryRecord, self.require_profile() + "/")
        return sorted(found, key=lambda t: t.started_at)

    def mark_mistake_tried(self, mistake_id: str, rules_version: int) -> None:
        """Remember that a change was tried for this mistake while the rules were at this
        version. Marking one twice changes nothing."""
        ids = self.tried_mistakes(rules_version) | {mistake_id}
        doc = {"rules_version": rules_version, "mistake_ids": sorted(ids)}
        self.store.put(_TRIED, self._tried_key(rules_version), doc)

    def tried_mistakes(self, rules_version: int) -> set[str]:
        """The mistakes already tried while the rules were at this version. A new version
        starts with none, so a mistake can be tried again once the rules have changed."""
        doc = self.store.get(_TRIED, self._tried_key(rules_version))
        return set() if doc is None else set(doc["mistake_ids"])

    def _tried_key(self, rules_version: int) -> str:
        return f"{self.require_profile()}/{rules_version:04d}"
