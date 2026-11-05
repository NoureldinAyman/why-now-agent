from pathlib import Path

import pytest

from why_now.profile import ProfileError, load_profile

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
