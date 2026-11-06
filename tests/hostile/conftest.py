from collections.abc import Callable
from typing import Any

import httpx
import pytest
from hostile_fakes import (
    CUTOFF,
    NOW,
    QUESTIONS,
    BrokenWriter,
    LeakyReader,
    fake_web_reader,
    models_with,
)

from why_now.ai import Models
from why_now.domain import FitQuestion, Profile
from why_now.hostile.attacks import Attack
from why_now.hostile.runner import AttackResult, run_attacks
from why_now.pipeline.reader import PageReader
from why_now.settings import Settings
from why_now.store.local import LocalStore
from why_now.tracing import LocalLogTracer, UnitCounter


@pytest.fixture
def questions() -> list[FitQuestion]:
    return QUESTIONS


@pytest.fixture
def profile(make_profile: Callable[..., Profile]) -> Profile:
    return make_profile()


@pytest.fixture
def tracer(tmp_path, store: LocalStore, settings: Settings) -> LocalLogTracer:
    return LocalLogTracer(
        tmp_path / "traces", UnitCounter(store, settings, lambda: NOW), lambda: NOW
    )


@pytest.fixture
def honest_models() -> Models:
    return models_with()


@pytest.fixture
def broken_writer() -> BrokenWriter:
    return BrokenWriter()


@pytest.fixture
def leaky_reader() -> LeakyReader:
    return LeakyReader()


@pytest.fixture
def web_requests() -> list[httpx.Request]:
    """Every request the fake web was sent. A refused address must leave this empty."""
    return []


@pytest.fixture
def real_reader(settings: Settings, web_requests: list[httpx.Request]) -> PageReader:
    return fake_web_reader(settings, web_requests)


@pytest.fixture
def run(
    settings: Settings, profile: Profile, tracer: LocalLogTracer, real_reader: PageReader
) -> Callable[..., list[AttackResult]]:
    def go(
        attacks: list[Attack], models: Models, reader: Any = None, category: str = "hostile"
    ) -> list[AttackResult]:
        return run_attacks(
            attacks,
            models,
            QUESTIONS,
            reader or real_reader,
            settings,
            category,
            profile=profile,
            cutoff=CUTOFF,
            tracer=tracer,
            now=NOW,
        )

    return go
