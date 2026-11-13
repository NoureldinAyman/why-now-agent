"""Drafting a profile from a few sentences, and previewing it on the last saved read."""

from datetime import UTC, date, datetime

import pytest

from why_now.ai import BadModelOutput
from why_now.domain import JobAd
from why_now.drafting import DraftedProfile, draft_profile, preview
from why_now.profile import ProfileError, parse_profile, profile_text
from why_now.sample.models import Script, ScriptedWriter
from why_now.workspace import Workspace

DRAFT = {
    "id": "throwaway-tool",
    "product_name": "Throwaway tool",
    "product_description": "A tool that helps new salespeople practise calls.",
    "users": "Sales managers who train new salespeople",
    "search_words": ["account executive", "sales representative"],
    "countries": [],
    "languages": [],
    "fit_questions": [
        {
            "id": "hires_for_itself",
            "text": "Are the salespeople hired to work for the company that placed the ads?",
            "kind": "required",
            "direction": "for",
            "yes_means": "It hires for its own team.",
            "no_means": "It is a staffing agency.",
        }
    ],
    "why_now": "A new sales role shows the team is growing.",
}


class RecordingWriter(ScriptedWriter):
    def __init__(self, script: Script):
        super().__init__(script)
        self.asked: list[str] = []

    def structured(self, *, system, untrusted, schema, category):
        self.asked.append(untrusted)
        return super().structured(
            system=system, untrusted=untrusted, schema=schema, category=category
        )


def test_a_scripted_draft_is_a_profile_the_loader_accepts():
    writer = RecordingWriter(Script(writes={DraftedProfile.__name__: DRAFT}))

    profile = draft_profile("A practice tool for new salespeople.", writer)

    assert writer.asked == ["A practice tool for new salespeople."]
    assert parse_profile(profile_text(profile), "draft") == profile
    assert profile.quick_look_questions == []  # left out, so the derived ones are used
    assert profile.public is False


def test_a_draft_with_no_search_words_is_refused():
    writer = ScriptedWriter(
        Script(writes={DraftedProfile.__name__: DRAFT | {"search_words": [" "]}})
    )
    with pytest.raises(ProfileError, match="search word"):
        draft_profile("A practice tool.", writer)


def test_a_model_that_drafts_nothing_usable_says_so():
    with pytest.raises(BadModelOutput):
        draft_profile("A practice tool.", ScriptedWriter(Script()))


def an_ad(board: str, title: str) -> JobAd:
    return JobAd(
        source="greenhouse", board=board, ad_id=title, company_name=board.title(), title=title,
        location="Remote", country=None, language="en", text="We are hiring.",
        url=f"https://jobs.test/{board}/{title}", published_at=datetime(2026, 11, 1, tzinfo=UTC),
        first_seen=date(2026, 11, 1),
    )  # fmt: skip


def test_preview_lists_the_companies_the_last_saved_read_gives(store, settings, make_profile):
    shared = Workspace(store)
    shared.save_board_ads("greenhouse", "acme", [an_ad("acme", "Account Executive")] * 1)
    shared.save_board_ads(
        "greenhouse",
        "globex",
        [an_ad("globex", "Sales Representative"), an_ad("globex", "Senior Sales Representative")],
    )
    shared.save_board_ads("greenhouse", "initech", [an_ad("initech", "Software Engineer")])
    profile = make_profile(search_words=["account executive", "sales representative"])

    shown = preview(shared, profile, settings)

    assert shown.ads_read == 4
    assert [(c.name, c.relevant_ads) for c in shown.companies] == [("Globex", 2), ("Acme", 1)]
    assert shown.company_count == 2


def test_preview_shows_at_most_the_set_number(store, settings, make_profile):
    shared = Workspace(store)
    for name in ("a1", "a2", "a3"):
        shared.save_board_ads("greenhouse", name, [an_ad(name, "Account Executive")])
    profile = make_profile(search_words=["account executive"])

    shown = preview(shared, profile, settings.model_copy(update={"preview_companies": 2}))

    assert len(shown.companies) == 2
    assert shown.company_count == 3


def test_preview_with_no_saved_read_is_empty(store, settings, make_profile):
    shown = preview(Workspace(store), make_profile(), settings)
    assert (shown.ads_read, shown.companies) == (0, [])
