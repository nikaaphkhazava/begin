"""Long term memory: the butler's notebook.

SQLite, because P1 memory needs to be inspectable with `sqlite3` and survive a
rollback without a service to restore. The vector store arrives in P4 for
similarity search; facts and action history do not need embeddings.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fact',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability TEXT NOT NULL,
    arguments TEXT NOT NULL,
    outcome TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    kind: str
    updated_at: float


@dataclass(frozen=True)
class Action:
    capability: str
    arguments: str
    outcome: str
    created_at: float


class MemoryStore:
    """Durable key/value facts plus an action history."""

    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._connection = sqlite3.connect(str(self.path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def remember(self, key: str, value: str, kind: str = "fact") -> Fact:
        """Store or replace a fact."""
        fact = Fact(key=key, value=value, kind=kind, updated_at=self._clock())
        self._connection.execute(
            "INSERT INTO facts (key, value, kind, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, kind=excluded.kind, "
            "updated_at=excluded.updated_at",
            (fact.key, fact.value, fact.kind, fact.updated_at),
        )
        self._connection.commit()
        return fact

    def recall(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM facts WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row["value"])

    def forget(self, key: str) -> bool:
        cursor = self._connection.execute("DELETE FROM facts WHERE key = ?", (key,))
        self._connection.commit()
        return cursor.rowcount > 0

    def search(self, term: str, limit: int = 10) -> list[Fact]:
        """Substring search over keys and values, newest first."""
        pattern = f"%{term}%"
        rows = self._connection.execute(
            "SELECT key, value, kind, updated_at FROM facts "
            "WHERE key LIKE ? OR value LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall()
        return [Fact(**dict(row)) for row in rows]

    def log_action(
        self, capability: str, arguments: Mapping[str, Any], outcome: str
    ) -> Action:
        action = Action(
            capability=capability,
            arguments=repr(dict(arguments)),
            outcome=outcome,
            created_at=self._clock(),
        )
        self._connection.execute(
            "INSERT INTO actions (capability, arguments, outcome, created_at) "
            "VALUES (?, ?, ?, ?)",
            (action.capability, action.arguments, action.outcome, action.created_at),
        )
        self._connection.commit()
        return action

    def recent_actions(self, limit: int = 20) -> list[Action]:
        rows = self._connection.execute(
            "SELECT capability, arguments, outcome, created_at FROM actions "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Action(**dict(row)) for row in rows]
