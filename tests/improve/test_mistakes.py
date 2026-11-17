from datetime import date, timedelta

from eval_world import NOW, add_case, make_run

from why_now.domain import Company, Decision, JobAd, Mark, RulesFile
from why_now.evaluation.evaluate import evaluate_pile
from why_now.improve.mistakes import find_mistakes, right_yes_reasons
from why_now.workspace import Workspace


def grade_practice(workspace, profile, settings, judge):
    """Grade the practice pile with a pretend AI. `judge` says, by company name, what number
    the judge gives. The quick look lets every company through."""
    run = make_run(workspace, profile, settings, quick={name: 0.9 for name in judge}, judge=judge)
    rules = RulesFile(profile_id=profile.id)
    return rules, evaluate_pile("practice", rules, run, "evaluation")


def decide(workspace, company_key, approved, from_list, reason="not for us", later=0):
    """Save the reviewer's decision on a daily list company."""
    workspace.save_decision(
        Decision(
            profile_id=workspace.require_profile(),
            company_key=company_key,
            approved=approved,
            reason=reason,
            decided_at=NOW + timedelta(hours=later),
            from_list=from_list,
        )
    )


def test_a_wrong_no_on_the_practice_pile_is_a_mistake(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    run = make_run(workspace, profile, settings, quick={"Acme": 0.9}, judge={"Acme": 0.1})
    rules = RulesFile(profile_id=profile.id)
    practice = evaluate_pile("practice", rules, run, "evaluation")

    mistakes = find_mistakes(workspace, practice, rules, settings)

    assert len(mistakes) == 1
    assert mistakes[0].origin == "practice"
    assert mistakes[0].company_key == "Acme"
    assert mistakes[0].agent_yes is False
    assert mistakes[0].reviewer_yes is True


def test_a_mistake_carries_the_reason_and_how_each_question_was_answered(
    store, settings, make_profile
):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.1})

    mistake = find_mistakes(workspace, practice, rules, settings)[0]

    assert mistake.id == "practice:Acme"
    assert mistake.reason == "r"
    assert [(a.question_id, a.probability) for a in mistake.answers] == [("f1", 0.1)]


def test_the_chips_the_reviewer_tapped_are_part_of_the_reason(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", None)
    workspace.save_mark(
        Mark(
            case_id="case-Acme",
            answer="yes",
            reason="has no sales team yet",
            marked_at=NOW,
            chips=["too small"],
        )
    )
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.1})

    mistake = find_mistakes(workspace, practice, rules, settings)[0]

    assert mistake.reason == "too small; has no sales team yet"


def test_a_rejected_company_from_the_short_list_is_a_wrong_yes(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")  # answered right, so no practice mistake
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})
    decide(workspace, "Beta", approved=False, from_list="short", reason="far too small")

    mistakes = find_mistakes(workspace, practice, rules, settings)

    assert len(mistakes) == 1
    assert mistakes[0].id == "decision:Beta"
    assert mistakes[0].origin == "decision"
    assert mistakes[0].agent_yes is True
    assert mistakes[0].reviewer_yes is False
    assert mistakes[0].reason == "far too small"


def test_an_approved_company_from_the_judged_no_list_is_a_wrong_no(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})
    decide(workspace, "Beta", approved=True, from_list="judged_no")

    mistakes = find_mistakes(workspace, practice, rules, settings)

    assert [(m.company_key, m.agent_yes, m.reviewer_yes) for m in mistakes] == [
        ("Beta", False, True)
    ]


def test_a_decision_that_agrees_with_the_agent_is_not_a_mistake(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})
    decide(workspace, "Beta", approved=True, from_list="short")
    decide(workspace, "Gamma", approved=False, from_list="judged_no")

    assert find_mistakes(workspace, practice, rules, settings) == []


def test_only_the_latest_decision_on_a_company_counts(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})
    decide(workspace, "Beta", approved=False, from_list="short", later=0)
    decide(workspace, "Beta", approved=True, from_list="short", later=1)

    assert find_mistakes(workspace, practice, rules, settings) == []


