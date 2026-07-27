"""How the broker executes commands.

Capabilities never touch :mod:`subprocess` directly. They call a ``Runner``,
which the tests replace with a recorder and ``dry_run`` policies replace with a
no-op. Shell strings are impossible here: a runner takes an argv sequence.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Sequence

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


Runner = Callable[[Sequence[str]], CommandResult]


def subprocess_runner(argv: Sequence[str]) -> CommandResult:
    """Run ``argv`` for real, without a shell."""
    argv = tuple(str(part) for part in argv)
    if shutil.which(argv[0]) is None:
        raise CapabilityFailed(f"executable {argv[0]!r} is not installed")
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    return CommandResult(
        argv=argv,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


@dataclass
class RecordingRunner:
    """A runner that records calls instead of executing them.

    Used by ``dry_run`` policies and by the test suite.
    """

    calls: list[tuple[str, ...]] = field(default_factory=list)
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        recorded = tuple(str(part) for part in argv)
        self.calls.append(recorded)
        return CommandResult(
            argv=recorded,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )
