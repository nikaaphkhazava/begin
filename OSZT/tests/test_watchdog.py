from __future__ import annotations

import socket
from pathlib import Path

from oszt import watchdog
from oszt.health import HealthMonitor
from oszt.runner import RecordingRunner
from oszt.snapshots import ImageDeployments
from oszt.supervisor import SupervisorDaemon


def test_notify_is_a_no_op_without_a_systemd_socket() -> None:
    assert watchdog.ready(environ={}) is False


def test_notify_sends_the_state_to_the_socket(tmp_path: Path) -> None:
    address = str(tmp_path / "notify.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(address)
        assert watchdog.watchdog_ping(environ={"NOTIFY_SOCKET": address}) is True
        assert server.recv(64) == b"WATCHDOG=1"


def test_status_messages_are_sent_verbatim(tmp_path: Path) -> None:
    address = str(tmp_path / "notify.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(address)
        watchdog.status("healthy", environ={"NOTIFY_SOCKET": address})
        assert server.recv(64) == b"STATUS=healthy"


def test_notify_reports_failure_when_nothing_is_listening(tmp_path: Path) -> None:
    assert watchdog.notify("READY=1", environ={"NOTIFY_SOCKET": str(tmp_path / "absent")}) is False


def _daemon(healthy: bool, **kwargs: object) -> tuple[SupervisorDaemon, RecordingRunner, list[str]]:
    runner = RecordingRunner()
    announced: list[str] = []
    daemon = SupervisorDaemon(
        monitor=HealthMonitor({"audio": lambda: healthy}),
        deployments=ImageDeployments(run=runner),
        sleep=lambda seconds: None,
        ping=lambda: True,
        announce=lambda message: announced.append(message) is None,
        **kwargs,
    )
    return daemon, runner, announced


def test_a_healthy_poll_announces_health_and_does_not_roll_back() -> None:
    daemon, runner, announced = _daemon(healthy=True)
    assert daemon.poll_once().healthy
    assert announced == ["healthy"]
    assert runner.calls == []


def test_an_unhealthy_poll_names_the_failing_check() -> None:
    daemon, _, announced = _daemon(healthy=False)
    daemon.poll_once()
    assert announced == ["unhealthy: audio"]


def test_rollback_needs_repeated_failures_so_one_flake_cannot_reboot_the_laptop() -> None:
    daemon, runner, _ = _daemon(healthy=False, failures_before_rollback=3)
    daemon.run(iterations=2)
    assert runner.calls == []


def test_rollback_fires_once_the_failure_threshold_is_reached() -> None:
    daemon, runner, _ = _daemon(healthy=False, failures_before_rollback=2)
    assert daemon.run(iterations=5) == 2
    assert runner.calls == [("rpm-ostree", "rollback")]


def test_a_healthy_run_never_rolls_back() -> None:
    daemon, runner, _ = _daemon(healthy=True, failures_before_rollback=1)
    assert daemon.run(iterations=3) == 0
    assert runner.calls == []


def test_the_default_monitor_covers_the_things_that_make_a_laptop_usable() -> None:
    from oszt.health import default_monitor

    names = set(default_monitor(RecordingRunner()).checks)
    assert {"display-manager", "audio", "network", "asus-daemon", "gpu"} <= names
