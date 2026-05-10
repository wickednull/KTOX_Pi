#!/usr/bin/env python3
# NAME: Jam Fi
"""
KTOx Payload – Jam_Fi Wi-Fi Toolkit
===================================
LCD wrapper for the external Jam_Fi CLI with quick command selection,
scrollable output, and full on-screen keyboard input for prompts/submenus.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

from payloads._lcd_cli_bridge import LCDCliBridge, first_existing_dir

JAM_FI_PATH = first_existing_dir([
    "/root/Jam_Fi",
    os.path.join(_REPO_ROOT, "vendor", "jam-fi"),
])

QUICK_COMMANDS = [
    ("1 Scan AP/Clients", "1"),
    ("2 Deauth Attack", "2"),
    ("3 Handshake Cap", "3"),
    ("4 Probe Spam", "4"),
    ("5 Evil AP", "5"),
    ("6 MITM Inject", "6"),
    ("7 CVE Scanner", "7"),
    ("8 Auto-Pwn", "8"),
    ("9 Router Exploit", "9"),
    ("10 Chaos Mode", "10"),
    ("0 Back/Exit", "0"),
    ("q Quit", "q"),
    ("Enter", ""),
    ("Keyboard Input", "__keyboard__"),
    ("Ctrl-C", "__ctrl_c__"),
]


def main():
    script = os.path.join(JAM_FI_PATH, "jam_fi.py")
    command = ["python3", script] if os.geteuid() == 0 else ["sudo", "python3", script]
    bridge = LCDCliBridge("JAM FI", command, JAM_FI_PATH, QUICK_COMMANDS)
    return bridge.run()


if __name__ == "__main__":
    raise SystemExit(main())
