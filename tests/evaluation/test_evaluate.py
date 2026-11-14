import pytest
from eval_world import NOW, ByCompany, Sequence, Tracer, add_case, make_run, models_saying

from why_now.domain import FitQuestion, RulesFile
from why_now.evaluation.evaluate import (
    EvalRun,
    baselines,
    compare_judges,
    consistency,
    evaluate_pile,
    open_final_pile,
    set_cutoff,
)
from why_now.evaluation.records import ScorePoint
from why_now.workspace import Workspace


def test_a_yes_company_the_agent_also_says_yes_is_a_right_yes(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    models = models_saying(quick={"Acme": 0.9}, judge={"Acme": 0.9})
    run = EvalRun(
        workspace=workspace, profile=profile, models=models, settings=settings, tracer=Tracer()
    )

    result = evaluate_pile("check", RulesFile(profile_id=profile.id), run, "evaluation")
    assert result.score.tp == 1
    assert result.score.n == 1


def test_a_cant_tell_company_is_left_out_of_the_score(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "cant_tell")
    models = models_saying(quick={"Acme": 0.9, "Beta": 0.9}, judge={"Acme": 0.9, "Beta": 0.9})
    run = EvalRun(
        workspace=workspace, profile=profile, models=models, settings=settings, tracer=Tracer()
    )

    result = evaluate_pile("check", RulesFile(profile_id=profile.id), run, "evaluation")

    assert result.score.n == 1


def test_a_failed_company_is_reported_and_not_counted_as_a_no(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "yes")
    models = models_saying(quick={"Acme": 0.9, "Beta": 0.9}, judge={"Acme": 0.9, "Beta": None})
    run = EvalRun(
        workspace=workspace, profile=profile, models=models, settings=settings, tracer=Tracer()
    )

    result = evaluate_pile("check", RulesFile(profile_id=profile.id), run, "evaluation")

    assert result.failed_cases == ["case-Beta"]
    assert result.score.n == 1


def test_evaluate_pile_refuses_the_final_pile(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "final", "yes")
    models = models_saying(quick={"Acme": 0.9}, judge={"Acme": 0.9})
    run = EvalRun(
        workspace=workspace, profile=profile, models=models, settings=settings, tracer=Tracer()
    )

    with pytest.raises(ValueError):
        evaluate_pile("final", RulesFile(profile_id=profile.id), run, "evaluation")


def test_every_final_opening_is_logged(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "final", "yes")
    workspace.save_cutoff("fake-1", 0.5)
    run = make_run(workspace, profile, settings, quick={"Acme": 0.9}, judge={"Acme": 0.9})

    open_final_pile(run, "first", None)

    assert [o.moment for o in workspace.final_pile_openings()] == ["first"]


def test_an_extra_opening_needs_a_reason_and_is_not_logged_without_one(
    store, settings, make_profile
):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "final", "yes")
    run = make_run(workspace, profile, settings, quick={"Acme": 0.9}, judge={"Acme": 0.9})

    with pytest.raises(ValueError):
        open_final_pile(run, "extra", None)

    assert workspace.final_pile_openings() == []


