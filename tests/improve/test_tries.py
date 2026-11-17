from datetime import timedelta
from typing import Literal

from eval_world import NOW

from why_now.improve.records import TryRecord
from why_now.workspace import Workspace


def a_try(
    number: int, outcome: Literal["kept", "discarded", "screened_out"], cost: float = 0.5
) -> TryRecord:
    return TryRecord(
        try_id=f"try-{number}",
        started_at=NOW + timedelta(minutes=number),
        change=None,
        screen_problem="names a company" if outcome == "screened_out" else None,
        check_before=None,
        check_after=None,
        practice_before=None,
        practice_after=None,
        outcome=outcome,
        reasons=[],
        cost_usd=cost,
        rules_version_before=0,
        rules_version_after=1 if outcome == "kept" else 0,
    )


def test_every_try_is_kept_whichever_way_it_went(store):
    workspace = Workspace(store, "p1")
    workspace.save_try(a_try(1, "kept"))
    workspace.save_try(a_try(2, "discarded"))
    workspace.save_try(a_try(3, "screened_out"))

    tries = workspace.tries()

    assert [t.outcome for t in tries] == ["kept", "discarded", "screened_out"]
    assert [t.cost_usd for t in tries] == [0.5, 0.5, 0.5]
    assert tries[2].screen_problem == "names a company"


def test_tries_are_kept_apart_for_each_profile(store):
    Workspace(store, "p1").save_try(a_try(1, "kept"))

    assert Workspace(store, "p2").tries() == []


def test_a_tried_mistake_is_remembered_for_that_rules_version_only(store):
    workspace = Workspace(store, "p1")
    workspace.mark_mistake_tried("practice:Acme", 0)

    assert workspace.tried_mistakes(0) == {"practice:Acme"}
    assert workspace.tried_mistakes(1) == set()  # the rules changed, so it may be tried again


def test_tried_mistakes_add_up_and_marking_twice_changes_nothing(store):
    workspace = Workspace(store, "p1")
    workspace.mark_mistake_tried("practice:Acme", 0)
    workspace.mark_mistake_tried("decision:Beta", 0)
    workspace.mark_mistake_tried("practice:Acme", 0)

    assert workspace.tried_mistakes(0) == {"practice:Acme", "decision:Beta"}


def test_tried_mistakes_are_kept_apart_for_each_profile(store):
    Workspace(store, "p1").mark_mistake_tried("practice:Acme", 0)

    assert Workspace(store, "p2").tried_mistakes(0) == set()
