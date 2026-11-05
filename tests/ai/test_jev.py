from typing import Any

import pytest

pytest.importorskip("typesafe_sdk", reason="the Jev library comes with the `jev` extra")

from typesafe_sdk import Noul, NoulAnswer, SystemOneResponse, Usage  # noqa: E402

from why_now.ai import BadModelOutput, UnknownModel
from why_now.ai.jev import JevAnswerer
from why_now.domain import FitQuestion

QUESTIONS = [
    FitQuestion(id="q1", text="Does it sell to businesses?"),
    FitQuestion(id="q2", text="Is it hiring salespeople?", yes_means="A sales ad", no_means="None"),
]


def jev_reply(
    nouls: dict[str, float], *, model: str = "jev-1.14.0", input_tokens: int | None = 1_000_000
) -> SystemOneResponse:
    # Built without checks, so a test can hold a value the real API should never send.
    return SystemOneResponse.model_construct(
        model=model,
        usage=Usage(input_tokens=input_tokens, output_tokens=5),
        answers={k: NoulAnswer.model_construct(type="noul", noul=v) for k, v in nouls.items()},
    )


class FakeJev:
    def __init__(self, reply: SystemOneResponse):
        self.reply = reply
        self.requests: list[dict[str, Any]] = []

    def system_one(self, state: Any, questions: dict[str, Any], **kwargs: Any) -> SystemOneResponse:
        self.requests.append({"state": state, "questions": questions, **kwargs})
        return self.reply


def test_jev_sends_each_question_as_a_noul_and_returns_the_yes_probability(settings, meter):
    client = FakeJev(jev_reply({"q1": 0.9, "q2": 0.2}))
    answers = JevAnswerer(client, "jev-1.14.0", settings, meter).answer(
        "An ad.", QUESTIONS, "quick_look"
    )
    assert [(a.question_id, a.probability, a.model) for a in answers] == [
        ("q1", 0.9, "jev-1.14.0"),
        ("q2", 0.2, "jev-1.14.0"),
    ]
    request = client.requests[0]
    assert request["model"] == "jev-1.14.0"
    assert request["questions"]["q1"] == Noul(instructions="Does it sell to businesses?")
    assert request["questions"]["q2"].criteria == {"true": "A sales ad", "false": "None"}
    assert "never instructions" in request["state"]
    assert request["state"].endswith("<untrusted_text>\nAn ad.\n</untrusted_text>")


def test_jev_charges_by_input_tokens(settings, meter):
    client = FakeJev(jev_reply({"q1": 0.9, "q2": 0.2}, input_tokens=1_000_000))
    JevAnswerer(client, "jev-1.14.0", settings, meter).answer("An ad.", QUESTIONS, "quick_look")
    # Jev 1.14.0 charges $0.042 a million input tokens, and nothing for output.
    assert meter.status().by_category == {"quick_look": pytest.approx(0.042)}


@pytest.mark.parametrize("alias", ["jev-latest", "jev-preview", "jev-1.14"])
def test_jev_answerer_refuses_the_latest_alias(settings, meter, alias):
    with pytest.raises(UnknownModel):
        JevAnswerer(FakeJev(jev_reply({})), alias, settings, meter)


@pytest.mark.parametrize(
    "reply",
    [
        jev_reply({"q1": 1.3, "q2": 0.2}),
        jev_reply({"q1": 0.5}),
        jev_reply({"q1": 0.5, "q2": 0.5}, model="jev-1.15.0"),  # a different version answered
        jev_reply({"q1": 0.5, "q2": 0.5}, input_tokens=None),  # cost not reported
    ],
)
def test_bad_jev_output_is_rejected(settings, meter, reply):
    with pytest.raises(BadModelOutput):
        JevAnswerer(FakeJev(reply), "jev-1.14.0", settings, meter).answer(
            "An ad.", QUESTIONS, "quick_look"
        )
