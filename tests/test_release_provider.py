from __future__ import annotations

import json
import unittest
import urllib.error

import release_provider as provider


class FakeHeaders:
    def __init__(self, content_type: str = "application/json") -> None:
        self.content_type = content_type

    def get_content_type(self) -> str:
        return self.content_type


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "application/json") -> None:
        self.payload = payload
        self.headers = FakeHeaders(content_type)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.payload[:size]


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

    def test_parse_builds_requires_https(self) -> None:
        records = self.records + [
            {
                **build("9.9.9"),
                "url": "http://cdn.builder.blender.org/download/daily/untrusted.zip",
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

    def test_selects_newest_release_available_for_platform(self) -> None:
        records = self.records + [
            build(
                "5.2.2",
                platform="linux",
                architecture="x86_64",
                extension="xz",
                mtime=50,
            )
        ]
        selected = provider.select_build(
            provider.parse_builds(json.dumps(records)),
            current_version=(5, 2, 0),
            channel="stable",
            build_platform="windows",
            architecture="amd64",
        )
        self.assertEqual(selected["version_tuple"], (5, 2, 1))

    def test_reports_when_channel_has_no_compatible_platform(self) -> None:
        records = [
            build(
                "5.2.2",
                platform="linux",
                architecture="x86_64",
                extension="xz",
            )
        ]
        with self.assertRaisesRegex(
            provider.ReleaseProviderError,
            "No windows amd64 builds were listed for the stable",
        ):
            provider.select_build(
                provider.parse_builds(json.dumps(records)),
                current_version=(5, 2, 0),
                channel="stable",
                build_platform="windows",
                architecture="amd64",
            )

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
            current_version="5.2.1",
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


class NetworkTests(unittest.TestCase):
    def test_fetches_bounded_json_response(self) -> None:
        payload = b'[{"app":"Blender"}]'

        def opener(request, *, timeout):
            self.assertEqual(request.full_url, provider.BUILDS_API_URL)
            self.assertEqual(timeout, 2.5)
            return FakeResponse(payload)

        self.assertEqual(
            provider.fetch_builds_json(timeout=2.5, opener=opener),
            payload.decode("utf-8"),
        )

    def test_rejects_unexpected_content_type(self) -> None:
        opener = lambda _request, **_kwargs: FakeResponse(b"[]", "text/html")
        with self.assertRaisesRegex(provider.ReleaseProviderError, "response type"):
            provider.fetch_builds_json(opener=opener)

    def test_rejects_oversized_response(self) -> None:
        payload = b"x" * (provider.MAX_RESPONSE_BYTES + 1)
        opener = lambda _request, **_kwargs: FakeResponse(payload)
        with self.assertRaisesRegex(provider.ReleaseProviderError, "unexpectedly large"):
            provider.fetch_builds_json(opener=opener)

    def test_rejects_invalid_utf8(self) -> None:
        opener = lambda _request, **_kwargs: FakeResponse(b"\xff")
        with self.assertRaisesRegex(provider.ReleaseProviderError, "valid UTF-8"):
            provider.fetch_builds_json(opener=opener)

    def test_wraps_network_error(self) -> None:
        def opener(_request, **_kwargs):
            raise urllib.error.URLError("offline")

        with self.assertRaisesRegex(provider.ReleaseProviderError, "Could not reach"):
            provider.fetch_builds_json(opener=opener)

    def test_wraps_timeout(self) -> None:
        def opener(_request, **_kwargs):
            raise TimeoutError

        with self.assertRaisesRegex(provider.ReleaseProviderError, "timed out"):
            provider.fetch_builds_json(opener=opener)


if __name__ == "__main__":
    unittest.main()
