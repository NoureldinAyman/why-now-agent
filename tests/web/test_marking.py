import re
from collections.abc import Sequence
from datetime import date, timedelta

from fastapi.testclient import TestClient

from why_now.ai.budget import BudgetStatus
from why_now.day_result import DayResult, ListEntry
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


def a_day(day: date, short: Sequence[str] = (), more: Sequence[str] = ()) -> DayResult:
    def entry(key: str) -> ListEntry:
        return ListEntry(
            company_key=key, company_name=key.title(), strength=0.5, brief=None, ads=[],
            pack_id=None, first_listed=day,
        )  # fmt: skip

    return DayResult(
        day=day, short_list=[entry(k) for k in short], more_list=[entry(k) for k in more],
        failed=[], skipped=[],
        costs=BudgetStatus(
            month="2026-11", spent_usd=0, by_category={}, warning=False, stopped=False,
            loop_stopped=False,
        ),
    )  # fmt: skip


def test_a_chip_alone_is_a_valid_reason(client, post_mark, workspace, case):
    reply = post_mark(case.case_id, answer="no", reason="", chips=["competitor"])
    assert reply.status_code == 303
    [mark] = workspace.marks("first")
    assert (mark.reason, mark.chips) == ("", ["competitor"])


def test_chips_and_a_sentence_are_both_kept(post_mark, workspace, case):
    post_mark(case.case_id, reason="Hires a lot.", chips=["good timing", "too big", "too big"])
    [mark] = workspace.marks("first")
    assert (mark.reason, mark.chips) == ("Hires a lot.", ["good timing", "too big"])


def test_an_answer_with_no_chip_and_no_sentence_is_refused(client, post_mark, workspace, case):
    reply = post_mark(case.case_id, answer="yes", reason="  ", chips=[])
    assert reply.status_code == 422
    assert "reason" in reply.text.lower()
    assert list(workspace.marks("first")) == []


def test_a_chip_that_is_not_one_of_the_settings_is_refused(post_mark, workspace, case):
    assert post_mark(case.case_id, reason="", chips=["made up"]).status_code == 422
    assert list(workspace.marks("first")) == []


def test_the_page_offers_the_chips_from_the_settings_and_one_tap_answers(client, settings, case):
    html = client.get("/mark").text
    for chip in settings.reason_chips:
        assert re.search(rf'name="chips" value="{chip}"', html)
    for answer in ("yes", "no", "cant_tell"):
        assert re.search(rf'<button[^>]*name="answer" value="{answer}"', html)


def test_the_chips_picked_stay_ticked_when_the_form_comes_back_with_an_error(
    client, post_mark, case
):
    reply = post_mark(case.case_id, answer="bogus", reason="", chips=["too small"])
    assert reply.status_code == 422
    assert re.search(r'value="too small"[^>]* checked', reply.text)
    assert not re.search(r'value="competitor"[^>]* checked', reply.text)


def test_a_mark_records_whether_the_company_was_on_a_list_before(
    client, post_mark, workspace, add_case
):
    listed, unlisted = add_case("acme"), add_case("globex")
    workspace.save_day(a_day(NOW.date() - timedelta(days=3), short=["acme"]))
    post_mark(listed.case_id)
    post_mark(unlisted.case_id)
    seen = {m.case_id: m.seen_on_list for m in workspace.marks("first")}
    assert seen == {listed.case_id: True, unlisted.case_id: False}


def test_the_more_list_counts_too_and_a_later_list_does_not(post_mark, workspace, add_case):
    on_more, later = add_case("acme"), add_case("globex")
    workspace.save_day(a_day(NOW.date() - timedelta(days=1), more=["acme"]))
    workspace.save_day(a_day(NOW.date() + timedelta(days=1), short=["globex"]))
    post_mark(on_more.case_id)
    post_mark(later.case_id)
    seen = {m.case_id: m.seen_on_list for m in workspace.marks("first")}
    assert seen == {on_more.case_id: True, later.case_id: False}


def test_the_page_shows_a_card_from_the_pack_and_the_full_pack_opens_below_it(
    client, workspace, profile, add_case
):
    case = add_case("acme")
    pack = workspace.load_pack(case.pack_id)
    page = "P" * 400 + "TAIL-ONLY-IN-FULL-PACK"
    workspace.store.put(  # a frozen pack is never changed, so a second one is saved by hand
        "packs", f"{profile.id}/pack-rich",
        pack.model_copy(update={
            "pack_id": "pack-rich",
            "ad_titles": ["Sales Rep", "Sales Rep", "Account Executive"],
            "newest_ad_at": NOW - timedelta(days=2),
            "sources": [*pack.sources, pack.sources[0].model_copy(
                update={"id": "pg", "kind": "page", "url": "https://acme.test/about", "text": page}
            )],
        }).model_dump(mode="json"),
    )  # fmt: skip
    workspace.save_case(case.model_copy(update={"pack_id": "pack-rich"}))
    html = client.get("/mark").text
    card_html, _, pack_html = html.partition("<details")
    assert "Sales Rep ×2" in card_html and "Account Executive" in card_html
    assert "Newest ad: 2026-11-04" in card_html
    assert "P" * 400 in card_html and "TAIL-ONLY-IN-FULL-PACK" not in card_html
    assert "TAIL-ONLY-IN-FULL-PACK" in pack_html
    assert "We are hiring sales staff" in pack_html and "We are hiring sales staff" not in card_html


def test_the_page_suggests_a_repeat_round_once_enough_first_marks_are_old_enough(
    make_ctx, settings, workspace, add_case
):
    small = TestClient(
        create_app(make_ctx(settings.model_copy(update={"remark_size": 2})), LocalAuth()),
        client=LOCAL, base_url="http://localhost",
    )  # fmt: skip
    old = NOW - timedelta(days=settings.remark_after_days + 1)
    for name in ("acme", "globex"):
        workspace.save_mark(
            Mark(case_id=add_case(name).case_id, answer="yes", reason="r", marked_at=old)
        )
    add_case("initech")  # one still waiting, so the case page is shown
    assert "marked again" in small.get("/mark").text

    workspace.save_repeat_selection(1, ["case-acme", "case-globex"], NOW)
    assert "marked again" not in small.get("/mark").text  # already picked


def test_no_repeat_round_is_suggested_when_too_few_marks_are_old_enough(
    make_ctx, settings, workspace, add_case
):
    small = TestClient(
        create_app(make_ctx(settings.model_copy(update={"remark_size": 2})), LocalAuth()),
        client=LOCAL, base_url="http://localhost",
    )  # fmt: skip
    old = NOW - timedelta(days=settings.remark_after_days + 1)
    workspace.save_mark(
        Mark(case_id=add_case("acme").case_id, answer="yes", reason="r", marked_at=old)
    )
    workspace.save_mark(  # a can't tell cannot be compared, and a recent mark is remembered
        Mark(case_id=add_case("globex").case_id, answer="cant_tell", reason="r", marked_at=old)
    )
    workspace.save_mark(
        Mark(case_id=add_case("initech").case_id, answer="no", reason="r", marked_at=NOW)
    )
    add_case("hooli")
    assert "marked again" not in small.get("/mark").text
