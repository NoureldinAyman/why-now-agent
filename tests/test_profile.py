from pathlib import Path

import pytest

from why_now.profile import ProfileError, load_profile, quick_look_questions

COMPLETE = """\
id: throwaway
product_name: Throwaway product
product_description: A tool that helps sales teams.
users: Sales teams
search_words: [sales]
quick_look_questions:
  - id: q1
    text: Does it sell to businesses?
fit_questions:
  - id: f1
    text: Is it hiring salespeople?
    kind: required
why_now: A new sales ad shows the team is growing.
"""


@pytest.fixture
def profile_file(tmp_path) -> Path:
    p = tmp_path / "p.yaml"
    p.write_text(COMPLETE, encoding="utf-8")
    return p


def test_incomplete_profile_names_the_missing_field(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("id: x")
    with pytest.raises(ProfileError, match="search_words"):
        load_profile(p)


def test_profile_is_private_by_default(profile_file):
    assert load_profile(profile_file).public is False


def test_a_misspelt_field_is_refused(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(COMPLETE.replace("search_words", "serach_words"), encoding="utf-8")
    with pytest.raises(ProfileError, match="serach_words"):
        load_profile(p)


def test_a_profile_with_no_search_words_is_refused(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(COMPLETE.replace("search_words: [sales]", "search_words: []"), encoding="utf-8")
    with pytest.raises(ProfileError, match="search_words"):
        load_profile(p)


def test_a_missing_file_gives_a_profile_error(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "nowhere.yaml")


def test_a_misspelt_field_inside_a_question_is_refused(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(COMPLETE.replace("kind: required", "knd: required"), encoding="utf-8")
    with pytest.raises(ProfileError, match="fit_questions.0.knd"):
        load_profile(p)


def test_a_profile_without_quick_look_questions_uses_required_ones_and_one_about_users(tmp_path):
    p = tmp_path / "p.yaml"
    text = COMPLETE.replace(
        "quick_look_questions:\n  - id: q1\n    text: Does it sell to businesses?\n", ""
    )
    p.write_text(text, encoding="utf-8")
    profile = load_profile(p)

    questions = quick_look_questions(profile)

    assert [q.id for q in questions] == ["f1", "has_users"]
    assert questions[0].text == "Is it hiring salespeople?"
    assert "Sales teams" in questions[1].text


def test_a_profile_with_quick_look_questions_uses_its_own(profile_file):
    assert [q.id for q in quick_look_questions(load_profile(profile_file))] == ["q1"]


def test_editing_a_profile_changes_its_version(profile_file, tmp_path):
    before = load_profile(profile_file)
    same = tmp_path / "same.yaml"
    same.write_text("# a comment changes nothing the profile says\n" + COMPLETE, encoding="utf-8")
    edited = tmp_path / "edited.yaml"
    edited.write_text(COMPLETE.replace("[sales]", "[sales, account executive]"), encoding="utf-8")

    assert before.version == load_profile(same).version
    assert before.version != load_profile(edited).version


def test_a_marking_guide_is_optional_and_part_of_the_profile_version(tmp_path, profile_file):
    without = load_profile(profile_file)
    assert without.marking_guide == ""
    p = tmp_path / "guided.yaml"
    p.write_text(COMPLETE + "marking_guide: An agency is a no.\n", encoding="utf-8")
    guided = load_profile(p)
    assert guided.marking_guide == "An agency is a no."
    assert guided.version != without.version
