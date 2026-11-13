"""The control pages: Run now, setup status, settings and the profile page.

Every test goes through the web pages, the way the reviewer uses them.
"""

import re
from datetime import date
from pathlib import Path
from typing import IO

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from why_now.domain import JobAd, Mark, Profile
from why_now.profile import load_profile, profile_text
from why_now.settings import Settings
from why_now.web.app import AppContext, create_app
from why_now.web.auth import LocalAuth
from why_now.web.run_now import RunNow
from why_now.workspace import Workspace

from .conftest import LOCAL, NOW

PAGES = ("/run", "/setup", "/settings", "/profile")


class FakeProcess:
    """Writes to the log by its path, as a real process keeps its own copy of the file."""

    def __init__(self, out: IO[str]):
        self.log = Path(out.name)
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code

    def finish(self, code: int, output: str) -> None:
        with self.log.open("a", encoding="utf-8") as f:
            f.write(output)
        self.code = code


class FakeLauncher:
    """Starts nothing. Records each command, and hands back a process the test finishes."""

    def __init__(self):
        self.commands: list[list[str]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, args: list[str], stdout: IO[str]) -> FakeProcess:
        self.commands.append(args)
        self.processes.append(FakeProcess(stdout))
        return self.processes[-1]


@pytest.fixture
def profile_file(tmp_path, profile) -> Path:
    path = tmp_path / "profiles" / "mine.yaml"
    path.parent.mkdir()
    path.write_text(profile_text(profile), encoding="utf-8")
    return path


@pytest.fixture
def launcher() -> FakeLauncher:
    return FakeLauncher()


@pytest.fixture
def ctx(settings, make_ctx, profile, profile_file, launcher, tmp_path) -> AppContext:
    ctx = make_ctx(settings)
    ctx.profile_files = {profile.id: profile_file}
    ctx.env = {}
    ctx.runner = RunNow(
        ["why-now"],
        settings_file=None,
        log_dir=tmp_path / "logs",
        launch=launcher,
        clock=lambda: NOW,
    )
    return ctx


def token(client: TestClient, path: str) -> str:
    found = re.search(r'name="form_token" value="([^"]+)"', client.get(path).text)
    assert found, f"{path} has no form token"
    return found.group(1)


class SignedIn:
    """A login that lets everyone in, as the deployed login does once signed in."""

    def current_user(self, request: Request) -> str | None:
        return "reviewer"


def test_every_control_page_needs_the_login(ctx):
    anonymous = TestClient(create_app(ctx, LocalAuth()), client=("203.0.113.9", 5000))
    for path in PAGES:
        assert anonymous.get(path).status_code == 401, path
    for path in ("/run", "/profile/preview", "/profile/draft", "/profile/save"):
        assert anonymous.post(path, data={}).status_code == 401, path


# Settings


def test_the_settings_page_lists_every_setting_with_its_value_and_reason(client):
    page = client.get("/settings").text
    for name, field in Settings.model_fields.items():
        assert name in page, name
        assert field.description and field.description.split(".")[0] in page.replace("&#39;", "'")
    assert "claude-sonnet-5-5" in page


def test_the_settings_page_escapes_every_value(settings, make_ctx):
    hostile = settings.model_copy(update={"reason_chips": ["<script>alert(1)</script>"]})
    page = TestClient(
        create_app(make_ctx(hostile), LocalAuth()), client=LOCAL, base_url="http://localhost"
    ).get("/settings")
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;" in page.text


# Setup status


def test_setup_shows_what_is_missing_and_how_to_fix_it(client, ctx):
    page = client.get("/setup").text
    assert "Claude API key" in page
    assert "ANTHROPIC_API_KEY" in page  # the name of what to set


def test_setup_never_shows_a_key_value(client, ctx):
    ctx.env = {"ANTHROPIC_API_KEY": "sk-very-secret-value", "TYPESAFE_API_KEY": "jev-secret"}
    page = client.get("/setup").text
    assert "sk-very-secret-value" not in page and "jev-secret" not in page
    assert "Claude API key" in page


# Run now


def run(client: TestClient, mode: str):
    # The token is read from the profile page, which always has a form. While a run is going,
    # the run page shows none.
    return client.post(
        "/run", data={"mode": mode, "form_token": token(client, "/profile")}, follow_redirects=False
    )


def test_run_now_starts_a_daily_run_on_the_saved_read_as_a_separate_process(
    client, launcher, profile_file
):
    assert run(client, "saved").status_code == 303
    assert launcher.commands == [
        ["why-now", "daily", "--profile", str(profile_file), "--saved-read"]
    ]
    assert "Running" in client.get("/run").text


def test_run_now_can_read_a_sample_of_careers_pages(client, launcher, settings, profile_file):
    run(client, "sample")
    assert launcher.commands == [
        [
            "why-now", "daily", "--profile", str(profile_file),
            "--sample-boards", str(settings.run_now_sample_boards),
        ]
    ]  # fmt: skip


def test_run_now_shows_the_last_result(client, launcher):
    run(client, "saved")
    launcher.processes[0].finish(0, "Short list for 2026-11-06: <b>2</b> companies\n")
    page = client.get("/run").text
    assert "Running" not in page
    assert "Finished" in page
    assert "Short list for 2026-11-06: &lt;b&gt;2&lt;/b&gt; companies" in page


def test_a_failed_run_says_so(client, launcher):
    run(client, "saved")
    launcher.processes[0].finish(1, "Error: no board lists\n")
    page = client.get("/run").text
    assert "Stopped with an error" in page and "no board lists" in page


