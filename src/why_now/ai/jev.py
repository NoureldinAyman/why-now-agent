"""The Jev version of an answerer, through TypeSafe's `typesafe-sdk` (the `jev` extra).

Each fit question is sent as a Noul, Jev's yes/no question, and the answer is
the probability of yes. Jev's documentation advises small, separate questions
and warns that irrelevant text lowers accuracy, so callers keep the text short.
"""

from typing import Any

from typesafe_sdk import Noul, NoulCriteria, SystemOneResponse, TypeSafeClient

from why_now.ai import UNTRUSTED_NOTE, BadModelOutput, check_answers, locked_price, mark_untrusted
from why_now.ai.budget import Meter, call_cost
from why_now.domain import Answer, FitQuestion
from why_now.settings import Settings


def jev_client(api_key: str, model: str) -> TypeSafeClient:
    # The model is set here too, so the library never falls back to its moving default alias.
    return TypeSafeClient(api_key=api_key, model=model)


class JevAnswerer:
    def __init__(self, client: Any, model: str, settings: Settings, meter: Meter):
        # `client` is a `TypeSafeClient`, or a fake with the same `system_one`.
        self.client = client
        self.model = model
        self.price = locked_price(model, settings)
        self.meter = meter

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        self.meter.ensure(category)
        reply: SystemOneResponse = self.client.system_one(
            state=f"{UNTRUSTED_NOTE}\n\n{mark_untrusted(state)}",
            questions={q.id: _noul(q) for q in questions},
            model=self.model,
        )
        tokens = reply.usage.input_tokens
        if tokens is None:
            # Still recorded, so a call that could not be costed shows in the spending list.
            self.meter.charge(category, 0.0, f"{self.model}: cost not reported")
            raise BadModelOutput(f"{self.model} did not report its token use")
        cost = call_cost(self.price, tokens, reply.usage.output_tokens or 0)
        self.meter.charge(category, cost, f"{self.model}: {tokens} in")
        if reply.model != self.model:
            raise BadModelOutput(f"asked {self.model}, but {reply.model} answered")
        return check_answers(
            [(name, answer.noul) for name, answer in reply.nouls.items()], questions, self.model
        )


def _noul(q: FitQuestion) -> Noul:
    if q.yes_means is None and q.no_means is None:
        return Noul(instructions=q.text)
    return Noul(instructions=q.text, criteria=NoulCriteria(true=q.yes_means, false=q.no_means))
