import re
from datetime import UTC, datetime, timedelta

import pytest

from why_now.domain import Mark

from .conftest import NOW

FIRST_REASON = "FIRST-ANSWER-REASON-7f3a"


def first_mark(case_id: str, answer: str = "yes", reason: str = FIRST_REASON) -> Mark:
    return Mark.model_validate(
        {
            "case_id": case_id, "answer": answer, "reason": reason,
            "marked_at": NOW - timedelta(days=8), "round": "first",
        }
    )  # fmt: skip


@pytest.fixture
def repeat_case(workspace, add_case):
    """A case marked a week ago and picked to be marked again."""
    c = add_case("acme", ad_text="Acme is hiring a sales lead.")
    workspace.save_mark(first_mark(c.case_id))
    workspace.save_repeat_selection(1, [c.case_id], NOW)
    return c


def form_token(client) -> str:
    html = client.get("/repeat").text
    found = re.search(r'name="form_token" value="([^"]+)"', html)
    assert found, "the repeat page has no form token"
    return found.group(1)


def post_repeat(client, case_id, answer="no", reason="Looks like a staffing firm.", token=None):
    data = {"answer": answer, "reason": reason, "form_token": token or form_token(client)}
    return client.post(f"/repeat/{case_id}", data=data, follow_redirects=False)


def test_nothing_is_shown_until_repeats_have_been_picked(client, case):
    page = client.get("/repeat")
    assert page.status_code == 200
    assert "repeat-marks" in page.text
    assert "Acme" not in page.text


def test_repeat_page_hides_the_first_answer(client, repeat_case):
    page = client.get("/repeat")
    assert page.status_code == 200
    assert "Acme is hiring a sales lead." in page.text  # the pack, as on the first round
    assert FIRST_REASON not in page.text
    assert "checked" not in page.text  # no answer is pre-selected


def test_the_first_answer_stays_hidden_when_the_form_is_sent_back_with_an_error(
    client, repeat_case
):
    reply = post_repeat(client, repeat_case.case_id, answer="no", reason="  ")
    assert reply.status_code == 422
    assert FIRST_REASON not in reply.text


def test_a_repeat_mark_is_saved_as_a_repeat_and_leaves_the_first_one_alone(
    client, workspace, repeat_case
):
    reply = post_repeat(client, repeat_case.case_id, answer="no", reason="Staffing firm.")
    assert reply.status_code == 303 and reply.headers["location"] == "/repeat"
    [again] = workspace.marks("repeat")
    assert (again.case_id, again.answer, again.reason) == (
        repeat_case.case_id,
        "no",
        "Staffing firm.",
    )
    assert again.marked_at == NOW
    [first] = workspace.marks("first")
    assert (first.answer, first.reason) == ("yes", FIRST_REASON)


def test_marking_again_twice_keeps_the_first_repeat(client, workspace, repeat_case):
    token = form_token(client)
    post_repeat(client, repeat_case.case_id, answer="no", token=token)
    post_repeat(client, repeat_case.case_id, answer="yes", token=token)
    assert [m.answer for m in workspace.marks("repeat")] == ["no"]


def test_the_page_is_done_once_every_picked_case_is_marked_again(client, repeat_case):
    post_repeat(client, repeat_case.case_id)
    page = client.get("/repeat")
    assert page.status_code == 200
    assert "Acme" not in page.text
    assert "why-now agreement" in page.text


def test_only_picked_cases_can_be_marked_again(client, workspace, repeat_case, add_case):
    other = add_case("globex")
    workspace.save_mark(first_mark(other.case_id))
    assert post_repeat(client, other.case_id, token=form_token(client)).status_code == 404
    assert workspace.marks("repeat") == []
    assert "Globex" not in client.get("/repeat").text


def test_a_repeat_save_needs_the_form_token(client, workspace, repeat_case):
    client.get("/repeat")
    reply = post_repeat(client, repeat_case.case_id, token="wrong")
    assert reply.status_code == 403
    assert workspace.marks("repeat") == []


def test_a_repeat_save_without_a_reason_is_refused(client, workspace, repeat_case):
    reply = post_repeat(client, repeat_case.case_id, reason="")
    assert reply.status_code == 422
    assert workspace.marks("repeat") == []


def test_first_round_marking_is_not_changed_by_repeat_marking(client, workspace, repeat_case):
    post_repeat(client, repeat_case.case_id)
    assert "All marked" in client.get("/mark").text
    assert [m.round for m in workspace.marks("first")] == ["first"]


def test_save_repeat_selection_keeps_the_first_pick(workspace):
    assert workspace.repeat_selection() is None
    assert workspace.save_repeat_selection(1, ["a", "b"], datetime(2026, 11, 6, tzinfo=UTC))
    assert not workspace.save_repeat_selection(2, ["c"], datetime(2026, 11, 7, tzinfo=UTC))
    assert workspace.repeat_selection() == ["a", "b"]
