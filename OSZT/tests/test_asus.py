from __future__ import annotations

from pathlib import Path

import pytest

from oszt import build_broker
from oszt.broker import Broker
from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.policy import Policy
from oszt.runner import RecordingRunner


@pytest.fixture
def asus_broker(tmp_path: Path, runner: RecordingRunner) -> Broker:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": [
                "set_power_profile",
                "get_power_profile",
                "set_keyboard_backlight",
                "set_keyboard_colour",
                "set_charge_limit",
                "get_gpu_mode",
                "set_gpu_mode",
                "gpu_status",
            ],
            "dry_run": False,
        }
    )
    return build_broker(policy, tmp_path / "audit.jsonl", runner=runner)


@pytest.mark.parametrize("profile", ["Quiet", "Balanced", "Performance"])
def test_power_profile_accepts_the_three_asus_profiles(
    asus_broker: Broker, runner: RecordingRunner, profile: str
) -> None:
    asus_broker.call("set_power_profile", profile=profile)
    assert runner.calls == [("asusctl", "profile", "--profile-set", profile)]


@pytest.mark.parametrize("profile", ["quiet", "Turbo", "", 3, None])
def test_power_profile_refuses_anything_else(asus_broker: Broker, profile: object) -> None:
    with pytest.raises(PolicyViolation):
        asus_broker.call("set_power_profile", profile=profile)


def test_get_power_profile_returns_trimmed_output(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    runner.stdout = "Balanced\n"
    assert asus_broker.call("get_power_profile") == "Balanced"


@pytest.mark.parametrize("level", ["off", "low", "med", "high"])
def test_keyboard_backlight_levels(
    asus_broker: Broker, runner: RecordingRunner, level: str
) -> None:
    asus_broker.call("set_keyboard_backlight", level=level)
    assert runner.calls == [("asusctl", "-k", level)]


def test_keyboard_backlight_refuses_an_invalid_level(asus_broker: Broker) -> None:
    with pytest.raises(PolicyViolation):
        asus_broker.call("set_keyboard_backlight", level="blinding")


def test_keyboard_colour_normalises_hex(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    asus_broker.call("set_keyboard_colour", colour="FF00AA")
    assert runner.calls == [("asusctl", "aura", "static", "-c", "ff00aa")]


@pytest.mark.parametrize("colour", ["#ff00aa", "ff00a", "ff00aaa", "gg0000", "", 16711680])
def test_keyboard_colour_refuses_malformed_values(
    asus_broker: Broker, colour: object
) -> None:
    with pytest.raises(PolicyViolation):
        asus_broker.call("set_keyboard_colour", colour=colour)


def test_charge_limit_passes_percentage(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    asus_broker.call("set_charge_limit", percent=80)
    assert runner.calls == [("asusctl", "-c", "80")]


@pytest.mark.parametrize("percent", [0, 49, 101, True, "80"])
def test_charge_limit_refuses_values_that_would_fake_a_dead_battery(
    asus_broker: Broker, percent: object
) -> None:
    with pytest.raises(PolicyViolation):
        asus_broker.call("set_charge_limit", percent=percent)


def test_get_gpu_mode_reads_supergfxctl(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    runner.stdout = "Hybrid\n"
    assert asus_broker.call("get_gpu_mode") == "Hybrid"
    assert runner.calls == [("supergfxctl", "--get")]


def test_set_gpu_mode_warns_that_the_session_ends(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    result = asus_broker.call("set_gpu_mode", mode="Integrated")
    assert result == {"mode": "Integrated", "session_ends": True}
    assert runner.calls == [("supergfxctl", "--mode", "Integrated")]


def test_set_gpu_mode_is_absent_from_the_shipped_tuf_policy() -> None:
    policy = Policy.load(Path(__file__).parent.parent / "policy.tuf-f15.json")
    assert "set_gpu_mode" not in policy.allowed_capabilities
    assert policy.dry_run is True


def test_a_daemon_that_is_not_running_surfaces_as_a_failure(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    runner.returncode = 1
    runner.stderr = "Failed to connect to asusd"
    with pytest.raises(CapabilityFailed):
        asus_broker.call("set_power_profile", profile="Quiet")


def test_gpu_status_parses_nvidia_smi(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    runner.stdout = "NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 1024, 47, 12\n"
    assert asus_broker.call("gpu_status") == {
        "name": "NVIDIA GeForce RTX 3050 Laptop GPU",
        "vram_total_mib": 4096,
        "vram_used_mib": 1024,
        "vram_free_mib": 3072,
        "temperature_c": 47,
        "utilisation_percent": 12,
    }


def test_gpu_status_reports_unparsable_output(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    runner.stdout = "no devices were found\n"
    with pytest.raises(CapabilityFailed):
        asus_broker.call("gpu_status")


def test_gpu_status_reports_empty_output(
    asus_broker: Broker, runner: RecordingRunner
) -> None:
    runner.stdout = ""
    with pytest.raises(CapabilityFailed):
        asus_broker.call("gpu_status")
