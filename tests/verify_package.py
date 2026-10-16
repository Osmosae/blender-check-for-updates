"""Verify that a built extension archive exactly matches its release sources."""

from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path
import tomllib
import zipfile


def _included_by_manifest(relative_path: Path, patterns: list[str]) -> bool:
    """Apply the manifest's build exclusions to a source-relative path."""
    path = relative_path.as_posix()
    for raw_pattern in patterns:
        pattern = raw_pattern.replace("\\", "/")
        if pattern.endswith("/"):
            directory = pattern.rstrip("/")
            if path == directory or path.startswith(f"{directory}/"):
                return False
        elif fnmatch.fnmatchcase(path, pattern):
            return False
        elif "/" not in pattern and any(
            fnmatch.fnmatchcase(part, pattern) for part in relative_path.parts[:-1]
        ):
            return False
    return True


def _manifest_files(root: Path, patterns: list[str]) -> set[str]:
    """List files Blender's manifest policy includes in the source tree."""
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and ".git" not in path.relative_to(root).parts
        and _included_by_manifest(path.relative_to(root), patterns)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", nargs="?", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / "blender_manifest.toml").read_text("utf-8"))
    version = str(manifest["version"])
    exclusions = manifest.get("build", {}).get("paths_exclude_pattern", [])
    expected_files = _manifest_files(root, exclusions)
    expected_name = f"{manifest['id']}-{version}.zip"
    archive = args.archive or root / expected_name

    if archive.name != expected_name:
        raise AssertionError(f"Expected package name {expected_name}, got {archive.name}")

    with zipfile.ZipFile(archive) as package:
        packaged_files = {name for name in package.namelist() if not name.endswith("/")}
        if packaged_files != expected_files:
            missing = sorted(expected_files - packaged_files)
            unexpected = sorted(packaged_files - expected_files)
            raise AssertionError(f"Package mismatch; missing={missing}, unexpected={unexpected}")
        for relative_path in expected_files:
            source_bytes = (root / relative_path).read_bytes()
            if package.read(relative_path) != source_bytes:
                raise AssertionError(f"Packaged file differs from source: {relative_path}")

    provider_source = (root / "release_provider.py").read_text("utf-8")
    expected_agent = f'USER_AGENT = "Release-Watcher/{version}"'
    if expected_agent not in provider_source:
        raise AssertionError("Manifest version and network user-agent version differ")

    print(f"PACKAGE_VERIFY_OK: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
