"""Health checks and the supervisor - the smoke alarm on the outside wall.

A heartbeat only proves the machine still boots. These checks prove it is still
*usable*, which is the failure mode that actually happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from oszt.errors import OSZTError
from oszt.snapshots import Snapshotter

Check = Callable[[], bool]


@dataclass(frozen=True)
class CheckResult:
    name: str
    healthy: bool
    detail: str = ""


@dataclass(frozen=True)
class HealthReport:
    results: tuple[CheckResult, ...]

    @property
    def healthy(self) -> bool:
        return all(result.healthy for result in self.results)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(result for result in self.results if not result.healthy)


@dataclass
class HealthMonitor:
    checks: dict[str, Check] = field(default_factory=dict)

    def add(self, name: str, check: Check) -> None:
        self.checks[name] = check

    def run(self) -> HealthReport:
        results: list[CheckResult] = []
        for name, check in self.checks.items():
            try:
                results.append(CheckResult(name=name, healthy=bool(check())))
            except Exception as error:  # a raising check is a failing check
                results.append(CheckResult(name=name, healthy=False, detail=str(error)))
        return HealthReport(results=tuple(results))


@dataclass
class Supervisor:
    """Runs a batch of agent actions between a snapshot and a health check.

    Lives outside the agent's sandbox: the agent cannot call it, silence it or
    prevent the rollback it decides on.
    """

    snapshotter: Snapshotter
    monitor: HealthMonitor
    on_rollback: Callable[[str, HealthReport], None] | None = None

    def guarded_batch(
        self, actions: Iterable[Callable[[], object]], label: str = "pre-batch"
    ) -> HealthReport:
        """Run ``actions``, then roll back if the system is no longer healthy.

        A failing action does not abort the health check: the machine may have
        been damaged before the failure.
        """
        snapshot = self.snapshotter.create(label)
        for action in actions:
            try:
                action()
            except OSZTError:
                pass  # recorded in the ledger by the broker; health decides the outcome
        report = self.monitor.run()
        if not report.healthy:
            self.snapshotter.rollback(snapshot)
            if self.on_rollback is not None:
                self.on_rollback(snapshot, report)
        return report


def command_check(run, argv: Sequence[str]) -> Check:
    """Turn a command's exit status into a health check."""

    def check() -> bool:
        try:
            return run(argv).returncode == 0
        except OSZTError:
            return False

    return check


def default_monitor(run) -> HealthMonitor:
    """The checks that decide whether the machine is still *usable*.

    Not "does it boot" - a wrecked desktop boots fine. These are the things
    whose absence makes the laptop useless to its owner.
    """
    return HealthMonitor(
        {
            "display-manager": command_check(run, ("systemctl", "is-active", "gdm")),
            "audio": command_check(
                run, ("systemctl", "--user", "is-active", "pipewire")
            ),
            "network": command_check(run, ("nmcli", "-t", "-f", "STATE", "general")),
            "asus-daemon": command_check(run, ("systemctl", "is-active", "asusd")),
            "gpu": command_check(run, ("nvidia-smi", "-L")),
            "disk-space": command_check(
                run, ("findmnt", "--noheadings", "--output", "TARGET", "/")
            ),
        }
    )
