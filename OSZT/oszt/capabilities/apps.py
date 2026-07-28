"""Launching, stopping, installing and removing allowlisted applications.

Installing is the only action where the agent decides what *code* lands on the
machine, so it is the most tightly drawn capability here:

- Flatpak only, and only ``--user``, so an install lands in
  ``~/.local/share/flatpak`` and can never write to the operating system. A
  system RPM (``dnf``) stays a human action - on an Atomic system it is not even
  possible without a reboot.
- The remote is fixed to Flathub by the code, not chosen by the agent.
- The application must be on the policy's ``installable_apps`` allowlist by
  exact id, so "install something to play music" cannot become "install
  anything".
- Removing an app deletes its data with it, which no trash can undo, so
  ``uninstall_app`` is restricted to that same allowlist: it can only remove
  what it was allowed to add.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oszt.errors import CapabilityFailed

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

# The one remote. Not a policy field: a hostile or mistaken remote is a way to
# install arbitrary code, so it is not the agent's or the model's to choose.
FLATHUB = "flathub"


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


def list_installable_apps(ctx: "Context") -> list[dict[str, object]]:
    """The applications this policy permits installing, and which are present."""
    installed = _installed_ids(ctx)
    return [
        {"app_id": app_id, "installed": app_id in installed}
        for app_id in sorted(ctx.policy.installable_apps)
    ]


def install_app(ctx: "Context", app_id: str) -> dict[str, object]:
    """Install an allowlisted Flatpak application into the user's own home.

    ``--user`` is what keeps this inside the boundary: the application, its
    runtime and its data all land under ``~/.local/share/flatpak``, so installing
    software never writes to the operating system and never needs root.
    """
    app_id = ctx.policy.check_installable_app(app_id)
    if app_id in _installed_ids(ctx):
        return {"app_id": app_id, "already_installed": True}

    argv = (
        "flatpak",
        "install",
        "--user",
        "--assumeyes",
        "--noninteractive",
        FLATHUB,
        app_id,
    )
    result = ctx.run(argv).check()
    return {
        "app_id": app_id,
        "remote": FLATHUB,
        "argv": list(argv),
        "returncode": result.returncode,
        "output": result.stdout[-2000:],
    }


def uninstall_app(ctx: "Context", app_id: str) -> dict[str, object]:
    """Remove an allowlisted Flatpak application and its unused runtimes.

    This is irreversible - the application's data goes with it and no trash can
    bring it back - so it is limited to the same allowlist as installing. The
    agent can undo its own additions and nothing else.
    """
    app_id = ctx.policy.check_installable_app(app_id)
    if app_id not in _installed_ids(ctx):
        return {"app_id": app_id, "already_absent": True}

    argv = ("flatpak", "uninstall", "--user", "--assumeyes", "--noninteractive", app_id)
    result = ctx.run(argv).check()
    return {
        "app_id": app_id,
        "argv": list(argv),
        "returncode": result.returncode,
        "output": result.stdout[-2000:],
    }


def _installed_ids(ctx: "Context") -> frozenset[str]:
    """The Flatpak ids present for this user, or an empty set if unknowable.

    Asking first makes install and uninstall idempotent, so a model that repeats
    itself costs a listing rather than a reinstall. A failure here is not fatal:
    it only means the shortcut cannot be taken.
    """
    argv = ("flatpak", "list", "--user", "--app", "--columns=application")
    try:
        result = ctx.run(argv)
    except CapabilityFailed:
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())
