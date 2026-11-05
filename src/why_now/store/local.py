"""A Store kept as one JSON file per document in a local folder."""

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

SUFFIX = ".json"


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, collection: str, key: str, doc: dict) -> None:
        path = self._path(collection, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write a temporary file next to the target, then swap it in, so an
        # interrupted write leaves the old document in place.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, collection: str, key: str) -> dict | None:
        path = self._path(collection, key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self, collection: str, prefix: str = "") -> Iterator[tuple[str, dict]]:
        folder = self._folder(collection)
        if not folder.is_dir():
            return
        keys = sorted(
            p.relative_to(folder).as_posix().removesuffix(SUFFIX)
            for p in folder.rglob(f"*{SUFFIX}")
            if p.is_file()
        )
        for key in keys:
            if key.startswith(prefix):
                doc = self.get(collection, key)
                if doc is not None:
                    yield key, doc

    def delete(self, collection: str, key: str) -> None:
        self._path(collection, key).unlink(missing_ok=True)

    def _folder(self, collection: str) -> Path:
        _check_parts(collection, [collection])
        return self.root / collection

    def _path(self, collection: str, key: str) -> Path:
        folder = self._folder(collection)
        _check_parts(key, key.split("/"))
        path = folder.joinpath(*key.split("/")).with_name(key.split("/")[-1] + SUFFIX)
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError(f"key leaves the workspace: {key!r}")
        return path


def _check_parts(name: str, parts: list[str]) -> None:
    """Refuse names that are empty, go up a folder, or could be read as a drive or root."""
    for part in parts:
        if part in ("", ".", "..") or any(c in part for c in "\\:\0") or part.startswith("."):
            raise ValueError(f"name not allowed in the workspace: {name!r}")
