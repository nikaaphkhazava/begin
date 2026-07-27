"""The ledger: an append-only record of every request the agent makes.

Written as JSON lines so a crash mid-write can never corrupt earlier entries.
Denied calls are recorded too - refusals are the most interesting rows.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class AuditRecord:
    timestamp: float
    capability: str
    arguments: Mapping[str, Any]
    outcome: str
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "timestamp": self.timestamp,
                "capability": self.capability,
                "arguments": _jsonable(self.arguments),
                "outcome": self.outcome,
                "detail": self.detail,
            },
            sort_keys=True,
        )


class AuditLog:
    """Appends :class:`AuditRecord` entries to a JSONL file."""

    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        capability: str,
        arguments: Mapping[str, Any],
        outcome: str,
        detail: str = "",
    ) -> AuditRecord:
        record = AuditRecord(
            timestamp=self._clock(),
            capability=capability,
            arguments=dict(arguments),
            outcome=outcome,
            detail=detail,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
