"""What every workspace area builds on: typed reads and writes over a Store."""

from collections.abc import Iterator

from pydantic import BaseModel

from why_now.store import Store


class WorkspaceBase:
    def __init__(self, store: Store, profile_id: str | None = None):
        self.store = store
        self.profile_id = profile_id

    def require_profile(self) -> str:
        """The profile this workspace was opened for, for areas kept per profile."""
        if self.profile_id is None:
            raise ValueError("this workspace was opened without a profile")
        return self.profile_id

    def put_model(self, collection: str, key: str, model: BaseModel) -> None:
        self.store.put(collection, key, model.model_dump(mode="json"))

    def get_model[M: BaseModel](self, collection: str, key: str, kind: type[M]) -> M | None:
        doc = self.store.get(collection, key)
        return None if doc is None else kind.model_validate(doc)

    def list_models[M: BaseModel](
        self, collection: str, kind: type[M], prefix: str = ""
    ) -> Iterator[M]:
        for _, doc in self.store.list(collection, prefix):
            yield kind.model_validate(doc)
