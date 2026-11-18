"""The few settings that can be changed on the review page, stored in the workspace.

The document holds overrides, which win over the settings file and the environment. Only the
names in `EDITABLE` can ever be stored or applied. Everything else stays as the file and the
environment say. The reasons: a stolen sign-in must not raise the budget and start paid runs,
and settings that shape the score or the piles must not change after scores have been seen.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from why_now.settings import Settings
from why_now.store import Store
from why_now.workspace.profiles import is_safe_id

_COLLECTION = "settings"
_KEY = "overrides"

EDITABLE = frozenset(
    {
        "short_list_size",
        "hide_days",
        "reason_chips",
        "judged_no_shown",
        "prepare_batch",
        "nightly_profiles",
    }
)


class SettingsRefused(ValueError):
    """A setting cannot be stored: it is not editable, or its value is out of bounds."""


def effective_settings(base: Settings, store: Store) -> Settings:
    """`base` (the file and the environment) with the stored overrides on top. A stored value
    that is not editable, out of bounds or no longer valid is left out, so a bad document
    never stops a run and never changes what the page may not."""
    doc = store.get(_COLLECTION, _KEY) or {}
    values = base.model_dump()
    for name in sorted(EDITABLE & doc.keys()):
        try:
            _check(base, name, doc[name])
        except SettingsRefused:
            continue
        values[name] = doc[name]
    return Settings.model_validate(values)


def save_overrides(store: Store, base: Settings, changes: Mapping[str, Any]) -> None:
    """Store `changes` as the overrides, replacing the document. Refused whole if any name is
    not editable or any value is out of bounds, so nothing is half stored."""
    for name in sorted(changes):
        if name not in EDITABLE:
            raise SettingsRefused(f"{name} cannot be changed here")
    for name, value in changes.items():
        _check(base, name, value)
    store.put(_COLLECTION, _KEY, dict(changes))


def _check(base: Settings, name: str, value: Any) -> None:
    try:
        Settings.model_validate(base.model_dump() | {name: value})
    except ValidationError as e:
        raise SettingsRefused(f"{name}: {e.errors()[0]['msg']}") from e
    low_high = base.editable_limits.get(name)
    if name == "reason_chips":
        _check_chips(base, value, low_high)
    elif name == "nightly_profiles":
        _check_ids(value)
    elif low_high is not None and not low_high[0] <= value <= low_high[1]:
        raise SettingsRefused(f"{name} must be from {low_high[0]} to {low_high[1]}")


def _check_chips(base: Settings, chips: list[str], count: tuple[int, int] | None) -> None:
    if count is not None and not count[0] <= len(chips) <= count[1]:
        raise SettingsRefused(f"reason_chips must have from {count[0]} to {count[1]} choices")
    if any(not chip.strip() for chip in chips) or len(set(chips)) != len(chips):
        raise SettingsRefused("reason_chips must be different, and not empty")
    if any(len(chip) > base.reason_chip_max_chars for chip in chips):
        raise SettingsRefused(
            f"a reason choice can be at most {base.reason_chip_max_chars} letters"
        )


def _check_ids(ids: list[str]) -> None:
    for profile_id in ids:
        if not is_safe_id(profile_id):
            raise SettingsRefused(f"nightly_profiles: {profile_id!r} is not a profile id")
