from __future__ import annotations

from pathlib import Path

import pytest

from oszt.broker import Broker
from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.runner import RecordingRunner


def test_open_app_runs_the_policy_defined_command(
    broker: Broker, runner: RecordingRunner
) -> None:
    result = broker.call("open_app", app="firefox")
    assert runner.calls == [("flatpak", "run", "org.mozilla.firefox")]
    assert result["app"] == "firefox"


def test_open_app_refuses_an_app_outside_the_policy(
    broker: Broker, runner: RecordingRunner
) -> None:
    with pytest.raises(PolicyViolation):
        broker.call("open_app", app="gparted")
    assert runner.calls == []


def test_open_app_reports_a_failing_command(broker: Broker, runner: RecordingRunner) -> None:
    runner.returncode = 1
    runner.stderr = "no such app"
    with pytest.raises(CapabilityFailed):
        broker.call("open_app", app="firefox")


def test_close_app_targets_the_flatpak_id_not_agent_input(
    broker: Broker, runner: RecordingRunner
) -> None:
    broker.call("close_app", app="firefox")
    assert runner.calls == [
        ("pkill", "--full", "--exact", "org.mozilla.firefox")
    ]


def test_close_app_targets_the_executable_for_native_apps(
    broker: Broker, runner: RecordingRunner
) -> None:
    broker.call("close_app", app="soundux")
    assert runner.calls == [("pkill", "--full", "--exact", "soundux")]


def test_list_files_lists_the_sandbox_root(broker: Broker) -> None:
    assert broker.call("list_files") == ["hello.txt", "sub"]


def test_list_files_refuses_a_path_outside_the_sandbox(broker: Broker) -> None:
    with pytest.raises(PolicyViolation):
        broker.call("list_files", path="/etc")


def test_list_files_rejects_a_file_target(broker: Broker) -> None:
    with pytest.raises(CapabilityFailed):
        broker.call("list_files", path="hello.txt")


def test_read_text_returns_file_contents(broker: Broker) -> None:
    assert broker.call("read_text", path="hello.txt") == "hello world\n"


def test_read_text_truncates_at_max_bytes(broker: Broker) -> None:
    assert broker.call("read_text", path="hello.txt", max_bytes=5) == "hello"


def test_read_text_rejects_an_absurd_max_bytes(broker: Broker) -> None:
    with pytest.raises(CapabilityFailed):
        broker.call("read_text", path="hello.txt", max_bytes=10**9)


def test_read_text_rejects_a_directory(broker: Broker) -> None:
    with pytest.raises(CapabilityFailed):
        broker.call("read_text", path="sub")


def test_read_text_cannot_follow_a_symlink_out_of_the_sandbox(
    broker: Broker, sandbox: Path
) -> None:
    (sandbox / "passwd").symlink_to("/etc/passwd")
    with pytest.raises(PolicyViolation):
        broker.call("read_text", path="passwd")


def test_set_volume_converts_percent_to_a_fraction(
    broker: Broker, runner: RecordingRunner
) -> None:
    broker.call("set_volume", percent=40)
    assert runner.calls == [("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.40")]


def test_set_volume_accepts_silence(broker: Broker, runner: RecordingRunner) -> None:
    broker.call("set_volume", percent=0)
    assert runner.calls == [("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.00")]


@pytest.mark.parametrize("percent", [-1, 101, 1000])
def test_set_volume_refuses_out_of_range_values(broker: Broker, percent: int) -> None:
    with pytest.raises(PolicyViolation):
        broker.call("set_volume", percent=percent)


@pytest.mark.parametrize("percent", ["50", 50.0, True, None])
def test_set_volume_refuses_non_integers(broker: Broker, percent: object) -> None:
    with pytest.raises(PolicyViolation):
        broker.call("set_volume", percent=percent)


def test_set_brightness_passes_a_percentage(broker: Broker, runner: RecordingRunner) -> None:
    broker.call("set_brightness", percent=70)
    assert runner.calls == [("brightnessctl", "set", "70%")]


@pytest.mark.parametrize("percent", [0, 4])
def test_set_brightness_will_not_blank_the_screen(broker: Broker, percent: int) -> None:
    with pytest.raises(PolicyViolation):
        broker.call("set_brightness", percent=percent)
