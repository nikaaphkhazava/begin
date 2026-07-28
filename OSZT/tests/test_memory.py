from __future__ import annotations

from pathlib import Path

import pytest

from oszt.memory import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.sqlite3")


def test_remember_then_recall(store: MemoryStore) -> None:
    store.remember("gpu", "RTX 3050 Laptop, 4GB")
    assert store.recall("gpu") == "RTX 3050 Laptop, 4GB"


def test_recall_of_an_unknown_key_is_none(store: MemoryStore) -> None:
    assert store.recall("nothing") is None


def test_remembering_the_same_key_replaces_the_value(store: MemoryStore) -> None:
    store.remember("profile", "Balanced")
    store.remember("profile", "Quiet")
    assert store.recall("profile") == "Quiet"
    assert len(store.search("profile")) == 1


def test_forget_removes_a_fact_and_reports_whether_it_existed(store: MemoryStore) -> None:
    store.remember("temp", "value")
    assert store.forget("temp") is True
    assert store.forget("temp") is False


def test_search_matches_keys_and_values(store: MemoryStore) -> None:
    store.remember("laptop", "ASUS TUF Gaming F15")
    store.remember("distro", "Fedora")
    assert [fact.key for fact in store.search("TUF")] == ["laptop"]
    assert [fact.key for fact in store.search("distro")] == ["distro"]


def test_search_with_an_empty_term_returns_everything_newest_first(
    tmp_path: Path,
) -> None:
    clock = iter([1.0, 2.0])
    store = MemoryStore(tmp_path / "memory.sqlite3", clock=lambda: next(clock))
    store.remember("older", "a")
    store.remember("newer", "b")
    assert [fact.key for fact in store.search("")] == ["newer", "older"]


def test_search_honours_the_limit(store: MemoryStore) -> None:
    for index in range(5):
        store.remember(f"key{index}", "value")
    assert len(store.search("key", limit=2)) == 2


def test_actions_are_recorded_newest_first(store: MemoryStore) -> None:
    store.log_action("open_app", {"app": "firefox"}, "allowed")
    store.log_action("set_gpu_mode", {"mode": "Integrated"}, "refused")
    actions = store.recent_actions()
    assert [action.capability for action in actions] == ["set_gpu_mode", "open_app"]
    assert actions[0].outcome == "refused"


def test_memory_survives_reopening_the_file(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    first = MemoryStore(path)
    first.remember("gpu", "RTX 3050")
    first.close()
    assert MemoryStore(path).recall("gpu") == "RTX 3050"


def test_parent_directories_are_created(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "nested" / "memory.sqlite3")
    store.remember("k", "v")
    assert store.path.exists()
