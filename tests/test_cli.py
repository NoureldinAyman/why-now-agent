from typer.testing import CliRunner

from why_now.cli import app


def test_the_command_starts_and_shows_help():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "why-now" in result.output or "Usage" in result.output
