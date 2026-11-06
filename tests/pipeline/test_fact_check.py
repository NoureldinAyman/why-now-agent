from datetime import UTC, datetime

import pytest

from why_now.domain import Brief, Claim, EvidencePack, Source
from why_now.pipeline.fact_check import fact_check

AD_ID = "ad-1"
PAGE_ID = "page-1"
AD_TEXT = "Sales lead (Berlin)\nWe are hiring five sales reps to open the new Berlin office."
PAGE_TEXT = "Our company blog: the team moved to a bigger office this year."


def source(id: str, kind: str, text: str) -> Source:
    return Source(
        id=id,
        kind=kind,  # type: ignore[arg-type]
        url=f"https://example.com/{id}",
        text=text,
        fetched_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def pack_of(*sources: Source) -> EvidencePack:
    return EvidencePack(
        pack_id="pack-1",
        profile_id="profile-1",
        company_key="acme",
        company_name="Acme",
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        sources=list(sources),
        relevant_ad_count=1,
        total_open_jobs=3,
        research_steps=0,
    )


def brief(
    quote: str = "hiring five sales reps",
    source: str = AD_ID,
    *,
    why_quote: str = "hiring five sales reps",
    why_quote_from: str = AD_ID,
    text: str = "The sales team is growing.",
) -> Brief:
    return Brief(
        company_key="acme",
        why_now=Claim(
            text="They are building a sales team now.", quote=why_quote, source_id=why_quote_from
        ),
        claims=[Claim(text=text, quote=quote, source_id=source)],
    )


@pytest.fixture
def pack_with_ad() -> EvidencePack:
    return pack_of(source(AD_ID, "job_ad", AD_TEXT))


@pytest.fixture
def pack_with_ad_and_page() -> EvidencePack:
    return pack_of(source(AD_ID, "job_ad", AD_TEXT), source(PAGE_ID, "page", PAGE_TEXT))


def test_real_quote_passes(pack_with_ad, settings):
    result = fact_check(brief(quote="hiring five sales reps", source=AD_ID), pack_with_ad, settings)
    assert result.ok
    assert result.problems == []


def test_changed_word_fails(pack_with_ad, settings):
    result = fact_check(brief(quote="hiring six sales reps", source=AD_ID), pack_with_ad, settings)
    assert not result.ok
    assert "hiring six sales reps" in result.problems[0]


def test_quote_from_the_wrong_source_fails(pack_with_ad_and_page, settings):
    # The quote is real, but it is in the ad, not the page the claim names.
    result = fact_check(
        brief(quote="hiring five sales reps", source=PAGE_ID), pack_with_ad_and_page, settings
    )
    assert not result.ok


def test_quote_from_a_source_not_in_the_pack_fails(pack_with_ad, settings):
    result = fact_check(brief(source="page-404"), pack_with_ad, settings)
    assert not result.ok
    assert "page-404" in result.problems[0]


def test_why_now_quote_must_come_from_a_job_ad(pack_with_ad_and_page, settings):
    b = brief(why_quote="moved to a bigger office", why_quote_from=PAGE_ID)
    result = fact_check(b, pack_with_ad_and_page, settings)
    assert not result.ok
    assert "job ad" in result.problems[0]


def test_spacing_and_case_are_ignored(pack_with_ad, settings):
    quote = "  HIRING five\n\tsales   Reps "
    assert fact_check(brief(quote=quote), pack_with_ad, settings).ok


def test_curly_quotes_nbsp_and_dashes_are_ignored(settings):  # Review Focus 4
    text = "Join the \u201cgrowth\u201d\u00a0team \u2014 new, and it\u2019s a 2\u20133 year plan."
    pack = pack_of(source(AD_ID, "job_ad", AD_TEXT + "\n" + text))
    assert fact_check(brief(quote='the "growth" team - new'), pack, settings).ok
    assert fact_check(brief(quote="it's a 2-3 year plan"), pack, settings).ok


def test_typography_does_not_hide_a_changed_word(settings):
    pack = pack_of(source(AD_ID, "job_ad", AD_TEXT + "\nthe \u201cgrowth\u201d team"))
    assert not fact_check(brief(quote='the "sales" team'), pack, settings).ok


def test_quote_must_start_and_end_on_whole_words(pack_with_ad, settings):
    # "iring five sales rep" is inside the text, but no one wrote those words.
    assert not fact_check(brief(quote="iring five sales rep"), pack_with_ad, settings).ok


def test_empty_brief_fails(pack_with_ad, settings):
    empty = Brief(company_key="acme", why_now=Claim(text="", quote="", source_id=AD_ID), claims=[])
    result = fact_check(empty, pack_with_ad, settings)
    assert not result.ok
    assert "empty" in result.problems[0]


def test_claim_with_a_blank_quote_fails(pack_with_ad, settings):
    assert not fact_check(brief(quote=" \u00a0 "), pack_with_ad, settings).ok


def test_too_long_brief_fails(pack_with_ad, settings):
    short = settings.model_copy(update={"brief_max_chars": 60})
    result = fact_check(brief(), pack_with_ad, short)
    assert not result.ok
    assert "60" in result.problems[0]
    roomy = settings.model_copy(update={"brief_max_chars": 1_000})
    assert fact_check(brief(), pack_with_ad, roomy).ok


def test_same_input_gives_same_result(pack_with_ad_and_page, settings):
    b = brief(quote="hiring six sales reps", why_quote="bigger office", why_quote_from=PAGE_ID)
    results = [fact_check(b, pack_with_ad_and_page, settings) for _ in range(3)]
    assert results[0] == results[1] == results[2]
    assert len(results[0].problems) == 2
