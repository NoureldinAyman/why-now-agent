"""The few settings stored in the workspace, and the guards around them."""

import pytest

from why_now.settings import Settings
from why_now.workspace.settings_doc import (
    EDITABLE,
    SettingsRefused,
    effective_settings,
    save_overrides,
)


def test_without_a_stored_document_the_settings_are_the_files_own(store, settings):
    assert effective_settings(settings, store) == settings


def test_the_stored_document_overrides_the_file(store, settings):
    save_overrides(store, settings, {"short_list_size": 4, "hide_days": 30})

    now = effective_settings(settings, store)

    assert now.short_list_size == 4 and now.hide_days == 30
    assert now.model_copy(update={"short_list_size": 10, "hide_days": 90}) == settings


def test_nightly_profiles_start_empty_and_can_be_stored(store, settings):
    assert settings.nightly_profiles == []
    save_overrides(store, settings, {"nightly_profiles": ["mine"]})
    assert effective_settings(settings, store).nightly_profiles == ["mine"]


@pytest.mark.parametrize(
    "name, value",
    [
        ("budget_limit_usd", 5000),
        ("budget_warning_usd", 4000),
        ("loop_budget_usd", 1000),
        ("new_ad_days", 365),
        ("tries_per_run", 40),
        ("tries_per_check_pile", 400),
        ("research_per_day", 500),
        ("workspace_path", "elsewhere"),
        ("editable_limits", {"short_list_size": [1, 9999]}),
    ],
)
def test_a_setting_that_is_not_editable_is_refused(store, settings, name, value):
    with pytest.raises(SettingsRefused, match=name):
        save_overrides(store, settings, {name: value})
    assert effective_settings(settings, store) == settings


def test_a_read_only_value_already_in_the_document_is_never_applied(store, settings):
    store.put("settings", "overrides", {"budget_limit_usd": 5000, "short_list_size": 3})
    now = effective_settings(settings, store)
    assert now.budget_limit_usd == settings.budget_limit_usd
    assert now.short_list_size == 3


@pytest.mark.parametrize(
    "name, value",
    [
        ("short_list_size", 0),
        ("short_list_size", 10_000),
        ("hide_days", 0),
        ("hide_days", 10_000),
        ("judged_no_shown", -1),
        ("judged_no_shown", 10_000),
        ("prepare_batch", 0),
        ("prepare_batch", 10_000),
        ("reason_chips", []),
        ("reason_chips", [f"reason {i}" for i in range(200)]),
        ("reason_chips", ["x" * 500]),
        ("reason_chips", ["  "]),
        ("reason_chips", ["same", "same"]),
        ("nightly_profiles", ["a/b"]),
    ],
)
def test_a_value_outside_its_bounds_is_refused(store, settings, name, value):
    with pytest.raises(SettingsRefused):
        save_overrides(store, settings, {name: value})
    assert effective_settings(settings, store) == settings


def test_the_edge_of_each_bound_is_allowed(store, settings):
    low = {name: lo for name, (lo, _) in settings.editable_limits.items() if name != "reason_chips"}
    save_overrides(store, settings, low)
    assert effective_settings(settings, store).short_list_size == low["short_list_size"]
    high = {
        name: hi for name, (_, hi) in settings.editable_limits.items() if name != "reason_chips"
    }
    save_overrides(store, settings, high)
    assert effective_settings(settings, store).prepare_batch == high["prepare_batch"]


def test_a_stored_value_that_no_longer_fits_is_ignored_not_fatal(store, settings):
    store.put("settings", "overrides", {"short_list_size": "many", "hide_days": 12})
    now = effective_settings(settings, store)
    assert now.short_list_size == settings.short_list_size and now.hide_days == 12


def test_every_editable_number_has_bounds_and_every_bound_names_an_editable_setting(settings):
    numbers = {name for name in EDITABLE if isinstance(getattr(settings, name), int)}
    assert numbers | {"reason_chips"} == set(settings.editable_limits)
    assert set(settings.editable_limits) <= EDITABLE


def test_every_editable_name_is_a_setting():
    assert set(Settings.model_fields) >= EDITABLE


@pytest.mark.parametrize(
    "name, value",
    [
        ("short_list_size", 99_999),
        ("hide_days", 0),
        ("prepare_batch", 10_000),
        ("reason_chips", ["x" * 500]),
        ("nightly_profiles", ["a/b"]),
    ],
)
def test_a_stored_value_outside_its_bounds_is_not_applied(store, settings, name, value):
    store.put("settings", "overrides", {name: value})
    assert effective_settings(settings, store) == settings
