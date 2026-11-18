"""Tell a new user what is ready, what is missing and what is optional.

Only the names of keys are looked at and shown. A key's value is never printed.
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from why_now.settings import Settings
from why_now.tracing import LANGFUSE_KEYS

CLAUDE_KEY = "ANTHROPIC_API_KEY"
JEV_KEY = "TYPESAFE_API_KEY"


class SetupItem(BaseModel):
    name: str
    status: Literal["ok", "missing", "optional"]
    how_to_fix: str = ""


def check_setup(
    settings: Settings, env: Mapping[str, str], profile_ids: Sequence[str] = ()
) -> list[SetupItem]:
    """What is ready and what is missing. `profile_ids` are the profiles in the workspace."""

    def has(key: str) -> bool:
        return bool(env.get(key, "").strip())

    items = [
        SetupItem(name="sample run", status="ok"),
        _key_item("Claude API key", [CLAUDE_KEY], "missing", env_has=has),
        _key_item("Jev key", [JEV_KEY], "optional", env_has=has),
        _key_item("Langfuse keys", list(LANGFUSE_KEYS), "optional", env_has=has),
    ]

    lists = list(settings.board_lists.values())
    items.append(
        _file_item(
            "careers page list",
            lists,
            "Add board_lists to your settings file, for example "
            'board_lists = { greenhouse = "examples/boards.greenhouse.example.json" }.',
        )
    )
    items.append(
        SetupItem(name="profile", status="ok")
        if profile_ids
        else SetupItem(
            name="profile",
            status="missing",
            how_to_fix="Upload a profile file with: why-now profile upload FILE",
        )
    )
    return items


def _key_item(
    name: str,
    keys: list[str],
    when_absent: Literal["missing", "optional"],
    env_has: Callable[[str], bool],
) -> SetupItem:
    absent = [k for k in keys if not env_has(k)]
    if not absent:
        return SetupItem(name=name, status="ok")
    return SetupItem(
        name=name,
        status=when_absent,
        how_to_fix=f"Set {' and '.join(absent)} in your environment.",
    )


def _file_item(name: str, paths: list[Path], how_to_fix: str) -> SetupItem:
    if paths and all(p.is_file() for p in paths):
        return SetupItem(name=name, status="ok")
    return SetupItem(name=name, status="missing", how_to_fix=how_to_fix)
