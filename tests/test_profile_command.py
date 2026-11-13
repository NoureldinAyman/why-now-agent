"""`why-now draft-profile`: a description in, a profile file out."""

from test_drafting import DRAFT
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import profile as profile_command
from why_now.drafting import DraftedProfile
from why_now.profile import load_profile
from why_now.sample.models import Script, ScriptedWriter


def test_draft_profile_writes_a_file_the_loader_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        profile_command,
        "make_writer",
        lambda settings: ScriptedWriter(Script(writes={DraftedProfile.__name__: DRAFT})),
    )
    out = tmp_path / "mine.yaml"

    result = CliRunner().invoke(
        app, ["draft-profile", "--out", str(out)], input="A practice tool for new salespeople.\n"
    )

    assert result.exit_code == 0, result.output
    assert load_profile(out).id == "throwaway-tool"
    assert "Read it" in result.output


def test_draft_profile_never_overwrites_a_file(tmp_path, monkeypatch):
    out = tmp_path / "mine.yaml"
    out.write_text("kept", encoding="utf-8")
    result = CliRunner().invoke(app, ["draft-profile", "--out", str(out)], input="Anything.\n")
    assert result.exit_code != 0
    assert out.read_text(encoding="utf-8") == "kept"
