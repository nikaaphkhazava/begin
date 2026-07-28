"""Command line front end, so every phase can be exercised by a human.

    python -m oszt doctor
    python -m oszt --policy policy.tuf-f15.json tools
    python -m oszt --policy policy.tuf-f15.json call open_app app=firefox
    python -m oszt --policy policy.tuf-f15.json health
    python -m oszt --policy policy.tuf-f15.json agent "put the laptop in quiet mode"
    python -m oszt --policy policy.tuf-f15.json memory remember gpu "RTX 3050 4GB"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oszt import build_broker
from oszt.agent import HermesAgent, OllamaClient
from oszt.agent.hermes import AgentError
from oszt.broker import Broker
from oszt.errors import OSZTError
from oszt.health import default_monitor
from oszt.memory import MemoryStore
from oszt.policy import Policy
from oszt.preflight import check, report

DEFAULT_MODEL = "qwen2.5:3b"


def _parse_argument(pair: str) -> tuple[str, object]:
    if "=" not in pair:
        raise SystemExit(f"arguments must be key=value, got {pair!r}")
    key, raw = pair.split("=", 1)
    try:
        return key, json.loads(raw)
    except json.JSONDecodeError:
        return key, raw


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oszt")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--audit", type=Path, default=Path("audit.jsonl"))
    parser.add_argument("--memory", type=Path, default=Path("memory.sqlite3"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="report which system tools are missing")
    subparsers.add_parser("tools", help="print the capabilities the agent can see")
    subparsers.add_parser("health", help="run the health checks once")

    call = subparsers.add_parser("call", help="invoke a single capability")
    call.add_argument("capability")
    call.add_argument("arguments", nargs="*")

    agent = subparsers.add_parser("agent", help="give the Hermes agent a goal")
    agent.add_argument("goal")
    agent.add_argument("--model", default=DEFAULT_MODEL)
    agent.add_argument("--max-steps", type=int, default=8)
    agent.add_argument("--ollama-url", default="http://127.0.0.1:11434")

    memory = subparsers.add_parser("memory", help="inspect or edit long term memory")
    memory_actions = memory.add_subparsers(dest="memory_command", required=True)
    remember = memory_actions.add_parser("remember")
    remember.add_argument("key")
    remember.add_argument("value")
    memory_actions.add_parser("list")
    forget = memory_actions.add_parser("forget")
    forget.add_argument("key")
    memory_actions.add_parser("actions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "doctor":
        print(report(check()))
        return 0

    if args.command == "memory":
        return _memory_command(args)

    if args.policy is None:
        print("--policy is required for this command", file=sys.stderr)
        return 2

    broker = build_broker(Policy.load(args.policy), args.audit)

    if args.command == "tools":
        print(json.dumps(broker.tool_list(), indent=2))
        return 0

    if args.command == "health":
        health = default_monitor(broker.runner).run()
        for result in health.results:
            print(f"{'ok  ' if result.healthy else 'FAIL'} {result.name} {result.detail}")
        return 0 if health.healthy else 1

    if args.command == "agent":
        return _agent_command(args, broker)

    arguments = dict(_parse_argument(pair) for pair in args.arguments)
    try:
        print(json.dumps(broker.call(args.capability, **arguments), default=str, indent=2))
    except OSZTError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


def _agent_command(args: argparse.Namespace, broker: Broker) -> int:
    agent = HermesAgent(
        broker=broker,
        client=OllamaClient(model=args.model, base_url=args.ollama_url),
        memory=MemoryStore(args.memory),
        max_steps=args.max_steps,
    )
    try:
        run = agent.run(args.goal)
    except AgentError as error:
        print(f"model unavailable: {error}", file=sys.stderr)
        return 1

    for step in run.steps:
        print(f"{'ok      ' if step.allowed else 'refused '}{step.capability} {step.detail}")
    print(run.reply)
    return 1 if run.exhausted else 0


def _memory_command(args: argparse.Namespace) -> int:
    store = MemoryStore(args.memory)
    if args.memory_command == "remember":
        store.remember(args.key, args.value)
    elif args.memory_command == "forget":
        if not store.forget(args.key):
            print(f"no memory named {args.key!r}", file=sys.stderr)
            return 1
    elif args.memory_command == "actions":
        for action in store.recent_actions():
            print(f"{action.outcome:<9}{action.capability} {action.arguments}")
    else:
        for fact in store.search(""):
            print(f"{fact.key}: {fact.value}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
