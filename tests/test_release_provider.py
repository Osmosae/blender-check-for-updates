from __future__ import annotations

import json
import unittest

import release_provider as provider


def build(
    version: str,
    *,
    cycle: str = "stable",
    build_hash: str = "abcdef123456",
    platform: str = "windows",
    architecture: str = "amd64",
    extension: str = "zip",
    mtime: int = 100,
) -> dict[str, object]:
    return {
        "app": "Blender",
        "version": version,
        "risk_id": cycle,
        "branch": "main" if cycle != "stable" else "v" + version.replace(".", "")[:2],
        "hash": build_hash,
        "platform": platform,
        "architecture": architecture,
        "bitness": 64,
        "file_mtime": mtime,
        "file_name": f"blender-{version}-{platform}.{architecture}.{extension}",
        "file_size": 123,
        "file_extension": extension,
        "release_cycle": cycle,
        "checksum": "00",
        "url": f"https://cdn.builder.blender.org/download/daily/{version}-{build_hash}.{extension}",
    }


class VersionTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(provider.parse_version("5.2.1"), (5, 2, 1))
        self.assertEqual(provider.parse_version((4, 5, 12)), (4, 5, 12))

    def test_rejects_incomplete_version(self) -> None:
        with self.assertRaises(provider.ReleaseProviderError):
            provider.parse_version("5.2")

    def test_platform_aliases(self) -> None:
        self.assertEqual(provider.platform_identity("win32", "AMD64"), ("windows", "amd64"))
        self.assertEqual(provider.platform_identity("darwin", "arm64"), ("darwin", "arm64"))
        self.assertEqual(provider.platform_identity("linux", "AMD64"), ("linux", "x86_64"))


class FeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            build("5.1.2", mtime=10),
            build("5.2.0", mtime=20),
            build("5.2.1", mtime=30),
            build("5.2.1", platform="linux", architecture="x86_64", extension="xz", mtime=31),
            build("5.3.0", cycle="alpha", build_hash="newdailyhash", mtime=40),
        ]
        self.payload = json.dumps(self.records)

    def test_parse_builds_ignores_untrusted_url(self) -> None:
        records = self.records + [
            {
                **build("9.9.9"),
                "url": "https://example.invalid/not-a-blender-build.zip",
            }
        ]
        parsed = provider.parse_builds(json.dumps(records))
        self.assertNotIn((9, 9, 9), [item["version_tuple"] for item in parsed])

    def test_selects_latest_stable_release(self) -> None:
        selected = provider.select_build(
            provider.parse_builds(self.payload),
            current_version=(5, 1, 0),
            channel="stable",
            build_platform="windows",
            architecture="amd64",
        )
        self.assertEqual(selected["version_tuple"], (5, 2, 1))

    def test_current_series_does_not_jump_to_new_series(self) -> None:
        selected = provider.select_build(
            provider.parse_builds(self.payload),
            current_version=(5, 1, 0),
            channel="series",
            build_platform="windows",
            architecture="amd64",
        )
        self.assertEqual(selected["version_tuple"], (5, 1, 2))

    def test_stable_result_reports_update(self) -> None:
        result = provider.check_for_updates(
            current_version=(5, 2, 0),
            current_hash="old",
            channel="stable",
            payload=self.payload,
            sys_platform="win32",
            machine="AMD64",
        )
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "5.2.1")
        self.assertEqual(result["download_url"], provider.STABLE_DOWNLOAD_URL)

    def test_stable_result_reports_current(self) -> None:
        result = provider.check_for_updates(
            current_version=(5, 2, 1),
            current_hash="irrelevant",
            channel="stable",
            payload=self.payload,
            sys_platform="win32",
            machine="AMD64",
        )
        self.assertFalse(result["update_available"])

    def test_daily_result_compares_build_hash(self) -> None:
        old_result = provider.check_for_updates(
            current_version=(5, 3, 0),
            current_hash="olddailyhash",
            channel="daily",
            payload=self.payload,
            sys_platform="win32",
            machine="AMD64",
        )
        current_result = provider.check_for_updates(
            current_version=(5, 3, 0),
            current_hash="newdailyhash",
            channel="daily",
            payload=self.payload,
            sys_platform="win32",
            machine="AMD64",
        )
        self.assertTrue(old_result["update_available"])
        self.assertFalse(current_result["update_available"])
        self.assertEqual(old_result["download_url"], provider.DAILY_DOWNLOAD_URL)

    def test_rejects_malformed_feed(self) -> None:
        with self.assertRaises(provider.ReleaseProviderError):
            provider.parse_builds("{}")


if __name__ == "__main__":
    unittest.main()
