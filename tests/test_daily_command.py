"""`why-now daily` with a profile kept outside the repo, fake web and scripted models."""

import json
import re
from datetime import UTC, datetime

import httpx
import yaml
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import daily as daily_command
from why_now.cli import read as read_command
from why_now.sample.data import HIRING_SENTENCE, sample_models, sample_profile

NOW = datetime(2026, 11, 6, 9, tzinfo=UTC)


def jobs(company: str) -> dict:
    ad = {
        "absolute_url": f"https://job-boards.greenhouse.io/{company}/jobs/1",
        "location": {"name": "Berlin"},
        "id": 1,
        "title": "Account Executive",
        "company_name": company.title(),
        "first_published": "2026-11-05T10:00:00Z",
        "language": "en",
        "content": f"&lt;p&gt;{HIRING_SENTENCE}.&lt;/p&gt;",
    }
    return {"jobs": [ad], "meta": {"total": 1}}


def setup(tmp_path, monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        match = re.fullmatch(r"/v1/boards/(\w+)/jobs", request.url.path)
        return httpx.Response(200, json=jobs(match.group(1))) if match else httpx.Response(404)

    monkeypatch.setattr(
        read_command,
        "make_http",
        lambda settings: httpx.Client(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(daily_command, "make_models", lambda settings, meter: sample_models())
    monkeypatch.setattr(daily_command, "now", lambda: NOW)

    # A profile in a folder of its own, not the repo.
    profile = sample_profile().model_copy(update={"id": "outside-repo"})
    outside = tmp_path / "private-profiles"
    outside.mkdir()
    profile_file = outside / "mine.yaml"
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")))

    boards = tmp_path / "boards.json"
    boards.write_text(json.dumps(["acme", "bolt"]))
    settings = tmp_path / "settings.toml"
    settings.write_text(
        "\n".join(
            [
                f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}",
                "request_delay_seconds = 0",
                f"board_lists = {{ greenhouse = {json.dumps(str(boards))} }}",
            ]
        )
    )
    return profile_file, settings


def test_daily_runs_for_a_profile_outside_the_repo(tmp_path, monkeypatch):
    profile_file, settings = setup(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        app, ["daily", "--profile", str(profile_file), "--settings", str(settings)]
    )
    assert result.exit_code == 0, result.output
    assert "Short list for 2026-11-06: 2 companies" in result.output
    assert "Acme" in result.output and "Bolt" in result.output
    assert (tmp_path / "ws").is_dir()


def test_daily_takes_the_list_size_and_new_ad_window_for_one_run(tmp_path, monkeypatch):
    profile_file, settings = setup(tmp_path, monkeypatch)
    args = ["daily", "--profile", str(profile_file), "--settings", str(settings)]
    result = CliRunner().invoke(app, args + ["--short-list-size", "1"])
    assert result.exit_code == 0, result.output
    assert "Short list for 2026-11-06: 1 companies" in result.output
    assert "More list: 1 companies" in result.output


def test_a_new_ad_window_too_short_for_the_ads_finds_nothing(tmp_path, monkeypatch):
    profile_file, settings = setup(tmp_path, monkeypatch)
    # The ads were published on the 5th. A window of 1 day, today only, leaves them out.
    args = ["daily", "--profile", str(profile_file), "--settings", str(settings)]
    result = CliRunner().invoke(app, args + ["--new-ad-days", "1"])
    assert result.exit_code == 0, result.output
    assert "Short list for 2026-11-06: 0 companies" in result.output


def test_daily_explains_a_missing_profile(tmp_path, monkeypatch):
    _, settings = setup(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        app, ["daily", "--profile", str(tmp_path / "none.yaml"), "--settings", str(settings)]
    )
    assert result.exit_code != 0 and "cannot read profile" in result.output


def test_daily_explains_missing_board_lists(tmp_path, monkeypatch):
    profile_file, _ = setup(tmp_path, monkeypatch)
    settings = tmp_path / "bare.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    result = CliRunner().invoke(
        app, ["daily", "--profile", str(profile_file), "--settings", str(settings)]
    )
    assert result.exit_code != 0 and "board_lists" in result.output


def test_daily_on_the_saved_read_reads_no_careers_page(tmp_path, monkeypatch):
    profile_file, settings = setup(tmp_path, monkeypatch)
    args = ["daily", "--profile", str(profile_file), "--settings", str(settings)]
    assert CliRunner().invoke(app, ["read", "--settings", str(settings)]).exit_code == 0
    asked: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(500)

    monkeypatch.setattr(
        read_command,
        "make_http",
        lambda settings: httpx.Client(transport=httpx.MockTransport(refuse)),
    )
    result = CliRunner().invoke(app, args + ["--saved-read"])

    assert result.exit_code == 0, result.output
    assert "Short list for 2026-11-06: 2 companies" in result.output
    assert not [p for p in asked if "/boards/" in p]


def test_daily_can_read_a_sample_of_careers_pages(tmp_path, monkeypatch):
    profile_file, settings = setup(tmp_path, monkeypatch)
    args = ["daily", "--profile", str(profile_file), "--settings", str(settings)]
    result = CliRunner().invoke(app, args + ["--sample-boards", "1"])
    assert result.exit_code == 0, result.output
    assert "Short list for 2026-11-06: 1 companies" in result.output


def test_saved_read_and_a_sample_cannot_be_asked_for_together(tmp_path, monkeypatch):
    profile_file, settings = setup(tmp_path, monkeypatch)
    args = ["daily", "--profile", str(profile_file), "--settings", str(settings)]
    result = CliRunner().invoke(app, args + ["--saved-read", "--sample-boards", "1"])
    assert result.exit_code != 0
