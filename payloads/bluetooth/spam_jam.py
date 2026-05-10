#!/usr/bin/env python3
# NAME: Spam Jam
"""
KTOx Payload – Spam-Jam BLE/Bluetooth Toolkit
=============================================
LCD wrapper for the external Spam-Jam CLI with quick command selection,
scrollable output, and full on-screen keyboard input for prompts/submenus.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

from payloads._lcd_toolkit_bridge import LCDToolkitBridge, first_existing_dir

SPAM_JAM_PATH = first_existing_dir([
    "/root/Spam-Jam",
    os.path.join(_REPO_ROOT, "vendor", "spam-jam"),
])

QUICK_COMMANDS = [
    ("1 BLE Scan", "1"),
    ("2 BLE Spam All", "2"),
    ("3 BLE Jam All", "3"),
    ("4 L2Ping Attack", "4"),
    ("5 RFCOMM Flood", "5"),
    ("6 Mesh Menu", "6"),
    ("0 Back/Exit", "0"),
    ("q Quit", "q"),
    ("Enter", ""),
    ("Keyboard Input", "__keyboard__"),
    ("Ctrl-C", "__ctrl_c__"),
]


def main():
    script = os.path.join(SPAM_JAM_PATH, "spam_jam.py")
    command = ["python3", script] if os.geteuid() == 0 else ["sudo", "python3", script]
    bridge = LCDToolkitBridge("SPAM JAM", command, SPAM_JAM_PATH, QUICK_COMMANDS)
    return bridge.run()


if __name__ == "__main__":
    raise SystemExit(main())
