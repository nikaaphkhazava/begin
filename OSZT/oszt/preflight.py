"""Preflight: what this machine is missing before OSZT can do anything real.

Every capability shells out to a specific binary. Rather than discovering that
at 2am through a stack trace, ``oszt doctor`` reports the gaps and the exact
command that closes each one. Package names target Fedora.

The models are checked too, and separately from the binaries: Ollama being
installed says nothing about whether the mind and the eye have been pulled, and
"the agent does nothing" is almost always one missing ``ollama pull``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class Requirement:
    binary: str
    install: str
    purpose: str
    optional: bool = False


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("wpctl", "sudo dnf install wireplumber", "set_volume"),
    Requirement("brightnessctl", "sudo dnf install brightnessctl", "set_brightness"),
    Requirement("pkill", "sudo dnf install procps-ng", "close_app"),
    Requirement(
        "flatpak",
        "sudo dnf install flatpak && flatpak remote-add --if-not-exists --user flathub "
        "https://flathub.org/repo/flathub.flatpakrepo",
        "open_app and install_app for flatpak apps",
    ),
    Requirement(
        "asusctl",
        "sudo dnf copr enable lukenukem/asus-linux && sudo dnf install asusctl "
        "&& sudo systemctl enable --now asusd",
        "fan profile, keyboard light, charge limit",
    ),
    Requirement(
        "supergfxctl",
        "sudo dnf install supergfxctl && sudo systemctl enable --now supergfxd",
        "GPU mode reporting and switching",
    ),
    Requirement(
        "nvidia-smi",
        "sudo dnf install akmod-nvidia xorg-x11-drv-nvidia-cuda  # needs RPM Fusion",
        "gpu_status",
    ),
    Requirement("btrfs", "sudo dnf install btrfs-progs", "snapshots before each batch"),
    Requirement(
        "ollama",
        "curl -fsSL https://ollama.com/install.sh | sh",
        "the local model behind the Hermes agent",
    ),
    Requirement("curl", "sudo dnf install curl", "download_file"),
    Requirement(
        "grim",
        "sudo dnf install grim  # Wayland; use scrot on an Xorg session",
        "capture_screen",
        optional=True,
    ),
    Requirement(
        "duperemove",
        "sudo dnf install duperemove",
        "deduplicate: reclaim duplicate space without deleting",
        optional=True,
    ),
    Requirement(
        "rpm-ostree",
        "only present on Fedora Atomic (Silverblue/Kinoite/bootc)",
        "the second heart: A/B image rollback",
        optional=True,
    ),
    Requirement(
        "ddcutil", "sudo dnf install ddcutil", "external monitor brightness", optional=True
    ),
    Requirement(
        "ydotool", "sudo dnf install ydotool", "synthetic input under Wayland", optional=True
    ),
)


@dataclass(frozen=True)
class ModelRequirement:
    """One local model the agent needs pulled, and what stops working without it."""

    name: str
    purpose: str
    size: str


DEFAULT_MODELS: tuple[ModelRequirement, ...] = (
    ModelRequirement("qwen2.5:3b", "the mind: Hermes deciding and calling tools", "~2GB"),
    ModelRequirement("moondream", "the eye: describing what is on the screen", "~1.7GB"),
)


@dataclass(frozen=True)
class ModelStatus:
    requirement: ModelRequirement
    present: bool


@dataclass(frozen=True)
class RequirementStatus:
    requirement: Requirement
    present: bool

    @property
    def blocking(self) -> bool:
        return not self.present and not self.requirement.optional


def check(
    requirements: Sequence[Requirement] = REQUIREMENTS,
    which: Callable[[str], str | None] = shutil.which,
) -> list[RequirementStatus]:
    return [
        RequirementStatus(requirement, which(requirement.binary) is not None)
        for requirement in requirements
    ]


def installed_models(
    which: Callable[[str], str | None] = shutil.which,
) -> frozenset[str] | None:
    """The model tags Ollama has locally, or ``None`` if it cannot be asked.

    ``None`` means Ollama is absent or not running - a different problem from
    "running, but the model was never pulled", and worth reporting differently.
    """
    if which("ollama") is None:
        return None
    try:
        completed = subprocess.run(
            ("ollama", "list"), capture_output=True, text=True, check=False, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    tags: set[str] = set()
    for line in completed.stdout.splitlines()[1:]:  # skip the NAME header
        name = line.split()[0] if line.split() else ""
        if name:
            tags.add(name)
    return frozenset(tags)


def check_models(
    models: Sequence[ModelRequirement] = DEFAULT_MODELS,
    present: frozenset[str] | None = None,
) -> list[ModelStatus] | None:
    """Which of ``models`` are pulled, or ``None`` if Ollama cannot be asked."""
    tags = installed_models() if present is None else present
    if tags is None:
        return None
    return [
        ModelStatus(model, _has_model(model.name, tags)) for model in models
    ]


def _has_model(name: str, tags: frozenset[str]) -> bool:
    """``moondream`` and ``moondream:latest`` are the same model to Ollama."""
    wanted = name if ":" in name else f"{name}:latest"
    return name in tags or wanted in tags


def report_models(statuses: Sequence[ModelStatus] | None) -> str:
    """The model half of ``doctor``: what to pull, and what it costs."""
    if statuses is None:
        return (
            "MISSING  ollama         no local model runtime is answering\n"
            "         -> curl -fsSL https://ollama.com/install.sh | sh\n"
            "         -> then: ollama pull qwen2.5:3b && ollama pull moondream\n"
            "\nwithout a model the broker still works and the buttons still run "
            "capabilities;\nonly the deciding and the screen descriptions are unavailable"
        )

    lines: list[str] = []
    for status in statuses:
        model = status.requirement
        lines.append(
            f"{'ok      ' if status.present else 'MISSING '} "
            f"{model.name:<14} {model.purpose} ({model.size})"
        )
        if not status.present:
            lines.append(f"         -> ollama pull {model.name}")
    missing = [status for status in statuses if not status.present]
    lines.append("")
    lines.append(
        "all models pulled"
        if not missing
        else f"{len(missing)} model(s) not pulled; Hermes will report the model as "
        "unavailable until then"
    )
    return "\n".join(lines)


def report(statuses: Sequence[RequirementStatus]) -> str:
    lines: list[str] = []
    for status in statuses:
        requirement = status.requirement
        if status.present:
            mark = "ok      "
        elif requirement.optional:
            mark = "missing?"
        else:
            mark = "MISSING "
        lines.append(f"{mark} {requirement.binary:<14} {requirement.purpose}")
        if not status.present:
            lines.append(f"         -> {requirement.install}")

    blocking = [status for status in statuses if status.blocking]
    lines.append("")
    lines.append(
        "all required tools present"
        if not blocking
        else f"{len(blocking)} required tool(s) missing; "
        "the matching capabilities will refuse until installed"
    )
    return "\n".join(lines)
