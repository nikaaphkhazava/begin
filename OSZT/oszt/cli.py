"""Command line front end, so P1 can be exercised by a human before any model.

    python -m oszt --policy policy.json tools
    python -m oszt --policy policy.json call open_app app=firefox
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oszt import build_broker
from oszt.errors import OSZTError
from oszt.policy import Policy


def _parse_argument(pair: str) -> tuple[str, object]:
    if "=" not in pair:
        raise SystemExit(f"arguments must be key=value, got {pair!r}")
    key, raw = pair.split("=", 1)
    try:
        return key, json.loads(raw)
    except json.JSONDecodeError:
        return key, raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oszt")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=Path("audit.jsonl"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("tools", help="print the capabilities the agent can see")
    call = subparsers.add_parser("call", help="invoke a single capability")
    call.add_argument("capability")
    call.add_argument("arguments", nargs="*")

    args = parser.parse_args(argv)
    broker = build_broker(Policy.load(args.policy), args.audit)

    if args.command == "tools":
        print(json.dumps(broker.tool_list(), indent=2))
        return 0

    arguments = dict(_parse_argument(pair) for pair in args.arguments)
    try:
        print(json.dumps(broker.call(args.capability, **arguments), default=str, indent=2))
    except OSZTError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
