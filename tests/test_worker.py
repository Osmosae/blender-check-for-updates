from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import worker
import worker_protocol


class WorkerTests(unittest.TestCase):
    def test_prerelease_identity_reaches_provider(self) -> None:
        provider = Mock()
        provider.check_for_updates.return_value = {
            "ok": True,
            "update_available": True,
            "current_version": "5.3.0",
            "latest_version": "5.3.0",
            "display_version": "5.3.0 beta (abcdef123456)",
            "latest_hash": "abcdef123456",
            "release_cycle": "beta",
            "channel": "series",
            "download_url": "https://builder.blender.org/download/daily/",
            "direct_download_url": "https://cdn.builder.blender.org/build.zip",
            "file_mtime": 1792026901,
        }
        def load_sibling(module_name: str, filename: str):
            if filename == "worker_protocol.py":
                return worker_protocol
            if filename == "release_provider.py":
                return provider
            raise AssertionError(f"Unexpected worker sibling: {filename}")

        output = io.StringIO()
        arguments = [
            "worker.py",
            "--current-version", "5.3.0",
            "--current-hash", "abcdef123456",
            "--current-cycle", "beta",
            "--current-commit-timestamp", "1792026901",
            "--channel", "series",
        ]
        with (
            patch.object(worker.sys, "argv", arguments),
            patch.object(worker, "_load_sibling", side_effect=load_sibling),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(worker.main(), 0)

        provider.check_for_updates.assert_called_once_with(
            current_version="5.3.0",
            current_hash="abcdef123456",
            current_cycle="beta",
            current_commit_timestamp=1792026901,
            channel="series",
            package_format="auto",
        )
        self.assertTrue(json.loads(output.getvalue())["update_available"])


if __name__ == "__main__":
    unittest.main()
