"""Seeing the screen.

Capture is a fixed command to a filename *we* choose, never one the model
supplies, so a screenshot cannot be used to overwrite a file. The images land in
a dedicated directory the human can browse and delete.

Wayland and Xorg need different tools, so the capability probes for whichever is
installed rather than assuming a session type. GNOME on Wayland requires
``grim``-style tooling with a portal; if nothing is available the capability
refuses instead of silently producing an empty file.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from oszt.errors import CapabilityFailed

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

# In preference order: Wayland, then Xorg, then the GNOME portal fallback.
CAPTURE_TOOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("grim", ("grim",)),
    ("scrot", ("scrot", "--overwrite")),
    ("gnome-screenshot", ("gnome-screenshot", "--file")),
)

MAX_KEPT_SHOTS = 20


def capture_screen(ctx: "Context") -> dict[str, object]:
    """Take a screenshot and return where it was written.

    The agent gets a path, not pixels. Turning pixels into words is
    ``describe_screen``, which costs a second model.
    """
    directory = ctx.policy.resolve_writable_path("screenshots")
    target = _unused_name(directory)

    tool = _available_tool(ctx)
    if tool is None:
        raise CapabilityFailed(
            "no screenshot tool found: install grim (Wayland) or scrot (Xorg)"
        )
    argv = (*tool, str(target))

    if ctx.dry_run:
        ctx.run(argv)
        return {"path": str(target), "dry_run": True}

    directory.mkdir(parents=True, exist_ok=True)
    ctx.run(argv).check()
    if not target.exists():
        raise CapabilityFailed("the screenshot tool wrote no file")
    _prune(directory)
    return {"path": str(target), "size_bytes": target.stat().st_size}


def read_screenshot_base64(ctx: "Context", path: str) -> str:
    """Return a captured screenshot encoded for a vision model.

    Deliberately separate from capture so the vision model is an explicit,
    auditable step rather than something that happens on every screenshot.
    """
    target = ctx.policy.resolve_path(path)
    if target.suffix.lower() != ".png":
        raise CapabilityFailed("only png screenshots can be read")
    if not target.is_file():
        raise CapabilityFailed(f"{str(target)!r} is not a file")
    if target.stat().st_size > 16 * 1024 * 1024:
        raise CapabilityFailed("screenshot is too large to send to a model")
    return base64.b64encode(target.read_bytes()).decode("ascii")


def _unused_name(directory: Path) -> Path:
    """A fresh filename, even for two captures in the same millisecond."""
    stamp = int(time.time() * 1000)
    candidate = directory / f"{stamp}.png"
    attempt = 1
    while candidate.exists():
        attempt += 1
        candidate = directory / f"{stamp}-{attempt}.png"
    return candidate


def _available_tool(ctx: "Context") -> Sequence[str] | None:
    for binary, argv in CAPTURE_TOOLS:
        if ctx.run.which(binary):
            return argv
    return None


def _prune(directory: Path) -> None:
    """Keep only the most recent screenshots; they are large and endless."""
    shots = sorted(directory.glob("*.png"), key=lambda item: item.name)
    for stale in shots[:-MAX_KEPT_SHOTS]:
        stale.unlink(missing_ok=True)
