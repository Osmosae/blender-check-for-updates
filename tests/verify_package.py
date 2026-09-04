"""Verify that a built extension archive exactly matches its release sources."""

from __future__ import annotations

import argparse
from pathlib import Path
import tomllib
import zipfile


RELEASE_FILES = {
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "__init__.py",
    "blender_manifest.toml",
    "release_provider.py",
    "worker.py",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", nargs="?", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / "blender_manifest.toml").read_text("utf-8"))
    version = str(manifest["version"])
    expected_name = f"{manifest['id']}-{version}.zip"
    archive = args.archive or root / expected_name

    if archive.name != expected_name:
        raise AssertionError(f"Expected package name {expected_name}, got {archive.name}")

    with zipfile.ZipFile(archive) as package:
        packaged_files = {name for name in package.namelist() if not name.endswith("/")}
        if packaged_files != RELEASE_FILES:
            missing = sorted(RELEASE_FILES - packaged_files)
            unexpected = sorted(packaged_files - RELEASE_FILES)
            raise AssertionError(f"Package mismatch; missing={missing}, unexpected={unexpected}")
        for relative_path in RELEASE_FILES:
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
