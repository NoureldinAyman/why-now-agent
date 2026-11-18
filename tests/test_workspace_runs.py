"""Run notes: one is written when a run starts and one when it finishes, and only one run goes
at a time. A start with no finish shows as a run that stopped."""

from datetime import UTC, datetime, timedelta

import pytest

from why_now.workspace import Workspace
from why_now.workspace.runs import RunAlreadyGoing, RunSummary, run_state

T0 = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)
STALE = timedelta(hours=12)


@pytest.fixture
def ws(store) -> Workspace:
    return Workspace(store)


def test_a_started_run_is_the_one_running(ws):
    note = ws.start_run("acme", "daily", T0, STALE)

    running = ws.running(T0 + timedelta(minutes=5), STALE)

    assert running == note
    assert (note.profile_id, note.mode, note.started_at, note.finished_at) == (
        "acme", "daily", T0, None,
    )  # fmt: skip


def test_two_runs_never_go_at_once(ws):
    first = ws.start_run("acme", "daily", T0, STALE)

    with pytest.raises(RunAlreadyGoing) as refused:
        ws.start_run("other", "improve", T0 + timedelta(minutes=1), STALE)

    assert refused.value.holder == first
    assert [n.profile_id for n in ws.last_runs("other", 10)] == []  # the refused one left no note


def test_a_finished_run_lets_the_next_one_start(ws):
    first = ws.start_run("acme", "daily", T0, STALE)
    ws.finish_run(first, T0 + timedelta(minutes=30), RunSummary(short_list=3))

    assert ws.running(T0 + timedelta(minutes=31), STALE) is None
    second = ws.start_run("acme", "improve", T0 + timedelta(hours=1), STALE)
    assert second.mode == "improve"


def test_the_finish_note_keeps_the_summary_and_how_it_ended(ws):
    note = ws.start_run("acme", "daily", T0, STALE)
    done = ws.finish_run(note, T0 + timedelta(minutes=9), RunSummary(short_list=3, more_list=40))

    (kept,) = ws.last_runs("acme", 10)

    assert kept == done
    assert (kept.ended, kept.finished_at) == ("finished", T0 + timedelta(minutes=9))
    assert (kept.summary.short_list, kept.summary.more_list) == (3, 40)
    assert run_state(kept, T0 + timedelta(hours=1), STALE) == "finished"


def test_a_run_that_failed_says_so_and_still_lets_the_next_start(ws):
    note = ws.start_run("acme", "daily", T0, STALE)
    ws.finish_run(note, T0 + timedelta(minutes=2), RunSummary(problem="no board lists"), "failed")

    (kept,) = ws.last_runs("acme", 10)

    assert run_state(kept, T0 + timedelta(hours=1), STALE) == "failed"
    assert kept.summary.problem == "no board lists"
    ws.start_run("acme", "daily", T0 + timedelta(hours=1), STALE)


def test_a_start_with_no_finish_shows_as_stopped_once_it_is_stale(ws):
    note = ws.start_run("acme", "night", T0, STALE)  # the night's task died, so no finish

    soon, morning = T0 + timedelta(hours=1), T0 + timedelta(hours=13)

    assert run_state(note, soon, STALE) == "running"
    assert ws.running(soon, STALE) == note
    assert run_state(note, morning, STALE) == "stopped"
    assert ws.running(morning, STALE) is None
    assert [run_state(n, morning, STALE) for n in ws.last_runs("acme", 10)] == ["stopped"]


def test_a_stale_note_does_not_block_forever(ws):
    ws.start_run("acme", "night", T0, STALE)

    later = ws.start_run("acme", "daily", T0 + timedelta(hours=13), STALE)

    assert ws.running(T0 + timedelta(hours=14), STALE) == later


def test_a_run_that_was_taken_over_cannot_release_the_new_ones_lock(ws):
    old = ws.start_run("acme", "night", T0, STALE)
    new = ws.start_run("acme", "daily", T0 + timedelta(hours=13), STALE)

    ws.finish_run(old, T0 + timedelta(hours=14), RunSummary())  # the old one wakes up late

    assert ws.running(T0 + timedelta(hours=14), STALE) == new


def test_last_runs_are_one_profiles_newest_first_and_limited(ws):
    for i in range(4):
        start = T0 + timedelta(days=i)
        note = ws.start_run("acme", "daily", start, STALE)
        ws.finish_run(note, start + timedelta(minutes=5), RunSummary(short_list=i))
    other = ws.start_run("other", "daily", T0 + timedelta(days=9), STALE)
    ws.finish_run(other, T0 + timedelta(days=9, minutes=5), RunSummary())

    runs = ws.last_runs("acme", 3)

    assert [n.summary.short_list for n in runs] == [3, 2, 1]
    assert all(n.profile_id == "acme" for n in runs)


def test_a_profile_id_that_cannot_name_a_place_is_refused(ws):
    with pytest.raises(ValueError):
        ws.start_run("../acme", "daily", T0, STALE)
    assert ws.running(T0, STALE) is None
