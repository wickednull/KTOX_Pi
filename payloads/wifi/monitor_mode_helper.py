#!/usr/bin/env python3
"""
wifi/monitor_mode_helper.py — KTOx Wi-Fi Monitor Mode Helper
============================================================
Safe monitor-mode helper for KTOx_Pi on Raspberry Pi Zero 2 W / Kali Linux.

Goals
-----
- Prefer external USB Wi-Fi adapter over onboard Pi Wi-Fi
- Avoid destructive global service kills
- Use iw/ip first, airmon-ng fallback
- Keep interface handling scoped and predictable
- Preserve compatibility with current KTOx payload names

Public API
----------
    find_monitor_capable_interface() -> str | None
    activate_monitor_mode(interface) -> str | None
    deactivate_monitor_mode(interface) -> bool

Additional helpers
------------------
    get_interfaces() -> list[str]
    get_type(iface) -> str
    is_onboard(iface) -> bool
"""

import os
import re
import json
import time
import subprocess

STATE_FILE = "/tmp/ktox_monitor_state.json"

try:
    from payloads._debug_helper import log as _log
except Exception:
    def _log(msg, level="INFO", tag="MON"):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] [{tag}] {msg}", flush=True)

_TAG = "MON"


# ──────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────────────────────────────────────

def _run(cmd, timeout=20):
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
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


def _wireless_iface(name):
    return os.path.isdir(f"/sys/class/net/{name}/wireless")


