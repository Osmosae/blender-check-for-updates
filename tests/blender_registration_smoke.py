"""Run with Blender's --python argument, from the repository root."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import bpy


root = Path.cwd()
spec = importlib.util.spec_from_file_location(
    "release_watcher",
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
schedule_preferences.last_successful_check_at_precise = repr(now - 60.0)
remaining = module._seconds_until_auto_check(schedule_preferences)
assert 7 * 24 * 60 * 60 - 62.0 < remaining < 7 * 24 * 60 * 60 - 58.0
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


def completed_worker(stdout, *, source, channel):
    worker = module.WorkerProcess()
    worker._process = CompletedProcess(stdout)
    worker._source = source
    worker._channel = channel
    module._WORKER = worker
    return worker


worker = completed_worker('{"ok":false,"error":"test"}', source="auto", channel="DAILY")
completed, result, requested_channel = module._poll_worker()
assert completed
assert result == {"ok": False, "error": "test"}
assert requested_channel == "DAILY"
assert not worker.active
assert worker.source == ""


class StubbornProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.reaped = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if timeout is not None:
            raise subprocess.TimeoutExpired("worker", timeout)
        self.reaped = True
        return -9

    def kill(self):
        self.killed = True


stubborn_process = StubbornProcess()
stubborn_worker = module.WorkerProcess()
stubborn_worker._process = stubborn_process
stubborn_worker._source = "auto"
stubborn_worker._channel = "STABLE"
module._WORKER = stubborn_worker
module._terminate_worker()
assert stubborn_process.terminated
assert stubborn_process.killed
assert stubborn_process.reaped
assert not stubborn_worker.active
assert stubborn_worker.source == ""

result_preferences = SimpleNamespace(
    update_channel="STABLE",
    last_checked_at=0.0,
    last_checked_at_precise="",
    last_successful_check_at=0.0,
    last_successful_check_at_precise="",
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
assert abs(module._last_checked_at(result_preferences) - time.time()) < 1.0
assert abs(module._last_successful_check_at(result_preferences) - time.time()) < 1.0
assert module._AUTO_FAILURE_COUNT == 0
assert result_preferences.last_message == "No newer build was found on this channel"
last_successful_check_at = module._last_successful_check_at(result_preferences)
module._apply_result(result_preferences, {"ok": False, "error": "temporary failure"})
assert result_preferences.last_status == "ERROR"
assert module._last_successful_check_at(result_preferences) == last_successful_check_at

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

completed_worker('{"ok":false,"error":"test"}', source="auto", channel="STABLE")
assert module._automatic_check_timer() == module._POLL_SECONDS
assert timer_preferences.last_status == "NEVER"

completed_worker('{"ok":false,"error":"temporary failure"}', source="auto", channel="DAILY")
module._AUTO_FAILURE_COUNT = 0
assert module._automatic_check_timer() == 15 * 60
assert module._AUTO_FAILURE_COUNT == 1
assert timer_preferences.last_status == "ERROR"

completed_worker('{"ok":false,"error":"temporary failure"}', source="auto", channel="DAILY")
assert module._automatic_check_timer() == 30 * 60
assert module._AUTO_FAILURE_COUNT == 2

module._preferences = original_preferences
module._AUTO_FAILURE_COUNT = 0

module._preferences = lambda _context=None: timer_preferences
timer_preferences.auto_check = True
module._schedule_automatic_check()
assert bpy.app.timers.is_registered(module._automatic_check_timer)
bpy.ops.wm.read_factory_settings(use_empty=True)
assert bpy.app.timers.is_registered(module._automatic_check_timer)
bpy.app.timers.unregister(module._automatic_check_timer)
module._preferences = original_preferences

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
