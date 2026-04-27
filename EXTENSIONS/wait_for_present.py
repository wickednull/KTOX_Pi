#!/usr/bin/env python3
"""CLI wrapper for WAIT_FOR_PRESENT."""
from __future__ import annotations

import argparse
import sys

from api import WAIT_FOR_PRESENT


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wait until a Bluetooth, Wi-Fi, or GPIO signal becomes present."
    )
    parser.add_argument(
        "--signal-type",
        choices=["bluetooth", "wifi", "gpio"],
        default="bluetooth",
        help="Signal family to monitor (default: bluetooth)",
    )
    parser.add_argument("--identifier", default="", help="Name/MAC (bluetooth), SSID (wifi), or GPIO label (gpio)")
    parser.add_argument("--name", default="", help="Device name to match (bluetooth only, partial)")
    parser.add_argument("--mac", default="", help="MAC address to match (AA:BB:CC:DD:EE:FF)")
    parser.add_argument("--service-uuid", default="", help="Service UUID to match (bluetooth only)")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Max wait time in seconds (0 = infinite)",
    )
    parser.add_argument(
        "--scan-window-seconds",
        type=int,
        default=4,
        help="Duration of each scan window",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=2,
        help="Interval between scans",
    )
    parser.add_argument(
        "--failure-policy",
        choices=["fail_closed", "warn_only"],
        default="fail_closed",
        help="Behavior on timeout",
    )
    args = parser.parse_args()

    if not args.identifier and args.signal_type != "gpio":
        if not args.name and not args.mac:
            print("Error: --identifier or (--name/--mac) required", file=sys.stderr)
            return 2

    try:
        fail_closed = args.failure_policy == "fail_closed"
        result = WAIT_FOR_PRESENT(
            signal_type=args.signal_type,
            identifier=args.identifier,
            name=args.name,
            mac=args.mac,
            service_uuid=args.service_uuid,
            timeout_seconds=args.timeout_seconds,
            scan_window_seconds=args.scan_window_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            fail_closed=fail_closed,
        )
        if result:
            print(f"Signal present: {args.signal_type}={args.identifier or args.name or args.mac}")
            return 0
        else:
            print("Signal not present (warn_only mode)", file=sys.stderr)
            return 1
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
