"""Pure-Python release lookup and selection.

This module deliberately has no dependency on ``bpy`` so it can be imported by
the background worker and tested with a regular Python interpreter.
"""

from __future__ import annotations

import datetime as datetime_module
from html.parser import HTMLParser
import json
import platform as platform_module
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any


BUILDS_API_URL = "https://builder.blender.org/download/daily/?format=json&v=2"
STABLE_DOWNLOAD_URL = "https://www.blender.org/download/"
DAILY_DOWNLOAD_URL = "https://builder.blender.org/download/daily/"
USER_AGENT = "Release-Watcher/1.3.0"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 8.0
COMMIT_API_URL = "https://projects.blender.org/api/v1/repos/blender/blender/git/commits/"

_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TRUSTED_BUILD_HOSTS = {"cdn.builder.blender.org"}
_PACKAGE_EXTENSIONS = {"zip", "msi", "msix", "dmg", "xz"}
_CYCLE_RANK = {"alpha": 0, "beta": 1, "rc": 2, "stable": 3}
_BUILD_FILENAME_PATTERN = re.compile(
    r"^blender-(?P<version>\d+\.\d+\.\d+)-"
    r"(?P<release_cycle>alpha|beta|rc|candidate|stable)\+"
    r"(?P<branch>[\w.-]+)\.(?P<hash>[0-9a-fA-F]{7,40})-"
    r"(?P<platform>windows|darwin|linux)\."
    r"(?P<architecture>amd64|x86_64|arm64)-release\."
    r"(?P<file_extension>zip|msi|msix|dmg|tar\.xz)$"
)


class ReleaseProviderError(RuntimeError):
    """An expected lookup, validation, or network failure."""


@dataclass(frozen=True)
class Build(Mapping[str, Any]):
    """A normalized, immutable build accepted from an official listing.

    The mapping interface keeps the parsed result convenient for older callers,
    while provider internals use the validated attributes directly.
    """

    version_tuple: tuple[int, int, int]
    release_cycle: str
    platform: str
    architecture: str
    file_extension: str
    hash: str
    url: str
    file_mtime: int
    file_name: str

    def __getitem__(self, key: str) -> Any:
        if key == "version":
            return ".".join(map(str, self.version_tuple))
        if key == "version_tuple":
            return self.version_tuple
        if key in {
            "release_cycle", "platform", "architecture", "file_extension",
            "hash", "url", "file_mtime", "file_name",
        }:
            return getattr(self, key)
        raise KeyError(key)

    def __iter__(self):
        return iter((
            "version", "version_tuple", "release_cycle", "platform",
            "architecture", "file_extension", "hash", "url", "file_mtime",
            "file_name",
        ))

    def __len__(self) -> int:
        return 10


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


