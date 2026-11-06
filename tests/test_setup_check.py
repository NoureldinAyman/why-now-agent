import json

from typer.testing import CliRunner

from why_now.cli import app
from why_now.setup_check import check_setup


def by_name(settings, env):
    return {i.name: i for i in check_setup(settings, env)}


def test_no_keys_still_allows_the_sample_run(settings):
    items = by_name(settings, {})
    assert items["sample run"].status == "ok"
    assert items["Claude API key"].status == "missing"
    assert items["Jev key"].status == "optional"
    assert items["Langfuse keys"].status == "optional"


def test_every_item_that_is_not_ok_says_how_to_fix_it(settings):
    for item in check_setup(settings, {}):
        if item.status != "ok":
            assert item.how_to_fix, item.name


def test_keys_that_are_set_show_as_ready(settings):
    env = {
        "ANTHROPIC_API_KEY": "a",
        "TYPESAFE_API_KEY": "b",
        "LANGFUSE_PUBLIC_KEY": "c",
        "LANGFUSE_SECRET_KEY": "d",
    }
    items = by_name(settings, env)
    for name in ("Claude API key", "Jev key", "Langfuse keys"):
        assert items[name].status == "ok", name


def test_one_langfuse_key_alone_is_not_enough(settings):
    items = by_name(settings, {"LANGFUSE_PUBLIC_KEY": "c"})
    assert items["Langfuse keys"].status == "optional"
    assert "LANGFUSE_SECRET_KEY" in items["Langfuse keys"].how_to_fix


def test_an_empty_key_counts_as_missing(settings):
    assert by_name(settings, {"ANTHROPIC_API_KEY": "  "})["Claude API key"].status == "missing"


def test_careers_page_list_and_profile_follow_the_settings(settings, tmp_path):
    items = by_name(settings, {})
    assert items["careers page list"].status == "missing"
    assert items["profile"].status == "missing"

    board_list = tmp_path / "boards.json"
    board_list.write_text(json.dumps(["acme"]))
    profile = tmp_path / "p.yaml"
    profile.write_text("id: x")
    ready = settings.model_copy(
        update={"board_lists": {"greenhouse": board_list}, "daily_profiles": [profile]}
    )
    items = by_name(ready, {})
    assert items["careers page list"].status == "ok"
    assert items["profile"].status == "ok"


def test_a_listed_file_that_does_not_exist_is_missing(settings, tmp_path):
    broken = settings.model_copy(
        update={
            "board_lists": {"greenhouse": tmp_path / "nope.json"},
            "daily_profiles": [tmp_path / "nope.yaml"],
        }
    )
    items = by_name(broken, {})
    assert items["careers page list"].status == "missing"
    assert items["profile"].status == "missing"


def run_cli(args, env):
    return CliRunner().invoke(app, args, env=env)


def test_setup_check_never_prints_key_values():
    secrets = {
        "ANTHROPIC_API_KEY": "secret-value-1",
        "TYPESAFE_API_KEY": "secret-value-2",
        "LANGFUSE_PUBLIC_KEY": "secret-value-3",
        "LANGFUSE_SECRET_KEY": "secret-value-4",
    }
    result = run_cli(["check-setup"], secrets)
    assert result.exit_code == 0, result.output
    assert "secret-value" not in result.output
    assert "Claude API key" in result.output


def test_setup_check_lists_ready_missing_and_optional(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    result = run_cli(["check-setup", "--settings", str(settings)], {"ANTHROPIC_API_KEY": ""})
    assert result.exit_code == 0, result.output
    assert "Ready" in result.output and "sample run" in result.output
    assert "Missing" in result.output and "Claude API key" in result.output
    assert "Optional" in result.output and "Jev key" in result.output
    assert "sample run can still work" in result.output
