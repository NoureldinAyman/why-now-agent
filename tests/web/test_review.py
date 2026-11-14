"""The review page: the short list, the more list, decisions and spending.

Every test goes through the web pages, the way the reviewer uses them.
"""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from why_now.ai.budget import BudgetStatus
from why_now.day_result import DayResult, ListEntry
from why_now.domain import Brief, Claim, Decision, EvidencePack, JobAd, Source
from why_now.web.app import create_app
from why_now.web.auth import LocalAuth
from why_now.workspace import Workspace

from .conftest import NOW

TODAY = NOW.date()
QUOTE = "We are hiring our first head of sales to build the team"


def an_ad(name: str, title: str = "Head of Sales") -> JobAd:
    return JobAd(
        source="greenhouse", board=name, ad_id="1", company_name=name.title(), title=title,
        location="Remote", country=None, language="en", text=QUOTE,
        url=f"https://jobs.test/{name}/1", published_at=NOW, first_seen=TODAY,
    )  # fmt: skip


def a_day(
    short: Sequence[ListEntry] = (), more: Sequence[ListEntry] = (), skipped: Sequence[str] = (),
    day: date = TODAY, judged_no: Sequence[ListEntry] = (),
) -> DayResult:  # fmt: skip
    return DayResult(
        day=day, short_list=list(short), more_list=list(more), judged_no=list(judged_no),
        failed=[], skipped=list(skipped),
        costs=BudgetStatus(
            month="2026-11", spent_usd=0, by_category={}, warning=False, stopped=False,
            loop_stopped=False,
        ),
    )  # fmt: skip


@pytest.fixture
def anonymous_client(ctx) -> TestClient:
    return TestClient(create_app(ctx, LocalAuth()), client=("203.0.113.9", 5000))


@pytest.fixture
def listed_company(workspace, profile) -> ListEntry:
    """A company on the short list, with a brief whose quote comes from its job ad."""
    pack = EvidencePack(
        pack_id="pack-acme", profile_id=profile.id, company_key="acme", company_name="Acme",
        created_at=NOW, relevant_ad_count=1, total_open_jobs=4, research_steps=0,
        sources=[
            Source(
                id="s1", kind="job_ad", url="https://jobs.test/acme/1", text=QUOTE, fetched_at=NOW
            )
        ],
    )  # fmt: skip
    workspace.save_pack(pack)
    entry = ListEntry(
        company_key="acme", company_name="Acme", strength=0.9, pack_id="pack-acme",
        brief=Brief(
            company_key="acme",
            why_now=Claim(text="Acme builds a sales team.", quote=QUOTE, source_id="s1"),
            claims=[],
        ),
        ads=[an_ad("acme")], first_listed=TODAY,
    )  # fmt: skip
    workspace.save_day(a_day(short=[entry]))
    return entry


def test_private_pages_need_login(anonymous_client):
    for path in ("/", "/more", "/mark", "/spending"):
        assert anonymous_client.get(path, follow_redirects=False).status_code in (302, 401)
    assert anonymous_client.post("/decide/acme", data={}).status_code in (302, 401)


def test_short_list_shows_quotes_and_links(client, listed_company):
    html = client.get("/").text
    assert listed_company.brief is not None
    assert listed_company.brief.why_now.quote in html
    assert 'href="https://jobs.test/acme/1"' in html
    assert "Open the job ad" in html  # the link says where it goes


def test_an_address_that_is_not_a_web_address_is_never_a_link(client, workspace, listed_company):
    bad = an_ad("acme").model_copy(update={"url": "javascript:alert(1)"})
    entry = listed_company.model_copy(update={"ads": [bad]})
    workspace.save_day(a_day(short=[entry]))
    assert "javascript:" not in client.get("/").text


@pytest.fixture
def more_company(workspace, listed_company) -> ListEntry:
    """A company on the more list: no brief, no pack, only its ads."""
    entry = ListEntry(
        company_key="globex", company_name="Globex", strength=0.4, brief=None,
        ads=[an_ad("globex", "Sales Manager")], pack_id=None, first_listed=TODAY,
    )  # fmt: skip
    workspace.save_day(a_day(short=[listed_company], more=[entry]))
    return entry


def form_token(client: TestClient, path: str = "/") -> str:
    found = re.search(r'name="form_token" value="([^"]+)"', client.get(path).text)
    assert found, "the page has no form token"
    return found.group(1)


@pytest.fixture
def decide(client):
    held: list[str] = []  # the form is loaded once, so sending it again reuses its token

    def send(key: str, decision: str = "approve", reason: str = "Hiring now.", **extra):
        if not held:
            held.append(form_token(client))
        data = {"decision": decision, "reason": reason, "form_token": held[0]} | extra
        return client.post(f"/decide/{key}", data=data, follow_redirects=False)

    return send


