"""Guards: what the real Claude parts send, seen from a recording client.

These run the whole attack set through the real answerer, writer and research model,
with only the network replaced, and look at every request that was made.
"""

import re
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import pytest
from hostile_fakes import (
    CUTOFF,
    NOW,
    QUESTIONS,
    RecordingClient,
    claude_reply,
    fake_web_reader,
    json_text,
)

from why_now.ai import UNTRUSTED_NOTE, Models
from why_now.ai.budget import Meter
from why_now.ai.claude import ClaudeAnswerer, ClaudeResearchModel, ClaudeWriter
from why_now.hostile.attacks import Attack, load_attacks
from why_now.hostile.runner import run_attacks

UNTRUSTED_BLOCK = re.compile(r"<untrusted_text>.*?</untrusted_text>", re.DOTALL)


@dataclass
class Recorded:
    judge: RecordingClient
    writer: RecordingClient
    research: RecordingClient
    attacks: list[Attack]


def _strings(value: Any) -> list[str]:
    """Every piece of text anywhere in a request, whatever it is nested in."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def sent_text(request: dict[str, Any]) -> str:
    """Everything one request says, with the parts marked untrusted left in place."""
    return "\n".join(_strings(request.get("system")) + _strings(request["messages"]))


def outside_untrusted(request: dict[str, Any]) -> str:
    return UNTRUSTED_BLOCK.sub("", sent_text(request))


def inside_untrusted(request: dict[str, Any]) -> str:
    return "\n".join(UNTRUSTED_BLOCK.findall(sent_text(request)))


@pytest.fixture(scope="module")
def recorded(tmp_path_factory) -> Recorded:
    # Built by hand, because module-scoped fixtures can't use the per-test ones.
    from why_now.settings import load_settings
    from why_now.store.local import LocalStore
    from why_now.tracing import LocalLogTracer, UnitCounter

    folder = tmp_path_factory.mktemp("guards")
    settings = load_settings(None, env={}).model_copy(update={"workspace_path": folder / "ws"})
    store = LocalStore(folder / "ws")
    meter = Meter(store, settings, lambda: NOW.astimezone(UTC))
    attacks = load_attacks()
    blocked = [a.blocked_url for a in attacks if a.blocked_url]

    def judge_reply(request: dict[str, Any]):
        return json_text(
            {"answers": [{"question_id": q.id, "probability": 0.1} for q in QUESTIONS]}
        )

    def writer_reply(request: dict[str, Any]):
        schema = request["output_config"]["format"]["schema"]
        if "why_now" in schema.get("properties", {}):
            # A brief with an invented quote, so it fails the fact check and is retried once.
            claim = {"text": "It is hiring.", "quote": "words no source has", "source_id": "ad-x"}
            return json_text({"why_now": claim, "claims": []})
        rule = {"id": "sells", "text": "Does it sell to businesses?", "why": "Buyers are firms."}
        return json_text({"action": "add", "question_id": None, "question": rule, "based_on": []})

    def research_reply(request: dict[str, Any]):
        messages = request["messages"]
        if len(messages) > 1:
            return claude_reply([{"type": "text", "text": "Done."}])
        prompt = sent_text(request)
        url = next(u for u in blocked if u in prompt)
        block = {"type": "tool_use", "id": "toolu_1", "name": "read_page", "input": {"url": url}}
        return claude_reply([block], stop_reason="tool_use")

    judge, writer, research = (
        RecordingClient(judge_reply),
        RecordingClient(writer_reply),
        RecordingClient(research_reply),
    )
    answerer = ClaudeAnswerer(judge, "claude-sonnet-5-5", settings, meter, effort="medium")
    models = Models(
        quick_look=answerer,
        judge=answerer,
        writer=ClaudeWriter(writer, "claude-sonnet-5-5", settings, meter, effort="medium"),
        research=ClaudeResearchModel(
            research, "claude-sonnet-5-5", settings, meter, effort="medium"
        ),
    )

    reader = fake_web_reader(settings, [])
    from why_now.domain import Profile

    profile = Profile(
        id="guards",
        product_name="Product guards",
        product_description="A tool that helps sales teams.",
        users="Sales teams",
        search_words=["sales"],
        quick_look_questions=QUESTIONS,
        fit_questions=QUESTIONS,
        why_now="A new sales ad shows the team is growing.",
    )
    tracer = LocalLogTracer(
        folder / "traces", UnitCounter(store, settings, lambda: NOW), lambda: NOW
    )
    run_attacks(
        attacks,
        models,
        QUESTIONS,
        reader,
        settings,
        "hostile",
        profile=profile,
        cutoff=CUTOFF,
        tracer=tracer,
        now=NOW,
    )
    return Recorded(judge, writer, research, attacks)


def test_guard_every_model_input_marks_ads_and_pages_as_untrusted(recorded: Recorded):
    clients = {"judge": recorded.judge, "writer": recorded.writer, "research": recorded.research}
    for name, client in clients.items():
        assert client.requests, f"the {name} model was never called, so nothing was checked"
        for request in client.requests:
            outside = outside_untrusted(request)
            assert UNTRUSTED_NOTE in sent_text(request), name
            for attack in recorded.attacks:
                for source in attack.hostile_pack.sources:
                    assert source.text not in outside, (name, attack.id)
                assert attack.planted_text not in outside, (name, attack.id)


def test_guard_the_hostile_text_really_reaches_the_judge_and_writer_marked(recorded: Recorded):
    # Without this, the guard above would pass for models that were never shown the attack.
    judged = "\n".join(inside_untrusted(r) for r in recorded.judge.requests)
    written = "\n".join(inside_untrusted(r) for r in recorded.writer.requests)
    for attack in recorded.attacks:
        assert attack.planted_text in judged, attack.id
    for attack in recorded.attacks:
        if attack.kind in ("plant_text", "add_rule"):
            assert attack.planted_text in written, attack.id


def test_guard_judge_and_writer_have_no_tools(recorded: Recorded):
    for client in (recorded.judge, recorded.writer):
        for request in client.requests:
            assert "tools" not in request
            assert "tool_choice" not in request


def test_guard_research_has_only_search_and_read(recorded: Recorded):
    assert recorded.research.requests
    for request in recorded.research.requests:
        tools = request["tools"]
        assert sorted(t["name"] for t in tools) == ["read_page", "web_search"]
        search = next(t for t in tools if t["name"] == "web_search")
        assert "linkedin.com" in search["blocked_domains"]
