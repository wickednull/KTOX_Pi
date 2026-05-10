#!/usr/bin/env python3
"""KTOx Payload – LCD-first Kismet launcher and status viewer."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from payloads._lcd_runtime import (  # noqa: E402
    LCDUI,
    command_exists,
    loot_dir,
    run_streaming_command,
    timestamp,
    wifi_interfaces,
)


PROFILES = [
    "Passive scan",
    "No channel hop",
    "Fresh log prefix",
]


def sudo_prefix() -> List[str]:
    if os.geteuid() == 0:
        return []
    return ["sudo"] if command_exists("sudo") else []


def interface_choices() -> List[str]:
    ifaces = wifi_interfaces()
    if not ifaces:
        ifaces = ["wlan1", "wlan0"]
    return ifaces + ["Exit"]


def build_command(iface: str, profile: str) -> List[str]:
    log_prefix = loot_dir("Kismet") / f"{timestamp()}_{iface}"
    source = iface
    if profile == "No channel hop":
        source = f"{iface}:channel_hop=false"
    cmd = sudo_prefix() + [
        "kismet",
        "--no-ncurses-wrapper",
        "--no-line-wrap",
        "--log-prefix",
        str(log_prefix),
        "-c",
        source,
    ]
    return cmd


def choose_profile(ui: LCDUI) -> Optional[str]:
    idx = ui.menu("Kismet mode", PROFILES + ["Back"])
    if idx is None or idx >= len(PROFILES):
        return None
    return PROFILES[idx]


def main() -> int:
    ui = LCDUI("Kismet")
    try:
        if not command_exists("kismet"):
            ui.draw_lines("Kismet", ["kismet not found", "Install kismet first"], "KEY3=Exit")
            return 127
        while True:
            ifaces = interface_choices()
            idx = ui.menu("Kismet iface", ifaces)
            if idx is None or ifaces[idx] == "Exit":
                return 0
            profile = choose_profile(ui)
            if not profile:
                continue
            ui.draw_lines("Kismet", [f"Iface: {ifaces[idx]}", "Web UI :2501", "Logs in loot"], "KEY3=Stop")
            cmd = build_command(ifaces[idx], profile)
            run_streaming_command(ui, "Kismet", cmd, "KEY3=Stop")
    finally:
        ui.close()


if __name__ == "__main__":
    raise SystemExit(main())
