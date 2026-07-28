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


def _janitor_policy(tmp_path: Path, sandbox: Path, *, dry_run: bool, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "allowed_capabilities": [
                    "list_cleaners",
                    "clean_caches",
                    "delete_path",
                    "list_trash",
                    "restore_path",
                ],
                "file_roots": [str(sandbox)],
                "write_roots": [str(sandbox)],
                "protected_paths": [],
                "trash_dir": str(tmp_path / "trash"),
                "allowed_cleaners": ["flatpak-unused", "thumbnails"],
                "dry_run": dry_run,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def clean_policy_file(tmp_path: Path, sandbox: Path) -> Path:
    """Cleanup jobs, in dry run: the tests must not empty this machine's caches."""
    return _janitor_policy(tmp_path, sandbox, dry_run=True, name="clean-policy.json")


@pytest.fixture
def janitor_policy_file(tmp_path: Path, sandbox: Path) -> Path:
    """The same capabilities, for real, inside the sandbox."""
    return _janitor_policy(tmp_path, sandbox, dry_run=False, name="janitor-policy.json")


def test_clean_without_arguments_lists_the_jobs(
    clean_policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(clean_policy_file, tmp_path, "clean")) == 0
    assert [job["name"] for job in json.loads(capsys.readouterr().out)] == [
        "flatpak-unused",
        "thumbnails",
    ]


def test_clean_all_runs_every_allowed_job(
    clean_policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(clean_policy_file, tmp_path, "clean", "--all")) == 0
    reported = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert [entry["cleaner"] for entry in reported] == ["flatpak-unused", "thumbnails"]


def test_clean_reports_a_job_the_policy_forbids(
    clean_policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(clean_policy_file, tmp_path, "clean", "dnf-cache")) == 1
    assert "refused" in capsys.readouterr().err


def test_the_trash_command_shows_how_to_undo_a_deletion(
    janitor_policy_file: Path, tmp_path: Path, sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(janitor_policy_file, tmp_path, "trash")) == 0
    assert "trash is empty" in capsys.readouterr().out

    argv = _argv(
        janitor_policy_file, tmp_path, "call", "delete_path", f"path={sandbox / 'hello.txt'}"
    )
    assert main(argv) == 0
    assert not (sandbox / "hello.txt").exists()

    assert main(_argv(janitor_policy_file, tmp_path, "trash")) == 0
    printed = capsys.readouterr().out
    assert "hello.txt" in printed
    assert "restore_path" in printed


def test_see_reports_a_missing_vision_model_instead_of_a_traceback(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _argv(policy_file, tmp_path, "see", "--ollama-url", "http://127.0.0.1:1")
    assert main(argv) == 1
    # capture_screen is not in this policy, so the refusal comes first.
    assert "refused" in capsys.readouterr().err


@pytest.fixture
def apps_policy_file(tmp_path: Path, sandbox: Path) -> Path:
    """Installing turned on, in dry run: the tests install nothing for real."""
    path = tmp_path / "apps-policy.json"
    path.write_text(
        json.dumps(
            {
                "allowed_capabilities": [
                    "list_installable_apps",
                    "install_app",
                    "uninstall_app",
                ],
                "file_roots": [str(sandbox)],
                "trash_dir": str(tmp_path / "trash"),
                "installable_apps": ["org.videolan.VLC", "org.mozilla.firefox"],
                "dry_run": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_apps_lists_what_may_be_installed(
    apps_policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(apps_policy_file, tmp_path, "apps")) == 0
    assert [entry["app_id"] for entry in json.loads(capsys.readouterr().out)] == [
        "org.mozilla.firefox",
        "org.videolan.VLC",
    ]


def test_apps_install_reports_the_exact_command(
    apps_policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _argv(apps_policy_file, tmp_path, "apps", "install", "org.videolan.VLC")
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["argv"] == [
        "flatpak",
        "install",
        "--user",
        "--assumeyes",
        "--noninteractive",
        "flathub",
        "org.videolan.VLC",
    ]


def test_apps_install_refuses_an_id_off_the_allowlist(
    apps_policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _argv(apps_policy_file, tmp_path, "apps", "install", "org.some.Miner")
    assert main(argv) == 1
    assert "not on the installable allowlist" in capsys.readouterr().err


def test_apps_install_without_an_id_is_an_error(
    apps_policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(apps_policy_file, tmp_path, "apps", "install")) == 1
    assert "needs an application id" in capsys.readouterr().err


def test_apps_is_refused_when_the_policy_withholds_installing(
    policy_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(policy_file, tmp_path, "apps")) == 1
    assert "refused" in capsys.readouterr().err
