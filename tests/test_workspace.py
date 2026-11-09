from datetime import UTC, date, datetime

from why_now.domain import JobAd, Mark
from why_now.workspace import Workspace


def ad(ad_id: str) -> JobAd:
    return JobAd(
        source="s",
        board="b",
        ad_id=ad_id,
        company_name="Acme",
        title="Sales Rep",
        location="Berlin",
        country="DE",
        language=None,
        text="Sell things.",
        url="https://example.com/1",
        published_at=datetime(2026, 11, 1, 9, tzinfo=UTC),
        first_seen=date(2026, 11, 2),
    )


def test_a_saved_document_can_be_read_back(store):
    ws = Workspace(store)
    ws.put_model("ads", "s/b/1", ad("1"))
    assert ws.get_model("ads", "s/b/1", JobAd) == ad("1")
    assert Workspace(store).get_model("ads", "s/b/1", JobAd) == ad("1")


def test_a_missing_document_reads_as_none(store):
    assert Workspace(store).get_model("ads", "nothing", JobAd) is None


def test_documents_list_in_key_order_by_prefix(store):
    ws = Workspace(store)
    for i in ["2", "1", "3"]:
        ws.put_model("ads", f"s/b/{i}", ad(i))
    ws.put_model("ads", "t/b/9", ad("9"))
    assert [a.ad_id for a in ws.list_models("ads", JobAd, prefix="s/")] == ["1", "2", "3"]


def test_documents_are_plain_json_in_the_store(store):
    mark = Mark(
        case_id="c1", answer="yes", reason="hiring", marked_at=datetime(2026, 11, 5, tzinfo=UTC)
    )
    Workspace(store).put_model("marks", "c1", mark)
    assert store.get("marks", "c1") == {
        "case_id": "c1",
        "answer": "yes",
        "reason": "hiring",
        "marked_at": "2026-11-05T00:00:00Z",
        "round": "first",
        "chips": [],
        "seen_on_list": False,
    }


def test_workspace_keeps_its_profile(store):
    assert Workspace(store, profile_id="p1").profile_id == "p1"
    assert Workspace(store).profile_id is None
