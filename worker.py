"""Standalone network worker launched by Blender in a separate process."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def _load_provider():
    provider_path = Path(__file__).with_name("release_provider.py")
    spec = importlib.util.spec_from_file_location("blender_update_release_provider", provider_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the release provider")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--current-hash", default="")
    parser.add_argument("--channel", choices=("stable", "series", "daily"), required=True)
    parser.add_argument("--package-format", default="auto")
    return parser.parse_args()


def main() -> int:
    try:
        args = _arguments()
        provider = _load_provider()
        result = provider.check_for_updates(
            current_version=provider.parse_version(args.current_version),
            current_hash=args.current_hash,
            channel=args.channel,
            package_format=args.package_format,
        )
    except Exception as exc:  # The parent process needs a small, stable error envelope.
        result = {"ok": False, "error": str(exc) or type(exc).__name__}

    sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    sys.stdout.flush()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
