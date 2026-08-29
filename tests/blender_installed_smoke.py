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
assert addon.preferences.update_channel == "STABLE"
assert hasattr(bpy.types, "WM_OT_check_for_blender_updates")
assert not bpy.app.timers.is_registered(module._automatic_check_timer)

command = module._worker_command(addon.preferences)
assert Path(command[-9]).name == "worker.py"
assert "-I" in command
assert command[-2:] == ["--package-format", "auto"]

print("BLENDER_INSTALLED_SMOKE_OK")
