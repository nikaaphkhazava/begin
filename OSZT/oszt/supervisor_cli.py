"""Entry point for ``oszt-supervisor``, the unit systemd keeps alive.

Separate from :mod:`oszt.cli` because this process runs as root and must not
import, or be importable by, anything the agent can reach.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from oszt.health import default_monitor
from oszt.runner import subprocess_runner
from oszt.snapshots import ImageDeployments
from oszt.supervisor import SupervisorDaemon


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oszt-supervisor")
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--failures-before-rollback", type=int, default=3)
    parser.add_argument(
        "--once", action="store_true", help="run a single poll and exit (for testing)"
    )
    parser.add_argument("--snapshot-dir", type=Path, default=Path("/var/lib/oszt/snapshots"))
    args = parser.parse_args(argv)

    daemon = SupervisorDaemon(
        monitor=default_monitor(subprocess_runner),
        deployments=ImageDeployments(run=subprocess_runner),
        failures_before_rollback=args.failures_before_rollback,
        interval_seconds=args.interval,
    )
    if args.once:
        return 0 if daemon.poll_once().healthy else 1
    daemon.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
