#!/usr/bin/env python3
"""
KTOx WiFi Monitor Mode Helper (CLEAN REBUILD)
Safe for Raspberry Pi Zero 2 W (Kali)

- No service killing
- No global network disruption
- Uses iw first, airmon-ng fallback
- Tracks state for safe restore
"""

import subprocess
import re
import os

STATE_FILE = "/tmp/ktox_iface_state"


# -------------------------------
# Helpers
# -------------------------------
def run(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
    except:
        return ""


def get_interfaces():
    output = run(["iw", "dev"])
    interfaces = re.findall(r"Interface\s+(\w+)", output)
    return interfaces


def get_type(iface):
    output = run(["iw", "dev", iface, "info"])
    match = re.search(r"type\s+(\w+)", output)
    return match.group(1) if match else "unknown"


def is_wireless(iface):
    return iface.startswith("wlan")


def is_onboard(iface):
    # crude but effective for Pi
    return iface == "wlan0"


# -------------------------------
# Interface Selection
# -------------------------------
def get_attack_interface():
    interfaces = get_interfaces()

    # prefer external adapters
    for iface in interfaces:
        if is_wireless(iface) and not is_onboard(iface):
            return iface

    # fallback to onboard if nothing else
    for iface in interfaces:
        if is_wireless(iface):
            return iface

    return None


# -------------------------------
# Monitor Mode
# -------------------------------
def enable_monitor_mode(iface):
    if not iface:
        return None

    original_type = get_type(iface)

    # Save state
    try:
        with open(STATE_FILE, "w") as f:
            f.write(f"{iface},{original_type}")
    except:
        pass

    # Try iw first
    run(["ip", "link", "set", iface, "down"])
    run(["iw", "dev", iface, "set", "type", "monitor"])
    run(["ip", "link", "set", iface, "up"])

    if get_type(iface) == "monitor":
        return iface

    # Fallback to airmon-ng
    output = run(["airmon-ng", "start", iface])

    match = re.search(r"\((\w+mon)\)", output)
    if match:
        return match.group(1)

    return None


def disable_monitor_mode():
    if not os.path.exists(STATE_FILE):
        return False

    try:
        with open(STATE_FILE, "r") as f:
            iface, original_type = f.read().strip().split(",")
    except:
        return False

    # If renamed (wlan1mon → wlan1)
    if iface.endswith("mon"):
        run(["airmon-ng", "stop", iface])
        iface = iface.replace("mon", "")

    # Restore type
    run(["ip", "link", "set", iface, "down"])
    run(["iw", "dev", iface, "set", "type", original_type])
    run(["ip", "link", "set", iface, "up"])

    try:
        os.remove(STATE_FILE)
    except:
        pass

    return True
