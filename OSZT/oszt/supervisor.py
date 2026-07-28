"""The supervisor daemon: the smoke alarm bolted to the outside wall.

Runs as its own systemd unit, as root, with no path back to the agent. It polls
the health checks, pings the systemd watchdog while things are fine, and asks
for the other heart when they are not.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from oszt import watchdog
from oszt.health import HealthMonitor, HealthReport
from oszt.snapshots import ImageDeployments


@dataclass
class SupervisorDaemon:
    monitor: HealthMonitor
    deployments: ImageDeployments
    failures_before_rollback: int = 3
    interval_seconds: float = 15.0
    sleep: Callable[[float], None] = time.sleep
    ping: Callable[[], bool] = watchdog.watchdog_ping
    announce: Callable[[str], bool] = watchdog.status

    def poll_once(self) -> HealthReport:
        report = self.monitor.run()
        if report.healthy:
            self.ping()
            self.announce("healthy")
        else:
            self.announce(
                "unhealthy: " + ",".join(result.name for result in report.failures)
            )
        return report

    def run(self, iterations: int | None = None) -> int:
        """Poll until ``iterations`` is exhausted, or forever when it is None.

        Returns the number of consecutive failures at exit. Rollback fires only
        after repeated failures, so one flaky probe cannot reboot the laptop.
        """
        watchdog.ready()
        consecutive = 0
        remaining = iterations
        while remaining is None or remaining > 0:
            if self.poll_once().healthy:
                consecutive = 0
            else:
                consecutive += 1
                if consecutive >= self.failures_before_rollback:
                    self.deployments.rollback_to_previous()
                    return consecutive
            if remaining is not None:
                remaining -= 1
                if remaining == 0:
                    break
            self.sleep(self.interval_seconds)
        return consecutive
