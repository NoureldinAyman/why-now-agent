"""The attack set against the real models. Costs money: run only on purpose, after the owner's yes.

    uv run pytest tests/hostile/test_live.py -m live

It needs ANTHROPIC_API_KEY, and TYPESAFE_API_KEY if the judge is a Jev model. It uses the
spending meter in a throwaway workspace, so it counts against no real month, but the calls
are real and paid for.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from why_now.ai import build_models
from why_now.ai.budget import Meter
from why_now.domain import FitQuestion
from why_now.hostile.attacks import load_attacks
from why_now.hostile.runner import run_attacks
from why_now.pipeline.reader import PageReader
from why_now.profile import load_profile
from why_now.settings import load_settings
from why_now.store.local import LocalStore
from why_now.tracing import LocalLogTracer, UnitCounter

EXAMPLE_PROFILE = Path("examples/profiles/practice-tool.example.yaml")


@pytest.mark.live
def test_real_models_resist_the_attack_set(tmp_path):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set")
    settings = load_settings(None, env=os.environ).model_copy(
        update={"workspace_path": tmp_path / "workspace"}
    )
    store = LocalStore(settings.workspace_path)
    now = datetime.now(UTC)
    meter = Meter(store, settings, lambda: now)
    models = build_models(settings, meter, os.environ)
    profile = load_profile(EXAMPLE_PROFILE)
    questions: list[FitQuestion] = profile.fit_questions
    tracer = LocalLogTracer(
        tmp_path / "traces", UnitCounter(store, settings, lambda: now), lambda: now
    )
    with httpx.Client(trust_env=False) as http:
        results = run_attacks(
            load_attacks(),
            models,
            questions,
            PageReader(http, settings),
            settings,
            "hostile",
            profile=profile,
            # A cut-off of one half is a test value: the attacks compare two decisions made
            # with the same cut-off, so any fixed value tests the same thing.
            cutoff=0.5,
            tracer=tracer,
            now=now,
        )
    failed = {r.attack_id: r.problem for r in results if not r.passed}
    assert not failed, failed
