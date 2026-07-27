"""Launching and stopping allowlisted applications."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context


def open_app(ctx: "Context", app: str) -> dict[str, object]:
    """Launch an allowlisted application by name."""
    argv = ctx.policy.command_for_app(app)
    result = ctx.run(argv).check()
    return {"app": app, "argv": list(argv), "returncode": result.returncode}


def close_app(ctx: "Context", app: str) -> dict[str, object]:
    """Terminate an allowlisted application by name.

    The process is matched on the policy-defined executable, never on a pattern
    supplied by the agent, so this cannot be aimed at an arbitrary process.
    """
    argv = ctx.policy.command_for_app(app)
    executable = argv[-1] if argv[0] in {"flatpak", "flatpak-spawn"} else argv[0]
    result = ctx.run(("pkill", "--full", "--exact", executable))
    return {"app": app, "target": executable, "returncode": result.returncode}
