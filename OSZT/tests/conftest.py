from __future__ import annotations

from pathlib import Path

import pytest

from oszt import build_broker
from oszt.policy import Policy
from oszt.runner import RecordingRunner


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "hello.txt").write_text("hello world\n", encoding="utf-8")
    (root / "sub").mkdir()
    return root


@pytest.fixture
def policy(sandbox: Path) -> Policy:
    return Policy.from_dict(
        {
            "allowed_capabilities": [
                "open_app",
                "close_app",
                "list_files",
                "read_text",
                "set_volume",
                "set_brightness",
            ],
            "allowed_apps": {
                "firefox": ["flatpak", "run", "org.mozilla.firefox"],
                "soundux": ["soundux"],
            },
            "file_roots": [str(sandbox)],
            "max_calls_per_minute": 10,
            "dry_run": False,
        }
    )


@pytest.fixture
def runner() -> RecordingRunner:
    return RecordingRunner()


@pytest.fixture
def broker(policy: Policy, tmp_path: Path, runner: RecordingRunner):
    return build_broker(policy, tmp_path / "audit.jsonl", runner=runner)
