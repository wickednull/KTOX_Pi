#!/usr/bin/env python3
"""KTOx Payload – LCD-first Wifite2 launcher.

The original payload tried to squeeze Wifite's full TTY UI onto the 1.44" LCD.
This version exposes the parts that work well from buttons: choose interface,
choose a Wifite2 mode, stream status, and put captures under loot/Wifite.

Wifite2 option notes used here come from derv82/wifite2: -i chooses the wireless
interface, -p/--pillage attacks all targets after a scan timer, --showb displays
BSSIDs, --pmkid limits the run to PMKID capture, --no-wps skips WPS attacks,
--nodeauths is passive/no-deauth mode, --hs-dir controls handshake storage, and
--cracked prints previously cracked access points.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from payloads._lcd_runtime import (  # noqa: E402
    LCDUI,
    command_exists,
    loot_dir,
    run_pty_command,
    wifi_interfaces,
)


MODES: List[Tuple[str, List[str]]] = [
    ("Passive all 30s", ["--showb", "-p", "30", "--nodeauths"]),
    ("PMKID all", ["--pmkid", "--showb", "-p", "20"]),
    ("WPA handshakes", ["--no-wps", "--showb", "-p", "20"]),
    ("WPS pixie", ["--wps-only", "--pixie", "--showb", "-p", "20"]),
    ("Client APs only", ["--clients-only", "--showb", "-p", "20"]),
    ("Show cracked", ["--cracked"]),
]


def wifite_binary() -> Optional[str]:
    for name in ("wifite", "wifite2"):
        if command_exists(name):
            return name
    return None


def sudo_prefix() -> List[str]:
    if os.geteuid() == 0:
        return []
    return ["sudo"] if command_exists("sudo") else []


def interface_choices() -> List[str]:
    ifaces = wifi_interfaces()
    if not ifaces:
        ifaces = ["wlan1", "wlan0"]
    return ifaces + ["Exit"]


def choose_mode(ui: LCDUI) -> Optional[Tuple[str, List[str]]]:
    idx = ui.menu("Wifite mode", [mode[0] for mode in MODES] + ["Back"])
    if idx is None or idx >= len(MODES):
        return None
    return MODES[idx]


def build_command(binary: str, iface: str, mode: Tuple[str, List[str]]) -> List[str]:
    name, args = mode
    cmd = sudo_prefix() + [binary]
    if name != "Show cracked":
        # Keep the LCD wrapper in control of interface/mode selection while
        # letting Wifite2 keep its expected interactive terminal behavior.
        cmd.extend(["-i", iface, "--kill", "--hs-dir", str(loot_dir("Wifite", "handshakes"))])
    cmd.extend(args)
    return cmd


def main() -> int:
    ui = LCDUI("Wifite")
    try:
        binary = wifite_binary()
        if not binary:
            ui.draw_lines("Wifite", ["wifite not found", "Install wifite2 first"], "KEY3=Exit")
            return 127
        while True:
            ifaces = interface_choices()
            idx = ui.menu("Wifite iface", ifaces)
            if idx is None or ifaces[idx] == "Exit":
                return 0
            mode = choose_mode(ui)
            if not mode:
                continue
            cmd = build_command(binary, ifaces[idx], mode)
            run_pty_command(ui, "Wifite", cmd, "KEY3=Stop OK=Enter")
    finally:
        ui.close()


if __name__ == "__main__":
    raise SystemExit(main())
