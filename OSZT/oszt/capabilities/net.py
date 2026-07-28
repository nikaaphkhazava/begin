"""Downloading.

The narrowest capability in the project, because "fetch a file from the internet
and put it on the disk" is how an agent installs something nobody asked for.
Four locks: https only, host on the policy allowlist, a size cap enforced by
curl, and the saved file has its execute bits stripped so the agent cannot run
what it just fetched.

Installing *software* deliberately does not live here - that is a Flatpak or dnf
capability with its own allowlist, not a download.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from oszt.errors import CapabilityFailed, PolicyViolation

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

SAFE_FILENAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
NON_EXECUTABLE = 0o600


def download_file(ctx: "Context", url: str, filename: str) -> dict[str, object]:
    """Download ``url`` to ``filename`` inside the workspace."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise PolicyViolation("only https downloads are permitted")
    if not parsed.hostname:
        raise PolicyViolation(f"{url!r} has no host")
    ctx.policy.check_host(parsed.hostname)

    if not SAFE_FILENAME.match(filename):
        raise PolicyViolation(
            "filename must be a plain name: no directories, no leading dot"
        )
    target = ctx.policy.resolve_writable_path(filename)
    if target.exists():
        raise CapabilityFailed(f"{str(target)!r} already exists")

    argv = (
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--proto",
        "=https",
        "--max-filesize",
        str(ctx.policy.max_download_bytes),
        "--max-time",
        "300",
        "--output",
        str(target),
        url,
    )
    if ctx.dry_run:
        ctx.run(argv)
        return {"url": url, "path": str(target), "dry_run": True}

    target.parent.mkdir(parents=True, exist_ok=True)
    ctx.run(argv).check()
    if target.exists():
        os.chmod(target, NON_EXECUTABLE)
    return {
        "url": url,
        "path": str(target),
        "size_bytes": target.stat().st_size if target.exists() else 0,
        "executable": False,
    }
