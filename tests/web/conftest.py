import re
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from why_now.ai.budget import Meter
from why_now.domain import CaseRecord, EvidencePack, Profile, Source
from why_now.settings import Settings
from why_now.web.app import AppContext, create_app
from why_now.web.auth import LocalAuth
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def profile(make_profile) -> Profile:
    return make_profile()


@pytest.fixture
def workspace(store, profile) -> Workspace:
    return Workspace(store, profile.id)


@pytest.fixture
def make_ctx(store, profile) -> Callable[[Settings], AppContext]:
    """An app context for the given settings, over the test store and profile."""

    def make(settings: Settings) -> AppContext:
        return AppContext(
            settings=settings,
            store=store,
            profiles={profile.id: profile},
            meter=Meter(store, settings, lambda: NOW),
            clock=lambda: NOW,
        )

    return make


@pytest.fixture
def ctx(settings, make_ctx) -> AppContext:
    return make_ctx(settings)


@pytest.fixture
def client(ctx) -> TestClient:
    return TestClient(create_app(ctx, LocalAuth()), client=LOCAL, base_url="http://localhost")


@pytest.fixture
def add_case(workspace, profile) -> Callable[..., CaseRecord]:
    """Save a case with a frozen evidence pack holding one job ad with the given text."""

    def add(name: str = "acme", ad_text: str = "We are hiring sales staff.") -> CaseRecord:
        case = CaseRecord(
            case_id=f"case-{name}", profile_id=profile.id, company_key=name, seed=1,
            pack_id=f"pack-{name}",
        )  # fmt: skip
        pack = EvidencePack(
            pack_id=f"pack-{name}",
            profile_id=profile.id,
            company_key=name,
            company_name=name.title(),
            created_at=NOW,
            sources=[
                Source(
                    id="s1", kind="job_ad", url=f"https://jobs.test/{name}/1",
                    text=ad_text, fetched_at=NOW,
                )
            ],
            relevant_ad_count=1,
            total_open_jobs=4,
            research_steps=0,
        )  # fmt: skip
        workspace.save_pack(pack)
        workspace.save_case(case)
        return case

    return add


@pytest.fixture
def case(add_case) -> CaseRecord:
    return add_case()


def token_of(client: TestClient) -> str:
    """The form token the page hands out, read the way a browser would: from the form."""
    html = client.get("/mark").text
    found = re.search(r'name="form_token" value="([^"]+)"', html)
    assert found, "the page has no form token"
    return found.group(1)


@pytest.fixture
def post_mark(client) -> Callable[..., object]:
    held: list[str] = []  # the form is loaded once, so sending it again reuses its token

    def post(case_id: str, answer: str = "yes", reason: str = "Hiring now.", **extra):
        if not held:
            held.append(token_of(client))
        data = {"answer": answer, "reason": reason, "form_token": held[0]} | extra
        return client.post(f"/mark/{case_id}", data=data, follow_redirects=False)

    return post
