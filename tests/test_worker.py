from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import worker


class WorkerTests(unittest.TestCase):
    def test_prerelease_identity_reaches_provider(self) -> None:
        provider = Mock()
        provider.check_for_updates.return_value = {"ok": True, "update_available": True}
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
            patch.object(worker, "_load_provider", return_value=provider),
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
