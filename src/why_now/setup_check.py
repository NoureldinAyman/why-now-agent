"""Tell a new user what is ready, what is missing and what is optional.

Only the names of keys are looked at and shown. A key's value is never printed.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from why_now.settings import Settings

CLAUDE_KEY = "ANTHROPIC_API_KEY"
JEV_KEY = "TYPESAFE_API_KEY"
LANGFUSE_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


class SetupItem(BaseModel):
    name: str
    status: Literal["ok", "missing", "optional"]
    how_to_fix: str = ""


def check_setup(settings: Settings, env: Mapping[str, str]) -> list[SetupItem]:
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
        _file_item(
            "profile",
            settings.daily_profiles,
            "Add daily_profiles to your settings file, pointing at a profile file you wrote.",
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
