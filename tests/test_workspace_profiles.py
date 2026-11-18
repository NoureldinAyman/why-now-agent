"""Profiles kept in the workspace, each version by its hash."""

import pytest

from why_now.profile import profile_text
from why_now.workspace import Workspace


def test_a_saved_profile_can_be_read_back_by_its_id(store, make_profile):
    profile = make_profile()
    workspace = Workspace(store)

    workspace.save_profile(profile, profile_text(profile))

    assert workspace.profile(profile.id) == profile
    assert workspace.profile_ids() == [profile.id]


def test_the_workspace_starts_with_no_profiles(store):
    workspace = Workspace(store)
    assert workspace.profile_ids() == []
    assert workspace.profile("nothing") is None


def test_an_old_version_stays_readable_after_a_new_upload(store, make_profile):
    workspace = Workspace(store)
    old = make_profile(id="mine")
    new = old.model_copy(update={"search_words": ["sales", "account executive"]})
    assert old.version != new.version

    workspace.save_profile(old, profile_text(old))
    workspace.save_profile(new, profile_text(new))

    assert workspace.profile("mine") == new
    assert workspace.profile_version("mine", old.version) == old
    assert workspace.profile_version("mine", new.version) == new
    assert workspace.profile_version("mine", "0" * 64) is None


def test_profile_ids_are_listed_in_order(store, make_profile):
    workspace = Workspace(store)
    for name in ("zeta", "alpha"):
        profile = make_profile(id=name)
        workspace.save_profile(profile, profile_text(profile))
    assert workspace.profile_ids() == ["alpha", "zeta"]


def test_the_text_is_kept_as_written(store, make_profile):
    profile = make_profile()
    text = "# my own note\n" + profile_text(profile)
    Workspace(store).save_profile(profile, text)
    assert Workspace(store).profile_text(profile.id) == text


def test_an_id_that_is_not_one_safe_name_is_refused(store, make_profile):
    for bad in ("a/b", "../x", "con", ""):
        profile = make_profile(id=bad)
        with pytest.raises(ValueError, match="profile id"):
            Workspace(store).save_profile(profile, profile_text(profile))
    assert Workspace(store).profile_ids() == []
