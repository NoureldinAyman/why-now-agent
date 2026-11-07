"""Where the workspace keeps its documents: a local folder, or S3 and DynamoDB on AWS."""

from collections.abc import Iterator
from typing import Protocol


class Store(Protocol):
    """JSON documents grouped into collections. Keys may contain `/` to group them further."""

    def put(self, collection: str, key: str, doc: dict) -> None: ...
    def get(self, collection: str, key: str) -> dict | None: ...
    def list(self, collection: str, prefix: str = "") -> Iterator[tuple[str, dict]]: ...
    def delete(self, collection: str, key: str) -> None: ...


# Characters Windows does not allow in file names, plus the folder separator `\`.
_BAD_CHARS = set('<>:"|?*\\') | {chr(c) for c in range(32)}
# Names Windows reserves for devices, with or without an extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(1, 10)}


def split_name(name: str) -> list[str]:
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
