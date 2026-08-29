"""Run with Blender's --python argument, from the repository root."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

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

assert hasattr(bpy.types, "WM_OT_check_for_blender_updates")
assert bpy.app.timers.is_registered(module._automatic_check_timer) is False

module.unregister()
assert not hasattr(bpy.types, "WM_OT_check_for_blender_updates")
print("BLENDER_REGISTRATION_SMOKE_OK")