def _fetch_text(
    url: str,
    *,
    content_types: set[str],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Fetch a bounded UTF-8 response from an official Blender service."""

    request = urllib.request.Request(
        url,
        headers={"Accept": ", ".join(sorted(content_types)), "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type not in content_types:
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


def fetch_builds_json(
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Fetch Blender's official machine-readable builds listing."""

    return _fetch_text(
        BUILDS_API_URL,
        content_types={"application/json", "text/json", "text/plain"},
        timeout=timeout,
        opener=opener,
    )


def _iso_timestamp(value: str) -> int:
    parsed = datetime_module.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp is missing its timezone")
    return int(parsed.timestamp())


class _BuildListingParser(HTMLParser):
    """Read download URLs and ISO dates from the official build table."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "li" and "build" in classes:
            self._row = {}
        if self._row is None:
            return
        if tag == "a" and "b-version" in classes:
            url = attributes.get("href") or ""
            name = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])
            match = _BUILD_FILENAME_PATTERN.fullmatch(name)
            if match:
                self._row.update(match.groupdict())
                self._row.update(app="Blender", url=url, file_name=name)
                if self._row["file_extension"] == "tar.xz":
                    self._row["file_extension"] = "xz"
        if "b-date" in classes:
            try:
                self._row["file_mtime"] = _iso_timestamp(attributes.get("title") or "")
            except (ValueError, OverflowError):
                pass

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._row is not None:
            self.records.append(self._row)
            self._row = None


def parse_builds_html(payload: str) -> list[Build]:
    parser = _BuildListingParser()
    parser.feed(payload)
    parser.close()
    return _validate_builds(parser.records)


def fetch_builds(
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[Build]:
    """Use the download table when the JSON service is unavailable or broken."""

    try:
        return parse_builds(fetch_builds_json(timeout=timeout, opener=opener))
    except ReleaseProviderError as json_error:
        try:
            return parse_builds_html(_fetch_text(
                DAILY_DOWNLOAD_URL,
                content_types={"text/html"},
                timeout=timeout,
                opener=opener,
            ))
        except ReleaseProviderError as html_error:
            raise ReleaseProviderError(
                f"Blender's build service is unavailable. JSON feed: {json_error}. "
                f"Download listing: {html_error}"
            ) from html_error


def fetch_commit_timestamp(build_hash: str) -> int:
    """Use commit time, not archive upload time, to establish build ordering."""

    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", build_hash):
        raise ReleaseProviderError("The build listing did not provide a valid commit hash")
    payload = _fetch_text(
        COMMIT_API_URL + build_hash,
        content_types={"application/json"},
    )
    try:
        record = json.loads(payload)
        resolved_hash = record["sha"].lower()
        if not resolved_hash.startswith(build_hash.lower()):
            raise ValueError("Commit hash did not match the requested build")
        return _iso_timestamp(record["commit"]["committer"]["date"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise ReleaseProviderError("Blender's commit information was not valid") from exc


def parse_builds(payload: str) -> list[Build]:
    """Parse and minimally validate build records from the official feed."""

    try:
        raw_builds = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReleaseProviderError("Blender's build listing was not valid JSON") from exc
    if not isinstance(raw_builds, list):
        raise ReleaseProviderError("Blender's build listing had an unexpected shape")
    return _validate_builds(raw_builds)


def _validate_builds(raw_builds: Iterable[Any]) -> list[Build]:
    builds: list[Build] = []
    for raw in raw_builds:
        if not isinstance(raw, Mapping) or raw.get("app") != "Blender":
            continue
        try:
            version = parse_version(str(raw["version"]))
            url = str(raw["url"])
            parsed_url = urllib.parse.urlparse(url)
            if (
                parsed_url.scheme != "https"
                or parsed_url.hostname not in _TRUSTED_BUILD_HOSTS
            ):
                continue
            file_mtime = int(raw["file_mtime"])
            if file_mtime < 0:
                continue
            cycle = str(raw.get("release_cycle", "")).lower()
            cycle = "rc" if cycle == "candidate" else cycle
            build_platform = str(raw["platform"]).lower()
            architecture = str(raw["architecture"]).lower()
            extension = str(raw["file_extension"]).lower()
            build_hash = str(raw["hash"]).strip().lower()
            filename = urllib.parse.unquote(parsed_url.path.rsplit("/", 1)[-1]).lower()
            expected_suffixes = {
                "zip": (".zip",),
                "msi": (".msi",),
                "msix": (".msix",),
                "dmg": (".dmg",),
                "xz": (".tar.xz", ".xz"),
            }
            declared_filename = str(raw.get("file_name", ""))
            if (
                cycle not in _CYCLE_RANK
                or build_platform not in {"windows", "darwin", "linux"}
                or architecture not in {"amd64", "x86_64", "arm64"}
                or (build_platform == "windows" and architecture == "x86_64")
                or (build_platform != "windows" and architecture == "amd64")
                or extension not in _PACKAGE_EXTENSIONS
                or not re.fullmatch(r"[0-9a-f]{7,40}", build_hash)
                or not filename.endswith(expected_suffixes.get(extension, ()))
                or (declared_filename and declared_filename.lower() != filename)
                or parsed_url.path.endswith((".sha256", ".sha512", ".md5"))
            ):
                continue
            builds.append(Build(
                version_tuple=version,
                release_cycle=cycle,
                platform=build_platform,
                architecture=architecture,
                file_extension=extension,
                hash=build_hash,
                url=url,
                file_mtime=file_mtime,
                file_name=declared_filename or filename,
            ))
        except (KeyError, TypeError, ValueError, ReleaseProviderError):
            continue

    if not builds:
        raise ReleaseProviderError("Blender's build listing contained no usable builds")
    return builds


def _select_package(
    builds: Iterable[Build],
    *,
    build_platform: str,
    architecture: str,
    package_format: str,
) -> Build | None:
    matching_platform = [
        build
        for build in builds
        if build.platform == build_platform
        and build.architecture == architecture
    ]
    if not matching_platform:
        return None

    extension = preferred_extension(build_platform, package_format)
    matching_format = [
        build for build in matching_platform if build.file_extension == extension
    ]
    choices = matching_format or matching_platform
    return max(choices, key=lambda build: build.file_mtime)


def select_build(
    builds: Iterable[Build],
    *,
    current_version: tuple[int, int, int],
    current_cycle: str = "release",
    channel: str,
    build_platform: str,
    architecture: str,
    package_format: str = "auto",
) -> Build:
    """Select the relevant release for the configured channel and machine."""

    channel = channel.lower()
    all_builds = list(builds)
    if channel in {"stable", "series"}:
        follow_prereleases = (
            channel == "series" and current_cycle in {"alpha", "beta", "rc"}
        )
        candidates = [
            build
            for build in all_builds
            if follow_prereleases or build.release_cycle == "stable"
        ]
        if channel == "series":
            candidates = [
                build
                for build in candidates
                if build.version_tuple[:2] == current_version[:2]
            ]
    elif channel == "daily":
        candidates = [
            build for build in all_builds if build.release_cycle != "stable"
        ]
    else:
        raise ReleaseProviderError(f"Unknown update channel: {channel}")

    if not candidates:
        label = "current release series" if channel == "series" else channel
        raise ReleaseProviderError(f"No builds were listed for the {label}")

    compatible_candidates = [
        build
        for build in candidates
        if build.platform == build_platform
        and build.architecture == architecture
    ]
    if not compatible_candidates:
        label = "current release series" if channel == "series" else channel
        raise ReleaseProviderError(
            f"No {build_platform} {architecture} builds were listed for the {label}"
        )

    newest_version = max(
        build.version_tuple for build in compatible_candidates
    )
    newest = [
        build
        for build in compatible_candidates
        if build.version_tuple == newest_version
    ]
    newest_cycle = max(_CYCLE_RANK[build.release_cycle] for build in newest)
    newest = [
        build
        for build in newest
        if _CYCLE_RANK[build.release_cycle] == newest_cycle
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
    current_version: str | Iterable[int],
    current_hash: str,
    current_cycle: str = "release",
    current_commit_timestamp: int = 0,
    channel: str,
    package_format: str = "auto",
    payload: str | None = None,
    sys_platform: str | None = None,
    machine: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable update result."""

    current_version = parse_version(current_version)
    build_platform, architecture = platform_identity(sys_platform, machine)
    builds = parse_builds(payload) if payload is not None else fetch_builds()
    selected = select_build(
        builds,
        current_version=current_version,
        current_cycle=current_cycle,
        channel=channel,
        build_platform=build_platform,
        architecture=architecture,
        package_format=package_format,
    )

    latest_version = selected.version_tuple
    latest_hash = selected.hash
    current_hash = current_hash.strip().lower()
    is_daily = channel.lower() == "daily"
    cycle = selected.release_cycle
    current_cycle = "stable" if current_cycle == "release" else current_cycle
    update_available = latest_version > current_version
    if latest_version == current_version:
        latest_rank = _CYCLE_RANK[cycle]
        current_rank = _CYCLE_RANK.get(current_cycle, _CYCLE_RANK["stable"])
        if latest_rank > current_rank:
            update_available = True
        elif (
            latest_rank == current_rank
            and (is_daily or channel.lower() == "series")
            and cycle != "stable"
        ):
            same_hash = bool(current_hash and latest_hash) and (
                current_hash.startswith(latest_hash) or latest_hash.startswith(current_hash)
            )
            if not same_hash:
                if current_commit_timestamp <= 0:
                    raise ReleaseProviderError(
                        "Could not determine the installed build's commit time"
                    )
                try:
                    latest_commit_timestamp = fetch_commit_timestamp(latest_hash)
                except ReleaseProviderError as exc:
                    raise ReleaseProviderError(
                        f"Could not verify whether the listed build is newer: {exc}"
                    ) from exc
                update_available = latest_commit_timestamp > current_commit_timestamp

    version_text = ".".join(map(str, latest_version))
    if cycle != "stable":
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
        "direct_download_url": selected.url,
        "file_mtime": selected.file_mtime,
    }
