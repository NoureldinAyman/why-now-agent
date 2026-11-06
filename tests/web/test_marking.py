import re

from fastapi.testclient import TestClient

from why_now.domain import Mark
from why_now.web.app import create_app
from why_now.web.auth import LocalAuth

from .conftest import LOCAL, NOW


def counts(client: TestClient) -> dict[str, int]:
    html = client.get("/mark/progress").text
    found = re.findall(r'id="count-(\w+)">(\d+)<', html)
    assert found, "the progress page shows no counts"
    return {name: int(n) for name, n in found}


def test_marking_page_shows_the_pack_and_no_agent_answer(client, workspace, case):
    # The agent's answers for this very company are saved, so a leak would show up.
    workspace.save_quick_answer(case.company_key, "state", "Does it sell to businesses?", "m", 0.87)
    html = client.get("/mark").text
    assert "We are hiring sales staff" in html
    for leak in ("strength", "probability", "0.87", "quick look", "verdict"):
        assert leak not in html.lower()


def test_saving_moves_to_the_next_case(client, post_mark, add_case):
    first, second = add_case("acme"), add_case("globex")
    assert "Acme" in client.get("/mark").text
    response = post_mark(first.case_id)
    assert response.status_code == 303
    assert response.headers["location"] == "/mark"
    page = client.get("/mark").text
    assert "Globex" in page and "Acme" not in page
    post_mark(second.case_id, answer="no")
    assert "all marked" in client.get("/mark").text.lower()


def test_a_saved_mark_keeps_the_answer_the_reason_and_the_time(client, post_mark, workspace, case):
    post_mark(case.case_id, answer="no", reason="  Sells to shoppers, not businesses. ")
    [mark] = workspace.marks("first")
    assert mark == Mark(
        case_id=case.case_id,
        answer="no",
        reason="Sells to shoppers, not businesses.",
        marked_at=NOW,
        round="first",
    )


def test_reason_is_required(client, post_mark, workspace, case):
    for reason in ("", "   \n"):
        assert post_mark(case.case_id, reason=reason).status_code == 422
    assert list(workspace.marks("first")) == []
    assert "Acme" in client.get("/mark").text  # the case is still waiting


def test_an_answer_other_than_yes_no_or_cant_tell_is_refused(post_mark, workspace, case):
    assert post_mark(case.case_id, answer="maybe").status_code == 422
    assert list(workspace.marks("first")) == []


def test_the_reason_box_is_a_plain_text_box(client, case):
    html = client.get("/mark").text
    assert re.search(r'<textarea[^>]*name="reason"', html)
    assert "<script" not in html.lower()  # nothing here stops dictated text going in


def test_cant_tell_is_saved_and_does_not_count_as_marked_yes_or_no(
    client, post_mark, workspace, add_case
):
    cases = [add_case("acme"), add_case("globex"), add_case("initech")]
    post_mark(cases[0].case_id, answer="cant_tell", reason="Too little to go on.")
    post_mark(cases[1].case_id, answer="yes")
    assert [m.answer for m in workspace.marks("first")] == ["cant_tell", "yes"]
    assert counts(client) == {"yes": 1, "no": 0, "cant_tell": 1, "left": 1}


def test_same_form_twice_saves_one_mark(client, post_mark, workspace, case):
    first = post_mark(case.case_id, answer="yes", reason="Hiring now.")
    again = post_mark(case.case_id, answer="no", reason="Changed my mind.")
    assert first.status_code == again.status_code == 303
    [mark] = workspace.marks("first")
    assert (mark.answer, mark.reason) == ("yes", "Hiring now.")


def test_html_in_an_ad_shows_as_text(client, add_case):
    add_case("acme", ad_text="<script>alert(1)</script> <b>Sales</b> wanted")
    html = client.get("/mark").text
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>Sales</b>" not in html


def test_marking_resumes_after_restart(ctx, client, post_mark, add_case):
    first, second = add_case("acme"), add_case("globex")
    post_mark(first.case_id)
    restarted = TestClient(create_app(ctx, LocalAuth()), client=LOCAL, base_url="http://localhost")
    page = restarted.get("/mark").text
    assert "Globex" in page and "Acme" not in page
    assert counts(restarted)["yes"] == 1
    assert second.case_id in page


def test_a_case_without_a_pack_is_not_offered(client, workspace, profile, case):
    workspace.save_case(case.model_copy(update={"case_id": "case-nopack", "pack_id": None}))
    assert "case-nopack" not in client.get("/mark").text


def test_posting_without_the_form_token_is_refused(client, workspace, case):
    client.get("/mark")  # a visit, so the browser has its cookie
    data = {"answer": "yes", "reason": "Hiring now."}
    assert client.post(f"/mark/{case.case_id}", data=data).status_code == 403
    wrong = data | {"form_token": "not-the-token"}
    assert client.post(f"/mark/{case.case_id}", data=wrong).status_code == 403
    assert list(workspace.marks("first")) == []


def test_a_token_from_another_session_is_refused(client, ctx, workspace, case):
    other = TestClient(create_app(ctx, LocalAuth()), client=LOCAL, base_url="http://localhost")
    stolen = re.search(r'name="form_token" value="([^"]+)"', other.get("/mark").text)
    assert stolen
    client.get("/mark")
    data = {"answer": "yes", "reason": "Hiring now.", "form_token": stolen.group(1)}
    assert client.post(f"/mark/{case.case_id}", data=data).status_code == 403
    assert list(workspace.marks("first")) == []


def test_marking_an_unknown_case_is_not_found(client, post_mark, case):
    assert post_mark("case-missing").status_code == 404


def test_marks_are_kept_per_round(workspace, case):
    first = Mark(case_id=case.case_id, answer="yes", reason="r", marked_at=NOW, round="first")
    again = first.model_copy(update={"round": "repeat", "answer": "no"})
    assert workspace.save_mark(first) is True
    assert workspace.save_mark(first) is False
    assert workspace.save_mark(again) is True
    assert [m.answer for m in workspace.marks("first")] == ["yes"]
    assert [m.answer for m in workspace.marks("repeat")] == ["no"]


def test_private_pages_are_not_cached_and_run_no_script(client, case):
    response = client.get("/mark")
    assert response.headers["cache-control"] == "no-store"
    assert "script-src" not in response.headers["content-security-policy"]
    assert "default-src 'none'" in response.headers["content-security-policy"]
