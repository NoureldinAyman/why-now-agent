"""Behaviour only the local store has. Shared behaviour is in test_store_contract.py."""

import os
from unittest.mock import Mock

import pytest

from why_now.store.local import LocalStore


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
        ("a/../..", "evil"),
        ("/abs", "evil"),
        ("C:", "evil"),
        ("ads", "con"),
        ("ads", "a/NUL"),
        ("ads", "a?b"),
        ("ads", "a*b"),
        ("ads", 'a"b'),
        ("ads", "a<b>"),
        ("ads", "a|b"),
        ("ads", "trailing."),
        ("ads", "trailing "),
        ("ads", "tab\there"),
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


def test_writes_from_several_threads_at_once_are_all_accepted(tmp_path):
    # The read step writes from one thread per job source. The check that a name
    # stays inside the workspace must not depend on folders other threads are making.
    from concurrent.futures import ThreadPoolExecutor

    s = LocalStore(tmp_path / "fresh")

    def write(i: int) -> None:
        for n in range(5):
            s.put(f"c{n}", f"k{i}", {"v": i})

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write, range(32)))
    assert len(list(s.list("c4"))) == 32
