"""Claude versions of the AI parts, through the `anthropic` library.

Answers and briefs come back as JSON that must match a schema (structured
output). The plan asked for one forced tool call, but Claude Sonnet 5.5 refuses
forced tool calls, and structured output gives the same guarantee of shape.
Everything else, such as probabilities from 0 to 1, is checked here, because the
schema cannot say it.
"""

from typing import Any

from anthropic import transform_schema
from anthropic.types import Message
from pydantic import BaseModel, ValidationError

from why_now.ai import (
    UNTRUSTED_NOTE,
    BadModelOutput,
    ResearchStep,
    check_answers,
    locked_price,
    mark_untrusted,
)
from why_now.ai.budget import Meter, call_cost
from why_now.domain import Answer, FitQuestion
from why_now.settings import Settings

ANSWER_SYSTEM = (
    "You judge whether a company fits a product, one yes/no question at a time. "
    "For each question, give the probability from 0 to 1 that the answer is yes, "
    "using only the text given. " + UNTRUSTED_NOTE
)
RESEARCH_SYSTEM = (
    "You research one company for a person deciding whether to contact it. "
    "Collect facts about the company, not about people. Use web_search to find "
    "pages and read_page to read one. Stop when you have enough. " + UNTRUSTED_NOTE
)
# Never searched or read, by the project's data rules.
BLOCKED_DOMAINS = ["linkedin.com", "linkedin.cn", "lnkd.in"]


class _RawAnswer(BaseModel):
    question_id: str
    probability: float


class _AnswerList(BaseModel):
    answers: list[_RawAnswer]


class ClaudeCaller:
    """The one place a Claude call is made: check the budget, call, then charge."""

    def __init__(self, client: Any, model: str, settings: Settings, meter: Meter):
        # `client` is an `anthropic.Anthropic`, or a fake with the same `messages.create`.
        self.client = client
        self.model = model
        self.price = locked_price(model, settings)
        self.max_tokens = settings.model_max_output_tokens
        self.meter = meter

    def create(self, category: str, **request: Any) -> Message:
        self.meter.ensure(category)
        message: Message = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, **request
        )
        usage = message.usage
        # Cached input is counted at the full input price. The agent does not use
        # caching, so these are normally zero.
        input_tokens = (
            usage.input_tokens
            + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0)
        )
        searches = usage.server_tool_use.web_search_requests if usage.server_tool_use else 0
        self.meter.charge(
            category,
            call_cost(self.price, input_tokens, usage.output_tokens, searches),
            f"{self.model} {message.id}: {input_tokens} in, {usage.output_tokens} out, "
            f"{searches} searches",
        )
        if message.stop_reason == "refusal":
            raise BadModelOutput(f"{self.model} refused")
        return message

    def create_json[M: BaseModel](
        self, category: str, schema: type[M], *, system: str, content: str
    ) -> M:
        message = self.create(
            category,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": transform_schema(schema.model_json_schema()),
                }
            },
        )
        if message.stop_reason == "max_tokens":
            raise BadModelOutput(f"{self.model} ran out of room before finishing")
        text = "".join(block.text for block in message.content if block.type == "text")
        try:
            return schema.model_validate_json(text)
        except ValidationError as e:
            raise BadModelOutput(f"{self.model} gave output that does not fit: {e}") from e


class ClaudeAnswerer:
    def __init__(self, client: Any, model: str, settings: Settings, meter: Meter):
        self.model = model
        self._caller = ClaudeCaller(client, model, settings, meter)

    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]:
        content = (
            mark_untrusted(state)
            + "\n\nAnswer each question about the company in the text above, by its id:\n"
            + "\n".join(_question_line(q) for q in questions)
        )
        out = self._caller.create_json(category, _AnswerList, system=ANSWER_SYSTEM, content=content)
        return check_answers(
            [(a.question_id, a.probability) for a in out.answers], questions, self.model
        )


class ClaudeWriter:
    def __init__(self, client: Any, model: str, settings: Settings, meter: Meter):
        self.model = model
        self._caller = ClaudeCaller(client, model, settings, meter)

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        return self._caller.create_json(
            category,
            schema,
            system=f"{system}\n\n{UNTRUSTED_NOTE}",
            content=mark_untrusted(untrusted),
        )


class ClaudeResearchModel:
    """One step of research: Claude may search the web and ask for pages to be read.

    `step` adds Claude's reply to `conversation`. The caller then reads the asked-for
    pages with its own page reader and adds the results, as `tool_result` blocks
    with the matching `tool_use_ids`, before the next step.
    """

    def __init__(self, client: Any, model: str, settings: Settings, meter: Meter):
        self.model = model
        self._caller = ClaudeCaller(client, model, settings, meter)

    def step(self, conversation: list[dict], category: str) -> ResearchStep:
        message = self._caller.create(
            category,
            system=RESEARCH_SYSTEM,
            messages=conversation,
            tools=[
                {
                    "type": "web_search_20260209",
                    "name": "web_search",
                    # One search a step, so the research steps setting also limits searches.
                    "max_uses": 1,
                    "blocked_domains": BLOCKED_DOMAINS,
                },
                {
                    "name": "read_page",
                    "description": "Read one web page. Returns its text, or why it was refused.",
                    "strict": True,
                    "input_schema": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                        "additionalProperties": False,
                    },
                },
            ],
        )
        conversation.append(
            {"role": "assistant", "content": [b.model_dump(mode="json") for b in message.content]}
        )
        reads = [b for b in message.content if b.type == "tool_use" and b.name == "read_page"]
        usage = message.usage.server_tool_use
        return ResearchStep(
            read_urls=[str(b.input.get("url", "")) for b in reads],
            tool_use_ids=[b.id for b in reads],
            searches_used=usage.web_search_requests if usage else 0,
            done=message.stop_reason == "end_turn" and not reads,
        )


def _question_line(q: FitQuestion) -> str:
    line = f"- {q.id}: {q.text}"
    if q.yes_means:
        line += f" (Yes means: {q.yes_means})"
    if q.no_means:
        line += f" (No means: {q.no_means})"
    return line
