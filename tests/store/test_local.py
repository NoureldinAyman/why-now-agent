import os
from unittest.mock import Mock

import pytest

from why_now.store.local import LocalStore


def test_store_round_trip_and_prefix(tmp_path):
    s = LocalStore(tmp_path)
    s.put("ads", "gh/acme", {"a": 1})
    s.put("ads", "lv/beta", {"a": 2})
    assert s.get("ads", "gh/acme") == {"a": 1}
    assert [k for k, _ in s.list("ads", "gh/")] == ["gh/acme"]
    assert s.get("ads", "missing") is None


def test_list_returns_keys_in_order_with_their_documents(tmp_path):
    s = LocalStore(tmp_path)
    for key in ["b", "a/2", "a/1"]:
        s.put("c", key, {"k": key})
    assert list(s.list("c")) == [("a/1", {"k": "a/1"}), ("a/2", {"k": "a/2"}), ("b", {"k": "b"})]
    assert list(s.list("empty")) == []


def test_put_replaces_and_delete_removes(tmp_path):
    s = LocalStore(tmp_path)
    s.put("c", "k", {"v": 1})
    s.put("c", "k", {"v": 2})
    assert s.get("c", "k") == {"v": 2}
    s.delete("c", "k")
    s.delete("c", "k")
    assert s.get("c", "k") is None


def test_text_survives_unchanged(tmp_path):
    s = LocalStore(tmp_path)
    doc = {"text": "Vertriebsmitarbeiter “Außendienst” – 東京"}
    s.put("c", "k", doc)
    assert LocalStore(tmp_path).get("c", "k") == doc


@pytest.mark.parametrize(
    ("collection", "key"),
    [
        ("ads", "../../evil"),
        ("ads", "../other/x"),
        ("../ads", "x"),
        ("ads", "/abs"),
        ("ads", "C:/abs"),
        ("ads", ""),
        ("", "x"),
        ("ads", "a\\..\\..\\evil"),
    ],
)
def test_store_refuses_keys_that_leave_the_folder(tmp_path, collection, key):
    s = LocalStore(tmp_path / "ws")
    with pytest.raises(ValueError):
        s.put(collection, key, {})
    with pytest.raises(ValueError):
        s.get(collection, key)


def test_interrupted_write_leaves_old_value(tmp_path, monkeypatch):
    s = LocalStore(tmp_path)
    s.put("c", "k", {"v": 1})
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError))
    with pytest.raises(OSError):
        s.put("c", "k", {"v": 2})
    monkeypatch.undo()
    assert s.get("c", "k") == {"v": 1}
    assert [k for k, _ in s.list("c")] == ["k"]
