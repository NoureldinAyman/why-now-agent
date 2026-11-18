"""The site reads profiles from the workspace on each visit."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from why_now.ai.budget import Meter
from why_now.profile import profile_text
from why_now.settings import Settings
from why_now.store.local import LocalStore
from why_now.web.app import AppContext, create_app
from why_now.web.auth import LocalAuth
from why_now.web.run_now import RunNow
from why_now.workspace import Workspace

from .conftest import LOCAL, NOW

PAGES = ["/", "/more", "/mark", "/mark/progress", "/profile", "/run", "/spending"]


class SignedIn:
    def current_user(self, request) -> str | None:
        return "reviewer"


@pytest.fixture
def empty_client(settings: Settings, tmp_path) -> TestClient:
    store = LocalStore(tmp_path / "empty")
    ctx = AppContext(settings, store, Meter(store, settings, lambda: NOW), lambda: NOW)
    return TestClient(create_app(ctx, LocalAuth()), client=LOCAL, base_url="http://localhost")


@pytest.mark.parametrize("path", PAGES)
def test_the_site_starts_with_no_profiles_and_says_how_to_upload_one(empty_client, path):
    page = empty_client.get(path)
    assert page.status_code == 200, path
    assert "why-now profile upload" in page.text


def test_a_profile_uploaded_after_the_site_started_shows_without_a_restart(
    empty_client, make_profile, tmp_path
):
    profile = make_profile(product_name="Latecomer")
    assert "Latecomer" not in empty_client.get("/profile").text

    Workspace(LocalStore(tmp_path / "empty")).save_profile(profile, profile_text(profile))

    assert "Latecomer" in empty_client.get("/profile").text


def test_the_top_bar_shows_the_profile_in_use_and_lists_the_others(
    client, store, profile, make_profile
):
    other = make_profile(product_name="Other Tool")
    Workspace(store).save_profile(other, profile_text(other))

    page = client.get("/mark", params={"profile": profile.id}).text

    assert f"in use: {profile.product_name}" in page.replace("<b>", "").replace("</b>", "")
    assert "<details" in page
    assert f'href="/mark?profile={other.id}"' in page
    assert "Other Tool" in page
    assert "<script" not in page


def test_the_switcher_keeps_to_the_page_the_reviewer_is_on(client, store, profile, make_profile):
    other = make_profile()
    Workspace(store).save_profile(other, profile_text(other))
    page = client.get("/more", params={"profile": profile.id}).text
    assert f'href="/more?profile={other.id}"' in page


def test_the_aws_profile_page_is_a_readable_view_with_no_form(settings, make_ctx, profile):
    ctx = make_ctx(settings.model_copy(update={"deployment": "aws"}))
    client = TestClient(create_app(ctx, SignedIn()))

    page = client.get("/profile").text

    assert "<form" not in page and "<textarea" not in page
    assert profile.product_name in page
    assert profile.search_words[0] in page
    assert profile.why_now in page
    for question in profile.fit_questions:
        assert question.text in page


def test_the_local_profile_page_keeps_the_text_box(client, profile):
    page = client.get("/profile").text
    assert "<textarea" in page and f"id: {profile.id}" in page


def token(client: TestClient, path: str) -> str:
    found = re.search(r'name="form_token" value="([^"]+)"', client.get(path).text)
    assert found
    return found.group(1)


def test_saving_the_text_box_saves_to_the_workspace(client, store, profile):
    edited = profile.model_copy(update={"search_words": ["sales", "account executive"]})

    reply = client.post(
        "/profile/save",
        data={"text": profile_text(edited), "form_token": token(client, "/profile")},
        follow_redirects=False,
    )

    assert reply.status_code == 303
    workspace = Workspace(store)
    assert workspace.profile(profile.id) == edited
    assert workspace.profile_version(profile.id, profile.version) == profile


def test_saving_also_writes_the_file_the_profile_came_from(ctx, store, profile, tmp_path):
    path: Path = tmp_path / "mine.yaml"
    path.write_text(profile_text(profile), encoding="utf-8")
    ctx.profile_files = {profile.id: path}
    client = TestClient(create_app(ctx, LocalAuth()), client=LOCAL, base_url="http://localhost")
    edited = profile.model_copy(update={"search_words": ["sales", "account executive"]})

    client.post(
        "/profile/save",
        data={"text": profile_text(edited), "form_token": token(client, "/profile")},
    )

    assert path.read_text(encoding="utf-8") == profile_text(edited)
    assert Workspace(store).profile(profile.id) == edited


def test_run_now_starts_the_run_for_the_profile_by_its_id(ctx, profile, tmp_path):
    started: list[list[str]] = []

    class Process:
        def poll(self):
            return None

    ctx.runner = RunNow(
        ["why-now"],
        None,
        tmp_path / "logs",
        launch=lambda args, out: started.append(args) or Process(),
        clock=lambda: NOW,
    )
    client = TestClient(create_app(ctx, LocalAuth()), client=LOCAL, base_url="http://localhost")

    reply = client.post(
        "/run", data={"mode": "saved", "form_token": token(client, "/run")}, follow_redirects=False
    )

    assert reply.status_code == 303
    assert started == [["why-now", "daily", "--profile", profile.id, "--saved-read"]]
