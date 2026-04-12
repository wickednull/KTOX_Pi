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
4. Fall back to raw iw/ip commands if airmon-ng is absent or fails
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
except Exception:
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


def _get_phy(iface):
    """Return the phy name for an interface (e.g. 'phy1'), or ''."""
    try:
        with open(f"/sys/class/net/{iface}/phy80211/name") as f:
            return f.read().strip()
    except Exception:
        pass
    rc, out = _run(["iw", "dev", iface, "info"])
    m = re.search(r"wiphy\s+(\d+)", out)
    if m:
        return f"phy{m.group(1)}"
    return ""


def _is_onboard(iface):
    """True if *iface* is the onboard Broadcom (brcmfmac / SDIO/mmc)."""
    try:
        devpath = os.path.realpath(f"/sys/class/net/{iface}/device")
        if "mmc" in devpath or "sdio" in devpath.lower():
            return True
    except Exception:
        pass
    try:
        drv = os.path.basename(
            os.path.realpath(f"/sys/class/net/{iface}/device/driver"))
        if drv in ("brcmfmac", "brcmfmac_sdio"):
            return True
    except Exception:
        pass
    return False


def _stop_interfering_services():
    """Stop NetworkManager and wpa_supplicant to prevent monitor mode fights."""
    for svc in ("NetworkManager", "wpa_supplicant"):
        rc, _ = _run(["systemctl", "is-active", "--quiet", svc], timeout=5)
        if rc == 0:
            _log(f"Stopping {svc}", tag=_TAG)
            _run(["systemctl", "stop", svc], timeout=10)


def _start_interfering_services():
    """Restart network services after monitor mode session ends."""
    for svc in ("wpa_supplicant", "NetworkManager"):
        _log(f"Starting {svc}", tag=_TAG)
        _run(["systemctl", "start", svc], timeout=10)


def _kill_interfering():
    """Kill processes that fight monitor mode."""
    if _has_cmd("airmon-ng"):
        _log("Running airmon-ng check kill", tag=_TAG)
        _run(["airmon-ng", "check", "kill"], timeout=15)
    else:
        # Manual fallback
        for proc in ("wpa_supplicant", "dhclient", "dhcpcd", "NetworkManager"):
            _run(["pkill", "-f", proc], timeout=5)


def _ensure_up(iface):
    """Bring an interface UP if it is DOWN."""
    rc, out = _run(["ip", "link", "show", iface], timeout=5)
    if rc == 0 and "state DOWN" in out:
        _log(f"Bringing {iface} UP before use", tag=_TAG)
        _run(["ip", "link", "set", iface, "up"])
        time.sleep(0.3)


def _current_monitor_ifaces():
    """Return all currently-existing interfaces in monitor mode."""
    found = []
    try:
        for name in os.listdir("/sys/class/net"):
            if _iface_mode(name) == "monitor":
                found.append(name)
    except Exception:
        pass
    return found


# ── Public API ────────────────────────────────────────────────────────────────

