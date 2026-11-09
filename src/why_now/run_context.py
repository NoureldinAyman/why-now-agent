"""Everything one daily run needs, gathered in one place so tests and the sample run can swap it.

`metered` wraps the models so the budget is checked before every paid call, whichever
models are used. The real models check it too; the scripted ones in tests and the
sample run do not, and the daily run must still stop when the money has run out.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from why_now.ai import Answerer, Models, ResearchModel, ResearchStep, Writer
from why_now.ai.budget import Meter
from why_now.domain import Answer, FitQuestion
from why_now.pipeline.reader import PageReader
from why_now.settings import Settings
from why_now.sources import JobSource
from why_now.sources.boards import BoardList
from why_now.store import Store
from why_now.tracing import Tracer


@dataclass
class RunContext:
    settings: Settings
    store: Store
    sources: list[JobSource]
    boards: dict[str, BoardList]
    models: Models
    reader: PageReader
    meter: Meter
    tracer: Tracer
    clock: Callable[[], datetime]


def metered(models: Models, meter: Meter) -> Models:
    """The same models, each checking the budget before it is called."""
    return Models(
        quick_look=_MeteredAnswerer(models.quick_look, meter),
        judge=_MeteredAnswerer(models.judge, meter),
        writer=_MeteredWriter(models.writer, meter),
        research=_MeteredResearch(models.research, meter),
    )


class _MeteredAnswerer:
    def __init__(self, inner: Answerer, meter: Meter):
        self.model = inner.model
        self.answer_key = inner.answer_key
        self._inner, self._meter = inner, meter

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        self._meter.ensure(category)
        return self._inner.answer(state, questions, category)


class _MeteredWriter:
    def __init__(self, inner: Writer, meter: Meter):
        self.model = inner.model
        self.answer_key = inner.answer_key
        self._inner, self._meter = inner, meter

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        self._meter.ensure(category)
        return self._inner.structured(
            system=system, untrusted=untrusted, schema=schema, category=category
        )


class _MeteredResearch:
    def __init__(self, inner: ResearchModel, meter: Meter):
        self.model = inner.model
        self.answer_key = inner.answer_key
        self._inner, self._meter = inner, meter

    def step(self, conversation: list[dict], category: str) -> ResearchStep:
        self._meter.ensure(category)
        return self._inner.step(conversation, category)
