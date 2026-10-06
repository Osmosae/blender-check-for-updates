from __future__ import annotations

import json
import unittest
from unittest.mock import patch
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
            build("5.3.0", cycle="alpha", build_hash="abcdef123456", mtime=40),
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

    @patch.object(provider, "fetch_commit_timestamp", return_value=40)
    def test_daily_result_compares_build_hash(self, fetch_timestamp) -> None:
        old_result = provider.check_for_updates(
            current_version=(5, 3, 0),
            current_hash="111111111111",
            current_cycle="alpha",
            current_commit_timestamp=30,
            channel="daily",
            payload=self.payload,
            sys_platform="win32",
            machine="AMD64",
        )
        current_result = provider.check_for_updates(
            current_version=(5, 3, 0),
            current_hash="abcdef123456",
            current_cycle="alpha",
            current_commit_timestamp=40,
            channel="daily",
            payload=self.payload,
            sys_platform="win32",
            machine="AMD64",
        )
        self.assertTrue(old_result["update_available"])
        self.assertFalse(current_result["update_available"])
        self.assertEqual(old_result["download_url"], provider.DAILY_DOWNLOAD_URL)
        fetch_timestamp.assert_called_once_with("abcdef123456")

    def check_beta(self, records, **overrides):
        arguments = dict(
            current_version="5.3.0",
            current_hash="111111111111",
            current_cycle="beta",
            current_commit_timestamp=100,
            channel="series",
            payload=json.dumps(records),
            sys_platform="win32",
            machine="AMD64",
        )
        arguments.update(overrides)
        return provider.check_for_updates(**arguments)

    @patch.object(provider, "fetch_commit_timestamp", return_value=110)
    def test_beta_series_tracks_same_version_not_next_alpha(self, fetch_timestamp) -> None:
        result = self.check_beta([
            build("5.3.0", cycle="beta", mtime=120),
            build("5.4.0", cycle="alpha", mtime=130),
        ])
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "5.3.0")
        self.assertEqual(result["release_cycle"], "beta")
        self.assertIn("abcdef123456", result["display_version"])
        fetch_timestamp.assert_called_once()

    @patch.object(provider, "fetch_commit_timestamp")
    def test_daily_can_offer_next_alpha_to_beta_user(self, fetch_timestamp) -> None:
        result = self.check_beta([
            build("5.3.0", cycle="beta"),
            build("5.4.0", cycle="alpha"),
        ], channel="daily")
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "5.4.0")
        fetch_timestamp.assert_not_called()

    @patch.object(provider, "fetch_commit_timestamp")
    def test_same_hash_accepts_short_or_full_case_insensitive_hash(self, fetch_timestamp) -> None:
        for current_hash in ("ABCDEF123456", "abcdef123456" + "0" * 28):
            with self.subTest(current_hash=current_hash):
                result = self.check_beta([build("5.3.0", cycle="beta")], current_hash=current_hash)
                self.assertFalse(result["update_available"])
        fetch_timestamp.assert_not_called()

    @patch.object(provider, "fetch_commit_timestamp", return_value=90)
    def test_older_commit_is_not_update_despite_later_upload(self, _fetch_timestamp) -> None:
        result = self.check_beta([build("5.3.0", cycle="beta", mtime=1000)])
        self.assertFalse(result["update_available"])

    @patch.object(provider, "fetch_commit_timestamp", side_effect=provider.ReleaseProviderError("offline"))
    def test_unverified_commit_reports_error(self, _fetch_timestamp) -> None:
        with self.assertRaisesRegex(provider.ReleaseProviderError, "Could not verify"):
            self.check_beta([build("5.3.0", cycle="beta")])

    def test_beta_to_final_is_update_without_number_change(self) -> None:
        for channel in ("stable", "series"):
            with self.subTest(channel=channel):
                result = self.check_beta([build("5.3.0")], channel=channel)
                self.assertTrue(result["update_available"])
                self.assertEqual(result["download_url"], provider.STABLE_DOWNLOAD_URL)

    def test_rc_selected_over_stale_beta_and_alpha(self) -> None:
        result = self.check_beta([
            build("5.3.0", cycle="alpha", mtime=300),
            build("5.3.0", cycle="beta", mtime=200),
            build("5.3.0", cycle="candidate", mtime=100),
        ])
        self.assertTrue(result["update_available"])
        self.assertEqual(result["release_cycle"], "rc")

    def test_stable_series_does_not_offer_next_prerelease(self) -> None:
        result = self.check_beta([
            build("5.3.0"),
            build("5.3.1", cycle="rc", mtime=200),
        ], current_cycle="release")
        self.assertFalse(result["update_available"])

    def test_daily_does_not_downgrade_release_stage_or_version(self) -> None:
        for version, cycle in (("5.3.0", "alpha"), ("5.2.3", "rc")):
            with self.subTest(version=version, cycle=cycle):
                result = self.check_beta([build(version, cycle=cycle)], channel="daily")
                self.assertFalse(result["update_available"])

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


