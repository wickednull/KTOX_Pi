#!/usr/bin/env python3
"""
wifi/monitor_mode_helper.py — KTOx Wi-Fi Monitor Mode Helper (Canonical)
=========================================================================
Single source of truth for WiFi monitor mode management across all payloads.

Strategy
--------
1. Detect and reject onboard Broadcom (brcmfmac) — no reliable monitor mode
2. Stop NetworkManager / wpa_supplicant to prevent interference
3. Try airmon-ng (Kali standard — cleanest, handles driver quirks)
4. Fall back to raw iw/ip commands if airmon-ng is absent
5. Verify mode via ``iw dev <iface> info`` (not deprecated iwconfig)
6. On deactivate: restore managed mode, bring base interface up, restart services

Public API
----------
    activate_monitor_mode(interface)   -> str | None
        Returns the monitor interface name (e.g. 'wlan1mon') or None on failure.

    deactivate_monitor_mode(interface) -> bool
        Restores managed mode.  Returns True on success.

    find_monitor_capable_interface()   -> str | None
        Returns the first non-onboard wireless interface found, or None.
"""

import os
import re
import subprocess
import time

try:
    from payloads._debug_helper import log as _log
except ImportError:
    def _log(msg, level="INFO", tag="MON"):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] [{tag}] {msg}", flush=True)

