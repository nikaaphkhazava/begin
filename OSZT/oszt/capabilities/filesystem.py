"""Creating, moving, copying and deleting files.

Two rules make broad write access survivable:

* every path passes ``resolve_writable_path``, so the OS, the agent's own code
  and the human's keys are unreachable no matter what the model asks for;
* nothing is destroyed - deletion means "moved to the trash with an undo entry",
  and an overwrite backs up the previous contents first.

Under a ``dry_run`` policy these capabilities report what they would do and
touch nothing.
"""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.trash import Trash

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

MAX_WRITE_BYTES = 8 * 1024 * 1024
MAX_RESULTS = 500


def write_text(ctx: "Context", path: str, content: str) -> dict[str, object]:
    """Create or replace a text file. The previous contents go to the trash."""
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise CapabilityFailed(f"refusing to write more than {MAX_WRITE_BYTES} bytes")
    target = ctx.policy.resolve_writable_path(path)
    if target.is_dir():
        raise CapabilityFailed(f"{str(target)!r} is a directory")

    backup: str | None = None
    if ctx.dry_run:
        return {"path": str(target), "bytes": len(content), "dry_run": True}
    if target.exists():
        backup = _trash(ctx).put(target).entry
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "bytes": len(content), "backup": backup}


def make_dir(ctx: "Context", path: str) -> dict[str, object]:
    """Create a directory, including missing parents."""
    target = ctx.policy.resolve_writable_path(path)
    if ctx.dry_run:
        return {"path": str(target), "dry_run": True}
    target.mkdir(parents=True, exist_ok=True)
    return {"path": str(target)}


def move_path(ctx: "Context", source: str, destination: str) -> dict[str, object]:
    """Move or rename a file or directory. Both ends must be writable."""
    origin = ctx.policy.resolve_writable_path(source)
    target = ctx.policy.resolve_writable_path(destination)
    if not origin.exists() and not origin.is_symlink():
        raise CapabilityFailed(f"{str(origin)!r} does not exist")
    if target.exists():
        raise CapabilityFailed(f"{str(target)!r} already exists")
    if ctx.dry_run:
        return {"source": str(origin), "destination": str(target), "dry_run": True}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origin), str(target))
    return {"source": str(origin), "destination": str(target)}


def copy_path(ctx: "Context", source: str, destination: str) -> dict[str, object]:
    """Copy a file, or a directory tree, to a new location."""
    origin = ctx.policy.resolve_path(source)  # reading is enough for the source
    target = ctx.policy.resolve_writable_path(destination)
    if not origin.exists():
        raise CapabilityFailed(f"{str(origin)!r} does not exist")
    if target.exists():
        raise CapabilityFailed(f"{str(target)!r} already exists")
    if ctx.dry_run:
        return {"source": str(origin), "destination": str(target), "dry_run": True}
    target.parent.mkdir(parents=True, exist_ok=True)
    if origin.is_dir():
        shutil.copytree(origin, target)
    else:
        shutil.copy2(origin, target)
    return {"source": str(origin), "destination": str(target)}


def delete_path(ctx: "Context", path: str) -> dict[str, object]:
    """Move a file or directory to the trash. Reversible with restore_path."""
    target = ctx.policy.resolve_writable_path(path)
    if ctx.dry_run:
        return {"path": str(target), "dry_run": True}
    entry = _trash(ctx).put(target)
    return {
        "path": entry.original_path,
        "trash_entry": entry.entry,
        "size_bytes": entry.size_bytes,
        "reversible": True,
    }


def restore_path(ctx: "Context", trash_entry: str) -> dict[str, object]:
    """Undo a deletion by putting a trashed entry back."""
    if "/" in trash_entry:
        raise PolicyViolation("trash_entry is a name, not a path")
    if ctx.dry_run:
        return {"trash_entry": trash_entry, "dry_run": True}
    restored = _trash(ctx).restore(trash_entry)
    return {"trash_entry": trash_entry, "restored_to": str(restored)}


def list_trash(ctx: "Context") -> list[dict[str, object]]:
    """List deletions that can still be undone."""
    return [
        {
            "trash_entry": entry.entry,
            "original_path": entry.original_path,
            "size_bytes": entry.size_bytes,
            "trashed_at": entry.trashed_at,
        }
        for entry in _trash(ctx).entries()
    ]


def find_files(ctx: "Context", pattern: str, path: str = ".", limit: int = 100) -> list[str]:
    """Search for files matching a glob pattern, inside a readable root."""
    if limit <= 0 or limit > MAX_RESULTS:
        raise CapabilityFailed(f"limit must be between 1 and {MAX_RESULTS}")
    root = ctx.policy.resolve_path(path)
    if not root.is_dir():
        raise CapabilityFailed(f"{str(root)!r} is not a directory")

    matches: list[str] = []
    for item in root.rglob("*"):
        if len(matches) >= limit:
            break
        if fnmatch.fnmatch(item.name, pattern):
            matches.append(str(item))
    return matches


def disk_usage(ctx: "Context", path: str = ".", top: int = 10) -> dict[str, object]:
    """Report total size and the largest subdirectories, to explain a full disk."""
    if top <= 0 or top > 100:
        raise CapabilityFailed("top must be between 1 and 100")
    root = ctx.policy.resolve_path(path)
    if not root.is_dir():
        raise CapabilityFailed(f"{str(root)!r} is not a directory")

    sizes: dict[str, int] = {}
    total = 0
    for child in root.iterdir():
        size = _tree_size(child)
        sizes[child.name] = size
        total += size
    largest = sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:top]
    return {
        "path": str(root),
        "total_bytes": total,
        "largest": [{"name": name, "bytes": size} for name, size in largest],
    }


def _trash(ctx: "Context") -> Trash:
    return Trash(ctx.policy.trash_dir)


def _tree_size(path: Path) -> int:
    if path.is_symlink():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                total += item.stat().st_size
            except OSError:  # vanished or unreadable mid-walk
                continue
    return total
