import pytest

from why_now.domain import LearnedQuestion, RulesFile
from why_now.improve.screen import RuleChange, apply_change, screen_change

WHY = "Ads that ask for this skill matched past yeses."


def add(text: str, why: str = WHY, qid: str = "L2") -> RuleChange:
    return RuleChange(
        action="add",
        question_id=None,
        question=LearnedQuestion(id=qid, text=text, why=why),
        based_on=["m1"],
    )


def screen(change, settings, names=(), ads=()):
    return screen_change(change, set(names), list(ads), settings)


def test_a_clean_change_passes(settings):
    r = screen(add("Does the company hire many engineers at once?"), settings)
    assert r.ok and r.problem is None


def test_rejects_a_company_name(settings):
    q = add("Is the team like the one at Acme Robotics?")
    assert not screen(q, settings, names={"Acme Robotics"}).ok


def test_company_name_is_case_insensitive_and_whole_word(settings):
    assert not screen(add("Does ACME hire?"), settings, names={"Acme"}).ok
    assert screen(add("Is this a pharmaceutical firm?"), settings, names={"Pharma"}).ok


def test_allows_a_common_word_inside_a_longer_word(settings):
    assert screen(add("Is the role in a city office?"), settings, names={"cit"}).ok


def test_rejects_long_text_copied_from_an_ad(settings):
    ad = "We are looking for a builder who ships small tools every single week."
    q = add("Does it want a builder who ships small tools every single week?")
    assert not screen(q, settings, ads=[ad]).ok


def test_short_overlap_with_an_ad_is_allowed(settings):
    ad = "We ship small tools every week."
    assert screen(add("Does it ship small tools?"), settings, ads=[ad]).ok


def test_rejects_two_sentences(settings):
    assert not screen(add("Does it hire? Is it growing?"), settings).ok


def test_rejects_a_long_why_clause_and_a_missing_one(settings):
    assert not screen(add("Does it hire?", why=" ".join(["word"] * 21)), settings).ok
    assert not screen(add("Does it hire?", why="  "), settings).ok


def test_remove_change_needs_no_new_wording(settings):
    change = RuleChange(action="remove", question_id="L1", question=None, based_on=["m1"])
    assert screen(change, settings).ok


def test_add_and_edit_need_a_question(settings):
    change = RuleChange(action="add", question_id=None, question=None, based_on=[])
    assert not screen(change, settings).ok


def rules() -> RulesFile:
    q = LearnedQuestion(id="L1", text="Does it hire?", why=WHY)
    return RulesFile(profile_id="p", version=3, questions=[q])


def test_cannot_change_a_profile_question():
    new = LearnedQuestion(id="profile-q1", text="Changed?", why=WHY)
    edit = RuleChange(action="edit", question_id="profile-q1", question=new, based_on=[])
    with pytest.raises(ValueError):
        apply_change(rules(), edit)
    gone = RuleChange(action="remove", question_id="profile-q1", question=None, based_on=[])
    with pytest.raises(ValueError):
        apply_change(rules(), gone)


def test_cannot_add_a_question_with_an_existing_id():
    with pytest.raises(ValueError):
        apply_change(rules(), add("Another?", qid="L1"))


def test_apply_returns_a_new_file_with_the_version_raised():
    original = rules()
    added = apply_change(original, add("Is it new?"))
    assert added.version == 4 and [q.id for q in added.questions] == ["L1", "L2"]
    assert original.version == 3 and len(original.questions) == 1
    new = LearnedQuestion(id="L1", text="Does it hire a lot?", why=WHY)
    edit = RuleChange(action="edit", question_id="L1", question=new, based_on=[])
    assert apply_change(original, edit).questions[0].text == "Does it hire a lot?"
    gone = RuleChange(action="remove", question_id="L1", question=None, based_on=[])
    removed = apply_change(original, gone)
    assert removed.questions == [] and removed.version == 4
