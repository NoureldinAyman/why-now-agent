from datetime import UTC, date, datetime
from itertools import count

from why_now.domain import Company, JobAd
from why_now.pipeline.search import company_key, search_ads

_ids = count()


def ad(
    title: str,
    *,
    board: str = "acme",
    source: str = "greenhouse",
    company_name: str = "Acme",
    location: str = "Berlin",
    country: str | None = None,
    language: str | None = None,
    text: str = "Join us.",
) -> JobAd:
    n = next(_ids)
    return JobAd(
        source=source,
        board=board,
        ad_id=str(n),
        company_name=company_name,
        title=title,
        location=location,
        country=country,
        language=language,
        text=text,
        url=f"https://example.com/{n}",
        published_at=datetime(2026, 11, 1, 9, tzinfo=UTC),
        first_seen=date(2026, 11, 2),
    )


def titles(companies: list[Company]) -> list[str]:
    return [a.title for c in companies for a in c.ads]


def test_matches_whole_words_in_titles_only(make_profile):
    p = make_profile(search_words=["sales", "sdr"])
    found = search_ads(
        [ad("Sales Manager"), ad("Wholesale Buyer"), ad("Engineer", text="sales")], p, {}
    )
    assert titles(found) == ["Sales Manager"]


def test_five_ads_become_one_company(make_profile):
    found = search_ads(
        [ad("Sales Rep", location=c) for c in "ABCDE"], make_profile(search_words=["sales"]), {}
    )
    assert len(found) == 1
    assert len(found[0].ads) == 5


def test_same_name_on_two_sources_is_one_company(make_profile):
    ads = [
        ad("Sales", board="Acme-Inc", source="greenhouse"),
        ad("Sales", board="acmeinc", source="lever"),
    ]
    found = search_ads(ads, make_profile(search_words=["sales"]), {})
    assert [(c.key, len(c.ads)) for c in found] == [("acmeinc", 2)]


def test_company_key_keeps_only_lowercase_letters_and_digits():
    assert company_key("Acme-Inc_2") == "acmeinc2"


def test_search_words_can_be_multi_word_and_any_case(make_profile):
    p = make_profile(search_words=["Account Executive"])
    found = search_ads(
        [ad("ACCOUNT  EXECUTIVE, EMEA"), ad("Account Manager"), ad("Executive Assistant")], p, {}
    )
    assert titles(found) == ["ACCOUNT  EXECUTIVE, EMEA"]


def test_total_open_jobs_counts_all_ads_not_only_matches(make_profile):
    ads = [ad("Sales Rep"), ad("Engineer"), ad("Designer"), ad("Sales Rep", board="beta")]
    found = search_ads(ads, make_profile(search_words=["sales"]), {"beta": 40})
    assert {c.key: c.total_open_jobs for c in found} == {"acme": 3, "beta": 40}


def test_country_and_language_filters_use_source_fields(make_profile):
    p = make_profile(search_words=["sales"], countries=["SG"], languages=["en"])
    ads = [
        ad("Sales Rep", country="sg", language="en", location="Somewhere"),
        ad("Sales Rep", country="DE", language="en", location="Singapore"),
        ad("Sales Rep", country="SG", language="de"),
        ad("Sales Rep", country="SG", language="en-GB"),
    ]
    assert [a.location for c in search_ads(ads, p, {}) for a in c.ads] == ["Somewhere", "Berlin"]


def test_ad_with_no_language_is_kept(make_profile):
    p = make_profile(search_words=["sales"], languages=["en"])
    assert titles(search_ads([ad("Sales Rep", language=None)], p, {})) == ["Sales Rep"]


def test_ad_with_no_country_is_kept(make_profile):
    # Greenhouse ads carry no country field, so dropping them would drop a whole job source.
    p = make_profile(search_words=["sales"], countries=["SG"])
    assert titles(search_ads([ad("Sales Rep", country=None)], p, {})) == ["Sales Rep"]


def test_filtered_out_ads_still_count_as_open_jobs(make_profile):
    p = make_profile(search_words=["sales"], countries=["SG"])
    found = search_ads([ad("Sales Rep", country="SG"), ad("Sales Rep", country="DE")], p, {})
    assert [(len(c.ads), c.total_open_jobs) for c in found] == [(1, 2)]


def test_no_matches_gives_no_companies(make_profile):
    assert search_ads([ad("Engineer")], make_profile(search_words=["sales"]), {}) == []
