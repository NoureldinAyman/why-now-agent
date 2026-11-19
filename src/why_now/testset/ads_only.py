"""Prepare that can make no paid call, so it is safe to offer where the keys are not at hand.

With `test_case_web_research` off a test case pack holds job ads only, and building it asks
no model anything. This runs the same `prepare` with models that refuse every call, so the
promise is kept by the code and not only by the setting, and it refuses at the start when
the setting is on. The review page on AWS uses it, because there the keys and the budget are
for the scheduled run, not for a web request.
"""

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import httpx

from why_now.ai import Models
from why_now.ai.budget import Meter
from why_now.domain import Profile
from why_now.pipeline.reader import PageReader
from why_now.run_context import RunContext
from why_now.settings import Settings
from why_now.store import Store
from why_now.testset.packs import BuildResult, prepare


class PaidCallRefused(RuntimeError):
    """Something asked for a paid call where none is allowed."""


class _Refusing:
    """Stands in for every kind of model, and refuses to be used."""

    model = answer_key = "none"

    def answer(self, *args: Any, **kwargs: Any) -> Any:
        raise PaidCallRefused("no model may be called here")

    def structured(self, *args: Any, **kwargs: Any) -> Any:
        raise PaidCallRefused("no model may be called here")

    def step(self, *args: Any, **kwargs: Any) -> Any:
        raise PaidCallRefused("no model may be called here")


class _NoTrace:
    def step(self, name: str, input: Any, output: Any) -> None:
        pass

    def score(self, name: str, value: float) -> None:
        pass


class _NoTracer:
    """Keeps nothing, so the web function writes no trace files."""

    @contextmanager
    def trace(self, name: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield _NoTrace()


def no_models() -> Models:
    return Models(
        quick_look=_Refusing(), judge=_Refusing(), writer=_Refusing(), research=_Refusing()
    )


def prepare_ads_only(
    settings: Settings,
    store: Store,
    profile: Profile,
    n: int,
    seed: int,
    *,
    clock: Callable[[], datetime],
) -> BuildResult:
    """Pick `n` companies and build their packs from job ads, calling no model."""
    if settings.test_case_web_research:
        raise PaidCallRefused(
            "Preparing here would need web research, which costs money. "
            "Prepare on your own computer, or turn test_case_web_research off."
        )
    reader = PageReader(httpx.Client(trust_env=False), settings)
    ctx = RunContext(
        settings=settings,
        store=store,
        sources=[],
        boards={},
        models=no_models(),
        reader=reader,
        meter=Meter(store, settings, clock),
        tracer=_NoTracer(),
        clock=clock,
    )
    with reader.http:
        return prepare(ctx, profile, n, seed)
