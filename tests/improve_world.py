"""A pretend AI for the improvement tests. It costs nothing and works offline."""

from collections.abc import Mapping

from pydantic import BaseModel

from why_now.ai.budget import Meter
from why_now.domain import Answer, FitQuestion


class RecordingWriter:
    """A pretend writer. It keeps everything it was asked.

    `reply` is what it gives back: one fixed reply, or a list of replies given in turn, the
    last one again when the list runs out. Given a `meter`, each call is charged `cost` dollars,
    as a real call would be.
    """

    model = "recorder"
    answer_key = "recorder"

    def __init__(self, reply: dict | list[dict], *, meter: Meter | None = None, cost: float = 0.0):
        self.replies = reply if isinstance(reply, list) else [reply]
        self.meter = meter
        self.cost = cost
        self.calls: list[dict] = []

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        self.calls.append({"system": system, "untrusted": untrusted, "category": category})
        if self.meter is not None:
            self.meter.charge(category, self.cost, "pretend call")
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        return schema.model_validate(reply)

    def all_prompts(self) -> str:
        """Everything the AI was shown, in one text."""
        return "\n".join(f"{c['system']}\n{c['untrusted']}" for c in self.calls)


class ByQuestion:
    """A pretend judge. It finds which company's name is in the text it is shown. A question
    listed in `numbers` gets that company's number, and every other question gets `otherwise`.

    So a company can be given a high number on one question and a low number on another.
    """

    def __init__(
        self,
        numbers: Mapping[str, Mapping[str, float]],
        companies: list[str],
        otherwise: float = 0.9,
        answer_key: str = "by-question-1",
    ):
        self.model = answer_key
        self.answer_key = answer_key
        self.numbers = numbers
        self.companies = companies
        self.otherwise = otherwise

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        name = next(c for c in self.companies if c in state)
        return [
            Answer(
                question_id=q.id,
                probability=self.numbers.get(q.id, {}).get(name, self.otherwise),
                model=self.model,
            )
            for q in questions
        ]