def test_deciding_needs_a_reason_and_hides_the_company(client, decide, listed_company, workspace):
    refused = decide("acme", reason="  ")
    assert refused.status_code == 422
    assert "reason" in refused.text.lower()
    assert workspace.decisions() == []
    assert "Acme" in client.get("/").text

    saved = decide("acme", decision="reject", reason="Looks like a staffing firm.")
    assert saved.status_code == 303
    [decision] = workspace.decisions()
    assert (decision.company_key, decision.approved) == ("acme", False)
    assert decision.reason == "Looks like a staffing firm."
    assert decision.from_list == "short"
    assert "Acme" not in client.get("/").text


def test_a_chip_alone_is_a_valid_reason_and_an_unknown_chip_is_not(
    decide, listed_company, workspace
):
    assert decide("acme", reason="", chips=["not a chip"]).status_code == 422
    assert decide("acme", reason="", chips=["good timing", "good timing"]).status_code == 303
    [decision] = workspace.decisions()
    assert (decision.approved, decision.reason, decision.chips) == (True, "", ["good timing"])


def test_same_decision_twice_saves_one(decide, listed_company, workspace):
    assert decide("acme").status_code == 303
    assert decide("acme").status_code == 303  # the same form sent again
    assert len(workspace.decisions()) == 1


def test_a_decision_needs_the_form_it_came_with(client, listed_company, workspace):
    data = {"decision": "approve", "reason": "Hiring now.", "form_token": "made-up"}
    assert client.post("/decide/acme", data=data).status_code == 403
    assert workspace.decisions() == []


def test_deciding_on_a_company_that_is_not_listed_is_refused(decide, listed_company, workspace):
    assert decide("nobody").status_code == 404
    assert decide("acme", decision="maybe").status_code == 422
    assert workspace.decisions() == []


def test_decision_from_the_more_list_is_recorded_as_such(client, decide, more_company, workspace):
    assert "Globex" in client.get("/more").text
    assert decide("globex").status_code == 303
    [decision] = workspace.decisions()
    assert (decision.company_key, decision.from_list) == ("globex", "more")
    assert "Globex" not in client.get("/more").text


@pytest.fixture
def meter_at_50(ctx) -> None:
    ctx.meter.charge("research", 50.0, "a month of research")


@pytest.fixture
def day_with_skips(workspace, listed_company) -> list[str]:
    skipped = ["Research was skipped for 3 companies because the monthly limit was reached."]
    workspace.save_day(a_day(short=[listed_company], skipped=skipped))
    return skipped


def test_spending_shows_with_no_warning_when_low(client, ctx, listed_company):
    ctx.meter.charge("research", 12.5, "a few companies")
    for path in ("/", "/spending"):
        html = client.get(path).text
        assert "$12.50" in html
        assert "$70" in html
        assert "Spending warning" not in html


def test_warning_appears_at_fifty_dollars(client, meter_at_50, listed_company):
    for path in ("/", "/spending"):
        html = client.get(path).text
        assert "Spending warning" in html
        assert "$50.00" in html


def test_skipped_work_is_shown_at_the_limit(client, ctx, day_with_skips):
    ctx.meter.charge("research", 70.0, "the whole month")
    for path in ("/", "/spending"):
        html = client.get(path).text
        assert "Paid work is stopped" in html
        assert day_with_skips[0] in html


def test_the_spending_page_splits_the_month_by_what_it_paid_for(client, ctx):
    ctx.meter.charge("research", 8.0, "research")
    ctx.meter.charge("loop", 2.0, "one try")
    html = client.get("/spending").text
    assert "Research" in html and "$8.00" in html
    assert "Loop" in html and "$2.00" in html


def test_short_list_precision_shows_with_its_count_and_counts_only_the_short_list(
    client, workspace, listed_company
):
    def decided(key: str, approved: bool, from_list: Literal["short", "more"], minute: int) -> None:
        workspace.save_decision(
            Decision(
                profile_id=workspace.require_profile(), company_key=key, approved=approved,
                reason="x", decided_at=NOW.replace(minute=minute), from_list=from_list,
            )
        )  # fmt: skip

    assert "No decisions yet" in client.get("/").text
    decided("a", True, "short", 1)
    decided("b", True, "short", 2)
    decided("c", False, "short", 3)
    decided("d", True, "more", 4)  # chosen by nobody, so it says nothing about the agent
    html = client.get("/").text
    assert "67%" in html
    assert "2 of 3" in html


def test_empty_day_says_so_plainly(client):
    assert "No companies are waiting for a decision." in client.get("/").text
    assert "Nothing is on the more list." in client.get("/more").text
    assert "No daily run" in client.get("/").text


def test_with_two_profiles_the_page_asks_which_and_decisions_stay_in_theirs(
    client, ctx, profile, make_profile, listed_company, workspace, store
):
    other = make_profile()
    ctx.profiles[other.id] = other
    for path in ("/", "/more", "/spending"):
        assert f"?profile={profile.id}" in client.get(path).text

    page = client.get(f"/?profile={profile.id}").text
    assert f'action="/decide/acme?profile={profile.id}"' in page
    token = form_token(client, f"/?profile={profile.id}")
    data = {"decision": "approve", "reason": "Hiring now.", "form_token": token}
    sent = client.post(f"/decide/acme?profile={profile.id}", data=data, follow_redirects=False)
    assert sent.status_code == 303
    assert sent.headers["location"] == f"/?profile={profile.id}"
    assert len(workspace.decisions()) == 1
    assert Workspace(store, other.id).decisions() == []


