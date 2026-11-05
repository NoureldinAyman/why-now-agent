import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from why_now.settings import Settings, load_settings

EXAMPLE = Path(__file__).parents[1] / "examples" / "settings.example.toml"


def test_defaults_match_the_design():
    s = load_settings(None, env={})
    assert (s.short_list_size, s.hide_days, s.new_ad_days) == (10, 90, 14)
    assert (s.research_per_day, s.research_steps, s.keep_min_gain) == (12, 5, 2)
    assert s.tries_per_check_pile == 50
    assert (s.practice_size, s.check_size, s.final_size) == (150, 75, 75)
    assert (s.target_yes_per_pile, s.floor_yes_per_pile) == (25, 15)
    assert (s.pilot_size, s.marking_ceiling, s.remark_size) == (40, 500, 30)
    assert s.request_delay_seconds == 1.0
    assert s.dead_after_days == 7
    assert (s.budget_limit_usd, s.budget_warning_usd, s.loop_budget_usd) == (70, 50, 25)
    assert s.langfuse_thin_at_units == 40_000
    assert s.public_results_enabled is False


def test_numbers_added_to_the_design_table_have_its_values():
    s = load_settings(None, env={})
    assert (s.newest_ads_read, s.remark_after_days) == (5, 7)
    assert (s.outage_share, s.retry_dead_after_days) == (0.9, 30)
    assert (s.request_attempts, s.max_retry_wait_seconds, s.source_timeout_seconds) == (3, 60, 30)
    assert s.fixed_monthly_costs_usd == 0
    assert (s.quick_look_pass, s.required_pass) == (0.3, 0.5)
    assert (s.max_page_bytes, s.page_timeout_seconds) == (2_000_000, 15)
    assert (s.max_ad_chars, s.max_pack_chars, s.brief_max_chars) == (20_000, 60_000, 1_200)
    assert (s.screen_max_copied_words, s.screen_max_why_words) == (8, 20)


def test_quick_look_has_a_fallback_model_setting():
    s = load_settings(None, env={})
    assert s.quick_look_fallback_model == "claude-haiku-5-5"


def test_settings_file_overrides_defaults(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text("short_list_size = 20")
    assert load_settings(f, env={}).short_list_size == 20


def test_environment_overrides_the_file(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text("short_list_size = 20\nhide_days = 30")
    s = load_settings(f, env={"WHY_NOW_SHORT_LIST_SIZE": "5", "OTHER": "1"})
    assert (s.short_list_size, s.hide_days) == (5, 30)


def test_environment_can_set_lists_dicts_and_booleans():
    s = load_settings(
        None,
        env={
            "WHY_NOW_DAILY_PROFILES": '["a.yaml"]',
            "WHY_NOW_BOARD_LISTS": '{"greenhouse": "boards.txt"}',
            "WHY_NOW_PUBLIC_RESULTS_ENABLED": "true",
        },
    )
    assert s.daily_profiles == [Path("a.yaml")]
    assert s.board_lists == {"greenhouse": Path("boards.txt")}
    assert s.public_results_enabled is True


def test_a_misspelt_setting_is_refused(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text("short_list_sise = 20")
    with pytest.raises(ValidationError):
        load_settings(f, env={})


def test_a_misspelt_environment_setting_is_refused():
    with pytest.raises(ValidationError):
        load_settings(None, env={"WHY_NOW_SHORT_LIST_SISE": "20"})


def test_example_file_lists_every_setting_with_its_default():
    text = EXAMPLE.read_text(encoding="utf-8")
    values = tomllib.loads(text)
    assert set(values) == set(Settings.model_fields)
    assert load_settings(EXAMPLE, env={}) == Settings()


def test_example_file_has_a_comment_for_every_setting():
    lines = EXAMPLE.read_text(encoding="utf-8").splitlines()
    for name in Settings.model_fields:
        starts = (f"{name} =", f"[{name}]")
        at = next(i for i, line in enumerate(lines) if line.startswith(starts))
        assert at > 0 and lines[at - 1].startswith("# "), name