_TAG = "MON"


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _run(cmd, timeout=30):
    """Run *cmd* (list), return (returncode, combined_output)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        out = (r.stdout + r.stderr).strip()
        return r.returncode, out
    except FileNotFoundError:
        return -1, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout}s: {' '.join(cmd)}"
    except Exception as e:
        return -1, str(e)


def _has_cmd(name):
    rc, _ = _run(["which", name], timeout=5)
    return rc == 0


def _iface_exists(name):
    return os.path.exists(f"/sys/class/net/{name}")


def _iface_mode(name):
    """Return interface mode ('monitor', 'managed', …) via iw, or ''."""
    rc, out = _run(["iw", "dev", name, "info"])
    if rc != 0:
        return ""
    m = re.search(r"type\s+(\S+)", out)
    return m.group(1).lower() if m else ""


def _is_onboard(iface):
    """True if *iface* is the onboard Broadcom (brcmfmac / SDIO/mmc)."""
    try:
        devpath = os.path.realpath(f"/sys/class/net/{iface}/device")
        if "mmc" in devpath:
            return True
    except Exception:
        pass
    try:
        drv = os.path.basename(
            os.path.realpath(f"/sys/class/net/{iface}/device/driver"))
        if drv == "brcmfmac":
            return True
    except Exception:
        pass
    return False


def _stop_interfering_services():
    """Stop NetworkManager and wpa_supplicant to prevent monitor mode fights."""
    for svc in ("NetworkManager", "wpa_supplicant"):
        rc, out = _run(["systemctl", "is-active", "--quiet", svc], timeout=5)
        if rc == 0:  # service is running
            _log(f"Stopping {svc}", tag=_TAG)
            _run(["systemctl", "stop", svc], timeout=10)


def _start_interfering_services():
    """Restart network services after monitor mode session ends."""
    for svc in ("wpa_supplicant", "NetworkManager"):
        _log(f"Starting {svc}", tag=_TAG)
        _run(["systemctl", "start", svc], timeout=10)


def _kill_interfering():
    """Kill processes airmon-ng identifies as problematic."""
    if _has_cmd("airmon-ng"):
        _log("Running airmon-ng check kill", tag=_TAG)
        _run(["airmon-ng", "check", "kill"], timeout=15)


# ── Public API ────────────────────────────────────────────────────────────────

def find_monitor_capable_interface():
    """
    Return the first non-onboard wireless interface that exists, or None.

    On a Pi Zero 2W with a USB dongle, this returns e.g. 'wlan1'.
    wlan0 (brcmfmac onboard) is always skipped.
    """
    try:
        for name in sorted(os.listdir("/sys/class/net")):
            if name == "lo":
                continue
            if os.path.isdir(f"/sys/class/net/{name}/wireless"):
                if not _is_onboard(name):
                    _log(f"Found monitor-capable interface: {name}", tag=_TAG)
                    return name
    except Exception as e:
        _log(f"Interface discovery failed: {e}", level="ERROR", tag=_TAG)
    _log("No monitor-capable interface found", level="WARN", tag=_TAG)
    return None


def activate_monitor_mode(interface: str) -> "str | None":
    """
    Put *interface* into monitor mode.

    Returns the resulting monitor interface name (e.g. 'wlan1mon' or 'wlan1')
    on success, or None on failure.
    """
    if not interface:
        _log("activate_monitor_mode: empty interface", level="ERROR", tag=_TAG)
        return None

    # Reject onboard Broadcom — brcmfmac doesn't support monitor mode reliably
    if _is_onboard(interface):
        _log(
            f"{interface} uses brcmfmac (onboard Pi WiFi) — "
            "monitor mode not supported on this adapter",
            level="ERROR", tag=_TAG,
        )
        return None

    # Already in monitor mode?
    current_mode = _iface_mode(interface)
    if current_mode == "monitor":
        _log(f"{interface} is already in monitor mode", tag=_TAG)
        return interface

    _log(f"Activating monitor mode on {interface}", tag=_TAG)
    _stop_interfering_services()
    _kill_interfering()

    # ── Strategy 1: airmon-ng ─────────────────────────────────────────────
    if _has_cmd("airmon-ng"):
        _log(f"Trying airmon-ng start {interface}", tag=_TAG)
        rc, out = _run(["airmon-ng", "start", interface], timeout=30)
        _log(f"airmon-ng output: {out[:120]}", level="DEBUG", tag=_TAG)

        # Parse the new interface name from airmon-ng output
        # Patterns: "monitor mode vif enabled on [wlan1mon]"
        #           "monitor mode enabled for [wlan1mon]"
        #           "(monitor mode enabled on wlan1mon)"
        for pattern in [
            r"(?:enabled on|enabled for|monitor mode vif enabled[^[]*)\[?(\w+)\]?",
            r"\(monitor mode enabled on (\w+)\)",
            r"monitor mode enabled[^[]*\[?(\w+)\]?",
        ]:
            m = re.search(pattern, out, re.IGNORECASE)
            if m:
                mon_iface = m.group(1).strip("[]")
                if _iface_exists(mon_iface) and _iface_mode(mon_iface) == "monitor":
                    _log(f"Monitor mode active on {mon_iface}", tag=_TAG)
                    return mon_iface
                break

        # Some drivers rename to <iface>mon
        mon_candidate = interface + "mon"
        if _iface_exists(mon_candidate) and _iface_mode(mon_candidate) == "monitor":
            _log(f"Monitor mode active on {mon_candidate}", tag=_TAG)
            return mon_candidate

        # Some drivers keep the same interface name
        if _iface_mode(interface) == "monitor":
            _log(f"Monitor mode active on {interface}", tag=_TAG)
            return interface

        _log("airmon-ng succeeded but monitor interface not confirmed; trying iw fallback", level="WARN", tag=_TAG)

    # ── Strategy 2: iw / ip ──────────────────────────────────────────────
    _log(f"Trying iw/ip fallback for {interface}", tag=_TAG)
    _run(["ip", "link", "set", interface, "down"])
    rc, out = _run(["iw", "dev", interface, "set", "type", "monitor"])
    if rc != 0:
        _log(f"iw set type monitor failed: {out}", level="ERROR", tag=_TAG)
        return None
    _run(["ip", "link", "set", interface, "up"])
    time.sleep(0.5)

    if _iface_mode(interface) == "monitor":
        _log(f"Monitor mode active on {interface} (iw fallback)", tag=_TAG)
        return interface

    _log(f"All strategies failed to activate monitor mode on {interface}", level="ERROR", tag=_TAG)
    return None


def deactivate_monitor_mode(interface: str) -> bool:
    """
    Take *interface* out of monitor mode and restore managed mode.

    Also restarts NetworkManager/wpa_supplicant.
    Returns True on success, False on failure.
    """
    if not interface:
        _log("deactivate_monitor_mode: empty interface", level="ERROR", tag=_TAG)
        return False

    if not _iface_exists(interface):
        # Interface is already gone (airmon-ng may have removed it)
        _log(f"{interface} no longer exists — assuming already cleaned up", tag=_TAG)
        _start_interfering_services()
        return True

    if _iface_mode(interface) != "monitor":
        _log(f"{interface} is not in monitor mode — nothing to do", tag=_TAG)
        _start_interfering_services()
        return True

    _log(f"Deactivating monitor mode on {interface}", tag=_TAG)
    base = interface.replace("mon", "") if interface.endswith("mon") else interface

    # ── Strategy 1: airmon-ng ─────────────────────────────────────────────
    if _has_cmd("airmon-ng"):
        _log(f"Trying airmon-ng stop {interface}", tag=_TAG)
        rc, out = _run(["airmon-ng", "stop", interface], timeout=30)
        _log(f"airmon-ng stop output: {out[:120]}", level="DEBUG", tag=_TAG)
        # airmon-ng stop typically removes the mon interface
        if not _iface_exists(interface):
            # Bring the base interface back up
            if base and base != interface and _iface_exists(base):
                _run(["ip", "link", "set", base, "up"])
                _log(f"Brought {base} back up", tag=_TAG)
            _start_interfering_services()
            return True
        if _iface_mode(interface) != "monitor":
            _start_interfering_services()
            return True

    # ── Strategy 2: iw / ip ──────────────────────────────────────────────
    _log(f"Trying iw/ip fallback to restore {interface}", tag=_TAG)
    _run(["ip", "link", "set", interface, "down"])
    rc, out = _run(["iw", "dev", interface, "set", "type", "managed"])
    if rc != 0:
        _log(f"iw set type managed failed: {out}", level="ERROR", tag=_TAG)
    _run(["ip", "link", "set", interface, "up"])
    time.sleep(0.3)

    success = _iface_mode(interface) != "monitor"
    if success:
        _log(f"Monitor mode deactivated on {interface}", tag=_TAG)
    else:
        _log(f"Failed to fully deactivate monitor mode on {interface}", level="ERROR", tag=_TAG)

    _start_interfering_services()
    return success