def test_a_company_on_both_lists_is_decided_on_the_list_the_form_came_from(
    client, workspace, listed_company
):
    twin = listed_company.model_copy(update={"brief": None, "pack_id": None, "strength": 0.3})
    workspace.save_day(a_day(short=[listed_company], more=[twin]))
    token = form_token(client, "/more")
    data = {"decision": "approve", "reason": "Hiring now.", "form_token": token}
    sent = client.post("/decide/acme", data=data | {"from_list": "more"}, follow_redirects=False)
    assert sent.status_code == 303
    assert sent.headers["location"] == "/more"
    [decision] = workspace.decisions()
    assert decision.from_list == "more"


def test_the_warning_starts_at_fifty_and_the_stop_at_seventy(client, ctx, listed_company):
    ctx.meter.charge("research", 49.99, "just under")
    assert "Spending warning" not in client.get("/").text
    ctx.meter.charge("research", 0.01, "exactly the warning")
    assert "Spending warning" in client.get("/").text
    ctx.meter.charge("research", 19.98, "just under the limit")
    html = client.get("/").text
    assert "Paid work is stopped" not in html
    ctx.meter.charge("research", 0.02, "exactly the limit")
    assert "Paid work is stopped" in client.get("/").text


def tile_of(html: str, name: str) -> str:
    """The generated tile beside a company's name."""
    found = re.search(rf'<svg class="tile-art[^>]*data-company="{name}".*?</svg>', html, re.S)
    assert found, f"no tile for {name}"
    return found.group(0)


def test_each_company_has_its_own_tile_and_it_never_changes(client, workspace, listed_company):
    other = listed_company.model_copy(update={"company_key": "globex", "company_name": "Globex"})
    workspace.save_day(a_day(short=[listed_company, other]))
    first = client.get("/").text
    assert tile_of(first, "acme") == tile_of(client.get("/").text, "acme")  # the same every time
    assert tile_of(first, "acme") != tile_of(first, "globex")


def test_a_company_shows_how_fresh_its_newest_ad_is(client, workspace, listed_company, ctx):
    assert "Newest ad today" in client.get("/").text
    old = an_ad("acme").model_copy(update={"published_at": NOW - timedelta(days=3)})
    workspace.save_day(a_day(short=[listed_company.model_copy(update={"ads": [old]})]))
    html = client.get("/").text
    assert "Newest ad 3 days ago" in html
    assert (
        html.count('class="tick') == ctx.settings.new_ad_days
    )  # one tick for each day of the window


def test_the_month_is_split_into_one_slice_per_thing_paid_for(client, ctx):
    ctx.meter.charge("research", 8.0, "research")
    ctx.meter.charge("loop", 2.0, "one try")
    html = client.get("/spending").text
    assert html.count('class="slice') == 2


def test_a_decision_records_the_profile_version(decide, listed_company, workspace, profile):
    decide("acme")
    [decision] = workspace.decisions()
    assert decision.profile_version == profile.version


def turned_down(key: str, strength: float) -> ListEntry:
    """A researched company the judge said no to: a pack and a strength, no brief."""
    return ListEntry(
        company_key=key, company_name=key.title(), strength=strength, brief=None,
        ads=[an_ad(key, "Sales Lead")], pack_id=f"pack-{key}", first_listed=TODAY,
    )  # fmt: skip


@pytest.fixture
def judged_no(workspace, listed_company) -> list[ListEntry]:
    entries = [
        turned_down("initech", 0.45),
        turned_down("hooli", 0.4),
        turned_down("umbrella", 0.3),
    ]
    workspace.save_day(a_day(short=[listed_company], judged_no=entries))
    return entries


def test_the_short_list_page_shows_the_judged_no_list_closest_to_a_yes_first(client, judged_no):
    html = client.get("/").text
    assert "Judged no" in html
    places = [html.index(name) for name in ("Acme", "Initech", "Hooli", "Umbrella")]
    assert places == sorted(places)


def test_the_page_shows_no_more_judged_no_companies_than_the_setting(make_ctx, settings, judged_no):
    ctx = make_ctx(settings.model_copy(update={"judged_no_shown": 1}))
    client = TestClient(
        create_app(ctx, LocalAuth()), client=("127.0.0.1", 5000), base_url="http://localhost"
    )
    html = client.get("/").text
    assert "Initech" in html and "Hooli" not in html


def test_a_decision_on_a_judged_no_company_is_recorded_as_such(
    client, decide, judged_no, workspace
):
    assert decide("hooli", from_list="judged_no", reason="They do fit.").status_code == 303
    [decision] = workspace.decisions()
    assert (decision.company_key, decision.approved, decision.from_list) == (
        "hooli", True, "judged_no"
    )  # fmt: skip
    assert "Hooli" not in client.get("/").text
    assert decide("acme", reason="").status_code == 422  # the short list still checks reasons


def test_no_judged_no_section_when_there_are_none(client, listed_company):
    assert "Judged no" not in client.get("/").text