def html_build(
    filename="blender-5.3.0-beta+v53.abcdef123456-windows.amd64-release.zip",
    *,
    date="2026-10-15T05:42:10+00:00",
    host="cdn.builder.blender.org",
):
    return (
        '<li class="t-row build is-windows">'
        f'<a class="t-cell b-version" href="https://{host}/download/daily/{filename}">Blender</a>'
        f'<div class="t-cell b-date" title="{date}">15 Oct 05:42</div></li>'
    )


class FallbackTests(unittest.TestCase):
    def test_parses_download_rows_ignoring_checksums_and_untrusted_hosts(self) -> None:
        filename = "blender-5.3.0-beta+v53.abcdef123456-windows.amd64-release.zip"
        payload = "<html><ul>" + "".join([
            html_build(filename + ".sha256"),
            html_build(filename),
            html_build(host="example.invalid"),
            html_build(date="not a date"),
            html_build(filename.replace("-release.zip", "-debug.zip")),
        ]) + "</ul></html>"
        builds = provider.parse_builds_html(payload)
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]["hash"], "abcdef123456")
        self.assertEqual(builds[0]["version_tuple"], (5, 3, 0))
        self.assertEqual(builds[0]["file_mtime"], 1792042930)

    def test_parses_mac_and_linux_packages(self) -> None:
        for platform, arch, extension, expected in (
            ("darwin", "arm64", "dmg", "dmg"),
            ("linux", "x86_64", "tar.xz", "xz"),
        ):
            with self.subTest(platform=platform):
                rows = provider.parse_builds_html(html_build(
                    f"blender-5.3.0-beta+v53.abcdef123456-{platform}.{arch}-release.{extension}"
                ))
                self.assertEqual(rows[0]["platform"], platform)
                self.assertEqual(rows[0]["architecture"], arch)
                self.assertEqual(rows[0]["file_extension"], expected)

    def test_healthy_json_feed_does_not_request_html(self) -> None:
        calls = []

        def opener(request, **_kwargs):
            calls.append(request.full_url)
            return FakeResponse(json.dumps([build("5.3.0", cycle="beta")]).encode())

        self.assertEqual(len(provider.fetch_builds(opener=opener)), 1)
        self.assertEqual(calls, [provider.BUILDS_API_URL])

    def test_php_fatal_error_labelled_json_uses_html_fallback(self) -> None:
        calls = []

        def opener(request, **_kwargs):
            calls.append(request.full_url)
            if request.full_url == provider.BUILDS_API_URL:
                return FakeResponse(b"<br /><b>Fatal error</b>: undefined method")
            return FakeResponse(html_build().encode(), "text/html")

        builds = provider.fetch_builds(opener=opener)
        self.assertEqual(builds[0]["version_tuple"], (5, 3, 0))
        self.assertEqual(calls, [provider.BUILDS_API_URL, provider.DAILY_DOWNLOAD_URL])

    def test_both_broken_sources_report_service_error(self) -> None:
        def opener(request, **_kwargs):
            return FakeResponse(b"error", "application/json" if "format=json" in request.full_url else "text/html")

        with self.assertRaisesRegex(provider.ReleaseProviderError, "build service is unavailable"):
            provider.fetch_builds(opener=opener)

    def test_json_checksum_is_not_selected_as_build(self) -> None:
        package = build("5.3.0", cycle="beta")
        checksum = {**package, "url": package["url"] + ".sha256", "file_mtime": 200}
        self.assertEqual(len(provider.parse_builds(json.dumps([package, checksum]))), 1)


class CommitTests(unittest.TestCase):
    @patch.object(provider, "_fetch_text")
    def test_uses_committer_not_author_or_upload_time(self, fetch_text) -> None:
        fetch_text.return_value = json.dumps({
            "sha": "abcdef123456" + "0" * 28,
            "commit": {
                "author": {"date": "2026-10-01T00:00:00Z"},
                "committer": {"date": "2026-10-15T12:15:01+11:00"},
            },
        })
        self.assertEqual(provider.fetch_commit_timestamp("abcdef123456"), 1792026901)

    @patch.object(provider, "_fetch_text")
    def test_rejects_mismatched_or_malformed_commit_metadata(self, fetch_text) -> None:
        for payload in ("<html>error</html>", "{}", json.dumps({
            "sha": "111111111111",
            "commit": {"committer": {"date": "2026-10-15T01:15:01Z"}},
        })):
            with self.subTest(payload=payload):
                fetch_text.return_value = payload
                with self.assertRaises(provider.ReleaseProviderError):
                    provider.fetch_commit_timestamp("abcdef123456")


if __name__ == "__main__":
    unittest.main()
