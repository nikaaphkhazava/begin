"""Reversible deletion.

Nothing the agent deletes is destroyed. It is moved into a dated trash
directory and recorded in a manifest, so every deletion has an undo. An OS
rollback cannot bring your files back - only this can.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from oszt.errors import CapabilityFailed


@dataclass(frozen=True)
class TrashEntry:
    entry: str
    original_path: str
    trashed_at: float
    size_bytes: int


class Trash:
    """A holding pen with a manifest, not an incinerator."""

    def __init__(self, directory: Path | str, clock: Callable[[], float] = time.time) -> None:
        self.directory = Path(directory).expanduser()
        self._clock = clock

    @property
    def manifest_path(self) -> Path:
        return self.directory / "manifest.jsonl"

    def put(self, path: Path) -> TrashEntry:
        """Move ``path`` into the trash and record how to undo it."""
        if not path.exists() and not path.is_symlink():
            raise CapabilityFailed(f"{str(path)!r} does not exist")

        self.directory.mkdir(parents=True, exist_ok=True)
        timestamp = self._clock()
        name = f"{int(timestamp)}-{path.name}"
        destination = self.directory / name
        suffix = 1
        while destination.exists():
            suffix += 1
            name = f"{int(timestamp)}-{suffix}-{path.name}"
            destination = self.directory / name

        entry = TrashEntry(
            entry=name,
            original_path=str(path),
            trashed_at=timestamp,
            size_bytes=_size_of(path),
        )
        shutil.move(str(path), str(destination))
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.__dict__, sort_keys=True) + "\n")
        return entry

    def entries(self) -> list[TrashEntry]:
        if not self.manifest_path.exists():
            return []
        return [
            TrashEntry(**json.loads(line))
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def restore(self, name: str) -> Path:
        """Put a trashed entry back where it came from."""
        matches = [entry for entry in self.entries() if entry.entry == name]
        if not matches:
            raise CapabilityFailed(f"no trash entry named {name!r}")
        entry = matches[-1]
        source = self.directory / entry.entry
        if not source.exists() and not source.is_symlink():
            raise CapabilityFailed(f"trash entry {name!r} is no longer on disk")

        destination = Path(entry.original_path)
        if destination.exists():
            raise CapabilityFailed(f"{entry.original_path!r} exists again; refusing to overwrite")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return destination

    def purge(self, older_than_days: float) -> list[str]:
        """Delete trash entries older than ``older_than_days``, irreversibly.

        Only ever called by the janitor timer, never by the agent: this is the
        one operation that actually destroys data.
        """
        if older_than_days < 1:
            raise CapabilityFailed("refusing to purge trash younger than a day")
        cutoff = self._clock() - older_than_days * 86400
        purged: list[str] = []
        for entry in self.entries():
            if entry.trashed_at >= cutoff:
                continue
            target = self.directory / entry.entry
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
                purged.append(entry.entry)
            elif target.exists() or target.is_symlink():
                target.unlink()
                purged.append(entry.entry)
        return purged


def _size_of(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    return sum(item.lstat().st_size for item in path.rglob("*") if not item.is_dir())
