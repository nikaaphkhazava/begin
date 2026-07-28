"""The menu of actions the broker can expose.

Adding a capability here does not grant it: the policy still has to list it.
``set_gpu_mode`` is registered but intentionally absent from every shipped
policy, because it ends the desktop session.
"""

from __future__ import annotations

from typing import Callable

from oszt.capabilities import apps, asus, files, gpu, system

BUILTIN_CAPABILITIES: dict[str, Callable[..., object]] = {
    "open_app": apps.open_app,
    "close_app": apps.close_app,
    "list_files": files.list_files,
    "read_text": files.read_text,
    "set_volume": system.set_volume,
    "set_brightness": system.set_brightness,
    "set_power_profile": asus.set_power_profile,
    "get_power_profile": asus.get_power_profile,
    "set_keyboard_backlight": asus.set_keyboard_backlight,
    "set_keyboard_colour": asus.set_keyboard_colour,
    "set_charge_limit": asus.set_charge_limit,
    "get_gpu_mode": asus.get_gpu_mode,
    "set_gpu_mode": asus.set_gpu_mode,
    "gpu_status": gpu.gpu_status,
}

__all__ = ["BUILTIN_CAPABILITIES", "apps", "asus", "files", "gpu", "system"]
