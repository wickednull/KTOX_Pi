#!/usr/bin/env python3
"""CLI wrapper for RUN_PAYLOAD."""
from __future__ import annotations

import argparse
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EXTENSIONS.api import RUN_PAYLOAD


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute another payload with environment setup.")
    parser.add_argument("payload", help="Relative path to payload (e.g., utilities/marker.py)")
    parser.add_argument("payload_args", nargs="*", help="Arguments to pass to the payload")
    parser.add_argument(
        "--selector-mode",
        choices=["auto", "manual", "policy"],
        default="auto",
        help="How the payload is chosen (default: auto)",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=0,
        help="Cooldown in seconds to prevent repeated launches",
    )
    args = parser.parse_args()

    try:
        exit_code = RUN_PAYLOAD(
            args.payload,
            *args.payload_args,
            selector_mode=args.selector_mode,
            cooldown_seconds=args.cooldown_seconds,
        )
        if exit_code == 124:
            print(f"Payload '{args.payload}' on cooldown", file=sys.stderr)
        return exit_code
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
