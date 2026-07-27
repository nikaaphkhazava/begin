"""The menu of actions the broker can expose.

Adding a capability here does not grant it: the policy still has to list it.
"""

from __future__ import annotations

from typing import Callable

from oszt.capabilities import apps, files, system

BUILTIN_CAPABILITIES: dict[str, Callable[..., object]] = {
    "open_app": apps.open_app,
    "close_app": apps.close_app,
    "list_files": files.list_files,
    "read_text": files.read_text,
    "set_volume": system.set_volume,
    "set_brightness": system.set_brightness,
}

__all__ = ["BUILTIN_CAPABILITIES", "apps", "files", "system"]
