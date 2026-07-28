"""How the broker executes commands.

Capabilities never touch :mod:`subprocess` directly. They call a ``Runner``,
which the tests replace with a recorder and ``dry_run`` policies replace with a
no-op. Shell strings are impossible here: a runner takes an argv sequence.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from oszt.errors import CapabilityFailed


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    def check(self) -> "CommandResult":
        if self.returncode != 0:
            raise CapabilityFailed(
                f"command {' '.join(self.argv)!r} exited {self.returncode}: {self.stderr.strip()}"
            )
        return self


class Runner(Protocol):
    """Executes an argv, and can say whether a tool exists at all."""

    def __call__(self, argv: Sequence[str]) -> CommandResult: ...

    def which(self, binary: str) -> str | None: ...


class SubprocessRunner:
    """Runs commands for real, without a shell."""

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(str(part) for part in argv)
        if self.which(command[0]) is None:
            raise CapabilityFailed(f"executable {command[0]!r} is not installed")
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        return CommandResult(
            argv=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)


subprocess_runner = SubprocessRunner()


@dataclass
class RecordingRunner:
    """A runner that records calls instead of executing them.

    Used by ``dry_run`` policies and by the test suite.
    """

    calls: list[tuple[str, ...]] = field(default_factory=list)
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    # None means "pretend every tool is installed"; a set narrows it, so tests
    # can reproduce a machine that is missing grim or duperemove.
    installed: set[str] | None = None

    def which(self, binary: str) -> str | None:
        if self.installed is None or binary in self.installed:
            return f"/usr/bin/{binary}"
        return None

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        recorded = tuple(str(part) for part in argv)
        self.calls.append(recorded)
        return CommandResult(
            argv=recorded,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )
