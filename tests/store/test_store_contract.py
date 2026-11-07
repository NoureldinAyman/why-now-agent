"""What every Store must do. Each test runs against the local store and the AWS store.

The AWS store runs against moto, a stand-in for S3 and DynamoDB that lives in this
process, so no test touches a real AWS account.
"""

import boto3
import pytest
from aws_fake import BUCKET, REGION, TABLE

from why_now.settings import load_settings
from why_now.store import Store
from why_now.store.aws import AwsStore
from why_now.store.local import LocalStore


def make_aws_store() -> AwsStore:
    return AwsStore(
        BUCKET,
        TABLE,
        lambda service: boto3.client(service, region_name=REGION),
        inline_max_bytes=load_settings(None, env={}).aws_inline_max_bytes,
    )


@pytest.fixture(params=["local", "aws"])
def any_store(request, tmp_path) -> Store:
    if request.param == "local":
        return LocalStore(tmp_path / "ws")
    request.getfixturevalue("moto_aws")
    return make_aws_store()


def test_round_trip(any_store):
    any_store.put("ads", "gh/acme", {"a": 1})
    any_store.put("ads", "lv/beta", {"a": 2})
    assert any_store.get("ads", "gh/acme") == {"a": 1}
    assert [k for k, _ in any_store.list("ads", "gh/")] == ["gh/acme"]
    assert any_store.get("ads", "missing") is None


def test_list_returns_keys_in_order_with_their_documents(any_store):
    for key in ["b", "a/2", "a/1"]:
        any_store.put("c", key, {"k": key})
    assert list(any_store.list("c")) == [
        ("a/1", {"k": "a/1"}),
        ("a/2", {"k": "a/2"}),
        ("b", {"k": "b"}),
    ]
    assert list(any_store.list("empty")) == []


def test_put_replaces_and_delete_removes(any_store):
    any_store.put("c", "k", {"v": 1})
    any_store.put("c", "k", {"v": 2})
    assert any_store.get("c", "k") == {"v": 2}
    any_store.delete("c", "k")
    any_store.delete("c", "k")
    assert any_store.get("c", "k") is None
    assert list(any_store.list("c")) == []


def test_text_and_numbers_survive_unchanged(any_store):
    doc = {
        "text": "Vertriebsmitarbeiter “Außendienst” – 東京",
        "probability": 0.1,
        "count": 3,
        "nested": {"list": [1.5, None, True, ""]},
    }
    any_store.put("c", "k", doc)
    assert any_store.get("c", "k") == doc


def test_collections_are_kept_apart(any_store):
    any_store.put("one", "k", {"v": 1})
    any_store.put("two", "k", {"v": 2})
    assert any_store.get("one", "k") == {"v": 1}
    assert [k for k, _ in any_store.list("one")] == ["k"]


def test_prefix_listing_handles_pagination(any_store):
    # DynamoDB hands back at most 1 MB per request, so 1,001 documents of about 2 KB
    # arrive over several pages, and every one of them must still be listed.
    filler = "x" * 2_000
    for i in range(1_001):
        any_store.put("many", f"p/{i:04}", {"i": i, "filler": filler})
    any_store.put("many", "q/0000", {"i": -1, "filler": filler})
    found = list(any_store.list("many", "p/"))
    assert [doc["i"] for _, doc in found] == list(range(1_001))


def test_large_document_round_trips(any_store):
    # Over DynamoDB's limit of 400 KB for one record.
    big = {"text": "ä" * 300_000}
    any_store.put("c", "big", big)
    assert any_store.get("c", "big") == big
    assert list(any_store.list("c")) == [("big", big)]
    any_store.put("c", "big", {"small": True})
    assert any_store.get("c", "big") == {"small": True}
    any_store.put("c", "big", big)
    any_store.delete("c", "big")
    assert any_store.get("c", "big") is None


def test_ads_and_packs_round_trip(any_store):
    any_store.put("board_ads", "greenhouse/acme", {"ads": [{"text": "Hiring."}]})
    any_store.put("packs", "p1/pack-1", {"sources": []})
    assert any_store.get("board_ads", "greenhouse/acme") == {"ads": [{"text": "Hiring."}]}
    assert list(any_store.list("packs")) == [("p1/pack-1", {"sources": []})]
    any_store.delete("packs", "p1/pack-1")
    assert any_store.get("packs", "p1/pack-1") is None


@pytest.mark.parametrize(
    ("collection", "key"),
    [
        ("ads", "../../evil"),
        ("../ads", "x"),
        ("ads", "/abs"),
        ("ads", ""),
        ("", "x"),
        ("ads", "a\\..\\..\\evil"),
        ("ads", "con"),
        ("ads", "a?b"),
        ("ads", "trailing."),
        ("ads", "tab\there"),
    ],
)
def test_store_refuses_unsafe_names(any_store, collection, key):
    # The same names are refused everywhere, so a workspace can move between stores.
    with pytest.raises(ValueError):
        any_store.put(collection, key, {})
    with pytest.raises(ValueError):
        any_store.get(collection, key)


# The AWS store only. It keeps large documents in S3 files, which two writers can race on.


class RunsAfterSmallWrite:
    """A DynamoDB client that runs `then` once, just after a small document's record is
    written, the way a second writer could get in between two steps of a save."""

    def __init__(self, client, then):
        self.client = client
        self.then = then

    def put_item(self, **kwargs):
        result = self.client.put_item(**kwargs)
        if "doc" in kwargs["Item"] and self.then is not None:
            then, self.then = self.then, None
            then()
        return result

    def __getattr__(self, name):
        return getattr(self.client, name)


def test_aws_store_keeps_the_newest_of_two_racing_writes(moto_aws):
    other = make_aws_store()
    old, newest = {"text": "a" * 400_000}, {"text": "b" * 400_000}
    other.put("c", "k", old)

    def clients(service):
        client = boto3.client(service, region_name=REGION)
        if service == "dynamodb":
            return RunsAfterSmallWrite(client, lambda: other.put("c", "k", newest))
        return client

    racing = AwsStore(BUCKET, TABLE, clients, inline_max_bytes=350_000)
    racing.put("c", "k", {"small": True})
    assert other.get("c", "k") == newest


def test_aws_store_removes_the_files_it_replaces(moto_aws):
    store = make_aws_store()
    store.put("packs", "p", {"v": 1})
    store.put("packs", "p", {"v": 2})
    store.put("c", "big", {"text": "x" * 400_000})
    store.put("c", "big", {"text": "y" * 400_000})
    store.put("c", "big", {"small": True})
    assert store.get("packs", "p") == {"v": 2}
    store.delete("packs", "p")
    found = boto3.client("s3", region_name=REGION).list_objects_v2(Bucket=BUCKET)
    assert found.get("KeyCount", 0) == 0
