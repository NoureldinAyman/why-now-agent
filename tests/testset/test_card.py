from datetime import UTC, date, datetime
from typing import Literal

from why_now.domain import CaseRecord, EvidencePack, Source
from why_now.settings import Settings
from why_now.testset.packs import card

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def source(kind: Literal["job_ad", "page"], text: str, id: str = "s") -> Source:
    return Source(id=id, kind=kind, url=f"https://x.test/{id}", text=text, fetched_at=NOW)


def pack(sources: list[Source], **values) -> EvidencePack:
    base = {
        "pack_id": "p1", "profile_id": "pr", "company_key": "acme", "company_name": "Acme",
        "created_at": NOW, "sources": sources, "relevant_ad_count": 3, "total_open_jobs": 9,
        "research_steps": 0,
        "ad_titles": ["Sales Rep", "Account Executive", "Sales Rep"],
        "newest_ad_at": datetime(2026, 11, 4, 22, 0, tzinfo=UTC),
    }  # fmt: skip
    return EvidencePack.model_validate(base | values)


def a_case() -> CaseRecord:
    return CaseRecord(case_id="c1", profile_id="pr", company_key="acme", seed=1)


def test_the_card_gives_the_facts_a_reviewer_reads_first():
    c = card(a_case(), pack([source("job_ad", "Sales Rep (Cairo)\nSell.")]), Settings())
    assert c.company_name == "Acme"
    assert c.titles == [("Sales Rep", 2), ("Account Executive", 1)]  # most common first
    assert (c.relevant_ads, c.open_jobs) == (3, 9)
    assert c.newest_ad == date(2026, 11, 4)


def test_the_card_starts_the_first_web_page_and_skips_job_ads():
    long_text = "A" * 399 + "BCDEF"
    sources = [
        source("job_ad", "Ad text that is not a page", "ad"),
        source("page", long_text, "p1"),
        source("page", "A second page", "p2"),
    ]
    c = card(a_case(), pack(sources), Settings(card_page_chars=400))
    assert c.page_start == "A" * 399 + "B"  # cut at the setting, not at a word
    assert c.page_truncated is True
    assert c.page_url == "https://x.test/p1"


def test_a_short_page_is_shown_whole_and_no_page_gives_none():
    c = card(a_case(), pack([source("page", "Short page.")]), Settings())
    assert (c.page_start, c.page_truncated) == ("Short page.", False)
    bare = card(a_case(), pack([source("job_ad", "Ad")]), Settings())
    assert (bare.page_start, bare.page_url) == (None, None)


def test_a_pack_without_ad_facts_still_makes_a_card():
    # Packs made before the titles and date were kept have neither.
    old = pack([source("job_ad", "Ad")], ad_titles=[], newest_ad_at=None)
    c = card(a_case(), old, Settings())
    assert c.titles == [] and c.newest_ad is None


def test_the_card_holds_only_what_the_pack_holds():
    # Nothing else is passed in, so nothing else can reach the card: its fields are
    # all taken from the pack or the settings, and a name that is only in the case record
    # (here, the company key) does not appear.
    case = a_case().model_copy(update={"company_key": "KEY-ONLY-IN-CASE"})
    c = card(case, pack([source("page", "About us.")]), Settings())
    assert "KEY-ONLY-IN-CASE" not in c.model_dump_json()
