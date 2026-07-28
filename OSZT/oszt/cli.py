"""Command line front end, so every phase can be exercised by a human.

    python -m oszt doctor
    python -m oszt --policy policy.tuf-f15.json tools
    python -m oszt --policy policy.tuf-f15.json call open_app app=firefox
    python -m oszt --policy policy.tuf-f15.json health
    python -m oszt --policy policy.tuf-f15.json agent "put the laptop in quiet mode"
    python -m oszt --policy policy.tuf-f15.json see
    python -m oszt --policy policy.tuf-f15.json trash
    python -m oszt --policy policy.tuf-f15.json clean --all
    python -m oszt --policy policy.tuf-f15.json memory remember gpu "RTX 3050 4GB"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oszt import build_broker
from oszt.agent import HermesAgent, OllamaClient, VisionClient, look_at_screen
from oszt.agent.transport import AgentError
from oszt.broker import Broker
from oszt.errors import OSZTError
from oszt.health import default_monitor
from oszt.memory import MemoryStore
from oszt.policy import Policy
from oszt.preflight import check, check_models, report, report_models

DEFAULT_MODEL = "qwen2.5:3b"
# Small enough to load beside nothing else on a 4GB card.
DEFAULT_VISION_MODEL = "moondream"


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

    subparsers.add_parser(
        "doctor", help="report which system tools and local models are missing"
    )
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
    agent.add_argument(
        "--see",
        action="store_true",
        help="let the agent look at the screen through a vision model",
    )
    agent.add_argument("--vision-model", default=DEFAULT_VISION_MODEL)

    see = subparsers.add_parser("see", help="describe what is on the screen right now")
    see.add_argument("question", nargs="?", default=None)
    see.add_argument("--vision-model", default=DEFAULT_VISION_MODEL)
    see.add_argument("--ollama-url", default="http://127.0.0.1:11434")

    subparsers.add_parser("trash", help="list deletions that can still be undone")

    apps = subparsers.add_parser("apps", help="list, install or remove applications")
    apps.add_argument("action", nargs="?", choices=["list", "install", "remove"], default="list")
    apps.add_argument("app_id", nargs="?", default=None)

    clean = subparsers.add_parser("clean", help="run cache cleanup jobs")
    clean.add_argument("cleaner", nargs="?", default=None)
    clean.add_argument("--all", action="store_true", help="run every allowed cleaner")

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
        print("\nmodels")
        print(report_models(check_models()))
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

    if args.command == "see":
        return _see_command(args, broker)

    if args.command == "trash":
        return _trash_command(broker)

    if args.command == "clean":
        return _clean_command(args, broker)

    if args.command == "apps":
        return _apps_command(args, broker)

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
        vision=(
            VisionClient(model=args.vision_model, base_url=args.ollama_url)
            if args.see
            else None
        ),
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


def _see_command(args: argparse.Namespace, broker: Broker) -> int:
    vision = VisionClient(model=args.vision_model, base_url=args.ollama_url)
    kwargs = {"question": args.question} if args.question else {}
    try:
        looked = look_at_screen(broker, vision, **kwargs)
    except OSZTError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    except AgentError as error:
        print(f"vision model unavailable: {error}", file=sys.stderr)
        return 1
    print(f"{looked['path']}\n{looked['description']}")
    return 0


def _trash_command(broker: Broker) -> int:
    try:
        entries = broker.call("list_trash")
    except OSZTError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    if not entries:
        print("the trash is empty: nothing has been deleted")
        return 0
    for entry in entries:
        print(f"{entry['trash_entry']}  {entry['original_path']}  {entry['size_bytes']} bytes")
    print("\nundo one with: oszt --policy ... call restore_path trash_entry=<name>")
    return 0


def _clean_command(args: argparse.Namespace, broker: Broker) -> int:
    if not args.all and args.cleaner is None:
        print(json.dumps(broker.call("list_cleaners"), indent=2))
        return 0
    names = (
        [str(job["name"]) for job in broker.call("list_cleaners")]
        if args.all
        else [args.cleaner]
    )
    failed = False
    for name in names:
        try:
            print(json.dumps(broker.call("clean_caches", cleaner=name), default=str))
        except OSZTError as error:
            print(f"refused: {name}: {error}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def _apps_command(args: argparse.Namespace, broker: Broker) -> int:
    """List the installable applications, or install/remove one of them."""
    if args.action == "list":
        try:
            print(json.dumps(broker.call("list_installable_apps"), indent=2))
        except OSZTError as error:
            print(f"refused: {error}", file=sys.stderr)
            return 1
        return 0

    if args.app_id is None:
        print(f"apps {args.action} needs an application id", file=sys.stderr)
        return 1
    capability = "install_app" if args.action == "install" else "uninstall_app"
    try:
        print(json.dumps(broker.call(capability, app_id=args.app_id), default=str, indent=2))
    except OSZTError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


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
