"""Owner action: with the Langfuse keys set, send one small trace and look at it in Langfuse."""

import os
from datetime import UTC, datetime

import pytest

from why_now.tracing import LangfuseTracer, UnitCounter, build_tracer

pytestmark = pytest.mark.live


def test_one_real_trace_reaches_langfuse(tmp_path, store, settings):
    clock = lambda: datetime.now(UTC)  # noqa: E731
    counter = UnitCounter(store, settings, clock)
    tracer = build_tracer(tmp_path / "traces", counter, clock, env=os.environ)
    if not isinstance(tracer, LangfuseTracer):
        pytest.skip("Langfuse keys are not set")
    with tracer.trace(
        "tracing_check", profile_id="example", rules_version=None, models={"judge": "none"}
    ) as t:
        t.step("hello", {"in": 1}, {"out": 2})
        t.score("check", 1.0)
    assert counter.used() == 3
