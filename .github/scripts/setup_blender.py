"""Download, checksum, and prepare the Blender version selected by CI."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile


def download(url: str, destination: Path) -> None:
    """Download a URL with bounded retries, replacing partial files on failure."""
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Release-Watcher-CI"})
            with urllib.request.urlopen(request, timeout=60) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
            return
        except (OSError, urllib.error.URLError):
            destination.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2**attempt)


def main() -> None:
    version = os.environ["BLENDER_VERSION"]
    runner_temp = Path(os.environ["RUNNER_TEMP"])
    cache = runner_temp / "blender-cache"
    cache.mkdir(parents=True, exist_ok=True)
    config = runner_temp / "blender-config"
    extensions = runner_temp / "blender-extensions"
    config.mkdir(parents=True, exist_ok=True)
    extensions.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        platform_name, suffix = "windows-x64", "zip"
    elif sys.platform == "darwin":
        if platform.machine().lower() not in {"arm64", "aarch64"}:
            raise RuntimeError("CI Blender package smoke expects macOS ARM64")
        platform_name, suffix = "macos-arm64", "dmg"
    elif sys.platform.startswith("linux"):
        platform_name, suffix = "linux-x64", "tar.xz"
    else:
        raise RuntimeError(f"Unsupported CI platform: {sys.platform}")

    archive = f"blender-{version}-{platform_name}.{suffix}"
    release_series = ".".join(version.split(".")[:-1])
    base_url = f"https://download.blender.org/release/Blender{release_series}"
    archive_path = cache / archive
    if not archive_path.is_file():
        download(f"{base_url}/{archive}", archive_path)

    checksum_path = cache / "checksums.sha256"
    download(f"{base_url}/blender-{version}.sha256", checksum_path)
    checksum_line = next(
        (
            line.strip()
            for line in checksum_path.read_text("utf-8").splitlines()
            if line.strip().endswith(f" {archive}")
            or line.strip().endswith(f"*{archive}")
        ),
        None,
    )
    if checksum_line is None:
        raise RuntimeError(f"Checksum not found for {archive}")
    expected_hash = checksum_line.split()[0].lower()
    digest = hashlib.sha256()
    with archive_path.open("rb") as archive_file:
        for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    if actual_hash != expected_hash:
        archive_path.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {archive}")

    if suffix == "tar.xz":
        with tarfile.open(archive_path, "r:xz") as package:
            package.extractall(runner_temp)
        blender_bin = runner_temp / f"blender-{version}-linux-x64" / "blender"
    elif suffix == "zip":
        with zipfile.ZipFile(archive_path) as package:
            package.extractall(runner_temp)
        blender_bin = runner_temp / f"blender-{version}-windows-x64" / "blender.exe"
    else:
        mount_point = runner_temp / "blender-mount"
        mount_point.mkdir(exist_ok=True)
        subprocess.run(
            ["hdiutil", "attach", str(archive_path), "-nobrowse", "-readonly", "-mountpoint", str(mount_point)],
            check=True,
        )
        blender_bin = mount_point / "Blender.app" / "Contents" / "MacOS" / "Blender"

    if not blender_bin.is_file():
        raise RuntimeError(f"Blender executable not found: {blender_bin}")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8", newline="\n") as env_file:
        env_file.write(f"BLENDER_BIN={blender_bin}\n")
        env_file.write(f"BLENDER_USER_CONFIG={config}\n")
        env_file.write(f"BLENDER_USER_EXTENSIONS={extensions}\n")


if __name__ == "__main__":
    main()
