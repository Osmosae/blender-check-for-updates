"""Blender Update Checker extension entry point."""

from __future__ import annotations

import datetime as _datetime
import json
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty


_PROCESS: subprocess.Popen[str] | None = None
_PROCESS_SOURCE = ""
_POLL_SECONDS = 0.35
_AUTO_START_DELAY_MIN = 45.0
_AUTO_START_DELAY_MAX = 90.0
_INTERVAL_SECONDS = {
    "DAILY": 24 * 60 * 60,
    "WEEKLY": 7 * 24 * 60 * 60,
    "MONTHLY": 30 * 24 * 60 * 60,
}


def _preferences(context: bpy.types.Context | None = None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def _decode_build_value(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _tag_redraw() -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            area.tag_redraw()


def _notification_visible(preferences) -> bool:
    return (
        preferences.last_status == "AVAILABLE"
        and bool(preferences.latest_version)
        and bool(preferences.download_url)
        and preferences.dismissed_version != preferences.latest_version
    )


def _notification_version_text(preferences) -> str:
    """Keep daily-build hashes out of the compact status-bar label."""

    return preferences.latest_version.split(" (", 1)[0]


def _worker_command(preferences) -> list[str]:
    worker_path = Path(__file__).with_name("worker.py")
    python_args = tuple(getattr(bpy.app, "python_args", ("-I",)))
    version = ".".join(map(str, bpy.app.version))
    build_hash = _decode_build_value(bpy.app.build_hash)
    return [
        sys.executable,
        *python_args,
        str(worker_path),
        "--current-version",
        version,
        "--current-hash",
        build_hash,
        "--channel",
        preferences.update_channel.lower(),
        "--package-format",
        "auto",
    ]


def _start_worker(preferences, *, source: str) -> bool:
    global _PROCESS, _PROCESS_SOURCE

    if _PROCESS is not None:
        return False
    if not bpy.app.online_access:
        return False

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        _PROCESS = subprocess.Popen(
            _worker_command(preferences),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
    except OSError as exc:
        preferences.last_status = "ERROR"
        preferences.last_message = f"Could not start the update checker: {exc}"
        preferences.last_checked_at = time.time()
        preferences.last_channel = preferences.update_channel
        _PROCESS = None
        _PROCESS_SOURCE = ""
        _tag_redraw()
        return False

    _PROCESS_SOURCE = source
    preferences.last_status = "CHECKING"
    preferences.last_message = "Checking Blender's official build service…"
    _tag_redraw()
    return True


def _poll_worker() -> tuple[bool, dict[str, Any] | None]:
    """Poll and return ``(completed, result)``."""

    global _PROCESS, _PROCESS_SOURCE

    process = _PROCESS
    if process is None:
        return True, None
    if process.poll() is None:
        return False, None

    stdout, stderr = process.communicate()
    _PROCESS = None
    _PROCESS_SOURCE = ""

    try:
        result = json.loads(stdout)
        if not isinstance(result, dict):
            raise ValueError("worker result was not an object")
    except (json.JSONDecodeError, ValueError) as exc:
        detail = stderr.strip() or str(exc)
        result = {"ok": False, "error": f"The update checker failed: {detail}"}
    return True, result


def _apply_result(preferences, result: dict[str, Any] | None) -> tuple[str, str]:
    preferences.last_checked_at = time.time()
    preferences.last_channel = preferences.update_channel
    if not result or not result.get("ok"):
        message = str((result or {}).get("error", "The update checker stopped"))
        preferences.last_status = "ERROR"
        preferences.last_message = message[:1024]
        _tag_redraw()
        return "WARNING", preferences.last_message

    preferences.latest_version = str(result.get("display_version", ""))
    preferences.download_url = str(result.get("download_url", ""))
    if result.get("update_available"):
        preferences.last_status = "AVAILABLE"
        preferences.last_message = f"Blender {preferences.latest_version} is available"
        level = "INFO"
    else:
        preferences.last_status = "UP_TO_DATE"
        if result.get("channel") == "daily":
            preferences.last_message = "This daily build is current"
        else:
            preferences.last_message = "This Blender version is up to date"
        level = "INFO"
    _tag_redraw()
    return level, preferences.last_message


def _terminate_worker() -> None:
    global _PROCESS, _PROCESS_SOURCE

    process = _PROCESS
    _PROCESS = None
    _PROCESS_SOURCE = ""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()


def _auto_check_due(preferences) -> bool:
    if preferences.last_channel != preferences.update_channel:
        return True
    interval = _INTERVAL_SECONDS.get(preferences.check_interval, _INTERVAL_SECONDS["WEEKLY"])
    return time.time() - preferences.last_checked_at >= interval


def _automatic_check_timer() -> float | None:
    preferences = _preferences()
    if preferences is None:
        return None

    if _PROCESS is not None and _PROCESS_SOURCE == "auto":
        completed, result = _poll_worker()
        if not completed:
            return _POLL_SECONDS
        _apply_result(preferences, result)
        return None

    if not preferences.auto_check:
        return None
    if _PROCESS is not None:
        return None

    if not bpy.app.online_access or not _auto_check_due(preferences):
        return None
    if _start_worker(preferences, source="auto"):
        return _POLL_SECONDS
    return None


def _manual_background_timer() -> float | None:
    preferences = _preferences()
    if preferences is None or _PROCESS_SOURCE != "manual_background":
        return None
    completed, result = _poll_worker()
    if not completed:
        return _POLL_SECONDS
    _apply_result(preferences, result)
    return None


def _schedule_automatic_check() -> None:
    preferences = _preferences()
    is_registered = bpy.app.timers.is_registered(_automatic_check_timer)
    if preferences is None or not preferences.auto_check:
        if is_registered and _PROCESS_SOURCE != "auto":
            bpy.app.timers.unregister(_automatic_check_timer)
        return
    if not is_registered:
        bpy.app.timers.register(
            _automatic_check_timer,
            first_interval=random.uniform(_AUTO_START_DELAY_MIN, _AUTO_START_DELAY_MAX),
        )


def _auto_check_changed(_self, _context) -> None:
    _schedule_automatic_check()


def _update_channel_changed(self, _context) -> None:
    if self.last_channel and self.last_channel != self.update_channel:
        self.last_status = "NEVER"
        self.last_message = ""
        self.latest_version = ""
        self.download_url = ""
    _schedule_automatic_check()
    _tag_redraw()


def _show_statusbar_notification_get(self) -> bool:
    return not self.latest_version or self.dismissed_version != self.latest_version


def _show_statusbar_notification_set(self, value: bool) -> None:
    self.dismissed_version = "" if value else self.latest_version
    _tag_redraw()


class WM_OT_check_for_blender_updates(bpy.types.Operator):
    """Check Blender's official servers in a separate process"""

    bl_idname = "wm.check_for_blender_updates"
    bl_label = "Check for Blender Updates"
    bl_description = "Check for Blender updates"
    bl_options = {"INTERNAL"}

    _event_timer = None

    def _begin(self, context: bpy.types.Context, source: str) -> bool:
        preferences = _preferences(context)
        if preferences is None:
            self.report({"ERROR"}, "Could not access the extension preferences")
            return False
        if not bpy.app.online_access:
            self.report(
                {"WARNING"},
                "Online access is disabled in Blender's System preferences",
            )
            return False
        if _PROCESS is not None:
            self.report({"INFO"}, "An update check is already running")
            return False
        if not _start_worker(preferences, source=source):
            self.report({"ERROR"}, preferences.last_message or "Could not start update check")
            return False
        return True

    def invoke(self, context: bpy.types.Context, _event):
        source = "manual_modal" if context.window is not None else "manual_background"
        if not self._begin(context, source):
            return {"CANCELLED"}
        if context.window is None:
            if not bpy.app.timers.is_registered(_manual_background_timer):
                bpy.app.timers.register(_manual_background_timer, first_interval=_POLL_SECONDS)
            return {"FINISHED"}

        window_manager = context.window_manager
        self._event_timer = window_manager.event_timer_add(_POLL_SECONDS, window=context.window)
        window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Checking for Blender updates")
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context):
        if not self._begin(context, "manual_background"):
            return {"CANCELLED"}
        if not bpy.app.timers.is_registered(_manual_background_timer):
            bpy.app.timers.register(_manual_background_timer, first_interval=_POLL_SECONDS)
        self.report({"INFO"}, "Checking for Blender updates")
        return {"FINISHED"}

    def modal(self, context: bpy.types.Context, event):
        if event.type == "ESC":
            self.cancel(context)
            self.report({"INFO"}, "Update check cancelled")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        completed, result = _poll_worker()
        if not completed:
            return {"PASS_THROUGH"}

        self._remove_event_timer(context)
        preferences = _preferences(context)
        if preferences is None:
            self.report({"ERROR"}, "Could not save the update result")
            return {"CANCELLED"}
        level, message = _apply_result(preferences, result)
        self.report({level}, message)
        return {"FINISHED"}

    def _remove_event_timer(self, context: bpy.types.Context) -> None:
        if self._event_timer is not None:
            context.window_manager.event_timer_remove(self._event_timer)
            self._event_timer = None

    def cancel(self, context: bpy.types.Context) -> None:
        self._remove_event_timer(context)
        _terminate_worker()
        preferences = _preferences(context)
        if preferences is not None and preferences.last_status == "CHECKING":
            preferences.last_status = "NEVER"
            preferences.last_message = "Update check cancelled"
        _tag_redraw()


class WM_OT_set_blender_update_notification_visibility(bpy.types.Operator):
    """Show or dismiss the available-update notification"""

    bl_idname = "wm.set_blender_update_notification_visibility"
    bl_label = "Update Notification"
    bl_options = {"INTERNAL"}

    show: BoolProperty(default=False, options={"HIDDEN"})

    def execute(self, context: bpy.types.Context):
        preferences = _preferences(context)
        if preferences is None or preferences.last_status != "AVAILABLE":
            return {"CANCELLED"}

        preferences.dismissed_version = "" if self.show else preferences.latest_version
        _tag_redraw()
        if self.show:
            self.report({"INFO"}, "Update notification restored")
        else:
            self.report({"INFO"}, "Update notification dismissed for this version")
        return {"FINISHED"}


class BlenderUpdateCheckerPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    auto_check: BoolProperty(
        name="Automatically Check for Updates",
        description="Run a delayed automatic check when the saved interval has elapsed",
        default=False,
        update=_auto_check_changed,
    )
    update_channel: EnumProperty(
        name="Updates to Check",
        description="Choose which Blender release channel to compare",
        items=(
            (
                "STABLE",
                "Latest Stable Release",
                "Check for the newest public Blender release",
            ),
            (
                "SERIES",
                "Current Release Series",
                "Only check for corrective releases in this major/minor series",
            ),
            (
                "DAILY",
                "Daily Builds",
                "Check the latest official development build",
            ),
        ),
        default="STABLE",
        update=_update_channel_changed,
    )
    check_interval: EnumProperty(
        name="Check Frequency",
        description="Minimum time between automatic checks",
        items=(
            ("DAILY", "Daily", "Check at most once per day"),
            ("WEEKLY", "Weekly", "Check at most once per week"),
            ("MONTHLY", "Monthly", "Check at most once every 30 days"),
        ),
        default="WEEKLY",
        update=_auto_check_changed,
    )
    last_checked_at: FloatProperty(default=0.0, options={"HIDDEN"})
    last_channel: StringProperty(default="", options={"HIDDEN"})
    last_status: EnumProperty(
        items=(
            ("NEVER", "Never", "No check has completed"),
            ("CHECKING", "Checking", "A check is running"),
            ("UP_TO_DATE", "Up to Date", "No update is available"),
            ("AVAILABLE", "Available", "An update is available"),
            ("ERROR", "Error", "The last check failed"),
        ),
        default="NEVER",
        options={"HIDDEN"},
    )
    last_message: StringProperty(default="", options={"HIDDEN"})
    latest_version: StringProperty(default="", options={"HIDDEN"})
    download_url: StringProperty(default="", options={"HIDDEN"})
    dismissed_version: StringProperty(default="", options={"HIDDEN"})
    show_statusbar_notification: BoolProperty(
        name="Show Status-Bar Notification",
        description="Show the available update in the status bar for this version",
        get=_show_statusbar_notification_get,
        set=_show_statusbar_notification_set,
    )

    def draw(self, _context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "update_channel")
        layout.prop(self, "auto_check")
        frequency_row = layout.row()
        frequency_row.active = self.auto_check
        frequency_row.prop(self, "check_interval")

        layout.separator()
        status_box = layout.box()
        status_box.label(text="Update Status")
        if self.last_status == "CHECKING":
            status_box.label(text=self.last_message or "Checking…", icon="SORTTIME")
        elif self.last_status == "AVAILABLE":
            status_box.label(text=self.last_message, icon="INFO")
            if self.download_url:
                operator = status_box.operator(
                    "wm.url_open",
                    text="Open Official Download Page",
                    icon="URL",
                )
                operator.url = self.download_url
            status_box.prop(self, "show_statusbar_notification")
        elif self.last_status == "UP_TO_DATE":
            status_box.label(text=self.last_message, icon="CHECKMARK")
        elif self.last_status == "ERROR":
            status_box.label(text=self.last_message or "The last check failed", icon="ERROR")
        else:
            status_box.label(text="No update check has been run", icon="QUESTION")

        if self.last_checked_at > 0.0:
            checked = _datetime.datetime.fromtimestamp(self.last_checked_at).astimezone()
            status_box.label(text=f"Last checked: {checked:%Y-%m-%d %H:%M}")

        status_box.operator(
            WM_OT_check_for_blender_updates.bl_idname,
            text="Check Now",
            icon="FILE_REFRESH",
        )


def _draw_help_menu(self, context: bpy.types.Context) -> None:
    preferences = _preferences(context)
    layout = self.layout
    layout.separator()
    if preferences is not None and preferences.last_status == "AVAILABLE":
        operator = layout.operator(
            "wm.url_open",
            text=f"Blender {preferences.latest_version} Available",
            icon="INFO",
        )
        operator.url = preferences.download_url
    layout.operator(
        WM_OT_check_for_blender_updates.bl_idname,
        text="Check for Blender Updates",
        icon="FILE_REFRESH",
    )


def _draw_statusbar_update(self, context: bpy.types.Context) -> None:
    preferences = _preferences(context)
    if preferences is None or not _notification_visible(preferences):
        return

    row = self.layout.row(align=True)
    operator = row.operator(
        "wm.url_open",
        text=f"Update to {_notification_version_text(preferences)}",
        icon="IMPORT",
        depress=True,
    )
    operator.url = preferences.download_url
    operator = row.operator(
        "preferences.addon_show",
        text="",
        icon="PREFERENCES",
    )
    operator.module = __package__
    operator = row.operator(
        WM_OT_set_blender_update_notification_visibility.bl_idname,
        text="",
        icon="X",
    )
    operator.show = False


_CLASSES = (
    WM_OT_check_for_blender_updates,
    WM_OT_set_blender_update_notification_visibility,
    BlenderUpdateCheckerPreferences,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_help.append(_draw_help_menu)
    bpy.types.STATUSBAR_HT_header.append(_draw_statusbar_update)
    _schedule_automatic_check()


def unregister() -> None:
    if bpy.app.timers.is_registered(_automatic_check_timer):
        bpy.app.timers.unregister(_automatic_check_timer)
    if bpy.app.timers.is_registered(_manual_background_timer):
        bpy.app.timers.unregister(_manual_background_timer)
    _terminate_worker()
    bpy.types.STATUSBAR_HT_header.remove(_draw_statusbar_update)
    bpy.types.TOPBAR_MT_help.remove(_draw_help_menu)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
