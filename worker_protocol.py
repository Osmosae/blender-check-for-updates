"""Validated JSON protocol shared by the Blender add-on worker boundary.

This module intentionally uses only the standard library so ``worker.py`` can
load it directly from its sibling file while running Python in isolated mode.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, TypeAlias


class ProtocolError(ValueError):
    """A request or result did not match the worker protocol."""


@dataclass(frozen=True)
class WorkerRequest:
    current_version: str
    current_hash: str
    current_cycle: str
    current_commit_timestamp: int
    channel: str
    package_format: str

    @classmethod
    def from_values(
        cls,
        *,
        current_version: object,
        current_hash: object = "",
        current_cycle: object = "release",
        current_commit_timestamp: object = 0,
        channel: object,
        package_format: object = "auto",
    ) -> "WorkerRequest":
        version = _string(current_version, "current_version", nonempty=True)
        build_hash = _string(current_hash, "current_hash")
        cycle = _string(current_cycle, "current_cycle")
        timestamp = _integer(current_commit_timestamp, "current_commit_timestamp")
        requested_channel = _string(channel, "channel")
        package = _string(package_format, "package_format")
        if cycle not in {"alpha", "beta", "rc", "release"}:
            raise ProtocolError("Invalid current_cycle")
        if requested_channel not in {"stable", "series", "daily"}:
            raise ProtocolError("Invalid channel")
        return cls(version, build_hash, cycle, timestamp, requested_channel, package)


@dataclass(frozen=True)
class WorkerSuccess:
    update_available: bool
    current_version: str
    latest_version: str
    display_version: str
    latest_hash: str
    release_cycle: str
    channel: str
    download_url: str
    direct_download_url: str
    file_mtime: int


@dataclass(frozen=True)
class WorkerFailure:
    error: str


WorkerResult: TypeAlias = WorkerSuccess | WorkerFailure


_SUCCESS_FIELDS = (
    "update_available",
    "current_version",
    "latest_version",
    "display_version",
    "latest_hash",
    "release_cycle",
    "channel",
    "download_url",
    "direct_download_url",
    "file_mtime",
)


def failure(error: object) -> dict[str, object]:
    """Create the stable failure envelope, even for unusual exception values."""

    try:
        message = str(error)
    except Exception:
        message = "Worker failed"
    return {"ok": False, "error": message or type(error).__name__}


def parse_result(payload: str) -> WorkerResult:
    """Parse and validate a result JSON document from the worker."""

    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Worker result was not valid JSON") from exc
    if not isinstance(value, dict) or type(value.get("ok")) is not bool:
        raise ProtocolError("Worker result was not a valid object")
    if value["ok"] is False:
        return WorkerFailure(_string(value.get("error"), "error", nonempty=True))
    missing = [field for field in _SUCCESS_FIELDS if field not in value]
    if missing:
        raise ProtocolError("Worker success result is missing required fields")
    if type(value["update_available"]) is not bool:
        raise ProtocolError("Worker result field 'update_available' must be boolean")
    values: dict[str, Any] = {}
    for field in _SUCCESS_FIELDS:
        if field == "update_available":
            values[field] = value[field]
        elif field == "file_mtime":
            values[field] = _integer(value[field], field)
        else:
            values[field] = _string(value[field], field)
    return WorkerSuccess(**values)


def decode_result(stdout: str, stderr: str = "") -> dict[str, object]:
    """Validate worker stdout and return its compatible result mapping.

    ``stderr`` is accepted so the parent can pass both process streams at the
    boundary. It is intentionally not used when stdout contains a valid result.
    Malformed stdout raises :class:`ProtocolError`; callers can then surface
    stderr as diagnostic context.
    """

    del stderr
    return result_mapping(parse_result(stdout))


def result_mapping(result: WorkerResult) -> dict[str, object]:
    """Return a validated result as the compatible public JSON object."""

    if isinstance(result, WorkerFailure):
        return {"ok": False, "error": _string(result.error, "error", nonempty=True)}
    if isinstance(result, WorkerSuccess):
        return {"ok": True, **{field: getattr(result, field) for field in _SUCCESS_FIELDS}}
    raise ProtocolError("Unsupported worker result type")


def serialize_result(value: Mapping[str, object] | WorkerResult) -> str:
    """Validate a provider result and serialize it using compact JSON."""

    if isinstance(value, (WorkerSuccess, WorkerFailure)):
        mapping = result_mapping(value)
    elif isinstance(value, Mapping):
        mapping = dict(value)
        # Route through the same parser used by consumers to validate every field.
        mapping = result_mapping(parse_result(json.dumps(mapping)))
    else:
        raise ProtocolError("Worker result must be an object")
    return json.dumps(mapping, ensure_ascii=True, separators=(",", ":"))


def encode_result(value: Mapping[str, object] | WorkerResult) -> str:
    """Public protocol name for validating and serializing a result."""

    return serialize_result(value)


def _string(value: object, field: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ProtocolError(f"Worker protocol field '{field}' must be a string")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ProtocolError(f"Worker protocol field '{field}' must be an integer")
    return value