def test_a_second_run_waits_for_the_first(client, launcher):
    run(client, "saved")
    assert run(client, "saved").status_code == 409
    assert len(launcher.commands) == 1
    launcher.processes[0].finish(0, "done\n")
    assert run(client, "saved").status_code == 303


def test_run_now_is_refused_on_aws(settings, make_ctx, launcher, tmp_path):
    ctx = make_ctx(settings.model_copy(update={"deployment": "aws"}))
    ctx.runner = RunNow(["why-now"], None, tmp_path / "logs", launch=launcher, clock=lambda: NOW)
    client = TestClient(create_app(ctx, SignedIn()))
    page = client.get("/run").text
    assert "own computer" in page
    assert 'name="mode"' not in page
    data = {"mode": "saved", "form_token": token(client, "/profile")}
    assert client.post("/run", data=data).status_code == 404
    assert launcher.commands == []


def test_an_unknown_mode_is_refused(client, launcher):
    assert run(client, "everything").status_code == 422
    assert launcher.commands == []


def test_improve_now_shows_only_once_the_improvement_run_exists(client, monkeypatch, launcher):
    from why_now.web import routes_control

    assert "Improve now" not in client.get("/run").text
    assert run(client, "improve").status_code == 422

    monkeypatch.setattr(routes_control, "improve_exists", lambda: True)
    assert "Improve now" in client.get("/run").text
    assert run(client, "improve").status_code == 303
    assert launcher.commands[0][:2] == ["why-now", "improve"]


# Profile


def an_ad(board: str, title: str) -> JobAd:
    return JobAd(
        source="greenhouse", board=board, ad_id="1", company_name=board.title(), title=title,
        location="Remote", country=None, language="en", text="We are hiring.",
        url=f"https://jobs.test/{board}/1", published_at=NOW, first_seen=date(2026, 11, 6),
    )  # fmt: skip


def send(client: TestClient, path: str, **data: str):
    return client.post(path, data=data | {"form_token": token(client, "/profile")})


def test_the_profile_page_holds_the_profile_file(client, profile_file):
    page = client.get("/profile").text
    assert "<textarea" in page
    assert "search_words:" in page


def test_preview_shows_the_companies_and_makes_no_paid_call(client, ctx, store, profile_file):
    Workspace(store).save_board_ads("greenhouse", "acme", [an_ad("acme", "Sales Lead")])
    text = profile_file.read_text(encoding="utf-8")

    page = send(client, "/profile/preview", text=text)

    assert page.status_code == 200
    assert "Acme" in page.text
    assert ctx.meter.status().spent_usd == 0
    assert profile_file.read_text(encoding="utf-8") == text  # a preview saves nothing


def test_a_profile_the_loader_refuses_is_explained_and_not_saved(client, profile_file):
    before = profile_file.read_text(encoding="utf-8")
    page = send(client, "/profile/save", text="id: x\n")
    assert page.status_code == 422
    assert "search_words" in page.text
    assert profile_file.read_text(encoding="utf-8") == before


def test_saving_an_edit_writes_the_file_and_changes_the_version(client, ctx, profile, profile_file):
    edited = profile.model_copy(update={"search_words": ["sales", "account executive"]})
    page = send(client, "/profile/save", text=profile_text(edited))
    assert page.status_code in (200, 303)
    assert load_profile(profile_file).search_words == ["sales", "account executive"]
    assert ctx.profiles[profile.id].version != profile.version
    assert ctx.profiles[profile.id].version == edited.version


def test_the_id_cannot_change_on_save(client, profile, profile_file):
    before = profile_file.read_text(encoding="utf-8")
    renamed = profile.model_copy(update={"id": "something-else"})
    page = send(client, "/profile/save", text=profile_text(renamed))
    assert page.status_code == 422
    assert profile_file.read_text(encoding="utf-8") == before


def test_after_the_first_mark_the_page_warns_that_saving_starts_a_new_version(
    client, workspace, case
):
    assert "new version" not in client.get("/profile").text
    workspace.save_mark(Mark(case_id=case.case_id, answer="yes", reason="Hiring.", marked_at=NOW))
    assert "new version" in client.get("/profile").text


def test_draft_from_description_fills_the_box_keeping_the_profile_id(
    client, ctx, profile, make_profile
):
    asked: list[str] = []

    def draft(description: str) -> Profile:
        asked.append(description)
        return make_profile(id="drafted-id", product_name="Drafted <b>tool</b>")

    ctx.draft = draft
    page = send(client, "/profile/draft", description="A practice tool.")

    assert asked == ["A practice tool."]
    assert page.status_code == 200
    assert f"id: {profile.id}" in page.text
    assert "Drafted &lt;b&gt;tool&lt;/b&gt;" in page.text


def test_draft_is_not_offered_without_a_model(client, ctx):
    ctx.draft = None
    assert "Draft from description" not in client.get("/profile").text
    assert send(client, "/profile/draft", description="Anything.").status_code == 404


def test_profile_text_is_escaped_in_the_box(client, profile, profile_file):
    hostile = profile.model_copy(update={"why_now": "</textarea><script>alert(1)</script>"})
    page = send(client, "/profile/preview", text=profile_text(hostile))
    assert "<script>alert(1)</script>" not in page.text


def test_editing_is_refused_on_aws(settings, make_ctx, profile, profile_file):
    ctx = make_ctx(settings.model_copy(update={"deployment": "aws"}))
    ctx.profile_files = {profile.id: profile_file}
    client = TestClient(create_app(ctx, SignedIn()))
    page = client.get("/profile").text
    assert "search_words:" in page
    assert 'action="/profile/save' not in page
    data = {
        "text": profile_file.read_text(encoding="utf-8"),
        "form_token": token(client, "/profile"),
    }
    assert client.post("/profile/save", data=data).status_code == 404