def test_a_company_not_marked_yet_is_left_out(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", None)
    run = make_run(
        workspace,
        profile,
        settings,
        quick={"Acme": 0.9, "Beta": 0.9},
        judge={"Acme": 0.9, "Beta": 0.9},
    )

    result = evaluate_pile("check", RulesFile(profile_id=profile.id), run, "evaluation")

    assert result.score.n == 1


class RecordingWorkspace(Workspace):
    """A workspace that remembers which evidence packs were read."""

    def __init__(self, store, profile_id):
        super().__init__(store, profile_id)
        self.packs_read: list[str] = []

    def load_pack(self, pack_id):
        self.packs_read.append(pack_id)
        return super().load_pack(pack_id)


def test_the_cutoff_is_chosen_on_the_practice_pile_only(store, settings, make_profile):
    profile = make_profile(
        fit_questions=[
            FitQuestion(id="f1", text="Is it hiring salespeople?", kind="required"),
            FitQuestion(id="s1", text="Is the sales team growing?"),
        ]
    )
    workspace = RecordingWorkspace(store, profile.id)
    add_case(workspace, "Acme", "practice", "yes")
    add_case(workspace, "Beta", "practice", "no")
    add_case(workspace, "Cora", "check", "yes")
    add_case(workspace, "Dune", "final", "no")
    judge = {"Acme": 0.9, "Beta": 0.6, "Cora": 0.1, "Dune": 0.1}
    run = make_run(workspace, profile, settings, quick={}, judge=judge)

    cutoff = set_cutoff(run)

    assert cutoff == 0.65
    assert workspace.cutoff(run.models.judge.answer_key) == 0.65
    assert sorted(workspace.packs_read) == ["pack-Acme", "pack-Beta"]


def test_each_row_shows_what_the_agent_and_the_reviewer_said(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "no")
    quick = {"Acme": 0.9, "Beta": 0.1}
    run = make_run(workspace, profile, settings, quick=quick, judge={"Acme": 0.9})

    result = evaluate_pile("check", RulesFile(profile_id=profile.id), run, "evaluation")

    rows = {row.case_id: row for row in result.rows}
    acme, beta = rows["case-Acme"], rows["case-Beta"]
    assert (acme.agent_yes, acme.reviewer_yes, acme.quick_passed) == (True, True, True)
    assert [a.question_id for a in acme.answers] == ["f1"]
    # The quick look dropped Beta, so the judge was never asked: it has no answers.
    assert (beta.agent_yes, beta.reviewer_yes, beta.quick_passed) == (False, False, False)
    assert beta.answers == []


def test_a_score_point_records_rules_version_models_profile_and_pile_size(
    store, settings, make_profile
):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    run = make_run(workspace, profile, settings, quick={"Acme": 0.9}, judge={"Acme": 0.9})
    rules = RulesFile(profile_id=profile.id, version=3)

    result = evaluate_pile("check", rules, run, "evaluation")
    workspace.save_score_point(ScorePoint(at=NOW, result=result))

    [point] = workspace.score_points()
    assert point.result.rules_version == 3
    assert point.result.models == {"quick_look": "quick-1", "judge": "fake-1"}
    assert point.result.profile_version == profile.version
    assert point.result.score.n == 1


def test_a_company_the_quick_look_cannot_answer_for_is_reported_not_counted_as_a_no(
    store, settings, make_profile
):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "yes")
    quick = {"Acme": 0.9, "Beta": None}
    run = make_run(workspace, profile, settings, quick=quick, judge={"Acme": 0.9})

    result = evaluate_pile("check", RulesFile(profile_id=profile.id), run, "evaluation")

    assert result.failed_cases == ["case-Beta"]
    assert result.score.n == 1


@pytest.fixture
def three_companies(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "no")
    add_case(workspace, "Cora", "check", "no")
    quick = {"Acme": 0.9, "Beta": 0.9, "Cora": 0.1}
    judge = {"Acme": 0.9, "Beta": 0.2}
    return make_run(workspace, profile, settings, quick=quick, judge=judge)


def test_yes_to_all_says_yes_to_every_company(three_companies):
    result = baselines("check", three_companies)["yes_to_all"]

    assert (result.tp, result.fp, result.n) == (1, 2, 3)


def test_quick_look_alone_decides_with_the_first_glance_only(three_companies):
    result = baselines("check", three_companies)["quick_look_only"]

    assert (result.tp, result.fp, result.n) == (1, 1, 3)


def test_empty_rules_is_the_agent_with_only_the_profiles_own_questions(three_companies):
    result = baselines("check", three_companies)["empty_rules"]

    assert (result.tp, result.fp, result.n) == (1, 0, 3)


def test_baselines_refuse_the_final_pile(three_companies):
    add_case(three_companies.workspace, "Dune", "final", "yes")

    with pytest.raises(ValueError):
        baselines("final", three_companies)


@pytest.fixture
def judging_world(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Pia", "practice", "yes")
    add_case(workspace, "Pete", "practice", "no")
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "no")
    add_case(workspace, "Cora", "check", "yes")
    quick = {name: 0.9 for name in ["Pia", "Pete", "Acme", "Beta", "Cora"]}
    return make_run(workspace, profile, settings, quick=quick, judge={})


def test_both_judges_are_scored_on_the_same_companies(judging_world):
    a = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2, "Cora": 0.9}, "judge-a")
    b = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2, "Cora": None}, "judge-b")

    result = compare_judges(judging_world, [a, b])

    assert {key: s.n for key, s in result.scores.items()} == {"judge-a": 2, "judge-b": 2}


def test_the_better_judge_wins_and_the_result_is_recorded(judging_world):
    a = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2, "Cora": 0.9}, "judge-a")
    b = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.9, "Cora": 0.9}, "judge-b")

    result = compare_judges(judging_world, [a, b])

    assert result.winner == "judge-a"
    assert [c.winner for c in judging_world.workspace.comparisons()] == ["judge-a"]