def _save_state(data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        _log(f"Failed to save state: {e}", level="WARN", tag=_TAG)


def _load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _clear_state():
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    except Exception as e:
        _log(f"Failed to clear state: {e}", level="WARN", tag=_TAG)


def _get_phy(iface):
    try:
        with open(f"/sys/class/net/{iface}/phy80211/name", "r") as f:
            return f.read().strip()
    except Exception:
        pass

    rc, out = _run(["iw", "dev", iface, "info"])
    if rc == 0:
        m = re.search(r"wiphy\s+(\d+)", out)
        if m:
            return f"phy{m.group(1)}"
    return ""


def _ensure_down(iface):
    _run(["ip", "link", "set", iface, "down"])
    time.sleep(0.2)


def _ensure_up(iface):
    _run(["ip", "link", "set", iface, "up"])
    time.sleep(0.3)


def _current_monitor_ifaces():
    out = []
    try:
        for name in os.listdir("/sys/class/net"):
            if get_type(name) == "monitor":
                out.append(name)
    except Exception:
        pass
    return out


def _stop_interfering_services():
    """
    Stop services that frequently interfere with monitor mode.
    Best-effort only; failures are non-fatal.
    """
    for svc in ("NetworkManager", "wpa_supplicant"):
        _run(["systemctl", "stop", svc], timeout=8)


def _start_interfering_services():
    """
    Restart services after monitor mode operations.
    Best-effort only; failures are non-fatal.
    """
    for svc in ("NetworkManager", "wpa_supplicant"):
        _run(["systemctl", "start", svc], timeout=8)


# ──────────────────────────────────────────────────────────────────────────────
# Public helper functions
# ──────────────────────────────────────────────────────────────────────────────

def get_interfaces():
    try:
        return sorted(
            name for name in os.listdir("/sys/class/net")
            if name != "lo" and _wireless_iface(name)
        )
    except Exception:
        return []


def get_type(iface):
    rc, out = _run(["iw", "dev", iface, "info"])
    if rc != 0:
        return ""
    m = re.search(r"type\s+(\S+)", out)
    return m.group(1).lower() if m else ""


# Backward-compat names used by older payloads
def _iface_mode(iface):
    return get_type(iface)


def is_onboard(iface):
    """
    Try to identify onboard Pi Wi-Fi (Broadcom / SDIO / mmc-backed).
    """
    try:
        devpath = os.path.realpath(f"/sys/class/net/{iface}/device")
        low = devpath.lower()
        if "mmc" in low or "sdio" in low:
            return True
    except Exception:
        pass

    try:
        drv = os.path.basename(
            os.path.realpath(f"/sys/class/net/{iface}/device/driver")
        )
        if drv in ("brcmfmac", "brcmfmac_sdio"):
            return True
    except Exception:
        pass

    return False


# Backward-compat name used by older payloads
def _is_onboard(iface):
    return is_onboard(iface)


def find_monitor_capable_interface():
    """
    Prefer external USB Wi-Fi interfaces.
    Fall back to any wireless interface if nothing else exists.
    """
    interfaces = get_interfaces()

    for iface in interfaces:
        if not is_onboard(iface):
            _log(f"Found preferred attack interface: {iface}", tag=_TAG)
            return iface

    for iface in interfaces:
        _log(f"Only onboard Wi-Fi found: {iface}", level="WARN", tag=_TAG)
        return iface

    _log("No wireless interfaces found", level="WARN", tag=_TAG)
    return None


def resolve_monitor_interface(preferred=None):
    """
    Resolve an active monitor interface from preferred iface, saved state,
    or current system interfaces.
    """
    if preferred and _iface_exists(preferred) and get_type(preferred) == "monitor":
        return preferred

    state = _load_state() or {}
    state_mon = state.get("monitor_iface")
    if state_mon and _iface_exists(state_mon) and get_type(state_mon) == "monitor":
        return state_mon

    mons = _current_monitor_ifaces()
    return mons[0] if mons else None


# ──────────────────────────────────────────────────────────────────────────────
# Monitor mode activation
# ──────────────────────────────────────────────────────────────────────────────

def activate_monitor_mode(interface):
    """
    Put the interface into monitor mode.

    Returns:
        monitor interface name on success
        None on failure
    """
    if not interface:
        _log("activate_monitor_mode called with empty interface", level="ERROR", tag=_TAG)
        return None

    if not _iface_exists(interface):
        _log(f"Interface does not exist: {interface}", level="ERROR", tag=_TAG)
        return None

    if is_onboard(interface):
        _log(
            f"{interface} appears to be onboard Pi Wi-Fi. "
            "USB adapter is strongly preferred for monitor mode.",
            level="WARN",
            tag=_TAG,
        )

    current_type = get_type(interface)
    if current_type == "monitor":
        _log(f"{interface} already in monitor mode", tag=_TAG)
        _save_state({
            "base_iface": interface,
            "monitor_iface": interface,
            "original_type": current_type or "managed",
            "method": "already_monitor",
        })
        return interface

    _log(f"Activating monitor mode on {interface}", tag=_TAG)

    original_type = current_type or "managed"

    # Strategy 1: iw dev <iface> set type monitor
    _log(f"Trying iw method on {interface}", tag=_TAG)
    _ensure_down(interface)
    rc, out = _run(["iw", "dev", interface, "set", "type", "monitor"])
    if rc == 0:
        _ensure_up(interface)
        if get_type(interface) == "monitor":
            _log(f"Monitor mode active on {interface} (iw)", tag=_TAG)
            _save_state({
                "base_iface": interface,
                "monitor_iface": interface,
                "original_type": original_type,
                "method": "iw",
            })
            return interface
    else:
        _log(f"iw method failed: {out}", level="WARN", tag=_TAG)

    # Strategy 2: iw phy <phy> set monitor none
    phy = _get_phy(interface)
    if phy:
        _log(f"Trying phy method on {interface} via {phy}", tag=_TAG)
        _ensure_down(interface)
        rc2, out2 = _run(["iw", "phy", phy, "set", "monitor", "none"])
        _ensure_up(interface)

        if get_type(interface) == "monitor":
            _log(f"Monitor mode active on {interface} (iw phy)", tag=_TAG)
            _save_state({
                "base_iface": interface,
                "monitor_iface": interface,
                "original_type": original_type,
                "method": "iw_phy",
            })
            return interface

        # Sometimes another monitor iface appears
        for mon in _current_monitor_ifaces():
            if mon != interface or get_type(mon) == "monitor":
                _log(f"Monitor mode active on {mon} (iw phy scan)", tag=_TAG)
                _save_state({
                    "base_iface": interface,
                    "monitor_iface": mon,
                    "original_type": original_type,
                    "method": "iw_phy_scan",
                })
                return mon

        if rc2 != 0:
            _log(f"iw phy failed: {out2}", level="WARN", tag=_TAG)

    # Strategy 3: airmon-ng fallback
    if _has_cmd("airmon-ng"):
        _log(f"Trying airmon-ng start {interface}", tag=_TAG)
        rc3, out3 = _run(["airmon-ng", "start", interface], timeout=30)

        # First check common candidates
        candidates = [interface + "mon", interface, interface + "0"]
        for candidate in candidates:
            if _iface_exists(candidate) and get_type(candidate) == "monitor":
                _log(f"Monitor mode active on {candidate} (airmon-ng)", tag=_TAG)
                _save_state({
                    "base_iface": interface,
                    "monitor_iface": candidate,
                    "original_type": original_type,
                    "method": "airmon-ng",
                })
                return candidate

        # Then scan all interfaces
        for mon in _current_monitor_ifaces():
            _log(f"Monitor mode active on {mon} (airmon-ng scan)", tag=_TAG)
            _save_state({
                "base_iface": interface,
                "monitor_iface": mon,
                "original_type": original_type,
                "method": "airmon-ng_scan",
            })
            return mon

        if rc3 != 0:
            _log(f"airmon-ng failed: {out3}", level="WARN", tag=_TAG)

    _log(f"Failed to activate monitor mode on {interface}", level="ERROR", tag=_TAG)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Monitor mode deactivation
# ──────────────────────────────────────────────────────────────────────────────

def deactivate_monitor_mode(interface=None):
    """
    Restore a monitor interface back to managed mode.

    Returns:
        True on success
        False on failure
    """
    if not interface:
        interface = resolve_monitor_interface()
        if not interface:
            _log("No active monitor interface found; ensuring services are up", tag=_TAG)
            _start_interfering_services()
            _clear_state()
            return True

    state = _load_state() or {}
    base = state.get("base_iface") or interface.replace("mon", "")
    mon_iface = state.get("monitor_iface") or interface
    original_type = state.get("original_type") or "managed"

    if get_type(mon_iface) != "monitor":
        detected = resolve_monitor_interface(preferred=interface)
        if detected:
            mon_iface = detected
        elif _iface_exists(interface):
            mon_iface = interface

    # If target vanished, treat as cleaned up if base exists
    if not _iface_exists(mon_iface):
        if base and _iface_exists(base):
            _log(f"{mon_iface} no longer exists; base iface {base} remains", tag=_TAG)
            _start_interfering_services()
            _clear_state()
            return True
        _log(f"{mon_iface} does not exist", level="WARN", tag=_TAG)
        _start_interfering_services()
        _clear_state()
        return True

    if get_type(mon_iface) != "monitor":
        _log(f"{mon_iface} is not in monitor mode", tag=_TAG)
        _clear_state()
        return True

    _log(f"Deactivating monitor mode on {mon_iface}", tag=_TAG)

    # Strategy 1: airmon-ng stop for renamed mon interfaces
    if mon_iface.endswith("mon") and _has_cmd("airmon-ng"):
        rc, out = _run(["airmon-ng", "stop", mon_iface], timeout=30)
        if rc == 0:
            time.sleep(0.5)
            if base and _iface_exists(base):
                _ensure_up(base)
                _log(f"Restored base interface {base} via airmon-ng", tag=_TAG)
                _start_interfering_services()
                _clear_state()
                return True
            if not _iface_exists(mon_iface):
                _start_interfering_services()
                _clear_state()
                return True
        else:
            _log(f"airmon-ng stop failed: {out}", level="WARN", tag=_TAG)

    # Strategy 2: direct restore on same interface
    restore_iface = mon_iface if _iface_exists(mon_iface) else base
    if not restore_iface or not _iface_exists(restore_iface):
        _log("No valid interface available for restore", level="ERROR", tag=_TAG)
        return False

    _ensure_down(restore_iface)
    rc2, out2 = _run(["iw", "dev", restore_iface, "set", "type", original_type])
    if rc2 != 0:
        _log(f"iw restore failed on {restore_iface}: {out2}", level="WARN", tag=_TAG)
        # fallback to managed explicitly
        rc3, out3 = _run(["iw", "dev", restore_iface, "set", "type", "managed"])
        if rc3 != 0:
            _log(f"managed fallback failed on {restore_iface}: {out3}", level="ERROR", tag=_TAG)
            _ensure_up(restore_iface)
            return False

    _ensure_up(restore_iface)

    if get_type(restore_iface) == "monitor":
        _log(f"{restore_iface} is still in monitor mode after restore", level="ERROR", tag=_TAG)
        return False

    _log(f"Restored {restore_iface} to {get_type(restore_iface) or 'managed'}", tag=_TAG)
    _start_interfering_services()
    _clear_state()
    return True
