"""Run with Blender's --python argument, from the repository root."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import bpy


root = Path.cwd()
spec = importlib.util.spec_from_file_location(
    "blender_update_checker",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load extension")

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.register()

now = time.time()
schedule_preferences = SimpleNamespace(
    last_channel="STABLE",
    update_channel="STABLE",
    check_interval="DAILY",
    last_checked_at=now,
)
for interval, expected_seconds in (
    ("DAILY", 24 * 60 * 60),
    ("WEEKLY", 7 * 24 * 60 * 60),
    ("MONTHLY", 30 * 24 * 60 * 60),
):
    schedule_preferences.check_interval = interval
    remaining = module._seconds_until_auto_check(schedule_preferences)
    assert expected_seconds - 2.0 < remaining <= expected_seconds
schedule_preferences.check_interval = "LAUNCH"
assert module._seconds_until_auto_check(schedule_preferences) == 0.0
schedule_preferences.check_interval = "WEEKLY"
schedule_preferences.last_channel = "DAILY"
assert module._seconds_until_auto_check(schedule_preferences) == 0.0

assert hasattr(bpy.types, "WM_OT_check_for_blender_updates")
assert hasattr(bpy.types, "WM_OT_set_blender_update_notification_visibility")
assert bpy.app.timers.is_registered(module._automatic_check_timer) is False

module.unregister()
assert not hasattr(bpy.types, "WM_OT_check_for_blender_updates")
assert not hasattr(bpy.types, "WM_OT_set_blender_update_notification_visibility")
print("BLENDER_REGISTRATION_SMOKE_OK")
