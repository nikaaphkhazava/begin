"""The menu of actions the broker can expose.

Adding a capability here does not grant it: the policy still has to list it.
``set_gpu_mode`` is registered but intentionally absent from every shipped
policy, because it ends the desktop session.
"""

from __future__ import annotations

from typing import Callable

from oszt.capabilities import (
    apps,
    asus,
    cloud_memory,
    files,
    filesystem,
    gpu,
    janitor,
    net,
    screen,
    system,
)

BUILTIN_CAPABILITIES: dict[str, Callable[..., object]] = {
    "open_app": apps.open_app,
    "close_app": apps.close_app,
    "list_installable_apps": apps.list_installable_apps,
    "install_app": apps.install_app,
    "uninstall_app": apps.uninstall_app,
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
    "write_text": filesystem.write_text,
    "make_dir": filesystem.make_dir,
    "move_path": filesystem.move_path,
    "copy_path": filesystem.copy_path,
    "delete_path": filesystem.delete_path,
    "restore_path": filesystem.restore_path,
    "list_trash": filesystem.list_trash,
    "find_files": filesystem.find_files,
    "disk_usage": filesystem.disk_usage,
    "list_cleaners": janitor.list_cleaners,
    "clean_caches": janitor.clean_caches,
    "find_duplicates": janitor.find_duplicates,
    "deduplicate": janitor.deduplicate,
    "download_file": net.download_file,
    "capture_screen": screen.capture_screen,
    "read_screenshot_base64": screen.read_screenshot_base64,
    "sync_preferences_to_cloud": cloud_memory.sync_preferences_to_cloud,
    "fetch_preferences_from_cloud": cloud_memory.fetch_preferences_from_cloud,
    "delete_cloud_history": cloud_memory.delete_cloud_history,
}

__all__ = [
    "BUILTIN_CAPABILITIES",
    "apps",
    "asus",
    "cloud_memory",
    "files",
    "filesystem",
    "gpu",
    "janitor",
    "net",
    "screen",
    "system",
]
