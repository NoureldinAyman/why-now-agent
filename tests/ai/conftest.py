import json
from datetime import UTC, datetime
from typing import Any

import pytest
from anthropic.types import Message

from why_now.ai.budget import Meter


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 11, 5, 12, tzinfo=UTC))


@pytest.fixture
def meter(store, settings, clock) -> Meter:
    return Meter(store, settings, clock)


def claude_message(
    content: list[dict[str, Any]],
    *,
    model: str = "claude-sonnet-5-5",
    stop_reason: str = "end_turn",
    input_tokens: int = 1_000,
    output_tokens: int = 200,
    searches: int = 0,
) -> Message:
    usage: dict[str, Any] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if searches:
        usage["server_tool_use"] = {"web_search_requests": searches, "web_fetch_requests": 0}
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage,
        }
    )


def json_reply(data: Any, **kwargs: Any) -> Message:
    return claude_message([{"type": "text", "text": json.dumps(data)}], **kwargs)


class FakeAnthropic:
    """Stands in for `anthropic.Anthropic`: records each request and returns the queued replies."""

    def __init__(self, *replies: Message):
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        self.requests.append(kwargs)
        return self.replies.pop(0)


@pytest.fixture
def fake_anthropic() -> type[FakeAnthropic]:
    return FakeAnthropic
