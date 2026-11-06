"""Scripted stand-ins for the AI models. They answer from a script, free and offline."""

from pydantic import BaseModel

from why_now.ai import BadModelOutput, Models, ResearchStep
from why_now.domain import Answer, FitQuestion

SCRIPTED = "scripted"


class Script(BaseModel):
    """What the scripted models answer.

    - `probabilities`: the probability of yes for each question id, and
      `default_probability` for any other question.
    - `writes`: the output for each schema, by the schema's class name.
    - `research`: research steps given in order, then `done`.
    """

    probabilities: dict[str, float] = {}
    default_probability: float = 0.5
    writes: dict[str, dict] = {}
    research: list[ResearchStep] = []


class ScriptedAnswerer:
    model = SCRIPTED

    def __init__(self, script: Script):
        self.script = script

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        p = self.script.probabilities
        return [
            Answer(
                question_id=q.id,
                probability=p.get(q.id, self.script.default_probability),
                model=self.model,
            )
            for q in questions
        ]


class ScriptedWriter:
    model = SCRIPTED

    def __init__(self, script: Script):
        self.script = script

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        if schema.__name__ not in self.script.writes:
            raise BadModelOutput(f"nothing scripted for {schema.__name__}")
        return schema.model_validate(self.script.writes[schema.__name__])


class ScriptedResearch:
    model = SCRIPTED

    def __init__(self, script: Script):
        self.steps = list(script.research)

    def step(self, conversation: list[dict], category: str) -> ResearchStep:
        if not self.steps:
            return ResearchStep(read_urls=[], searches_used=0, done=True)
        return self.steps.pop(0)


def scripted_models(script: Script) -> Models:
    answerer = ScriptedAnswerer(script)
    return Models(
        quick_look=answerer,
        judge=answerer,
        writer=ScriptedWriter(script),
        research=ScriptedResearch(script),
    )
