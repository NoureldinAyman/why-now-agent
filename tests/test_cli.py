import json
from pathlib import Path

import httpx
from commoncrawl_fake import fake_index, lines
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import read as read_command
from why_now.cli import sources as sources_command
from why_now.store.local import LocalStore
from why_now.workspace import Workspace


def test_the_command_starts_and_shows_help():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "judge companies against a profile" in result.output


def fake_greenhouse(fixture: dict):
    """Greenhouse stand-in: the `acme` page answers with the fixture, any other page is missing."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/v1/boards/acme/jobs":
            return httpx.Response(200, json=fixture)
        return httpx.Response(404, json={"status": 404})

    return lambda settings: httpx.Client(transport=httpx.MockTransport(handle))


def read_setup(tmp_path, monkeypatch, names):
    fixture = json.loads(
        (Path(__file__).parent / "sources" / "fixtures" / "greenhouse_jobs.json").read_text()
    )
    monkeypatch.setattr(read_command, "make_http", fake_greenhouse(fixture))
    boards = tmp_path / "boards.json"
    boards.write_text(json.dumps(names))
    settings = tmp_path / "settings.toml"
    settings.write_text(
        f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n"
        "request_delay_seconds = 0\n"
        f"board_lists = {{ greenhouse = {json.dumps(str(boards))} }}\n"
    )
    return settings


def test_read_saves_ads_and_says_what_failed(tmp_path, monkeypatch):
    settings = read_setup(tmp_path, monkeypatch, ["acme", "gone"])
    result = CliRunner().invoke(app, ["read", "--sample", "2", "--settings", str(settings)])
    assert result.exit_code == 0, result.output
    assert "greenhouse: read 1 of 2 careers pages, 2 job ads (2 new)" in result.output
    assert "gone" in result.output and "404" in result.output
    ads = Workspace(LocalStore(tmp_path / "ws")).load_board_ads("greenhouse", "acme")
    assert ads is not None and len(ads) == 2


def test_a_second_read_on_the_same_day_finds_nothing_new(tmp_path, monkeypatch):
    settings = read_setup(tmp_path, monkeypatch, ["acme"])
    CliRunner().invoke(app, ["read", "--settings", str(settings)])
    result = CliRunner().invoke(app, ["read", "--settings", str(settings)])
    assert "2 job ads (0 new)" in result.output


def test_read_sample_takes_only_that_many_pages(tmp_path, monkeypatch):
    settings = read_setup(tmp_path, monkeypatch, ["acme", "gone", "lost", "missing"])
    result = CliRunner().invoke(app, ["read", "--sample", "1", "--settings", str(settings)])
    assert "of 1 careers pages" in result.output


def test_read_reports_a_whole_source_outage(tmp_path, monkeypatch):
    settings = read_setup(tmp_path, monkeypatch, ["gone", "lost"])
    result = CliRunner().invoke(app, ["read", "--settings", str(settings)])
    assert "greenhouse looks down" in result.output


def test_read_explains_a_missing_board_list(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    result = CliRunner().invoke(app, ["read", "--settings", str(settings)])
    assert result.exit_code != 0
    assert "board_lists" in result.output


def test_build_list_writes_a_merged_list_without_duplicates(tmp_path, monkeypatch):
    http = fake_index(
        {"jobs.lever.co": [lines("https://jobs.lever.co/a/1", "https://jobs.lever.co/b/2")]}
    )
    monkeypatch.setattr(sources_command, "make_http", lambda settings: http)
    out = tmp_path / "lever.json"
    out.write_text(json.dumps(["b", "c"]))
    settings = tmp_path / "settings.toml"
    settings.write_text("request_delay_seconds = 0\n")
    result = CliRunner().invoke(
        app, ["build-list", "--source", "lever", "--out", str(out), "--settings", str(settings)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text()) == ["b", "c", "a"]
    assert "1 new" in result.output and "3 careers pages" in result.output


def test_build_list_reports_failure_plainly_and_keeps_the_old_list(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sources_command, "make_http", lambda settings: fake_index({}, fail_with=504)
    )
    out = tmp_path / "lever.json"
    out.write_text(json.dumps(["b"]))
    settings = tmp_path / "settings.toml"
    settings.write_text("request_delay_seconds = 0\n")
    result = CliRunner().invoke(
        app, ["build-list", "--source", "lever", "--out", str(out), "--settings", str(settings)]
    )
    assert result.exit_code != 0
    assert "504" in result.output and "supply your own" in result.output
    assert json.loads(out.read_text()) == ["b"]
