"""Read-only filesystem access, confined to the policy's roots.

There is deliberately no write, move or delete capability in P1. Those arrive
only once snapshot-and-rollback is proven reliable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oszt.errors import CapabilityFailed

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

MAX_READ_BYTES = 64 * 1024


def list_files(ctx: "Context", path: str = ".") -> list[str]:
    """List entries of a directory inside an allowed root."""
    target = ctx.policy.resolve_path(path)
    if not target.is_dir():
        raise CapabilityFailed(f"{str(target)!r} is not a directory")
    return sorted(entry.name for entry in target.iterdir())


def read_text(ctx: "Context", path: str, max_bytes: int = MAX_READ_BYTES) -> str:
    """Read a UTF-8 text file inside an allowed root."""
    if max_bytes <= 0 or max_bytes > MAX_READ_BYTES:
        raise CapabilityFailed(f"max_bytes must be between 1 and {MAX_READ_BYTES}")
    target = ctx.policy.resolve_path(path)
    if not target.is_file():
        raise CapabilityFailed(f"{str(target)!r} is not a file")
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(max_bytes)
