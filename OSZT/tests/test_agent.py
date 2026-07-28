from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from oszt import build_broker
from oszt.agent import HermesAgent, OllamaClient, VisionClient
from oszt.agent.hermes import AgentError
from oszt.broker import Broker
from oszt.memory import MemoryStore
from oszt.policy import Policy
from oszt.runner import RecordingRunner

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AEBmwHqAAAAAElFTkSuQmCC"
)


def _FakeVision() -> VisionClient:
    """A vision model that always sees the same thing."""
    return VisionClient(
        transport=lambda url, payload: {"response": "a terminal full of red output"}
    )


class FakeCapture(RecordingRunner):
    """Stands in for grim."""

    def __call__(self, argv):  # type: ignore[no-untyped-def]
        Path(argv[-1]).write_bytes(PNG)
        return super().__call__(argv)


@pytest.fixture
def seeing_broker(policy: Policy, sandbox: Path, tmp_path: Path) -> Broker:
    """A broker whose policy lets the agent take screenshots."""
    seeing = Policy.from_dict(
        {
            "allowed_capabilities": sorted(
                {*policy.allowed_capabilities, "capture_screen", "read_screenshot_base64"}
            ),
            "allowed_apps": {name: list(argv) for name, argv in policy.allowed_apps.items()},
            "file_roots": [str(sandbox)],
            "write_roots": [str(sandbox)],
            "protected_paths": [],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": False,
        }
    )
    return build_broker(seeing, tmp_path / "seeing-audit.jsonl", runner=FakeCapture())


class FakeModel:
    """Replays scripted assistant messages and records what it was sent."""

    def __init__(self, *messages: Mapping[str, Any]) -> None:
        self._messages = list(messages)
        self.payloads: list[Mapping[str, Any]] = []

    def __call__(self, url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if not self._messages:
            return {"message": {"role": "assistant", "content": "done"}}
        return {"message": self._messages.pop(0)}


def _tool_call(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": dict(arguments)}}],
    }


def _agent(broker: Broker, model: FakeModel, **kwargs: Any) -> HermesAgent:
    return HermesAgent(broker=broker, client=OllamaClient(transport=model), **kwargs)


def test_agent_executes_a_tool_call_then_reports(
    broker: Broker, runner: RecordingRunner
) -> None:
    model = FakeModel(
        _tool_call("set_volume", {"percent": 30}),
        {"role": "assistant", "content": "volume set to 30%"},
    )
    run = _agent(broker, model).run("turn the volume down")

    assert runner.calls == [("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.30")]
    assert [step.capability for step in run.steps] == ["set_volume"]
    assert run.steps[0].allowed
    assert run.reply == "volume set to 30%"


def test_the_model_only_ever_sees_allowed_capabilities(broker: Broker) -> None:
    model = FakeModel({"role": "assistant", "content": "nothing to do"})
    _agent(broker, model).run("hello")

    advertised = {
        tool["function"]["name"] for tool in model.payloads[0]["tools"]
    }
    assert advertised == set(broker.policy.allowed_capabilities)
    assert "set_gpu_mode" not in advertised


def test_a_refusal_is_fed_back_as_a_tool_result_not_raised(broker: Broker) -> None:
    model = FakeModel(
        _tool_call("open_app", {"app": "gparted"}),
        {"role": "assistant", "content": "that application is not permitted"},
    )
    run = _agent(broker, model).run("open gparted")

    assert run.steps[0].allowed is False
    assert "not permitted" in run.steps[0].detail
    tool_messages = [
        message
        for message in model.payloads[-1]["messages"]
        if message.get("role") == "tool"
    ]
    assert tool_messages[0]["content"].startswith("refused: ")


def test_an_unknown_capability_does_not_crash_the_loop(broker: Broker) -> None:
    model = FakeModel(
        _tool_call("format_disk", {"device": "/dev/nvme0n1"}),
        {"role": "assistant", "content": "I cannot do that"},
    )
    run = _agent(broker, model).run("wipe the disk")
    assert run.steps[0].allowed is False
    assert run.reply == "I cannot do that"


def test_string_encoded_arguments_are_parsed(broker: Broker, runner: RecordingRunner) -> None:
    model = FakeModel(
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "set_volume", "arguments": json.dumps({"percent": 10})}}
            ],
        },
        {"role": "assistant", "content": "done"},
    )
    _agent(broker, model).run("quieter")
    assert runner.calls == [("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.10")]


def test_unparsable_arguments_become_an_argument_refusal(broker: Broker) -> None:
    model = FakeModel(
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "set_volume", "arguments": "{oops"}}],
        },
        {"role": "assistant", "content": "sorry"},
    )
    run = _agent(broker, model).run("quieter")
    assert run.steps[0].allowed is False


