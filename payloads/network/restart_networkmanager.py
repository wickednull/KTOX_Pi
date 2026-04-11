#!/usr/bin/env python3
"""Restart NetworkManager via systemctl."""

import subprocess
import sys

result = subprocess.run(
    ["sudo", "systemctl", "restart", "NetworkManager"],
    capture_output=True, text=True
)

if result.returncode == 0:
    print("[+] NetworkManager restarted successfully.")
else:
    print(f"[-] Failed (exit {result.returncode})")
    if result.stderr:
        print(result.stderr.strip())
    sys.exit(result.returncode)
