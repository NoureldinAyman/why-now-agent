import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from why_now.tracing import TRY, LocalLogTracer, UnitCounter


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 11, 5, 12, tzinfo=UTC))


def events(folder: Path) -> list[dict]:
    return [
        json.loads(line)
        for f in sorted(folder.glob("*.jsonl"))
        for line in f.open(encoding="utf-8")
    ]


def test_trace_records_profile_rules_version_and_models(tmp_path, store, settings, clock):
    tracer = LocalLogTracer(tmp_path / "traces", UnitCounter(store, settings, clock), clock)
    with tracer.trace(
        "judge", profile_id="p1", rules_version=3, models={"judge": "claude-sonnet-5-5"}
    ) as t:
        t.step("answer", {"pack": "x"}, {"q1": 0.7})
        t.score("strength", 0.6)
    first, step, score = events(tmp_path / "traces")
    assert first["event"] == "trace" and first["name"] == "judge"
    assert (first["profile_id"], first["rules_version"]) == ("p1", 3)
    assert first["models"] == {"judge": "claude-sonnet-5-5"}
    assert (step["event"], step["name"], step["output"]) == ("step", "answer", {"q1": 0.7})
    assert (score["event"], score["value"]) == ("score", 0.6)
    assert step["trace_id"] == score["trace_id"] == first["trace_id"]


def test_traces_steps_and_scores_each_count_as_a_unit(tmp_path, store, settings, clock):
    counter = UnitCounter(store, settings, clock)
    tracer = LocalLogTracer(tmp_path / "traces", counter, clock)
    with tracer.trace("judge", profile_id="p1", rules_version=None, models={}) as t:
        t.step("a", 1, 2)
        t.step("b", 1, 2)
        t.score("s", 1.0)
    assert counter.used() == 4


def test_tracer_thins_company_traces_but_not_tries_near_the_limit(tmp_path, store, settings, clock):
    counter = UnitCounter(store, settings.model_copy(update={"langfuse_thin_at_units": 10}), clock)
    counter.add(10)
    tracer = LocalLogTracer(tmp_path / "traces", counter, clock)
    with tracer.trace("judge", profile_id="p1", rules_version=1, models={}) as t:
        t.step("a", 1, 2)
        t.step("b", 1, 2)
        t.score("strength", 0.4)
    with tracer.trace(TRY, profile_id="p1", rules_version=1, models={}) as t:
        t.step("a", 1, 2)
    logged = events(tmp_path / "traces")
    judge_id = logged[0]["trace_id"]
    judge = [e for e in logged if e["trace_id"] == judge_id]
    tries = [e for e in logged if e["trace_id"] != judge_id]
    assert judge[0]["detail"] == "light"
    assert [e["event"] for e in judge] == ["trace", "score", "totals"]
    assert judge[-1]["steps_skipped"] == 2
    assert tries[0]["detail"] == "full"
    assert [e["event"] for e in tries] == ["trace", "step"]


def test_light_traces_skip_steps_even_below_the_limit(tmp_path, store, settings, clock):
    tracer = LocalLogTracer(tmp_path / "traces", UnitCounter(store, settings, clock), clock)
    with tracer.trace(
        "quick_look", profile_id="p1", rules_version=None, models={}, detail="light"
    ) as t:
        t.step("company", 1, 2)
    assert [e["event"] for e in events(tmp_path / "traces")] == ["trace", "totals"]


def test_units_start_again_each_month(store, settings, clock):
    counter = UnitCounter(store, settings, clock)
    counter.add(5)
    clock.now = datetime(2026, 12, 1, tzinfo=UTC)
    assert counter.used() == 0


def test_an_error_inside_a_trace_is_recorded_and_raised(tmp_path, store, settings, clock):
    tracer = LocalLogTracer(tmp_path / "traces", UnitCounter(store, settings, clock), clock)
    with (
        pytest.raises(RuntimeError),
        tracer.trace("judge", profile_id="p1", rules_version=None, models={}),
    ):
        raise RuntimeError("boom")
    assert events(tmp_path / "traces")[-1]["event"] == "error"
