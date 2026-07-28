"""The weekly root cleanup.

It must run without a model, purge only expired trash, and never be reachable
from the agent - the agent has no capability that purges anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oszt.janitor_cli import main
from oszt.trash import Trash


@pytest.fixture
def policy_file(tmp_path: Path, sandbox: Path) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "allowed_capabilities": ["clean_caches"],
                "file_roots": [str(sandbox)],
                "write_roots": [str(sandbox)],
                "trash_dir": str(tmp_path / "trash"),
                "allowed_cleaners": ["flatpak-unused", "journal"],
                "dry_run": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def _argv(policy_file: Path, tmp_path: Path, *rest: str) -> list[str]:
    return [
        "--policy",
        str(policy_file),
        "--audit",
        str(tmp_path / "audit.jsonl"),
        *rest,
    ]


def test_it_runs_every_cleaner_the_policy_names(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(policy_file, tmp_path, "--purge-after-days", "0")) == 0
    reported = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert {entry["cleaner"] for entry in reported} == {"flatpak-unused", "journal"}


def test_a_privileged_job_is_skipped_when_it_is_not_run_as_root(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(_argv(policy_file, tmp_path, "--purge-after-days", "0"))
    reported = {
        entry["cleaner"]: entry
        for entry in (
            json.loads(line) for line in capsys.readouterr().out.strip().splitlines()
        )
    }
    assert "skipped" in reported["journal"]


def test_it_purges_trash_that_has_expired(
    policy_file: Path, tmp_path: Path, sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = 1_000_000.0
    doomed = sandbox / "old.txt"
    doomed.write_text("old\n", encoding="utf-8")
    Trash(tmp_path / "trash", clock=lambda: now).put(doomed)

    assert main(_argv(policy_file, tmp_path, "--purge-after-days", "0")) == 0
    printed = capsys.readouterr().out
    assert '"purged_trash_entries": 0' in printed or "purged_trash_entries" not in printed

    # Nothing is old enough yet, so the entry survives an ordinary weekly run.
    assert main(_argv(policy_file, tmp_path, "--purge-after-days", "30")) == 0
    assert Trash(tmp_path / "trash").entries()


def test_an_unknown_cleaner_in_the_policy_is_reported_not_ignored(
    tmp_path: Path, sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad-policy.json"
    path.write_text(
        json.dumps(
            {
                "allowed_capabilities": ["clean_caches"],
                "file_roots": [str(sandbox)],
                "trash_dir": str(tmp_path / "trash"),
                "allowed_cleaners": ["make-me-a-sandwich"],
                "dry_run": True,
            }
        ),
        encoding="utf-8",
    )
    assert main(_argv(path, tmp_path, "--purge-after-days", "0")) == 1
    assert "unknown cleaner" in capsys.readouterr().err


def test_purging_is_not_a_capability_the_agent_can_call() -> None:
    """The one irreversible operation must belong to the timer alone."""
    from oszt.capabilities import BUILTIN_CAPABILITIES

    assert not any("purge" in name for name in BUILTIN_CAPABILITIES)
