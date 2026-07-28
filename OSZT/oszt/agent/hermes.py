"""Hermes: the mind.

A bounded loop around a local Ollama model. The model receives exactly one
thing - the broker's tool list - and can do exactly one thing: request a tool
call. Refusals are fed back to it as tool results rather than raised, so hitting
the policy is a normal, recoverable observation instead of a crash. The loop is
step-bounded, so a confused model burns steps rather than the machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from oszt.agent.transport import AgentError, Transport, http_transport
from oszt.agent.vision import VisionClient, look_at_screen
from oszt.broker import Broker
from oszt.errors import OSZTError
from oszt.memory import MemoryStore

__all__ = [
    "AgentError",
    "AgentRun",
    "AgentStep",
    "HermesAgent",
    "OllamaClient",
    "http_transport",
]

LOOK_TOOL: dict[str, Any] = {
    "name": "look_at_screen",
    "description": (
        "Look at the current screen and get a written description of it. Use it "
        "when you need to know what the user is doing or see an error message."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "what to look for on the screen",
            }
        },
        "required": [],
    },
}

SYSTEM_PROMPT = """You are Hermes, the operator of this computer.
You cannot run shell commands and you have no filesystem access.
You act only by calling the provided tools.
If a tool call is refused, the refusal is final: do not retry it and do not look
for a way around it. Explain the limit to the user instead.
When the goal is met, reply with a short plain-language summary and no tool call.
"""


@dataclass
class OllamaClient:
    """Minimal Ollama chat client with tool calling."""

    model: str = "qwen2.5:3b"
    base_url: str = "http://127.0.0.1:11434"
    transport: Transport = http_transport
    options: Mapping[str, Any] = field(default_factory=lambda: {"temperature": 0.0})

    def chat(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "tools": [{"type": "function", "function": dict(tool)} for tool in tools],
            "stream": False,
            "options": dict(self.options),
        }
        response = self.transport(f"{self.base_url}/api/chat", payload)
        message = response.get("message")
        if not isinstance(message, dict):
            raise AgentError(f"malformed response from the model: {response!r}")
        return message


@dataclass(frozen=True)
class AgentStep:
    capability: str
    arguments: Mapping[str, Any]
    allowed: bool
    detail: str


@dataclass(frozen=True)
class AgentRun:
    goal: str
    steps: tuple[AgentStep, ...]
    reply: str
    exhausted: bool = False


@dataclass
class HermesAgent:
    broker: Broker
    client: OllamaClient
    memory: MemoryStore | None = None
    max_steps: int = 8
    # Sight is optional and composite: capture plus describe, both audited. It is
    # offered only when a vision client exists and the policy allows capture.
    vision: VisionClient | None = None

    def run(self, goal: str) -> AgentRun:
        tools = self._tools()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": self._memory_briefing()},
            {"role": "user", "content": goal},
        ]
        steps: list[AgentStep] = []

        for _ in range(self.max_steps):
            message = self.client.chat(messages, tools)
            messages.append(message)
            calls = message.get("tool_calls") or []
            if not calls:
                return AgentRun(
                    goal=goal, steps=tuple(steps), reply=str(message.get("content", ""))
                )
            for call in calls:
                step = self._execute(call)
                steps.append(step)
                messages.append(
                    {
                        "role": "tool",
                        "name": step.capability,
                        "content": ("ok: " if step.allowed else "refused: ") + step.detail,
                    }
                )

        return AgentRun(
            goal=goal,
            steps=tuple(steps),
            reply="step budget exhausted before the goal was met",
            exhausted=True,
        )

    def _tools(self) -> list[dict[str, Any]]:
        tools = self.broker.tool_list()
        if self.vision is not None and any(
            tool["name"] == "capture_screen" for tool in tools
        ):
            tools.append(LOOK_TOOL)
        return tools

    def _execute(self, call: Mapping[str, Any]) -> AgentStep:
        function = call.get("function") or {}
        name = str(function.get("name", ""))
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}

        try:
            if name == "look_at_screen" and self.vision is not None:
                result: Any = look_at_screen(self.broker, self.vision, **arguments)
            else:
                result = self.broker.call(name, **arguments)
        except OSZTError as error:
            step = AgentStep(name, arguments, allowed=False, detail=str(error))
        else:
            step = AgentStep(
                name, arguments, allowed=True, detail=json.dumps(result, default=str)
            )

        if self.memory is not None:
            self.memory.log_action(
                name, arguments, "allowed" if step.allowed else "refused"
            )
        return step

    def _memory_briefing(self) -> str:
        if self.memory is None:
            return "You have no stored memories."
        facts = self.memory.search("", limit=20)
        if not facts:
            return "You have no stored memories."
        lines = "\n".join(f"- {fact.key}: {fact.value}" for fact in facts)
        return f"Things you remember about this machine and user:\n{lines}"