def test_a_decision_on_a_check_or_final_company_is_not_learned_from(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    add_case(workspace, "Beta", "check", "yes")
    add_case(workspace, "Gamma", "final", "yes")
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})
    decide(workspace, "Beta", approved=False, from_list="short")
    decide(workspace, "Gamma", approved=False, from_list="short")

    assert find_mistakes(workspace, practice, rules, settings) == []


def test_a_practice_mistake_carries_a_short_excerpt_of_the_companys_ad(
    store, settings, make_profile
):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.1})

    mistake = find_mistakes(workspace, practice, rules, settings)[0]

    assert mistake.quotes == ['Sales: "Acme is hiring salespeople."']


def test_only_the_first_few_ads_and_the_first_characters_of_each_are_kept(
    store, settings, make_profile
):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    case_id = add_case(workspace, "Acme", "practice", "yes")
    rules, practice = grade_practice(workspace, profile, settings, {"Acme": 0.1})
    ads = [
        JobAd(
            source="example-source",
            board="Acme",
            ad_id=f"Acme-{i}",
            company_name="Acme",
            title=f"Role {i}",
            location="Berlin",
            country=None,
            language=None,
            text="x" * 50,
            url="https://example.com/x",
            published_at=NOW,
            first_seen=date(2026, 11, 2),
        )
        for i in range(5)
    ]
    case = next(c for c in workspace.cases() if c.case_id == case_id)
    workspace.save_case(case, Company(key="Acme", name="Acme", ads=ads, total_open_jobs=10))
    small = settings.model_copy(update={"mistake_ads": 2, "mistake_ad_chars": 10})

    mistake = find_mistakes(workspace, practice, rules, small)[0]

    assert mistake.quotes == ['Role 0: "xxxxxxxxxx"', 'Role 1: "xxxxxxxxxx"']


def marked(workspace, name, answer, reason):
    """A practice company marked by the reviewer with the given answer and reason."""
    add_case(workspace, name, "practice", None)
    workspace.save_mark(Mark(case_id=f"case-{name}", answer=answer, reason=reason, marked_at=NOW))


def test_reasons_for_right_yeses_on_the_practice_pile_are_collected(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    marked(workspace, "Acme", "yes", "hires in many cities")  # the agent says yes: a right yes
    marked(workspace, "Beta", "no", "wrong sector")  # the agent says no: a right no
    marked(workspace, "Gamma", "yes", "has a sales team")  # the agent says no: a wrong no
    _, practice = grade_practice(
        workspace, profile, settings, {"Acme": 0.9, "Beta": 0.1, "Gamma": 0.1}
    )

    assert right_yes_reasons(workspace, practice) == ["hires in many cities"]


def test_a_right_yes_with_no_reason_adds_nothing(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    marked(workspace, "Acme", "yes", "")
    _, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})

    assert right_yes_reasons(workspace, practice) == []


def test_an_approved_company_from_the_short_or_more_list_is_a_right_yes(
    store, settings, make_profile
):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    marked(workspace, "Acme", "yes", "")
    _, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})
    decide(workspace, "Beta", approved=True, from_list="short", reason="clear sales team")
    decide(workspace, "Gamma", approved=True, from_list="more", reason="hiring a lot")
    decide(workspace, "Delta", approved=True, from_list="judged_no", reason="a wrong no")
    decide(workspace, "Epsilon", approved=False, from_list="short", reason="too small")

    reasons = right_yes_reasons(workspace, practice)

    assert sorted(reasons) == ["clear sales team", "hiring a lot"]


def test_reasons_on_a_check_or_final_company_are_not_read(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    add_case(workspace, "Beta", "check", "yes")
    add_case(workspace, "Gamma", "final", "yes")
    _, practice = grade_practice(workspace, profile, settings, {"Acme": 0.9})
    decide(workspace, "Beta", approved=True, from_list="short", reason="check reason")
    decide(workspace, "Gamma", approved=True, from_list="short", reason="final reason")

    assert right_yes_reasons(workspace, practice) == ["r"]  # only Acme's own mark
