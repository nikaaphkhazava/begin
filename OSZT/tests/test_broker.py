from __future__ import annotations

from pathlib import Path

import pytest

from oszt import build_broker
from oszt.audit import AuditLog
from oszt.broker import Broker, Context
from oszt.errors import PolicyViolation, QuotaExceeded, UnknownCapability
from oszt.policy import Policy
from oszt.runner import RecordingRunner


def test_unknown_capability_is_refused_and_logged(broker: Broker) -> None:
    with pytest.raises(UnknownCapability):
        broker.call("format_disk")
    entry = broker.audit.entries()[-1]
    assert entry["capability"] == "format_disk"
    assert entry["outcome"] == "unknown"


def test_registered_but_unlisted_capability_is_denied(
    tmp_path: Path, sandbox: Path, runner: RecordingRunner
) -> None:
    policy = Policy.from_dict(
        {"allowed_capabilities": ["list_files"], "file_roots": [str(sandbox)]}
    )
    broker = build_broker(policy, tmp_path / "audit.jsonl", runner=runner)
    with pytest.raises(PolicyViolation):
        broker.call("set_volume", percent=50)
    assert broker.audit.entries()[-1]["outcome"] == "denied"
    assert runner.calls == []


def test_tool_list_hides_capabilities_the_policy_forbids(
    tmp_path: Path, sandbox: Path
) -> None:
    policy = Policy.from_dict(
        {"allowed_capabilities": ["list_files"], "file_roots": [str(sandbox)]}
    )
    broker = build_broker(policy, tmp_path / "audit.jsonl")
    assert [tool["name"] for tool in broker.tool_list()] == ["list_files"]


def test_tool_list_exposes_parameters_without_the_context(broker: Broker) -> None:
    tools = {tool["name"]: tool for tool in broker.tool_list()}
    assert tools["read_text"]["parameters"] == ["path", "max_bytes"]
    assert "ctx" not in tools["read_text"]["parameters"]


def test_successful_call_is_logged_as_allowed(broker: Broker) -> None:
    broker.call("list_files")
    entry = broker.audit.entries()[-1]
    assert entry["capability"] == "list_files"
    assert entry["outcome"] == "allowed"


def test_rate_limit_throttles_after_the_configured_budget(broker: Broker) -> None:
    for _ in range(broker.policy.max_calls_per_minute):
        broker.call("list_files")
    with pytest.raises(QuotaExceeded):
        broker.call("list_files")
    assert broker.audit.entries()[-1]["outcome"] == "throttled"


def test_rate_limit_window_expires(tmp_path: Path, sandbox: Path) -> None:
    clock = iter([0.0, 61.0])
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["list_files"],
            "file_roots": [str(sandbox)],
            "max_calls_per_minute": 1,
        }
    )
    broker = Broker(
        policy=policy,
        audit=AuditLog(tmp_path / "audit.jsonl"),
        runner=RecordingRunner(),
        clock=lambda: next(clock),
    )
    broker.register("list_files", lambda ctx: [])
    broker.call("list_files")
    broker.call("list_files")  # a minute later, so the budget has reset


def test_bad_arguments_surface_as_policy_violations(broker: Broker) -> None:
    with pytest.raises(PolicyViolation):
        broker.call("open_app", application="firefox")
    assert broker.audit.entries()[-1]["outcome"] == "invalid-arguments"


def test_capabilities_cannot_be_registered_twice(broker: Broker) -> None:
    with pytest.raises(ValueError):
        broker.register("open_app", lambda ctx: None)


def test_dry_run_policy_never_executes_commands(tmp_path: Path) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["open_app"],
            "allowed_apps": {"firefox": ["flatpak", "run", "org.mozilla.firefox"]},
            "dry_run": True,
        }
    )
    broker = build_broker(policy, tmp_path / "audit.jsonl")
    broker.call("open_app", app="firefox")
    assert isinstance(broker.runner, RecordingRunner)
    assert broker.runner.calls == [("flatpak", "run", "org.mozilla.firefox")]


def test_capability_receives_policy_and_runner(broker: Broker) -> None:
    seen: list[Context] = []

    broker.register("probe", lambda ctx: seen.append(ctx))
    broker.policy = Policy.from_dict(
        {
            "allowed_capabilities": ["probe"],
            "file_roots": [str(broker.policy.file_roots[0])],
        }
    )
    broker.call("probe")
    assert seen[0].policy is broker.policy
    assert seen[0].run is broker.runner
