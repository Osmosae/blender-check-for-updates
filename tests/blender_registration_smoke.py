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
    last_successful_check_at=now,
    last_status="UP_TO_DATE",
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

schedule_preferences.last_channel = "STABLE"
schedule_preferences.last_status = "ERROR"
schedule_preferences.last_successful_check_at = 0.0
assert module._seconds_until_auto_check(schedule_preferences) == 0.0
schedule_preferences.last_status = "UP_TO_DATE"
remaining = module._seconds_until_auto_check(schedule_preferences)
assert 7 * 24 * 60 * 60 - 2.0 < remaining <= 7 * 24 * 60 * 60
assert module._automatic_error_retry_seconds(1) == 15 * 60
assert module._automatic_error_retry_seconds(2) == 30 * 60
assert module._automatic_error_retry_seconds(3) == 60 * 60
assert module._automatic_error_retry_seconds(20) == 60 * 60
assert module._result_matches_channel(schedule_preferences, "STABLE")
assert not module._result_matches_channel(schedule_preferences, "DAILY")


class CompletedProcess:
    def __init__(self, stdout='{"ok":false,"error":"test"}'):
        self.stdout = stdout

    def poll(self):
        return 0

    def communicate(self):
        return self.stdout, ""


module._PROCESS = CompletedProcess()
module._PROCESS_SOURCE = "auto"
module._PROCESS_CHANNEL = "DAILY"
completed, result, requested_channel = module._poll_worker()
assert completed
assert result == {"ok": False, "error": "test"}
assert requested_channel == "DAILY"
assert module._PROCESS is None
assert module._PROCESS_SOURCE == ""
assert module._PROCESS_CHANNEL == ""

result_preferences = SimpleNamespace(
    update_channel="STABLE",
    last_checked_at=0.0,
    last_successful_check_at=0.0,
    last_channel="",
    last_status="NEVER",
    last_message="",
    latest_version="",
    download_url="",
)
module._AUTO_FAILURE_COUNT = 3
module._apply_result(
    result_preferences,
    {
        "ok": True,
        "update_available": False,
        "display_version": "5.2.1",
        "download_url": "https://www.blender.org/download/",
        "channel": "stable",
    },
)
assert result_preferences.last_successful_check_at > 0.0
assert module._AUTO_FAILURE_COUNT == 0
assert result_preferences.last_message == "No newer build was found on this channel"
last_successful_check_at = result_preferences.last_successful_check_at
module._apply_result(result_preferences, {"ok": False, "error": "temporary failure"})
assert result_preferences.last_status == "ERROR"
assert result_preferences.last_successful_check_at == last_successful_check_at

timer_preferences = SimpleNamespace(
    auto_check=True,
    check_interval="WEEKLY",
    update_channel="DAILY",
    last_checked_at=0.0,
    last_successful_check_at=0.0,
    last_channel="STABLE",
    last_status="NEVER",
    last_message="",
    latest_version="",
    download_url="",
)
original_preferences = module._preferences
module._preferences = lambda _context=None: timer_preferences

module._PROCESS = CompletedProcess()
module._PROCESS_SOURCE = "auto"
module._PROCESS_CHANNEL = "STABLE"
assert module._automatic_check_timer() == module._POLL_SECONDS
assert timer_preferences.last_status == "NEVER"

module._PROCESS = CompletedProcess()
module._PROCESS_SOURCE = "auto"
module._PROCESS_CHANNEL = "DAILY"
module._AUTO_FAILURE_COUNT = 0
assert module._automatic_check_timer() == 15 * 60
assert module._AUTO_FAILURE_COUNT == 1
assert timer_preferences.last_status == "ERROR"

module._PROCESS = CompletedProcess()
module._PROCESS_SOURCE = "auto"
module._PROCESS_CHANNEL = "DAILY"
assert module._automatic_check_timer() == 30 * 60
assert module._AUTO_FAILURE_COUNT == 2

module._preferences = original_preferences
module._AUTO_FAILURE_COUNT = 0

stale_preferences = SimpleNamespace(
    last_status="CHECKING",
    last_message="Checking…",
)
assert module._recover_stale_check(stale_preferences)
assert stale_preferences.last_status == "ERROR"
assert stale_preferences.last_message == "The previous update check did not finish"
assert not module._recover_stale_check(stale_preferences)

assert hasattr(bpy.types, "WM_OT_check_for_blender_updates")
assert hasattr(bpy.types, "WM_OT_set_blender_update_notification_visibility")
assert bpy.app.timers.is_registered(module._automatic_check_timer) is False

module.unregister()
assert not hasattr(bpy.types, "WM_OT_check_for_blender_updates")
assert not hasattr(bpy.types, "WM_OT_set_blender_update_notification_visibility")
print("BLENDER_REGISTRATION_SMOKE_OK")
