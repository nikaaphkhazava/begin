"""The broker: the only door between the agent and the machine.

The agent has no shell, no filesystem handle and no subprocess access. It can
only name a registered capability and pass keyword arguments. Every call is
policy-checked, rate-limited and written to the audit ledger - including the
ones that are refused.
"""

from __future__ import annotations

import inspect
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from oszt.audit import AuditLog
from oszt.errors import OSZTError, PolicyViolation, QuotaExceeded, UnknownCapability
from oszt.policy import Policy
from oszt.runner import Runner, RecordingRunner, subprocess_runner


@dataclass(frozen=True)
class Context:
    """What a capability is allowed to know about the world."""

    policy: Policy
    run: Runner


Capability = Callable[..., Any]


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    handler: Capability
    description: str

    def schema(self) -> dict[str, Any]:
        """Describe the capability as JSON schema, for the model's tool list.

        Derived from the handler signature so the advertised contract can never
        drift from the code that enforces it.
        """
        signature = inspect.signature(self.handler)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for parameter in list(signature.parameters.values())[1:]:  # skip ctx
            properties[parameter.name] = {"type": _json_type(parameter.annotation)}
            if parameter.default is inspect.Parameter.empty:
                required.append(parameter.name)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class Broker:
    def __init__(
        self,
        policy: Policy,
        audit: AuditLog,
        runner: Runner | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self.audit = audit
        self._runner = runner or (RecordingRunner() if policy.dry_run else subprocess_runner)
        self._clock = clock
        self._registry: dict[str, CapabilitySpec] = {}
        self._recent: deque[float] = deque()

    @property
    def runner(self) -> Runner:
        return self._runner

    def register(self, name: str, handler: Capability, description: str = "") -> None:
        if name in self._registry:
            raise ValueError(f"capability {name!r} is already registered")
        self._registry[name] = CapabilitySpec(
            name=name,
            handler=handler,
            description=description or (inspect.getdoc(handler) or "").split("\n")[0],
        )

    def register_all(self, specs: Iterable[tuple[str, Capability]]) -> None:
        for name, handler in specs:
            self.register(name, handler)

    def tool_list(self) -> list[dict[str, Any]]:
        """The complete set of actions the agent can see.

        Capabilities the policy forbids are not advertised at all, so a denied
        action is invisible rather than merely rejected.
        """
        return [
            spec.schema()
            for name, spec in sorted(self._registry.items())
            if name in self.policy.allowed_capabilities
        ]

    def call(self, name: str, **arguments: Any) -> Any:
        try:
            spec = self._registry.get(name)
            if spec is None:
                raise UnknownCapability(f"capability {name!r} is not registered")
            self.policy.check_capability(name)
            self._check_rate_limit()
            result = spec.handler(Context(policy=self.policy, run=self._runner), **arguments)
        except OSZTError as error:
            self.audit.record(name, arguments, _outcome_for(error), str(error))
            raise
        except TypeError as error:
            self.audit.record(name, arguments, "invalid-arguments", str(error))
            raise PolicyViolation(f"invalid arguments for {name!r}: {error}") from error

        self.audit.record(name, arguments, "allowed", _summarise(result))
        return result

    def _check_rate_limit(self) -> None:
        now = self._clock()
        while self._recent and now - self._recent[0] >= 60.0:
            self._recent.popleft()
        if len(self._recent) >= self.policy.max_calls_per_minute:
            raise QuotaExceeded(
                f"rate limit of {self.policy.max_calls_per_minute} calls per minute reached"
            )
        self._recent.append(now)


_JSON_TYPES = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
}


def _json_type(annotation: Any) -> str:
    name = getattr(annotation, "__name__", str(annotation))
    return _JSON_TYPES.get(name, "string")


def _outcome_for(error: OSZTError) -> str:
    return {
        UnknownCapability: "unknown",
        PolicyViolation: "denied",
        QuotaExceeded: "throttled",
    }.get(type(error), "failed")


def _summarise(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, (str, int, float, bool)):
        return str(result)
    if isinstance(result, Mapping):
        return ",".join(sorted(str(key) for key in result))
    if isinstance(result, (list, tuple)):
        return f"{len(result)} items"
    return type(result).__name__