def find_monitor_capable_interface():
    """
    Return the first non-onboard wireless interface, or None.
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

    Returns the monitor interface name (e.g. 'wlan1mon' or 'wlan1') or None.
    """
    if not interface:
        _log("activate_monitor_mode: empty interface", level="ERROR", tag=_TAG)
        return None

    # Reject onboard Broadcom — brcmfmac doesn't support monitor mode reliably
    if _is_onboard(interface):
        _log(
            f"{interface} uses brcmfmac (onboard Pi WiFi) — "
            "monitor mode not supported; plug in a USB WiFi dongle",
            level="ERROR", tag=_TAG,
        )
        return None

    # Already in monitor mode?
    if _iface_mode(interface) == "monitor":
        _log(f"{interface} is already in monitor mode", tag=_TAG)
        return interface

    _log(f"Activating monitor mode on {interface}", tag=_TAG)

    _stop_interfering_services()
    _kill_interfering()
    time.sleep(1)  # Let the dust settle after killing services

    # Ensure interface is UP after service-kills may have brought it down
    if not _iface_exists(interface):
        _log(f"{interface} disappeared after service kills!", level="ERROR", tag=_TAG)
        return None
    _ensure_up(interface)

    # ── Strategy 1: airmon-ng ─────────────────────────────────────────────
    if _has_cmd("airmon-ng"):
        _log(f"Trying: airmon-ng start {interface}", tag=_TAG)
        rc, out = _run(["airmon-ng", "start", interface], timeout=30)
        _log(f"airmon-ng rc={rc} output: {out[:200]}", level="DEBUG", tag=_TAG)

        # 1a. Check for any NEW interface that is now in monitor mode
        #     (handles any naming scheme airmon-ng chooses)
        for candidate in [interface + "mon", interface, interface + "0"]:
            if _iface_exists(candidate) and _iface_mode(candidate) == "monitor":
                _log(f"Monitor mode confirmed on {candidate} (airmon-ng)", tag=_TAG)
                return candidate

        # 1b. Scan ALL interfaces for one that entered monitor mode
        for mon_iface in _current_monitor_ifaces():
            _log(f"Monitor mode confirmed on {mon_iface} (airmon-ng scan)", tag=_TAG)
            return mon_iface

        # 1c. Parse airmon-ng output for the interface name
        #     Real outputs seen in the wild:
        #       (mac80211 monitor mode vif enabled for [phy1]wlan1 on [phy1]wlan1mon)
        #       (monitor mode enabled on wlan1mon)
        #       monitor mode enabled for wlan1mon
        for pattern in [
            r"enabled\s+(?:for|on)\s+\[?\w+\]?(\w+mon\w*)",  # prefer "mon" suffixed names
            r"\bon\s+\[?\w*\]?(\w+mon\w*)",
            r"monitor mode.*\b(\w+mon\b)",
            r"enabled.*\[?\w+\]?(\w+)",                        # generic last-resort
        ]:
            for m in re.finditer(pattern, out, re.IGNORECASE):
                candidate = m.group(1).strip("[]")
                if candidate.startswith("phy"):
                    continue  # skip phy names
                if _iface_exists(candidate) and _iface_mode(candidate) == "monitor":
                    _log(f"Monitor mode confirmed on {candidate} (regex)", tag=_TAG)
                    return candidate

        _log("airmon-ng ran but no monitor interface confirmed; falling back to iw", level="WARN", tag=_TAG)

    # ── Strategy 2: iw / ip ──────────────────────────────────────────────
    _log(f"Trying: ip/iw manual for {interface}", tag=_TAG)
    _run(["ip", "link", "set", interface, "down"])
    time.sleep(0.3)
    rc, out = _run(["iw", "dev", interface, "set", "type", "monitor"])
    _log(f"iw set type monitor rc={rc}: {out}", level="DEBUG", tag=_TAG)
    _run(["ip", "link", "set", interface, "up"])
    time.sleep(0.5)

    if _iface_mode(interface) == "monitor":
        _log(f"Monitor mode active on {interface} (iw fallback)", tag=_TAG)
        return interface

    if rc != 0:
        _log(f"iw set type monitor failed ({out}). Trying iw phy approach.", level="WARN", tag=_TAG)

    # ── Strategy 3: iw phy ───────────────────────────────────────────────
    phy = _get_phy(interface)
    if phy:
        _log(f"Trying: iw phy {phy} set monitor none", tag=_TAG)
        _run(["ip", "link", "set", interface, "down"])
        time.sleep(0.2)
        rc2, out2 = _run(["iw", "phy", phy, "set", "monitor", "none"])
        _log(f"iw phy rc={rc2}: {out2}", level="DEBUG", tag=_TAG)
        _run(["ip", "link", "set", interface, "up"])
        time.sleep(0.5)

        if _iface_mode(interface) == "monitor":
            _log(f"Monitor mode active on {interface} (iw phy fallback)", tag=_TAG)
            return interface

        # Also check for any newly-created mon interface
        for mon_iface in _current_monitor_ifaces():
            _log(f"Monitor mode confirmed on {mon_iface} (iw phy scan)", tag=_TAG)
            return mon_iface

    _log(f"All strategies failed on {interface}. Driver may need special handling.", level="ERROR", tag=_TAG)
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
        _log(f"{interface} no longer exists — cleaned up already", tag=_TAG)
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
        _log(f"Trying: airmon-ng stop {interface}", tag=_TAG)
        rc, out = _run(["airmon-ng", "stop", interface], timeout=30)
        _log(f"airmon-ng stop rc={rc}: {out[:120]}", level="DEBUG", tag=_TAG)
        if not _iface_exists(interface):
            if base and base != interface and _iface_exists(base):
                _run(["ip", "link", "set", base, "up"])
                _log(f"Brought {base} back up", tag=_TAG)
            _start_interfering_services()
            return True
        if _iface_mode(interface) != "monitor":
            _start_interfering_services()
            return True

    # ── Strategy 2: iw / ip ──────────────────────────────────────────────
    _log(f"Trying: iw/ip fallback to restore {interface}", tag=_TAG)
    _run(["ip", "link", "set", interface, "down"])
    rc, out = _run(["iw", "dev", interface, "set", "type", "managed"])
    if rc != 0:
        _log(f"iw set type managed failed: {out}", level="WARN", tag=_TAG)
    _run(["ip", "link", "set", interface, "up"])
    time.sleep(0.3)

    success = _iface_mode(interface) != "monitor"
    if success:
        _log(f"Monitor mode deactivated on {interface}", tag=_TAG)
    else:
        _log(f"Could not deactivate monitor mode on {interface}", level="ERROR", tag=_TAG)

    _start_interfering_services()
    return success
