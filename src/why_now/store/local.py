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
                f.flush()
                os.fsync(f.fileno())
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
        return self._inside(self.root.joinpath(*_parts(collection)), collection)

    def _path(self, collection: str, key: str) -> Path:
        parts = _parts(key)
        folder = self._folder(collection).joinpath(*parts[:-1])
        return self._inside(folder / (parts[-1] + SUFFIX), key)

    def _inside(self, path: Path, name: str) -> Path:
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError(f"name leaves the workspace: {name!r}")
        return path


# Characters Windows does not allow in file names, plus the folder separator `\`.
_BAD_CHARS = set('<>:"|?*\\') | {chr(c) for c in range(32)}
# Names Windows reserves for devices, with or without an extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(1, 10)}


def _parts(name: str) -> list[str]:
    """Split a `/`-separated name, refusing any part that is not a safe file name everywhere.

    Refused: empty parts, parts starting with `.` (so `..` and the store's own
    temporary files), trailing dots or spaces, characters Windows forbids, and
    Windows device names such as `con`. Keys built from company names must be
    made safe before they reach the store.
    """
    parts = name.split("/")
    for part in parts:
        if (
            not part
            or part.startswith(".")
            or part.endswith((".", " "))
            or _BAD_CHARS & set(part)
            or part.split(".")[0].upper() in _RESERVED
        ):
            raise ValueError(f"name not allowed in the workspace: {name!r}")
    return parts
