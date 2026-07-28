"""ASUS hardware control - the Linux equivalent of Armoury Crate.

Backed by ``asusctl`` and ``supergfxctl`` (asusd/supergfxd), which is what
actually drives fans, keyboard lighting, battery limits and the dGPU on a TUF
or ROG laptop. Every value the agent can pass is validated against a fixed set
here, so a malformed or hostile argument never reaches the daemon.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from oszt.errors import PolicyViolation

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

POWER_PROFILES = ("Quiet", "Balanced", "Performance")
KEYBOARD_LEVELS = ("off", "low", "med", "high")
GPU_MODES = ("Integrated", "Hybrid", "AsusMuxDgpu")
MIN_CHARGE_LIMIT = 50
HEX_COLOUR = re.compile(r"\A[0-9a-fA-F]{6}\Z")


def set_power_profile(ctx: "Context", profile: str) -> dict[str, object]:
    """Switch the platform profile between Quiet, Balanced and Performance."""
    profile = _one_of(profile, POWER_PROFILES, "profile")
    ctx.run(("asusctl", "profile", "--profile-set", profile)).check()
    return {"profile": profile}


def get_power_profile(ctx: "Context") -> str:
    """Report the active platform profile."""
    return ctx.run(("asusctl", "profile", "--profile-get")).check().stdout.strip()


def set_keyboard_backlight(ctx: "Context", level: str) -> dict[str, object]:
    """Set keyboard backlight brightness to off, low, med or high."""
    level = _one_of(level, KEYBOARD_LEVELS, "level")
    ctx.run(("asusctl", "-k", level)).check()
    return {"level": level}


def set_keyboard_colour(ctx: "Context", colour: str) -> dict[str, object]:
    """Set a static keyboard colour from a six digit hex string."""
    if not isinstance(colour, str) or not HEX_COLOUR.match(colour):
        raise PolicyViolation(f"colour must be six hex digits, got {colour!r}")
    ctx.run(("asusctl", "aura", "static", "-c", colour.lower())).check()
    return {"colour": colour.lower()}


def set_charge_limit(ctx: "Context", percent: int) -> dict[str, object]:
    """Cap battery charging at a percentage to reduce wear.

    Floored well above zero: a low cap on a laptop that lives on mains power is
    indistinguishable from a dead battery.
    """
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise PolicyViolation(f"percent must be an integer, got {type(percent).__name__}")
    if percent < MIN_CHARGE_LIMIT or percent > 100:
        raise PolicyViolation(
            f"percent must be between {MIN_CHARGE_LIMIT} and 100, got {percent}"
        )
    ctx.run(("asusctl", "-c", str(percent))).check()
    return {"percent": percent}


def get_gpu_mode(ctx: "Context") -> str:
    """Report the current supergfxctl graphics mode."""
    return ctx.run(("supergfxctl", "--get")).check().stdout.strip()


def set_gpu_mode(ctx: "Context", mode: str) -> dict[str, object]:
    """Switch the graphics mode between Integrated, Hybrid and AsusMuxDgpu.

    Deliberately left out of the default policy: a mode change ends the desktop
    session (and AsusMuxDgpu needs a reboot), so losing unsaved work is the
    expected outcome rather than a bug. Enable it only for a session the human
    is watching.
    """
    mode = _one_of(mode, GPU_MODES, "mode")
    ctx.run(("supergfxctl", "--mode", mode)).check()
    return {"mode": mode, "session_ends": True}


def _one_of(value: object, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise PolicyViolation(f"{field} must be one of {', '.join(allowed)}, got {value!r}")
    assert isinstance(value, str)
    return value
