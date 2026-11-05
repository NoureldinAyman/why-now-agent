"""Load a profile from a YAML file and say clearly what is wrong with it."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from why_now.domain import Profile


class ProfileError(Exception):
    """A profile file is missing, unreadable or incomplete."""


def load_profile(path: Path) -> Profile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ProfileError(f"cannot read profile {path}: {e}") from e
    except yaml.YAMLError as e:
        raise ProfileError(f"profile {path} is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ProfileError(f"profile {path} must be a set of named fields")

    unknown = sorted(str(k) for k in raw if k not in Profile.model_fields)
    if unknown:
        raise ProfileError(f"profile {path} has unknown fields: {', '.join(unknown)}")

    try:
        profile = Profile.model_validate(raw)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            field = ".".join(str(part) for part in err["loc"])
            problems.append(
                f"missing field {field}" if err["type"] == "missing" else f"{field}: {err['msg']}"
            )
        raise ProfileError(f"profile {path} is incomplete: {'; '.join(problems)}") from e

    if not [w for w in profile.search_words if w.strip()]:
        raise ProfileError(f"profile {path} needs at least one search word in search_words")
    return profile
