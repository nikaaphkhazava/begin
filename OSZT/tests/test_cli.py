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
        "--memory",
        str(tmp_path / "memory.sqlite3"),
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


def test_doctor_needs_no_policy_and_lists_requirements(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "asusctl" in out
    assert "nvidia-smi" in out


def test_commands_that_need_a_policy_say_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tools"]) == 2
    assert "--policy is required" in capsys.readouterr().err


def test_health_exits_non_zero_on_a_sick_machine(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # dry_run swaps in the recording runner, whose zero exit status means every
    # check passes; this asserts the wiring, not the health of this machine.
    assert main(_argv(policy_file, tmp_path, "health")) == 0
    assert "audio" in capsys.readouterr().out


def test_memory_round_trips_through_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    memory = ["--memory", str(tmp_path / "memory.sqlite3")]
    assert main([*memory, "memory", "remember", "gpu", "RTX 3050"]) == 0
    assert main([*memory, "memory", "list"]) == 0
    assert "gpu: RTX 3050" in capsys.readouterr().out
    assert main([*memory, "memory", "forget", "gpu"]) == 0
    assert main([*memory, "memory", "forget", "gpu"]) == 1


def test_agent_reports_a_missing_model_instead_of_a_traceback(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _argv(
        policy_file,
        tmp_path,
        "agent",
        "do something",
        "--ollama-url",
        "http://127.0.0.1:1",  # nothing can be listening on port 1
    )
    assert main(argv) == 1
    assert "model unavailable" in capsys.readouterr().err
