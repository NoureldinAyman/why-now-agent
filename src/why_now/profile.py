"""Load a profile from a YAML file and say clearly what is wrong with it."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from why_now.domain import FitQuestion, Profile

QUESTION_LISTS = ("quick_look_questions", "fit_questions")


class ProfileError(Exception):
    """A profile file is missing, unreadable or incomplete."""


def load_profile(path: Path) -> Profile:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ProfileError(f"cannot read profile {path}: {e}") from e
    return parse_profile(text, str(path))


def parse_profile(text: str, path: str) -> Profile:
    """The profile written in `text`, checked as `load_profile` checks a file. `path` names
    where the text came from in any error."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ProfileError(f"profile {path} is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ProfileError(f"profile {path} must be a set of named fields")

    # A misspelt field would otherwise be dropped quietly and its default used instead.
    unknown = sorted(str(k) for k in raw if k not in Profile.model_fields)
    for name in QUESTION_LISTS:
        questions = raw.get(name)
        if isinstance(questions, list):
            for i, q in enumerate(questions):
                if isinstance(q, dict):
                    unknown += [f"{name}.{i}.{k}" for k in q if k not in FitQuestion.model_fields]
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


USERS_QUESTION_ID = "has_users"


def quick_look_questions(profile: Profile) -> list[FitQuestion]:
    """The profile's own quick look questions or, if it has none, its required questions plus
    one built from who uses the product."""
    if profile.quick_look_questions:
        return profile.quick_look_questions
    required = [q for q in profile.fit_questions if q.kind == "required"]
    users = profile.users.strip().rstrip(".")
    built = FitQuestion(
        id=USERS_QUESTION_ID,
        text=f"Does the company employ people who fit this description: {users}?",
    )
    return [*required, built]


def profile_text(profile: Profile) -> str:
    """The profile as the YAML a profile file holds, fields in their usual order."""
    return yaml.safe_dump(
        profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100
    )
