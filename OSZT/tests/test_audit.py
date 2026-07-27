from __future__ import annotations

import json
from pathlib import Path

from oszt.audit import AuditLog


def test_records_append_rather_than_overwrite(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("open_app", {"app": "firefox"}, "allowed")
    log.record("set_volume", {"percent": 50}, "denied", "not permitted")
    assert [entry["capability"] for entry in log.entries()] == ["open_app", "set_volume"]


def test_each_record_is_one_json_line(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("list_files", {"path": "."}, "allowed")
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["outcome"] == "allowed"


def test_unserialisable_arguments_are_stringified(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("read_text", {"path": Path("/tmp/x")}, "allowed")
    assert log.entries()[0]["arguments"]["path"] == "/tmp/x"


def test_timestamp_comes_from_the_injected_clock(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", clock=lambda: 1234.5)
    assert log.record("list_files", {}, "allowed").timestamp == 1234.5


def test_entries_is_empty_before_anything_is_written(tmp_path: Path) -> None:
    assert AuditLog(tmp_path / "audit.jsonl").entries() == []


def test_parent_directory_is_created(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "nested" / "deeper" / "audit.jsonl")
    log.record("list_files", {}, "allowed")
    assert log.path.exists()
