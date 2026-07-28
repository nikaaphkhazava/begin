"""The policy: the printed menu the agent is allowed to order from.

The policy is data, not code. It is loaded from JSON and owned by the human, so
widening what the agent may do is always a reviewable diff.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from oszt.errors import PolicyViolation


# The 0.1%: paths the agent must never write to, whatever the policy says.
# The operating system, the agent's own code and configuration, its ledger, its
# safety net, and the human's keys. Everything else is negotiable.
DEFAULT_PROTECTED_PATHS: tuple[str, ...] = (
    "/usr",
    "/etc",
    "/boot",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/var",
    "/opt",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/ostree",
    "/sysroot",
    "~/.ssh",
    "~/.gnupg",
    "~/.pki",
    "~/.local/share/keyrings",
    "~/.config/oszt",
    "~/.local/share/oszt",
)

# org.mozilla.firefox, com.valvesoftware.Steam: at least two dot-separated
# segments of letters, digits, hyphens and underscores.
_FLATPAK_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9][A-Za-z0-9_-]*){2,}")


@dataclass(frozen=True)
class Policy:
    """An allowlist of capabilities, applications and filesystem roots.

    Reading and writing are separate questions. ``file_roots`` says what the
    agent may look at; ``write_roots`` minus ``protected_paths`` says what it may
    change. Broad write access is fine precisely because the exclusions are
    absolute and the deletions are reversible.
    """

    allowed_capabilities: frozenset[str] = frozenset()
    allowed_apps: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    file_roots: tuple[Path, ...] = ()
    write_roots: tuple[Path, ...] = ()
    protected_paths: tuple[Path, ...] = ()
    trash_dir: Path = Path("~/.local/share/oszt-trash").expanduser()
    allowed_hosts: frozenset[str] = frozenset()
    max_download_bytes: int = 512 * 1024 * 1024
    allowed_cleaners: frozenset[str] = frozenset()
    installable_apps: frozenset[str] = frozenset()
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

        roots = _paths(data.get("file_roots", []))
        trash = Path(
            data.get("trash_dir", "~/.local/share/oszt-trash")
        ).expanduser()
        # The trash is protected too: the agent must not be able to empty the
        # bin it just dropped your files into.
        protected = _paths(data.get("protected_paths", DEFAULT_PROTECTED_PATHS)) + (
            trash.resolve(),
        )
        return cls(
            allowed_capabilities=frozenset(data.get("allowed_capabilities", [])),
            allowed_apps=apps,
            file_roots=roots,
            write_roots=_paths(data.get("write_roots", [])),
            protected_paths=protected,
            trash_dir=trash,
            allowed_hosts=frozenset(data.get("allowed_hosts", [])),
            max_download_bytes=int(data.get("max_download_bytes", 512 * 1024 * 1024)),
            allowed_cleaners=frozenset(data.get("allowed_cleaners", [])),
            installable_apps=_flatpak_ids(data.get("installable_apps", [])),
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
            if _contains(root, candidate):
                return candidate
        raise PolicyViolation(f"path {str(candidate)!r} is outside every allowed root")

    def resolve_writable_path(self, raw: Path | str) -> Path:
        """Resolve ``raw`` and confirm the agent may *change* it.

        Two independent gates: it must sit inside a write root, and it must not
        touch a protected path. The protected check wins, so nesting a write
        root above the OS cannot open it up.
        """
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            if not self.write_roots:
                raise PolicyViolation("no write roots are configured")
            candidate = self.write_roots[0] / candidate
        candidate = _resolve_for_write(candidate)

        for protected in self.protected_paths:
            if _contains(protected, candidate) or _contains(candidate, protected):
                raise PolicyViolation(
                    f"path {str(candidate)!r} is protected and can never be modified"
                )
        for root in self.write_roots:
            if _contains(root, candidate):
                return candidate
        raise PolicyViolation(f"path {str(candidate)!r} is outside every write root")

    def check_host(self, host: str) -> None:
        if host not in self.allowed_hosts:
            raise PolicyViolation(f"host {host!r} is not permitted by the policy")

    def check_cleaner(self, name: str) -> None:
        if name not in self.allowed_cleaners:
            raise PolicyViolation(f"cleaner {name!r} is not permitted by the policy")

    def check_installable_app(self, app_id: str) -> str:
        """Confirm ``app_id`` is an application the human agreed may be installed.

        Installing is the one action where the agent chooses what *code* runs on
        the machine, so the allowlist is of exact Flatpak application ids - not
        of remotes, and not of name patterns.
        """
        if app_id not in self.installable_apps:
            raise PolicyViolation(
                f"application {app_id!r} is not on the installable allowlist"
            )
        return app_id


def _flatpak_ids(raw: Any) -> frozenset[str]:
    """Validate the installable allowlist as Flatpak application ids.

    A reversed-DNS id (``org.mozilla.firefox``) cannot be mistaken for an option,
    a path or a second argument, so a malformed policy is refused at load time
    rather than reaching ``flatpak`` as an argv fragment.
    """
    ids: set[str] = set()
    for item in raw:
        app_id = str(item)
        if not _FLATPAK_ID.fullmatch(app_id):
            raise PolicyViolation(
                f"installable_apps[{app_id!r}] is not a Flatpak application id"
            )
        ids.add(app_id)
    return frozenset(ids)


def _paths(raw: Any) -> tuple[Path, ...]:
    return tuple(Path(str(item)).expanduser().resolve() for item in raw)


def _contains(ancestor: Path, candidate: Path) -> bool:
    return candidate == ancestor or ancestor in candidate.parents


def _resolve_for_write(candidate: Path) -> Path:
    """Resolve a path that may not exist yet, without following its final link.

    The parent is resolved (so symlinked directories cannot smuggle a write out
    of the allowed area) but the leaf is not, so deleting a symlink deletes the
    link rather than its target.
    """
    if candidate.is_symlink():
        return candidate.parent.resolve() / candidate.name
    return candidate.resolve()