def test_on_a_tie_the_first_judge_listed_wins(judging_world):
    numbers = {"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2, "Cora": 0.9}
    current, challenger = ByCompany(numbers, "current"), ByCompany(numbers, "challenger")

    result = compare_judges(judging_world, [current, challenger])

    assert result.winner == "current"


@pytest.fixture
def one_pack(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Pia", "practice", "yes")
    pack = workspace.load_pack("pack-Pia")
    assert pack is not None
    return make_run(workspace, profile, settings, quick={}, judge={}), pack


def test_every_ask_goes_to_the_model_and_none_comes_from_saved_answers(one_pack):
    run, pack = one_pack
    answerer = Sequence([0.2, 0.4, 0.6, 0.8, 1.0])

    consistency(run, answerer, [pack], asks=5)
    consistency(run, answerer, [pack], asks=5)

    assert answerer.calls == 10


def test_the_spread_is_the_highest_answer_minus_the_lowest(one_pack):
    run, pack = one_pack
    answerer = Sequence([0.2, 0.4, 0.6, 0.8, 1.0])

    result = consistency(run, answerer, [pack], asks=5)

    assert result.spread["f1"].worst == pytest.approx(0.8)
    assert result.spread["f1"].average == pytest.approx(0.8)
    assert (result.asks, result.companies) == (5, 1)


def test_a_pile_other_than_practice_or_check_is_refused(three_companies):
    rules = RulesFile(profile_id=three_companies.profile.id)

    with pytest.raises(ValueError, match="practice or check"):
        evaluate_pile("bogus", rules, three_companies, "evaluation")
    with pytest.raises(ValueError, match="practice or check"):
        baselines("bogus", three_companies)


def test_a_blank_reason_is_no_reason_and_the_opening_is_not_logged(three_companies):
    three_companies.workspace.save_cutoff("fake-1", 0.5)

    with pytest.raises(ValueError, match="needs a reason"):
        open_final_pile(three_companies, "extra", "   ")

    assert three_companies.workspace.final_pile_openings() == []


def test_the_final_pile_is_not_opened_without_a_recorded_cutoff(three_companies):
    with pytest.raises(ValueError, match="cut-off"):
        open_final_pile(three_companies, "first", None)

    assert three_companies.workspace.final_pile_openings() == []


def test_a_result_says_which_cutoff_it_used_and_whether_one_was_recorded(three_companies):
    rules = RulesFile(profile_id=three_companies.profile.id)

    before = evaluate_pile("check", rules, three_companies, "evaluation")
    three_companies.workspace.save_cutoff("fake-1", 0.65)
    after = evaluate_pile("check", rules, three_companies, "evaluation")

    assert (before.cutoff, before.cutoff_recorded) == (0.5, False)
    assert (after.cutoff, after.cutoff_recorded) == (0.65, True)


def test_the_baselines_cover_the_same_companies_as_the_agent(store, settings, make_profile):
    profile = make_profile()
    workspace = Workspace(store, profile.id)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "no")
    add_case(workspace, "Cora", "check", "no")
    quick = {"Acme": 0.9, "Beta": 0.9, "Cora": 0.9}
    judge = {"Acme": 0.9, "Beta": None, "Cora": 0.2}  # the judge cannot answer for Beta
    run = make_run(workspace, profile, settings, quick=quick, judge=judge)

    result = baselines("check", run)

    assert {name: s.n for name, s in result.items()} == {
        "yes_to_all": 2,
        "quick_look_only": 2,
        "empty_rules": 2,
    }


def test_judges_with_no_company_in_common_cannot_be_compared(judging_world):
    a = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": None, "Cora": None}, "judge-a")
    b = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": None, "Beta": 0.2, "Cora": None}, "judge-b")

    with pytest.raises(ValueError, match="in common"):
        compare_judges(judging_world, [a, b])

    assert judging_world.workspace.comparisons() == []


def test_a_judge_that_fails_on_every_company_stops_the_comparison_with_a_clear_message(
    judging_world,
):
    a = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2, "Cora": 0.9}, "judge-a")
    b = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": None, "Beta": None, "Cora": None}, "judge-b")

    with pytest.raises(ValueError, match="could be graded"):
        compare_judges(judging_world, [a, b])

    assert judging_world.workspace.comparisons() == []


def test_a_comparison_records_the_companies_it_left_out_and_the_versions(judging_world):
    a = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2, "Cora": 0.9}, "judge-a")
    b = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2, "Cora": None}, "judge-b")

    result = compare_judges(judging_world, [a, b])

    assert result.dropped_cases == ["case-Cora"]
    assert result.rules_version == 0
    assert result.profile_version == judging_world.profile.version
