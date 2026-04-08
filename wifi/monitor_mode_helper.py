#!/usr/bin/env python3
"""
monitor_mode_helper.py — KTOx Wi-Fi Monitor Mode Helper
=========================================================
Provides activate_monitor_mode() and deactivate_monitor_mode() used by
every Wi-Fi payload in payloads/wifi/.

Strategy
--------
1. Try airmon-ng (Kali standard — cleanest, handles driver quirks)
2. Fall back to raw iw/ip commands if airmon-ng is absent

activate_monitor_mode(interface) -> str | None
    Puts *interface* into monitor mode.
    Returns the resulting monitor interface name (e.g. "wlan1mon")
    or None on failure.

deactivate_monitor_mode(interface) -> bool
    Takes *interface* out of monitor mode, restores managed mode.
    Returns True on success, False on failure.
"""

import os
import re
import subprocess
import time


# ── Internal helpers ──────────────────────────────────────────────────────────

def _run(cmd, timeout=30):
    """Run a command list, return (returncode, stdout+stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return -1, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def _has_cmd(name):
    rc, _ = _run(["which", name])
    return rc == 0


def _iface_exists(name):
    return os.path.exists(f"/sys/class/net/{name}")


def _iface_mode(name):
    """Return interface mode string ('monitor', 'managed', etc.) or ''."""
    rc, out = _run(["iw", "dev", name, "info"])
    if rc != 0:
        return ""
    m = re.search(r"type\s+(\S+)", out)
    return m.group(1).lower() if m else ""


def _kill_interfering():
    """Kill processes that interfere with monitor mode (like airmon-ng check kill)."""
    _run(["airmon-ng", "check", "kill"])


# ── Public API ────────────────────────────────────────────────────────────────

def activate_monitor_mode(interface: str) -> str | None:
    """
    Put *interface* into monitor mode.

    Returns the monitor interface name on success (e.g. 'wlan1mon' or 'wlan1'),
    or None on failure.
    """
    if not interface:
        return None

    # Already in monitor mode?
    if _iface_mode(interface) == "monitor":
        return interface

    # ── Strategy 1: airmon-ng ──────────────────────────────────────────────
    if _has_cmd("airmon-ng"):
        _kill_interfering()
        rc, out = _run(["airmon-ng", "start", interface], timeout=30)

        # airmon-ng typically prints "monitor mode vif enabled on [wlan1mon]"
        # or "monitor mode enabled for [wlan1mon]"
        m = re.search(r"(?:enabled on|enabled for|monitor mode vif enabled[^[]*)\[?(\w+)\]?", out, re.IGNORECASE)
        if m:
            mon_iface = m.group(1).strip("[]")
            if _iface_exists(mon_iface) and _iface_mode(mon_iface) == "monitor":
                return mon_iface

        # Some drivers rename to <iface>mon
        mon_candidate = interface + "mon"
        if _iface_exists(mon_candidate) and _iface_mode(mon_candidate) == "monitor":
            return mon_candidate

        # Some drivers keep the same name
        if _iface_mode(interface) == "monitor":
            return interface

    # ── Strategy 2: iw / ip ───────────────────────────────────────────────
    _run(["ip", "link", "set", interface, "down"])
    _run(["iw", "dev", interface, "set", "type", "monitor"])
    _run(["ip", "link", "set", interface, "up"])
    time.sleep(0.5)

    if _iface_mode(interface) == "monitor":
        return interface

    print(f"[monitor_mode_helper] ERROR: failed to activate monitor mode on {interface}",
          flush=True)
    return None


def deactivate_monitor_mode(interface: str) -> bool:
    """
    Take *interface* out of monitor mode and restore managed mode.

    Returns True on success, False on failure.
    """
    if not interface:
        return False

    # Already managed (or doesn't exist)?
    if not _iface_exists(interface):
        return True
    if _iface_mode(interface) != "monitor":
        return True

    # ── Strategy 1: airmon-ng ──────────────────────────────────────────────
    if _has_cmd("airmon-ng"):
        rc, out = _run(["airmon-ng", "stop", interface], timeout=30)
        # airmon-ng stop typically removes the mon iface and restores the base
        base = interface.replace("mon", "")
        if not _iface_exists(interface):
            # interface was removed — bring base back up
            if base and _iface_exists(base):
                _run(["ip", "link", "set", base, "up"])
            return True
        if _iface_mode(interface) != "monitor":
            return True

    # ── Strategy 2: iw / ip ───────────────────────────────────────────────
    _run(["ip", "link", "set", interface, "down"])
    _run(["iw", "dev", interface, "set", "type", "managed"])
    _run(["ip", "link", "set", interface, "up"])
    time.sleep(0.3)

    if _iface_mode(interface) != "monitor":
        return True

    print(f"[monitor_mode_helper] ERROR: failed to deactivate monitor mode on {interface}",
          flush=True)
    return False
