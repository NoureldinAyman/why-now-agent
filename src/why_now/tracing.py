"""Tracing: a record of what the agent read, asked and answered.

`LocalLogTracer` writes one JSON line per event to a folder in the workspace, one
file per day. `LangfuseTracer` sends the same traces to Langfuse, an optional extra
behind the same `Tracer` interface. `build_tracer` picks Langfuse only when both
keys are set and the library can start, and otherwise keeps the local log.

Langfuse's free plan counts traces, steps and scores as units, with a monthly
limit. `UnitCounter` keeps count per month, and near the `langfuse_thin_at_units`
setting company traces are thinned: their steps are counted but not recorded,
while scores are kept. Tries are always traced in full, because the record of
every try is what makes the loop's results checkable. Both tracers thin the same
way, so the local log shows what Langfuse would have received.
"""

import json
import logging
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from why_now.settings import Settings
from why_now.store import Store

TRY = "try"  # the trace name for one try of the improvement loop, never thinned
UNITS_COLLECTION = "trace_units"
LANGFUSE_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")

log = logging.getLogger(__name__)

Detail = Literal["full", "light"]


class TraceHandle(Protocol):
    def step(self, name: str, input: Any, output: Any) -> None: ...
    def score(self, name: str, value: float) -> None: ...


class Tracer(Protocol):
    def trace(
        self,
        name: str,
        *,
        profile_id: str,
        rules_version: int | None,
        models: dict[str, str],
        detail: Detail = "full",
    ) -> AbstractContextManager[TraceHandle]: ...


class UnitCounter:
    """Tracing units used this month (UTC), kept in the store."""

    def __init__(self, store: Store, settings: Settings, clock: Callable[[], datetime]):
        self.store = store
        self.settings = settings
        self.clock = clock

    def add(self, units: int = 1) -> None:
        month = self._month()
        doc = self.store.get(UNITS_COLLECTION, month) or {"month": month, "units": 0}
        doc["units"] += units
        self.store.put(UNITS_COLLECTION, month, doc)

    def used(self) -> int:
        doc = self.store.get(UNITS_COLLECTION, self._month())
        return 0 if doc is None else int(doc["units"])

    def thin(self) -> bool:
        return self.used() >= self.settings.langfuse_thin_at_units

    def _month(self) -> str:
        return self.clock().astimezone(UTC).strftime("%Y-%m")


class LocalLogTracer:
    def __init__(self, folder: Path, counter: UnitCounter, clock: Callable[[], datetime]):
        self.folder = Path(folder)
        self.counter = counter
        self.clock = clock

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        profile_id: str,
        rules_version: int | None,
        models: dict[str, str],
        detail: Detail = "full",
    ) -> Iterator[TraceHandle]:
        if detail == "full" and name != TRY and self.counter.thin():
            detail = "light"
        handle = _LocalHandle(self, uuid.uuid4().hex, detail)
        handle.write(
            "trace",
            name=name,
            profile_id=profile_id,
            rules_version=rules_version,
            models=models,
            detail=detail,
        )
        try:
            yield handle
        except BaseException as e:
            handle.write("error", error=repr(e))
            raise
        finally:
            if handle.skipped:
                handle.write("totals", steps_skipped=handle.skipped)


class _LocalHandle:
    def __init__(self, tracer: LocalLogTracer, trace_id: str, detail: Detail):
        self.tracer = tracer
        self.trace_id = trace_id
        self.detail = detail
        self.skipped = 0

    def step(self, name: str, input: Any, output: Any) -> None:
        if self.detail == "light":
            self.skipped += 1
            return
        self.write("step", name=name, input=input, output=output)

    def score(self, name: str, value: float) -> None:
        self.write("score", name=name, value=value)

    def write(self, event: str, **fields: Any) -> None:
        now = self.tracer.clock()
        line = {"event": event, "trace_id": self.trace_id, "at": now.isoformat(), **fields}
        self.tracer.folder.mkdir(parents=True, exist_ok=True)
        path = self.tracer.folder / f"{now.astimezone(UTC):%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=_jsonable) + "\n")
        self.tracer.counter.add(1)


class LangfuseTracer:
    """Sends traces to Langfuse (SDK v5: `start_as_current_observation`, `score_trace`).

    One trace is a root span named after the trace. Profile, rules version, models and
    detail go in its metadata. Each step is a child span with its input and output, and
    each score is a trace-level score. Units are counted as the local log counts them:
    the trace, each step sent and each score. The client is flushed when a trace ends,
    because Langfuse sends in the background and the process may exit right after.
    """

    def __init__(self, client: Any, counter: UnitCounter):
        self.client = client
        self.counter = counter

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        profile_id: str,
        rules_version: int | None,
        models: dict[str, str],
        detail: Detail = "full",
    ) -> Iterator[TraceHandle]:
        if detail == "full" and name != TRY and self.counter.thin():
            detail = "light"
        metadata = {
            "profile_id": profile_id,
            "rules_version": rules_version,
            "models": models,
            "detail": detail,
        }
        self.counter.add(1)
        try:
            with self.client.start_as_current_observation(
                as_type="span", name=name, metadata=metadata
            ) as root:
                handle = _LangfuseHandle(self, root, detail)
                try:
                    yield handle
                except BaseException as e:
                    root.update(level="ERROR", status_message=repr(e))
                    raise
                finally:
                    if handle.skipped:
                        root.update(metadata={**metadata, "steps_skipped": handle.skipped})
        finally:
            self.client.flush()


class _LangfuseHandle:
    def __init__(self, tracer: LangfuseTracer, root: Any, detail: Detail):
        self.tracer = tracer
        self.root = root
        self.detail = detail
        self.skipped = 0

    def step(self, name: str, input: Any, output: Any) -> None:
        if self.detail == "light":
            self.skipped += 1
            return
        self.root.start_observation(name=name, as_type="span", input=input, output=output).end()
        self.tracer.counter.add(1)

    def score(self, name: str, value: float) -> None:
        self.root.score_trace(name=name, value=value, data_type="NUMERIC")
        self.tracer.counter.add(1)


def _langfuse_client() -> Any:
    from langfuse import Langfuse  # optional extra; keys and address come from the environment

    return Langfuse()


def build_tracer(
    folder: Path,
    counter: UnitCounter,
    clock: Callable[[], datetime],
    env: Mapping[str, str],
    make_client: Callable[[], Any] = _langfuse_client,
) -> Tracer:
    """Langfuse when both keys are set and it can start, otherwise the local log."""
    if all(env.get(k, "").strip() for k in LANGFUSE_KEYS):
        try:
            return LangfuseTracer(make_client(), counter)
        except Exception as e:  # missing extra or a bad setup must never stop a run
            log.warning("Langfuse is not available (%s); using the local log.", type(e).__name__)
    return LocalLogTracer(folder, counter, clock)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)
