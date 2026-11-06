"""The read step's documents: each careers page's job ads, and each job source's page health."""

from pydantic import TypeAdapter

from why_now.domain import BoardHealth, JobAd
from why_now.workspace.base import WorkspaceBase

_HEALTH = TypeAdapter(dict[str, BoardHealth])


class ReadArea(WorkspaceBase):
    def load_board_ads(self, source: str, board: str) -> list[JobAd] | None:
        """The ads saved at the last good read of a careers page, or None if never read."""
        doc = self.store.get("board_ads", _board_key(source, board))
        return None if doc is None else [JobAd.model_validate(a) for a in doc["ads"]]

    def save_board_ads(self, source: str, board: str, ads: list[JobAd]) -> bool:
        """Save a careers page's ads. Returns False, writing nothing, if they haven't changed."""
        doc = {"ads": [a.model_dump(mode="json") for a in ads]}
        return self._put_if_changed("board_ads", _board_key(source, board), doc)

    def all_board_ads(self) -> list[JobAd]:
        """Every job ad saved at the last good read of every careers page."""
        return [
            JobAd.model_validate(a) for _, doc in self.store.list("board_ads") for a in doc["ads"]
        ]

    def board_health(self, source: str) -> dict[str, BoardHealth]:
        doc = self.store.get("board_health", source)
        return {} if doc is None else _HEALTH.validate_python(doc)

    def save_board_health(self, source: str, health: dict[str, BoardHealth]) -> bool:
        """Save page health for a source. Returns False, writing nothing, if it hasn't changed."""
        return self._put_if_changed(
            "board_health", source, _HEALTH.dump_python(health, mode="json")
        )

    def _put_if_changed(self, collection: str, key: str, doc: dict) -> bool:
        # Each write costs money on AWS, so an unchanged document is not written again.
        if self.store.get(collection, key) == doc:
            return False
        self.store.put(collection, key, doc)
        return True


def _board_key(source: str, board: str) -> str:
    # Lower case, because on Windows `Acme` and `acme` would be the same file.
    return f"{source}/{board.lower()}"
