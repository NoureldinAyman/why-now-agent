import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from why_now.domain import FitQuestion, Profile
from why_now.settings import Settings, load_settings
from why_now.store.local import LocalStore


@pytest.fixture
def store(tmp_path) -> LocalStore:
    return LocalStore(tmp_path / "workspace")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return load_settings(None, env={}).model_copy(update={"workspace_path": tmp_path / "workspace"})


@pytest.fixture
def make_profile() -> Callable[..., Profile]:
    """A throwaway profile with a random product name, so no test depends on a real product."""

    def make(**overrides: Any) -> Profile:
        name = f"Product {uuid.uuid4().hex[:8]}"
        values: dict[str, Any] = {
            "id": name.lower().replace(" ", "-"),
            "product_name": name,
            "product_description": "A tool that helps sales teams.",
            "users": "Sales teams",
            "search_words": ["sales"],
            "quick_look_questions": [FitQuestion(id="q1", text="Does it sell to businesses?")],
            "fit_questions": [
                FitQuestion(id="f1", text="Is it hiring salespeople?", kind="required")
            ],
            "why_now": "A new sales ad shows the team is growing.",
        }
        return Profile.model_validate(values | overrides)

    return make


@pytest.fixture
def moto_aws(monkeypatch) -> Iterator[None]:
    """A stand-in AWS with fake keys. See `aws_fake.py`."""
    from aws_fake import REGION, fake_aws

    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with fake_aws():
        yield
