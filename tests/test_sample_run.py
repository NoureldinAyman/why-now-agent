import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from why_now.cli import app

ROOT = Path(__file__).parents[1]
KEYS = ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY")


def repo_status() -> str:
    try:
        return subprocess.run(
            ["git", "status", "--porcelain", "--ignored"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a Git checkout")


def test_sample_run_needs_no_keys_and_leaves_the_repo_clean(tmp_path, monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    before = repo_status()
    result = CliRunner().invoke(app, ["sample-run", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 0, result.output
    assert "Simulated data" in result.output
    assert repo_status() == before


def test_sample_run_shows_both_lists_and_spends_nothing(tmp_path):
    result = CliRunner().invoke(app, ["sample-run", "--workspace", str(tmp_path / "ws")])
    assert "Short list for" in result.output and "10 companies" in result.output
    assert "More list: 3 companies" in result.output
    assert "Nettle Staffing Agency" not in result.output  # dropped at the quick look
    assert "Orchard Lane Press" not in result.output  # its only ad is too old to be new
    assert "Spent $0.00" in result.output
    assert "Failed" not in result.output and "Skipped" not in result.output


def test_every_line_of_a_sample_run_is_labelled_as_simulated(tmp_path):
    result = CliRunner().invoke(app, ["sample-run", "--workspace", str(tmp_path / "ws")])
    headings = [line for line in result.output.splitlines() if not line.startswith(" ")]
    assert headings and all("Simulated data" in line for line in headings[:1] + headings[-1:])
    assert any(line.startswith("Simulated data. Short list") for line in headings)


def test_without_a_folder_the_sample_run_makes_its_own_outside_the_repo():
    result = CliRunner().invoke(app, ["sample-run"])
    assert result.exit_code == 0, result.output
    saved = (
        result.output.split("Saved in ")[1].split(".", 1)[0] if "Saved in " in result.output else ""
    )
    assert saved and not Path(saved).is_relative_to(ROOT)
