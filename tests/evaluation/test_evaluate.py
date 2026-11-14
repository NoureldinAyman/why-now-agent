import pytest
from eval_world import Tracer, add_case, make_run, models_saying

from why_now.domain import FitQuestion, RulesFile
from why_now.evaluation.evaluate import EvalRun, evaluate_pile, open_final_pile, set_cutoff
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
