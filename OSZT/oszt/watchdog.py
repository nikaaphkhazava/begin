"""sd_notify: how the supervisor proves it is alive to systemd.

If these pings stop, systemd restarts the supervisor - and after the configured
number of failures, ``oszt-rollback.service`` boots the other heart. The agent
runs in a separate unit with no access to ``NOTIFY_SOCKET``, so it cannot forge
a heartbeat on the supervisor's behalf.
"""

from __future__ import annotations

import os
import socket
from typing import Mapping


def notify(state: str, environ: Mapping[str, str] | None = None) -> bool:
    """Send ``state`` to systemd's notify socket.

    Returns False when there is no socket (running outside systemd) rather than
    raising, so the supervisor is testable from a plain shell.
    """
    environ = os.environ if environ is None else environ
    address = environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):  # abstract namespace
        address = "\0" + address[1:]

    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        try:
            client.connect(address)
            client.sendall(state.encode("utf-8"))
        except OSError:
            return False
    return True


def ready(environ: Mapping[str, str] | None = None) -> bool:
    return notify("READY=1", environ)


def watchdog_ping(environ: Mapping[str, str] | None = None) -> bool:
    return notify("WATCHDOG=1", environ)


def status(message: str, environ: Mapping[str, str] | None = None) -> bool:
    return notify(f"STATUS={message}", environ)
