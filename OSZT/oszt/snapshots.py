"""Snapshot and rollback - the photograph of every room before work starts.

These commands are intentionally *not* capabilities: the agent can neither take
nor restore a snapshot. Only the supervisor drives them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from oszt.runner import Runner, subprocess_runner


@dataclass
class Snapshotter:
    """Btrfs-backed snapshots of the mutable subvolume."""

    subvolume: Path
    snapshot_dir: Path
    run: Runner = subprocess_runner

    def create(self, label: str = "pre-batch") -> str:
        name = f"{label}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        target = self.snapshot_dir / name
        self.run(
            ("btrfs", "subvolume", "snapshot", "-r", str(self.subvolume), str(target))
        ).check()
        return name

    def rollback(self, name: str) -> None:
        """Restore a snapshot over the live subvolume.

        A reboot is required afterwards; the supervisor owns that decision.
        """
        source = self.snapshot_dir / name
        self.run(("btrfs", "subvolume", "delete", str(self.subvolume))).check()
        self.run(
            ("btrfs", "subvolume", "snapshot", str(source), str(self.subvolume))
        ).check()

    def list_snapshots(self) -> list[str]:
        if not self.snapshot_dir.exists():
            return []
        return sorted(entry.name for entry in self.snapshot_dir.iterdir())


@dataclass
class ImageDeployments:
    """The second heart: the A/B system images that rpm-ostree maintains."""

    run: Runner = subprocess_runner

    def rollback_to_previous(self) -> None:
        """Boot the previous known-good deployment on next start."""
        self.run(("rpm-ostree", "rollback")).check()

    def status(self) -> str:
        return self.run(("rpm-ostree", "status", "--json")).check().stdout
