#!/usr/bin/env python3
"""KTOx Payload – LCD-first Nmap scanner.

This is intentionally not a pasted terminal-in-a-window.  It gives the 128x128
LCD a small workflow: choose a target, choose a scan profile, watch live Nmap
output, and save normal/XML/grepable loot for the web UI/loot viewer.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from payloads._lcd_runtime import (  # noqa: E402
    LCDUI,
    command_exists,
    default_gateway,
    local_cidrs,
    loot_dir,
    run_streaming_command,
    timestamp,
)


SCAN_PROFILES: List[Tuple[str, List[str], bool]] = [
    ("Ping sweep", ["-sn"], False),
    ("Fast ports", ["-T4", "-F", "--open"], False),
    ("Services", ["-sV", "--version-light", "--open"], False),
    ("Full TCP", ["-p-", "--open", "-T4"], False),
    ("Aggressive", ["-A", "-T4", "--open"], True),
    ("Vuln scripts", ["-sV", "--script", "vuln", "--open"], True),
]


def sudo_prefix(needs_root: bool) -> List[str]:
    if os.geteuid() == 0 or not needs_root:
        return []
    return ["sudo"] if command_exists("sudo") else []


def target_choices() -> List[str]:
    choices: List[str] = []
    gw = default_gateway()
    if gw:
        choices.append(f"Gateway {gw}")
    for cidr in local_cidrs():
        choices.append(f"Local {cidr}")
    choices.extend(["192.168.1.0/24", "10.0.0.0/24", "Custom from env", "Exit"])
    deduped: List[str] = []
    for choice in choices:
        if choice not in deduped:
            deduped.append(choice)
    return deduped


def normalize_target(choice: str) -> Optional[str]:
    if choice == "Exit":
        return None
    if choice == "Custom from env":
        return os.environ.get("KTOX_NMAP_TARGET") or os.environ.get("NMAP_TARGET") or "192.168.1.1"
    if choice.startswith("Gateway ") or choice.startswith("Local "):
        return choice.split(" ", 1)[1]
    return choice


def build_command(target: str, profile: Tuple[str, Sequence[str], bool]) -> List[str]:
    name, args, needs_root = profile
    out_base = loot_dir("Nmap") / f"{timestamp()}_{name.lower().replace(' ', '_')}"
    return sudo_prefix(needs_root) + ["nmap", *args, "-oA", str(out_base), target]


def choose_profile(ui: LCDUI) -> Optional[Tuple[str, List[str], bool]]:
    idx = ui.menu("Nmap profile", [profile[0] for profile in SCAN_PROFILES] + ["Back"])
    if idx is None or idx >= len(SCAN_PROFILES):
        return None
    return SCAN_PROFILES[idx]


def main() -> int:
    ui = LCDUI("Nmap")
    try:
        if not command_exists("nmap"):
            ui.draw_lines("Nmap", ["nmap not found", "Install nmap first"], "KEY3=Exit")
            return 127
        while True:
            choices = target_choices()
            idx = ui.menu("Nmap target", choices)
            if idx is None:
                return 0
            target = normalize_target(choices[idx])
            if not target:
                return 0
            profile = choose_profile(ui)
            if not profile:
                continue
            cmd = build_command(target, profile)
            run_streaming_command(ui, "Nmap", cmd, "KEY3=Stop")
    finally:
        ui.close()


if __name__ == "__main__":
    raise SystemExit(main())
