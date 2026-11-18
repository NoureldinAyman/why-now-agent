"""A Store kept as one JSON file per document in a local folder."""

import json
import os
import tempfile
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

from why_now.store import split_name

SUFFIX = ".json"


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._swapping = threading.Lock()

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

    def collections(self) -> Sequence[str]:
        """The collections that hold at least one document, by name. Other files in the folder,
        such as trace logs, are not documents and do not count."""
        if not self.root.is_dir():
            return []
        return sorted(
            p.name
            for p in self.root.iterdir()
            if p.is_dir() and any(f.suffix == SUFFIX for f in p.rglob(f"*{SUFFIX}"))
        )

    def swap(self, collection: str, key: str, expected: dict | None, new: dict | None) -> bool:
        """Creating is atomic, even between programs: the finished file is linked into place,
        and the link fails if the name is taken. Replacing or removing is checked then done,
        one at a time inside this program, which is enough for one person on one computer."""
        path = self._path(collection, key)
        if expected is None:
            return new is not None and self._create(path, new)
        with self._swapping:
            if self.get(collection, key) != expected:
                return False
            if new is None:
                self.delete(collection, key)
            else:
                self.put(collection, key, new)
            return True

    def _create(self, path: Path, doc: dict) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                return False
            return True
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _folder(self, collection: str) -> Path:
        return self._inside(self.root.joinpath(*split_name(collection)), collection)

    def _path(self, collection: str, key: str) -> Path:
        parts = split_name(key)
        folder = self._folder(collection).joinpath(*parts[:-1])
        return self._inside(folder / (parts[-1] + SUFFIX), key)

    def _inside(self, path: Path, name: str) -> Path:
        # Compared as text, after making both absolute. Asking the disk instead
        # (`Path.resolve`) can give different answers on Windows while another
        # thread is creating folders, which refused safe names. `split_name` already
        # refuses `..` and separators, so this is a second guard.
        if not Path(os.path.abspath(path)).is_relative_to(os.path.abspath(self.root)):
            raise ValueError(f"name leaves the workspace: {name!r}")
        return path
