"""Pure-Python release lookup and selection.

This module deliberately has no dependency on ``bpy`` so it can be imported by
the background worker and tested with a regular Python interpreter.
"""

from __future__ import annotations

import json
import platform as platform_module
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any


BUILDS_API_URL = "https://builder.blender.org/download/daily/?format=json&v=2"
STABLE_DOWNLOAD_URL = "https://www.blender.org/download/"
DAILY_DOWNLOAD_URL = "https://builder.blender.org/download/daily/"
USER_AGENT = "Blender-Update-Checker/0.3"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 8.0

_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TRUSTED_BUILD_HOSTS = {"cdn.builder.blender.org"}


class ReleaseProviderError(RuntimeError):
    """An expected lookup, validation, or network failure."""


def parse_version(value: str | Iterable[int]) -> tuple[int, int, int]:
    """Return a validated three-component Blender version tuple."""

    if isinstance(value, str):
        match = _VERSION_PATTERN.fullmatch(value.strip())
        if match is None:
            raise ReleaseProviderError(f"Invalid Blender version: {value!r}")
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]

    parts = tuple(int(part) for part in value)
    if len(parts) != 3 or any(part < 0 for part in parts):
        raise ReleaseProviderError(f"Invalid Blender version: {value!r}")
    return parts


def platform_identity(
    sys_platform: str | None = None,
    machine: str | None = None,
) -> tuple[str, str]:
    """Map Python's platform values to Blender's build-feed values."""

    sys_platform = (sys_platform or sys.platform).lower()
    machine = (machine or platform_module.machine()).lower()

    if sys_platform.startswith("win"):
        build_platform = "windows"
    elif sys_platform == "darwin":
        build_platform = "darwin"
    elif sys_platform.startswith("linux"):
        build_platform = "linux"
    else:
        raise ReleaseProviderError(f"Unsupported platform: {sys_platform}")

    architecture_aliases = {
        "amd64": "amd64" if build_platform == "windows" else "x86_64",
        "x86_64": "amd64" if build_platform == "windows" else "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    try:
        architecture = architecture_aliases[machine]
    except KeyError as exc:
        raise ReleaseProviderError(f"Unsupported architecture: {machine}") from exc

    return build_platform, architecture


def preferred_extension(build_platform: str, package_format: str) -> str:
    """Resolve an AUTO package choice to an extension used by the feed."""

    requested = package_format.lower()
    if requested != "auto":
        return requested
    return {
        "windows": "zip",
        "darwin": "dmg",
        "linux": "xz",
    }[build_platform]


def fetch_builds_json(
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Fetch Blender's official machine-readable builds listing."""

    request = urllib.request.Request(
        BUILDS_API_URL,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"application/json", "text/json", "text/plain"}:
                raise ReleaseProviderError(
                    f"Unexpected response type: {content_type or 'unknown'}"
                )
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ReleaseProviderError(f"Blender server returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ReleaseProviderError(f"Could not reach Blender's update server: {reason}") from exc
    except TimeoutError as exc:
        raise ReleaseProviderError("The Blender update check timed out") from exc

    if len(payload) > MAX_RESPONSE_BYTES:
        raise ReleaseProviderError("Blender's build listing was unexpectedly large")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseProviderError("Blender's build listing was not valid UTF-8") from exc


def parse_builds(payload: str) -> list[dict[str, Any]]:
    """Parse and minimally validate build records from the official feed."""

    try:
        raw_builds = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReleaseProviderError("Blender's build listing was not valid JSON") from exc
    if not isinstance(raw_builds, list):
        raise ReleaseProviderError("Blender's build listing had an unexpected shape")

    builds: list[dict[str, Any]] = []
    for raw in raw_builds:
        if not isinstance(raw, Mapping) or raw.get("app") != "Blender":
            continue
        try:
            version = parse_version(str(raw["version"]))
            url = str(raw["url"])
            hostname = urllib.parse.urlparse(url).hostname
            if hostname not in _TRUSTED_BUILD_HOSTS:
                continue
            file_mtime = int(raw["file_mtime"])
            if file_mtime < 0:
                continue
            build = dict(raw)
            build["version_tuple"] = version
            build["file_mtime"] = file_mtime
            builds.append(build)
        except (KeyError, TypeError, ValueError, ReleaseProviderError):
            continue

    if not builds:
        raise ReleaseProviderError("Blender's build listing contained no usable builds")
    return builds


def _select_package(
    builds: Iterable[Mapping[str, Any]],
    *,
    build_platform: str,
    architecture: str,
    package_format: str,
) -> Mapping[str, Any] | None:
    matching_platform = [
        build
        for build in builds
        if build.get("platform") == build_platform
        and build.get("architecture") == architecture
    ]
    if not matching_platform:
        return None

    extension = preferred_extension(build_platform, package_format)
    matching_format = [
        build for build in matching_platform if build.get("file_extension") == extension
    ]
    choices = matching_format or matching_platform
    return max(choices, key=lambda build: int(build.get("file_mtime", 0)))


def select_build(
    builds: Iterable[Mapping[str, Any]],
    *,
    current_version: tuple[int, int, int],
    channel: str,
    build_platform: str,
    architecture: str,
    package_format: str = "auto",
) -> Mapping[str, Any]:
    """Select the relevant release for the configured channel and machine."""

    channel = channel.lower()
    all_builds = list(builds)
    if channel in {"stable", "series"}:
        candidates = [
            build for build in all_builds if build.get("release_cycle") == "stable"
        ]
        if channel == "series":
            candidates = [
                build
                for build in candidates
                if tuple(build["version_tuple"][:2]) == current_version[:2]
            ]
    elif channel == "daily":
        candidates = [
            build for build in all_builds if build.get("release_cycle") != "stable"
        ]
    else:
        raise ReleaseProviderError(f"Unknown update channel: {channel}")

    if not candidates:
        label = "current release series" if channel == "series" else channel
        raise ReleaseProviderError(f"No builds were listed for the {label}")

    newest_version = max(tuple(build["version_tuple"]) for build in candidates)
    newest = [
        build for build in candidates if tuple(build["version_tuple"]) == newest_version
    ]
    selected = _select_package(
        newest,
        build_platform=build_platform,
        architecture=architecture,
        package_format=package_format,
    )
    if selected is None:
        raise ReleaseProviderError(
            f"No {build_platform} {architecture} build was listed for "
            f"{'.'.join(map(str, newest_version))}"
        )
    return selected


def check_for_updates(
    *,
    current_version: tuple[int, int, int],
    current_hash: str,
    channel: str,
    package_format: str = "auto",
    payload: str | None = None,
    sys_platform: str | None = None,
    machine: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable update result."""

    current_version = parse_version(current_version)
    build_platform, architecture = platform_identity(sys_platform, machine)
    builds = parse_builds(payload if payload is not None else fetch_builds_json())
    selected = select_build(
        builds,
        current_version=current_version,
        channel=channel,
        build_platform=build_platform,
        architecture=architecture,
        package_format=package_format,
    )

    latest_version = tuple(selected["version_tuple"])
    latest_hash = str(selected.get("hash", ""))
    is_daily = channel.lower() == "daily"
    if is_daily:
        update_available = latest_version > current_version or (
            latest_version == current_version
            and bool(latest_hash)
            and latest_hash != current_hash
        )
    else:
        update_available = latest_version > current_version

    version_text = ".".join(map(str, latest_version))
    cycle = str(selected.get("release_cycle", ""))
    if is_daily and cycle:
        display_version = f"{version_text} {cycle} ({latest_hash[:12]})"
        download_url = DAILY_DOWNLOAD_URL
    else:
        display_version = version_text
        download_url = STABLE_DOWNLOAD_URL

    return {
        "ok": True,
        "update_available": update_available,
        "current_version": ".".join(map(str, current_version)),
        "latest_version": version_text,
        "display_version": display_version,
        "latest_hash": latest_hash,
        "release_cycle": cycle,
        "channel": channel.lower(),
        "download_url": download_url,
        "direct_download_url": str(selected["url"]),
        "file_mtime": int(selected["file_mtime"]),
    }
