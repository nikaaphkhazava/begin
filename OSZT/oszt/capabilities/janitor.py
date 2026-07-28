"""Cleaning up: caches, junk and duplicates.

Cleaners are *named jobs with fixed commands*, not free-form file judgement. The
model decides "run the cleanup", never "this file looks useless to me" - a small
local model is fine at the former and untrustworthy at the latter.

Duplicates are reported, never deleted. On Btrfs, ``deduplicate`` reclaims the
space while both copies keep existing, which is the only way to free disk with
zero risk of losing a file something depended on.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from oszt.errors import CapabilityFailed

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

MIN_DUPLICATE_BYTES = 1024 * 1024
HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Cleaner:
    """One cleanup job: either a fixed command, or a fixed directory to empty.

    Emptying happens in Python against a hard-coded path rather than by shelling
    out to ``rm -rf``: there is then no argv for a bug or a prompt injection to
    extend, and the code can refuse a path that is not the one it expects.
    """

    name: str
    description: str
    argv: tuple[str, ...] = ()
    directory: str = ""
    privileged: bool = False


CLEANERS: dict[str, Cleaner] = {
    "flatpak-unused": Cleaner(
        "flatpak-unused",
        "runtimes no installed app still needs - usually the biggest win",
        argv=("flatpak", "uninstall", "--unused", "--assumeyes"),
    ),
    "journal": Cleaner(
        "journal",
        "system logs older than two weeks",
        argv=("journalctl", "--vacuum-time=14d"),
        privileged=True,
    ),
    "dnf-cache": Cleaner(
        "dnf-cache",
        "downloaded rpm files already installed",
        argv=("dnf", "clean", "packages"),
        privileged=True,
    ),
    "thumbnails": Cleaner(
        "thumbnails",
        "regenerable image thumbnails",
        directory="~/.cache/thumbnails",
    ),
    "coredumps": Cleaner(
        "coredumps",
        "crash dumps nobody is going to read",
        directory="/var/lib/systemd/coredump",
        privileged=True,
    ),
}


def list_cleaners(ctx: "Context") -> list[dict[str, object]]:
    """List the cleanup jobs this policy permits."""
    return [
        {
            "name": cleaner.name,
            "description": cleaner.description,
            "privileged": cleaner.privileged,
        }
        for name, cleaner in sorted(CLEANERS.items())
        if name in ctx.policy.allowed_cleaners
    ]


def clean_caches(ctx: "Context", cleaner: str) -> dict[str, object]:
    """Run one named cleanup job.

    Privileged jobs are skipped rather than attempted when the process is not
    root: the agent user must not be able to acquire root by asking nicely.
    """
    ctx.policy.check_cleaner(cleaner)
    try:
        job = CLEANERS[cleaner]
    except KeyError:
        raise CapabilityFailed(f"unknown cleaner {cleaner!r}")

    if job.privileged and os.geteuid() != 0:
        return {
            "cleaner": job.name,
            "skipped": "needs the privileged janitor timer, which runs as root",
        }

    if job.directory:
        return _empty_directory(ctx, job)

    result = ctx.run(job.argv).check()
    return {"cleaner": job.name, "returncode": result.returncode, "output": result.stdout[-2000:]}


def _empty_directory(ctx: "Context", job: Cleaner) -> dict[str, object]:
    """Delete the *contents* of one hard-coded cache directory.

    The directory itself stays, because the application that owns it expects it
    to exist. Nothing here is reversible, which is why the only paths reachable
    are the two literals above - caches the system rebuilds by itself.
    """
    directory = Path(job.directory).expanduser()
    if not directory.is_dir():
        return {"cleaner": job.name, "skipped": f"{str(directory)!r} does not exist"}

    freed = 0
    removed = 0
    for item in sorted(directory.iterdir()):
        try:
            freed += _size_of(item)
            if ctx.dry_run:
                removed += 1
                continue
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
        except OSError:
            continue  # in use, or not ours: leave it alone
    return {
        "cleaner": job.name,
        "directory": str(directory),
        "removed": removed,
        "freed_bytes": freed,
        "dry_run": ctx.dry_run,
    }


def _size_of(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def find_duplicates(
    ctx: "Context", path: str = ".", min_bytes: int = MIN_DUPLICATE_BYTES
) -> list[dict[str, object]]:
    """Report groups of identical files. Deletes nothing.

    Files are grouped by size first and only then hashed, so a large tree costs
    one stat per file and a read only for genuine candidates.
    """
    if min_bytes < MIN_DUPLICATE_BYTES:
        raise CapabilityFailed(
            f"min_bytes must be at least {MIN_DUPLICATE_BYTES}: hunting small "
            "duplicates finds thousands of files that programs need"
        )
    root = ctx.policy.resolve_path(path)
    if not root.is_dir():
        raise CapabilityFailed(f"{str(root)!r} is not a directory")

    by_size: dict[int, list[Path]] = {}
    for item in root.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        try:
            size = item.stat().st_size
        except OSError:
            continue
        if size >= min_bytes:
            by_size.setdefault(size, []).append(item)

    groups: list[dict[str, object]] = []
    for size, candidates in by_size.items():
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for candidate in candidates:
            try:
                by_hash.setdefault(_digest(candidate), []).append(candidate)
            except OSError:
                continue
        for digest, matches in by_hash.items():
            if len(matches) < 2:
                continue
            groups.append(
                {
                    "digest": digest,
                    "size_bytes": size,
                    "reclaimable_bytes": size * (len(matches) - 1),
                    "paths": sorted(str(match) for match in matches),
                }
            )
    return sorted(groups, key=lambda group: int(group["reclaimable_bytes"]), reverse=True)


def deduplicate(ctx: "Context", path: str = ".") -> dict[str, object]:
    """Reclaim duplicate space on Btrfs without deleting anything.

    ``duperemove`` points identical extents at the same blocks. Both files still
    exist and still open; the disk gets the space back.
    """
    root = ctx.policy.resolve_writable_path(path)
    if not root.is_dir():
        raise CapabilityFailed(f"{str(root)!r} is not a directory")
    result = ctx.run(("duperemove", "-dr", str(root))).check()
    return {"path": str(root), "output": result.stdout[-2000:], "deleted_nothing": True}


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()
