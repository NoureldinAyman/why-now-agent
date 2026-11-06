import json
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from why_now.ai import BadModelOutput
from why_now.domain import Answer, Claim, EvidencePack, Source, Verdict
from why_now.pipeline.brief import BriefDraft, write_brief
from why_now.tracing import LocalLogTracer, UnitCounter

NOW = datetime(2026, 11, 6, tzinfo=UTC)
AD_ID = "ad-1"
AD_TEXT = "Sales lead (Berlin)\nWe are hiring five sales reps to open the new Berlin office."

GOOD = BriefDraft(
    why_now=Claim(
        text="They are building a sales team now.", quote="hiring five sales reps", source_id=AD_ID
    ),
    claims=[
        Claim(text="A new office is opening.", quote="open the new Berlin office", source_id=AD_ID)
    ],
)
INVENTED = BriefDraft(
    why_now=Claim(
        text="They are building a sales team now.", quote="hiring fifty sales reps", source_id=AD_ID
    ),
    claims=[],
)


class FakeWriter:
    """Returns the scripted drafts in turn, and records what it was sent."""

    model = "writer-model"

    def __init__(self, *drafts: BriefDraft | Exception):
        self.drafts = list(drafts)
        self.sent: list[dict[str, str]] = []

    @property
    def calls(self) -> int:
        return len(self.sent)

    def structured[M: BaseModel](
        self, *, system: str, untrusted: str, schema: type[M], category: str
    ) -> M:
        self.sent.append({"system": system, "untrusted": untrusted, "category": category})
        draft = self.drafts[min(len(self.sent), len(self.drafts)) - 1]
        if isinstance(draft, Exception):
            raise draft
        assert schema is BriefDraft
        return schema.model_validate(draft.model_dump())


@pytest.fixture
def pack() -> EvidencePack:
    return EvidencePack(
        pack_id="pack-1",
        profile_id="profile-1",
        company_key="acme",
        company_name="Acme",
        created_at=NOW,
        sources=[
            Source(
                id=AD_ID, kind="job_ad", url="https://example.com/ad", text=AD_TEXT, fetched_at=NOW
            )
        ],
        relevant_ad_count=1,
        total_open_jobs=3,
        research_steps=0,
    )


@pytest.fixture
def verdict() -> Verdict:
    return Verdict(
        yes=True, strength=0.8, answers=[Answer(question_id="f1", probability=0.9, model="m")]
    )


@pytest.fixture
def tracer(tmp_path, store, settings) -> LocalLogTracer:
    return LocalLogTracer(
        tmp_path / "traces", UnitCounter(store, settings, lambda: NOW), lambda: NOW
    )


@pytest.fixture
def profile(make_profile):
    return make_profile()


def trace_events(tmp_path) -> list[dict]:
    return [
        json.loads(line)
        for f in sorted((tmp_path / "traces").glob("*.jsonl"))
        for line in f.read_text(encoding="utf-8").splitlines()
    ]


def test_a_brief_that_passes_is_returned(pack, verdict, profile, settings, tracer):
    writer = FakeWriter(GOOD)
    brief = write_brief(pack, verdict, profile, writer, settings, tracer)
    assert brief is not None
    assert brief.company_key == "acme"
    assert brief.why_now == GOOD.why_now
    assert brief.claims == GOOD.claims
    assert writer.calls == 1


def test_failed_brief_gets_one_more_attempt_then_none(pack, verdict, profile, settings, tracer):
    writer_always_inventing = FakeWriter(INVENTED)
    assert write_brief(pack, verdict, profile, writer_always_inventing, settings, tracer) is None
    assert writer_always_inventing.calls == 2


def test_retry_tells_the_writer_what_failed(pack, verdict, profile, settings, tracer):
    recording_writer = FakeWriter(INVENTED, GOOD)
    brief = write_brief(pack, verdict, profile, recording_writer, settings, tracer)
    assert brief is not None
    assert recording_writer.calls == 2
    first, second = recording_writer.sent
    assert "hiring fifty sales reps" not in first["untrusted"]
    assert "hiring fifty sales reps" in second["untrusted"]
    assert "failed the fact check" in second["system"]


def test_the_writer_sees_the_evidence_and_the_length_limit(
    pack, verdict, profile, settings, tracer
):
    writer = FakeWriter(GOOD)
    write_brief(pack, verdict, profile, writer, settings, tracer)
    assert f"[{AD_ID}]" in writer.sent[0]["untrusted"]
    assert AD_TEXT in writer.sent[0]["untrusted"]
    assert str(settings.brief_max_chars) in writer.sent[0]["system"]
    assert profile.product_name in writer.sent[0]["system"]


def test_unusable_writer_output_counts_as_a_failed_attempt(
    pack, verdict, profile, settings, tracer
):
    writer = FakeWriter(BadModelOutput("refused"), GOOD)
    assert write_brief(pack, verdict, profile, writer, settings, tracer) is not None
    assert "refused" in writer.sent[1]["untrusted"]

    always_bad = FakeWriter(BadModelOutput("refused"))
    assert write_brief(pack, verdict, profile, always_bad, settings, tracer) is None
    assert always_bad.calls == 2


def test_a_dropped_brief_is_recorded_in_the_trace(
    tmp_path, pack, verdict, profile, settings, tracer
):
    write_brief(pack, verdict, profile, FakeWriter(INVENTED), settings, tracer)
    events = trace_events(tmp_path)
    scores = [e for e in events if e["event"] == "score" and e["name"] == "fact_check_passed"]
    assert scores[-1]["value"] == 0
    assert any("hiring fifty sales reps" in json.dumps(e) for e in events)