def test_the_step_budget_bounds_a_looping_model(broker: Broker) -> None:
    model = FakeModel(*[_tool_call("list_files", {}) for _ in range(20)])
    run = _agent(broker, model, max_steps=3).run("look around forever")

    assert run.exhausted is True
    assert len(run.steps) == 3


def test_steps_are_written_to_memory(broker: Broker, tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    model = FakeModel(
        _tool_call("open_app", {"app": "firefox"}),
        {"role": "assistant", "content": "opened"},
    )
    _agent(broker, model, memory=memory).run("open firefox")

    actions = memory.recent_actions()
    assert [(action.capability, action.outcome) for action in actions] == [
        ("open_app", "allowed")
    ]


def test_stored_memories_are_briefed_to_the_model(broker: Broker, tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    memory.remember("laptop", "ASUS TUF F15, RTX 3050")
    model = FakeModel({"role": "assistant", "content": "noted"})

    _agent(broker, model, memory=memory).run("what am I running on?")

    briefing = model.payloads[0]["messages"][1]["content"]
    assert "ASUS TUF F15, RTX 3050" in briefing


def test_agent_without_memory_says_so(broker: Broker) -> None:
    model = FakeModel({"role": "assistant", "content": "noted"})
    _agent(broker, model).run("hello")
    assert model.payloads[0]["messages"][1]["content"] == "You have no stored memories."


def test_a_malformed_model_response_is_an_agent_error(broker: Broker) -> None:
    def broken(url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {"error": "model not found"}

    agent = HermesAgent(broker=broker, client=OllamaClient(transport=broken))
    with pytest.raises(AgentError):
        agent.run("anything")


def test_the_client_posts_to_the_ollama_chat_endpoint(broker: Broker) -> None:
    seen: list[str] = []

    def transport(url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        seen.append(url)
        return {"message": {"role": "assistant", "content": "hi"}}

    HermesAgent(
        broker=broker,
        client=OllamaClient(transport=transport, base_url="http://127.0.0.1:11434"),
    ).run("hi")
    assert seen == ["http://127.0.0.1:11434/api/chat"]


def test_tools_are_advertised_with_json_schema_parameters(broker: Broker) -> None:
    model = FakeModel({"role": "assistant", "content": "hi"})
    _agent(broker, model).run("hi")

    tools = {
        tool["function"]["name"]: tool["function"] for tool in model.payloads[0]["tools"]
    }
    parameters = tools["read_text"]["parameters"]
    assert parameters["type"] == "object"
    assert parameters["properties"]["max_bytes"] == {"type": "integer"}
    assert parameters["required"] == ["path"]


def test_the_screen_tool_is_hidden_unless_the_policy_allows_capture(
    broker: Broker,
) -> None:
    """The base policy has no capture_screen, so sight must not be advertised."""
    model = FakeModel({"role": "assistant", "content": "hi"})
    _agent(broker, model, vision=_FakeVision()).run("what is on my screen?")
    advertised = {tool["function"]["name"] for tool in model.payloads[0]["tools"]}
    assert "look_at_screen" not in advertised


def test_the_screen_tool_appears_when_capture_is_allowed(
    seeing_broker: Broker,
) -> None:
    model = FakeModel({"role": "assistant", "content": "hi"})
    _agent(seeing_broker, model, vision=_FakeVision()).run("hi")
    advertised = {tool["function"]["name"] for tool in model.payloads[0]["tools"]}
    assert "look_at_screen" in advertised


def test_without_a_vision_client_there_is_no_screen_tool(seeing_broker: Broker) -> None:
    model = FakeModel({"role": "assistant", "content": "hi"})
    _agent(seeing_broker, model).run("hi")
    advertised = {tool["function"]["name"] for tool in model.payloads[0]["tools"]}
    assert "look_at_screen" not in advertised


def test_the_agent_can_look_at_the_screen_and_gets_words_back(
    seeing_broker: Broker,
) -> None:
    model = FakeModel(
        _tool_call("look_at_screen", {"question": "what is failing?"}),
        {"role": "assistant", "content": "your test run is red"},
    )
    run = _agent(seeing_broker, model, vision=_FakeVision()).run("why is it broken?")

    assert run.steps[0].capability == "look_at_screen"
    assert run.steps[0].allowed is True
    tool_messages = [
        message for message in model.payloads[-1]["messages"] if message.get("role") == "tool"
    ]
    assert "a terminal" in tool_messages[0]["content"]
