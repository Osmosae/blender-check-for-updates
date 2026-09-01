"""Smoke-test an installed and enabled extension in an isolated Blender profile."""

from __future__ import annotations

import importlib
from pathlib import Path

import bpy


package_name = "bl_ext.user_default.blender_update_checker"
module = importlib.import_module(package_name)
addon = bpy.context.preferences.addons.get(package_name)

assert addon is not None
assert addon.preferences.auto_check is False
assert addon.preferences.check_on_launch is False
assert addon.preferences.update_channel == "STABLE"
assert hasattr(bpy.types, "WM_OT_check_for_blender_updates")
assert hasattr(bpy.types, "WM_OT_set_blender_update_notification_visibility")
assert not bpy.app.timers.is_registered(module._automatic_check_timer)
addon.preferences.auto_check = True
assert bpy.app.timers.is_registered(module._automatic_check_timer)
addon.preferences.auto_check = False
assert not bpy.app.timers.is_registered(module._automatic_check_timer)

addon.preferences.last_status = "AVAILABLE"
addon.preferences.latest_version = "5.3.0 alpha (abcdef123456)"
addon.preferences.download_url = "https://builder.blender.org/download/daily/"
addon.preferences.dismissed_version = ""
assert module._notification_visible(addon.preferences)
assert module._notification_version_text(addon.preferences) == "5.3.0 alpha"
addon.preferences.dismissed_version = addon.preferences.latest_version
assert not module._notification_visible(addon.preferences)
assert addon.preferences.show_statusbar_notification is False
addon.preferences.show_statusbar_notification = True
assert addon.preferences.dismissed_version == ""
assert module._notification_visible(addon.preferences)

command = module._worker_command(addon.preferences)
assert Path(command[-9]).name == "worker.py"
assert "-I" in command
assert command[-2:] == ["--package-format", "auto"]

print("BLENDER_INSTALLED_SMOKE_OK")
