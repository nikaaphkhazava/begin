"""The weekly cleanup, run by systemd rather than by the agent.

Root-owned, so it can vacuum the journal and the dnf cache, and it is the only
thing allowed to purge old trash - the operation that actually destroys data. It
never asks a model anything: it runs a fixed list of jobs.

    oszt-janitor --policy /etc/oszt/policy.json --purge-after-days 30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oszt import build_broker
from oszt.capabilities.janitor import CLEANERS
from oszt.errors import OSZTError
from oszt.policy import Policy
from oszt.trash import Trash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oszt-janitor")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=Path("/var/log/oszt/audit.jsonl"))
    parser.add_argument(
        "--purge-after-days",
        type=float,
        default=30.0,
        help="permanently delete trash older than this (0 disables)",
    )
    args = parser.parse_args(argv)

    policy = Policy.load(args.policy)
    broker = build_broker(policy, args.audit)

    failures = 0
    for name in sorted(policy.allowed_cleaners):
        if name not in CLEANERS:
            print(f"unknown cleaner in policy: {name}", file=sys.stderr)
            failures += 1
            continue
        try:
            print(json.dumps(broker.call("clean_caches", cleaner=name), default=str))
        except OSZTError as error:
            print(f"{name}: {error}", file=sys.stderr)
            failures += 1

    if args.purge_after_days:
        purged = Trash(policy.trash_dir).purge(args.purge_after_days)
        print(json.dumps({"purged_trash_entries": len(purged)}))

    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
