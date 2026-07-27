from __future__ import annotations

import json
from pathlib import Path

import pytest

from oszt.cli import main


@pytest.fixture
def policy_file(tmp_path: Path, sandbox: Path) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "allowed_capabilities": ["list_files", "open_app"],
                "allowed_apps": {"firefox": ["flatpak", "run", "org.mozilla.firefox"]},
                "file_roots": [str(sandbox)],
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


def test_tools_prints_the_allowed_capabilities(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(policy_file, tmp_path, "tools")) == 0
    names = [tool["name"] for tool in json.loads(capsys.readouterr().out)]
    assert names == ["list_files", "open_app"]


def test_call_runs_a_capability(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(policy_file, tmp_path, "call", "list_files", "path=.")) == 0
    assert json.loads(capsys.readouterr().out) == ["hello.txt", "sub"]


def test_call_reports_a_refusal_on_stderr(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(policy_file, tmp_path, "call", "set_volume", "percent=50")) == 1
    assert "refused" in capsys.readouterr().err


def test_arguments_must_be_key_value_pairs(policy_file: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(_argv(policy_file, tmp_path, "call", "list_files", "nonsense"))


def test_json_argument_values_are_parsed(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(_argv(policy_file, tmp_path, "call", "open_app", 'app="firefox"'))
    assert json.loads(capsys.readouterr().out)["app"] == "firefox"
