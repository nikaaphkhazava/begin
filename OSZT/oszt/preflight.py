"""Preflight: what this machine is missing before OSZT can do anything real.

Every capability shells out to a specific binary. Rather than discovering that
at 2am through a stack trace, ``oszt doctor`` reports the gaps and the exact
command that closes each one. Package names target Fedora.
"""

from __future__ import annotations

import shutil
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
    Requirement("flatpak", "sudo dnf install flatpak", "open_app for flatpak apps"),
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
