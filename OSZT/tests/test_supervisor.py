from __future__ import annotations

from pathlib import Path

from oszt.errors import PolicyViolation
from oszt.health import HealthMonitor, HealthReport, Supervisor, command_check
from oszt.runner import RecordingRunner
from oszt.snapshots import ImageDeployments, Snapshotter


def _snapshotter(tmp_path: Path, runner: RecordingRunner) -> Snapshotter:
    return Snapshotter(
        subvolume=tmp_path / "live", snapshot_dir=tmp_path / "snapshots", run=runner
    )


def test_snapshot_create_names_and_invokes_btrfs(tmp_path: Path) -> None:
    runner = RecordingRunner()
    name = _snapshotter(tmp_path, runner).create("pre-batch")
    assert name.startswith("pre-batch-")
    assert runner.calls[0][:4] == ("btrfs", "subvolume", "snapshot", "-r")


def test_rollback_replaces_the_live_subvolume(tmp_path: Path) -> None:
    runner = RecordingRunner()
    _snapshotter(tmp_path, runner).rollback("pre-batch-1")
    assert runner.calls[0][:3] == ("btrfs", "subvolume", "delete")
    assert runner.calls[1][:3] == ("btrfs", "subvolume", "snapshot")


def test_second_heart_rollback_uses_rpm_ostree() -> None:
    runner = RecordingRunner()
    ImageDeployments(run=runner).rollback_to_previous()
    assert runner.calls == [("rpm-ostree", "rollback")]


def test_healthy_batch_is_not_rolled_back(tmp_path: Path) -> None:
    runner = RecordingRunner()
    monitor = HealthMonitor({"audio": lambda: True, "network": lambda: True})
    supervisor = Supervisor(_snapshotter(tmp_path, runner), monitor)

    report = supervisor.guarded_batch([lambda: None])

    assert report.healthy
    assert not any(call[:3] == ("btrfs", "subvolume", "delete") for call in runner.calls)


def test_unhealthy_batch_triggers_rollback_and_notifies(tmp_path: Path) -> None:
    runner = RecordingRunner()
    monitor = HealthMonitor({"audio": lambda: False})
    notified: list[tuple[str, HealthReport]] = []
    supervisor = Supervisor(
        _snapshotter(tmp_path, runner),
        monitor,
        on_rollback=lambda name, report: notified.append((name, report)),
    )

    report = supervisor.guarded_batch([lambda: None])

    assert not report.healthy
    assert [result.name for result in report.failures] == ["audio"]
    assert any(call[:3] == ("btrfs", "subvolume", "delete") for call in runner.calls)
    assert notified and notified[0][0].startswith("pre-batch-")


def test_a_failing_action_does_not_skip_the_health_check(tmp_path: Path) -> None:
    runner = RecordingRunner()
    checked: list[bool] = []

    def check() -> bool:
        checked.append(True)
        return True

    supervisor = Supervisor(
        _snapshotter(tmp_path, runner), HealthMonitor({"probe": check})
    )

    def boom() -> None:
        raise PolicyViolation("denied")

    assert supervisor.guarded_batch([boom]).healthy
    assert checked == [True]


def test_a_raising_check_counts_as_unhealthy() -> None:
    def check() -> bool:
        raise RuntimeError("dbus is gone")

    report = HealthMonitor({"desktop": check}).run()
    assert not report.healthy
    assert report.failures[0].detail == "dbus is gone"


def test_command_check_maps_exit_status_to_health() -> None:
    runner = RecordingRunner()
    assert command_check(runner, ("systemctl", "is-active", "pipewire"))() is True
    runner.returncode = 3
    assert command_check(runner, ("systemctl", "is-active", "pipewire"))() is False


def test_list_snapshots_is_empty_before_any_exist(tmp_path: Path) -> None:
    assert _snapshotter(tmp_path, RecordingRunner()).list_snapshots() == []
