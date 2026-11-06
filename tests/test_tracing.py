import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from why_now.tracing import TRY, LangfuseTracer, LocalLogTracer, UnitCounter, build_tracer


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


class FakeObservation:
    def __init__(self, client, name, as_type, kwargs):
        self.client, self.name, self.as_type, self.kwargs = client, name, as_type, kwargs
        self.ended = False
        self.updates: list[dict] = []
        self.scores: list[tuple[str, float]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.ended = True
        return False

    def start_observation(self, *, name, as_type="span", **kwargs):
        child = FakeObservation(self.client, name, as_type, kwargs)
        self.client.observations.append(child)
        return child

    def end(self):
        self.ended = True

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def score_trace(self, *, name, value, data_type="NUMERIC", **_):
        self.scores.append((name, value))


class FakeLangfuse:
    def __init__(self):
        self.observations: list[FakeObservation] = []
        self.flushed = 0

    def start_as_current_observation(self, *, name, as_type="span", **kwargs):
        root = FakeObservation(self, name, as_type, kwargs)
        self.observations.append(root)
        return root

    def flush(self):
        self.flushed += 1


def test_langfuse_trace_maps_names_metadata_steps_and_scores(store, settings, clock):
    client = FakeLangfuse()
    counter = UnitCounter(store, settings, clock)
    tracer = LangfuseTracer(client, counter)
    with tracer.trace(
        "judge", profile_id="p1", rules_version=3, models={"judge": "claude-sonnet-5-5"}
    ) as t:
        t.step("answer", {"pack": "x"}, {"q1": 0.7})
        t.score("strength", 0.6)
    root, step = client.observations
    assert root.name == "judge"
    assert root.kwargs["metadata"] == {
        "profile_id": "p1",
        "rules_version": 3,
        "models": {"judge": "claude-sonnet-5-5"},
        "detail": "full",
    }
    assert (step.name, step.kwargs["input"], step.kwargs["output"]) == (
        "answer",
        {"pack": "x"},
        {"q1": 0.7},
    )
    assert step.ended
    assert root.scores == [("strength", 0.6)]
    assert client.flushed == 1
    assert counter.used() == 3  # the trace, one step and one score


def test_langfuse_tracer_thins_company_traces_but_not_tries(store, settings, clock):
    client = FakeLangfuse()
    counter = UnitCounter(store, settings.model_copy(update={"langfuse_thin_at_units": 10}), clock)
    counter.add(10)
    tracer = LangfuseTracer(client, counter)
    with tracer.trace("judge", profile_id="p1", rules_version=1, models={}) as t:
        t.step("a", 1, 2)
        t.score("strength", 0.4)
    with tracer.trace(TRY, profile_id="p1", rules_version=1, models={}) as t:
        t.step("a", 1, 2)
    judge, try_root, try_step = client.observations
    assert judge.kwargs["metadata"]["detail"] == "light"
    assert judge.scores == [("strength", 0.4)]
    assert judge.updates[-1]["metadata"]["steps_skipped"] == 1
    assert try_root.kwargs["metadata"]["detail"] == "full" and try_step.name == "a"
    assert counter.used() == 10 + 2 + 2  # judge: trace and score; try: trace and step


def test_langfuse_error_is_marked_and_raised(store, settings, clock):
    client = FakeLangfuse()
    tracer = LangfuseTracer(client, UnitCounter(store, settings, clock))
    with (
        pytest.raises(RuntimeError),
        tracer.trace("judge", profile_id="p1", rules_version=None, models={}),
    ):
        raise RuntimeError("boom")
    assert client.observations[0].updates[-1]["level"] == "ERROR"
    assert client.flushed == 1


def test_build_tracer_uses_the_local_log_without_keys(tmp_path, store, settings, clock):
    counter = UnitCounter(store, settings, clock)
    tracer = build_tracer(tmp_path / "traces", counter, clock, env={})
    assert isinstance(tracer, LocalLogTracer)


def test_build_tracer_uses_langfuse_when_both_keys_are_set(tmp_path, store, settings, clock):
    counter = UnitCounter(store, settings, clock)
    made = []
    tracer = build_tracer(
        tmp_path / "traces",
        counter,
        clock,
        env={"LANGFUSE_PUBLIC_KEY": "a", "LANGFUSE_SECRET_KEY": "b"},
        make_client=lambda: made.append(1) or FakeLangfuse(),
    )
    assert isinstance(tracer, LangfuseTracer) and made == [1]


def test_build_tracer_falls_back_when_the_client_cannot_start(tmp_path, store, settings, clock):
    def broken():
        raise ImportError("no langfuse")

    tracer = build_tracer(
        tmp_path / "traces",
        UnitCounter(store, settings, clock),
        clock,
        env={"LANGFUSE_PUBLIC_KEY": "a", "LANGFUSE_SECRET_KEY": "b"},
        make_client=broken,
    )
    assert isinstance(tracer, LocalLogTracer)
