"""Standalone network worker launched by Blender in a separate process."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys


def _load_sibling(module_name: str, filename: str):
    module_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses (used by the protocol and process modules) resolve their
    # defining module through sys.modules while the class body is executing.
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    return module


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--current-hash", default="")
    parser.add_argument(
        "--current-cycle", choices=("alpha", "beta", "rc", "release"), default="release"
    )
    parser.add_argument("--current-commit-timestamp", type=int, default=0)
    parser.add_argument("--channel", choices=("stable", "series", "daily"), required=True)
    parser.add_argument("--package-format", default="auto")
    return parser.parse_args()


def main() -> int:
    protocol = _load_sibling("blender_update_worker_protocol", "worker_protocol.py")
    try:
        args = _arguments()
        request = protocol.WorkerRequest.from_values(
            current_version=args.current_version,
            current_hash=args.current_hash,
            current_cycle=args.current_cycle,
            current_commit_timestamp=args.current_commit_timestamp,
            channel=args.channel,
            package_format=args.package_format,
        )
        provider = _load_sibling("blender_update_release_provider", "release_provider.py")
        result = provider.check_for_updates(
            current_version=request.current_version,
            current_hash=request.current_hash,
            current_cycle=request.current_cycle,
            current_commit_timestamp=request.current_commit_timestamp,
            channel=request.channel,
            package_format=request.package_format,
        )
        output = protocol.encode_result(result)
    except SystemExit:
        # Argument parsing also raises SystemExit; keep stdout machine-readable
        # for the parent even when the command line is malformed.
        output = protocol.encode_result(protocol.failure("Invalid worker arguments"))
    except Exception as exc:
        output = protocol.encode_result(protocol.failure(exc))

    sys.stdout.write(output)
    sys.stdout.flush()
    try:
        decoded = protocol.decode_result(output)
    except protocol.ProtocolError:
        return 1
    return 0 if decoded.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
