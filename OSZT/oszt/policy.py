"""The policy: the printed menu the agent is allowed to order from.

The policy is data, not code. It is loaded from JSON and owned by the human, so
widening what the agent may do is always a reviewable diff.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from oszt.errors import PolicyViolation


@dataclass(frozen=True)
class Policy:
    """An allowlist of capabilities, applications and filesystem roots."""

    allowed_capabilities: frozenset[str] = frozenset()
    allowed_apps: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    file_roots: tuple[Path, ...] = ()
    max_calls_per_minute: int = 60
    dry_run: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Policy":
        apps: dict[str, tuple[str, ...]] = {}
        for name, argv in dict(data.get("allowed_apps", {})).items():
            if not isinstance(argv, Sequence) or isinstance(argv, str) or not argv:
                raise PolicyViolation(
                    f"allowed_apps[{name!r}] must be a non-empty list of command arguments"
                )
            apps[name] = tuple(str(part) for part in argv)

        roots = tuple(
            Path(root).expanduser().resolve() for root in data.get("file_roots", [])
        )
        return cls(
            allowed_capabilities=frozenset(data.get("allowed_capabilities", [])),
            allowed_apps=apps,
            file_roots=roots,
            max_calls_per_minute=int(data.get("max_calls_per_minute", 60)),
            dry_run=bool(data.get("dry_run", True)),
        )

    @classmethod
    def load(cls, path: Path | str) -> "Policy":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def check_capability(self, name: str) -> None:
        """Raise unless ``name`` is on the allowlist."""
        if name not in self.allowed_capabilities:
            raise PolicyViolation(f"capability {name!r} is not permitted by the policy")

    def command_for_app(self, app: str) -> tuple[str, ...]:
        """Return the exact argv for ``app``, or raise if it is not allowlisted.

        The agent never supplies a command line; it supplies a name that the
        policy maps to a fixed argv. That removes argument injection entirely.
        """
        try:
            return self.allowed_apps[app]
        except KeyError:
            raise PolicyViolation(f"application {app!r} is not permitted by the policy")

    def resolve_path(self, raw: Path | str) -> Path:
        """Resolve ``raw`` and confirm it stays inside an allowed root.

        Resolution happens before the check so that symlinks and ``..`` cannot
        be used to walk out of the jail.
        """
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            if not self.file_roots:
                raise PolicyViolation("no file roots are configured")
            candidate = self.file_roots[0] / candidate
        candidate = candidate.resolve()

        for root in self.file_roots:
            if candidate == root or root in candidate.parents:
                return candidate
        raise PolicyViolation(f"path {str(candidate)!r} is outside every allowed root")
