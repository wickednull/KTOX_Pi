#!/usr/bin/env python3
"""
KTOx Payload – FlockU  v2
author: wickednull

Real-time radar display for Flock Safety cameras, Penguin/FS Ext
Battery units, Raven gunshot detectors, and related ALPR hardware.

Detection stack:
WiFi (monitor mode)
1. tshark  – raw 802.11 probe req + beacon, full SSID + RSSI
2. airodump-ng CSV  – AP block + Station block fallback
3. tcpdump  – last-resort 802.11 mgmt frame parser

BLE (always parallel)
4. hcidump -R  – raw HCI parsing; catches manufacturer ID
0x09C8 (XUNTONG/Penguin) even when name is
stripped (firmware update March 2025)
5. hcitool lescan  – name-based fallback if hcidump unavailable

Research sources:

- ryanohoro.com  “Spotting Flock Safety’s Falcon Cameras” (2024/2025)
- colonelpanichacks/flock-you  (crowdsourced OUI + BLE patterns)
- wgreenberg/flock-you  (0x09C8 manufacturer ID method)
- GainSec  “Bird Hunting Season” (Raven GATT service UUIDs)
- deflock.me  (crowdsourced device signatures)

Interface handling:
Accepts wlan0, wlan1, wlan0mon, wlan1mon etc.
Auto-detects; prefers wlan1 (dedicated dongle), falls back to wlan0.
If the interface already ends in ‘mon’ it is used directly.

Controls (Waveshare 1.44” LCD HAT – BCM GPIO):
KEY2 short   – toggle list / radar view
KEY2 long    – export loot to JSON
KEY1         – reset all detection data
UP / DOWN    – scroll flock list (list view)
OK           – view flock detail (list view)
KEY3         – exit (auto-exports if data present)

Loot: /root/KTOx/loot/FlockDetect/
"""

import os
import re
import sys
import json
import math
import time
import signal
import hashlib
import threading
import subprocess
import tempfile
import shutil
from datetime import datetime

# ── KTOx hardware ─────────────────────────────────────────────────────

import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config
from PIL import Image, ImageDraw, ImageFont

# ══════════════════════════════════════════════════════════════════════

# LCD / GPIO INIT

# ══════════════════════════════════════════════════════════════════════

PINS = {
    "UP":    6,  "DOWN": 19, "LEFT":  5,
    "RIGHT": 26, "OK":   13, "KEY1": 21,
    "KEY2": 20,  "KEY3": 16,
}

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
for _p in PINS.values():
    GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD_Config.Driver_Delay_ms(500)
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
LCD.LCD_Clear()

W, H = 128, 128

def _font(size: int = 9):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()

FONT_SM = _font(8)
FONT_MD = _font(9)

# ══════════════════════════════════════════════════════════════════════

# BUTTON HELPERS

# ══════════════════════════════════════════════════════════════════════

def wait_btn(timeout: float = 0.06) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.04)
                return name
        time.sleep(0.01)
    return None

def is_long_press(btn: str, hold: float = 2.0) -> bool:
    pin = PINS[btn]
    if GPIO.input(pin) != 0:
        return False
    start = time.monotonic()
    while GPIO.input(pin) == 0:
        time.sleep(0.04)
        if time.monotonic() - start >= hold:
            while GPIO.input(pin) == 0:
                time.sleep(0.04)
            return True
    return False

# ══════════════════════════════════════════════════════════════════════

# PATHS

# ══════════════════════════════════════════════════════════════════════

LOOT_DIR = "/root/KTOx/loot/FlockDetect"
os.makedirs(LOOT_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════

# DETECTION DATABASES  (research-derived)

# ══════════════════════════════════════════════════════════════════════

# Verified Flock / ALPR hardware OUIs
# Sources: deflock.me, ryanohoro.com, colonelpanichacks/flock-you oui.txt

FLOCK_MAC_PREFIXES = {
    # LiteOn (primary Falcon V2 WiFi chipset – FCC ID WCBN3510A)
    "74:4C:A1", "00:90:4C", "CC:40:D0", "A0:A4:C5",
    # Axis Communications (camera SoC)
    "00:0C:43", "00:40:8C", "AC:CC:8E",
    # Sierra Wireless RC76B (cellular modem – FCC ID N7NRC76B)
    "00:A0:D5", "00:13:A2",
    # Raspberry Pi (edge compute)
    "B8:27:EB", "DC:A6:32", "E4:5F:01",
    # Hikvision / Dahua (rebranded ALPR units)
    "00:1E:C7", "4C:11:AE", "70:E4:22",
    "00:12:C9", "4C:54:99", "9C:8E:CD",
    # FLIR / Bosch
    "00:1C:F0", "00:1E:3D", "00:0B:5D", "00:07:5F",
    # Compulab (Flock compute-on-module)
    "00:50:C2",
    # Cradlepoint cellular
    "00:1C:8E",
}

# SSID patterns – WiFi only active during install/troubleshoot
# Source: ryanohoro.com, WiGLE.net data, colonelpanichacks/flock-you

FLOCK_SSID_PATTERNS = [
    r"^Flock-[0-9A-Fa-f]{4,8}$",   # canonical: Flock-AABBCC
    r"^Flock[-*]",
    r"^FS[-*]",
    r"^FS Ext Battery",
    r"^FlockSafety",
    r"(?i)flock.safety",
    r"(?i)flock",
    r"(?i)penguin",
    r"(?i)raven",
    r"(?i)pigvision",
    r"^ALPRcam",
    r"(?i)alpr",
]

# BLE device names (hcitool lescan path)
# NOTE: "Penguin-XXXXXXXXXX" renamed to 10-digit serial in Mar 2025 FW update
# Primary detection is now 0x09C8 manufacturer ID via hcidump.

FLOCK_BLE_NAMES = [
    "FS Ext Battery",
    "FlockSafety",
    "Flock",
    "Penguin",
    "Pigvision",
    "Raven",
]

# BLE manufacturer company ID 0x09C8 = XUNTONG (little-endian: C8 09)
# Catches Penguin batteries even after name was stripped in Mar 2025 firmware.
# Source: wgreenberg/flock-you, ryanohoro.com validated packet capture

XUNTONG_LE = bytes([0xC8, 0x09])

# Raven gunshot detector BLE GATT service UUIDs
# Source: GainSec raven_configurations.json (fw 1.1.7, 1.2.0, 1.3.1)

RAVEN_SERVICE_UUIDS = {
    "0000180a-0000-1000-8000-00805f9b34fb",  # Device Information
    "0000180f-0000-1000-8000-00805f9b34fb",  # Battery Service
    "a3c87500-8ed3-4bdf-8a39-a01bebede295",  # GPS
    "a3c87600-8ed3-4bdf-8a39-a01bebede295",  # Power/charging
    "a3c87700-0000-1000-8000-00805f9b34fb",  # Network/cellular
    "a3c87800-0000-1000-8000-00805f9b34fb",  # Upload
    "a3c87900-0000-1000-8000-00805f9b34fb",  # Error reporting
    "a3c87000-0000-1000-8000-00805f9b34fb",  # Health (legacy fw1.1.x)
    "a3c87100-0000-1000-8000-00805f9b34fb",  # Location (legacy fw1.1.x)
}

# Scoring weights

SCORES = {
    "mac_prefix":    40,
    "ssid_exact":    75,
    "ssid_pattern":  55,
    "probe_ssid":    55,
    "ble_name":      50,
    "ble_mfg_id":    85,   # 0x09C8 – highest confidence single signal
    "ble_raven_uuid":90,   # Raven GATT UUID
    "ap_assoc":      35,
    "mac_ble_prefix":45,
}

# ══════════════════════════════════════════════════════════════════════

# SHARED STATE

# ══════════════════════════════════════════════════════════════════════

_lock        = threading.RLock()
running      = True
view_mode    = "radar"
detail_view  = False
detail_flock = None
scroll_pos   = 0
selected_idx = 0
sweep_deg    = 0.0
sweep_speed  = 3.5       # degrees per render frame

detected_devices: dict = {}
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

# ══════════════════════════════════════════════════════════════════════

# SUBPROCESS HELPERS

# ══════════════════════════════════════════════════════════════════════

def _run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""

def _kill(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    except Exception:
        pass

def _cmd_exists(name: str) -> bool:
    return subprocess.run(["which", name], capture_output=True).returncode == 0

# ══════════════════════════════════════════════════════════════════════

# INTERFACE DETECTION & MONITOR MODE

# ══════════════════════════════════════════════════════════════════════

def _iface_exists(name: str) -> bool:
    return os.path.exists(f"/sys/class/net/{name}")

def _is_monitor(iface: str) -> bool:
    return "monitor" in _run(f"iw dev {iface} info 2>/dev/null").lower()

def find_wifi_iface() -> str | None:
    """
    Return the best available base wireless interface name.
    Priority: wlan1 > wlan0.
    Also detects pre-existing wlanXmon interfaces.
    """
    for iface in ["wlan1", "wlan0"]:
        if _iface_exists(iface):
            return iface
        mon = f"{iface}mon"
        if _iface_exists(mon) and _is_monitor(mon):
            return iface   # return base; enable_monitor will find mon
    return None

def enable_monitor_mode(iface: str) -> str | None:
    """
    Put iface into monitor mode.
    Handles: wlan0, wlan1, and pre-existing wlan0mon / wlan1mon.
    Returns the active monitor interface name or None on failure.
    """
    base = iface.replace("mon", "")
    mon  = f"{base}mon"

    # Already in monitor mode?
    if _iface_exists(mon) and _is_monitor(mon):
        return mon
    if _iface_exists(base) and _is_monitor(base):
        return base

    # Kill interfering processes, start monitor mode
    _run("airmon-ng check kill")
    time.sleep(0.6)
    _run(f"airmon-ng start {base}")
    time.sleep(0.5)

    if _iface_exists(mon) and _is_monitor(mon):
        return mon
    if _iface_exists(base) and _is_monitor(base):
        return base

    # Manual fallback
    _run(f"ip link set {base} down")
    _run(f"iw dev {base} set type monitor")
    _run(f"ip link set {base} up")
    time.sleep(0.4)

    if _iface_exists(base) and _is_monitor(base):
        return base
    if _iface_exists(mon) and _is_monitor(mon):
        return mon

    return None

def disable_monitor_mode(iface: str, mon_iface: str):
    """Restore managed mode. Called from finally – must never raise."""
    base = iface.replace("mon", "")
    try:
        _run(f"airmon-ng stop {mon_iface}", timeout=10)
    except Exception:
        pass
    try:
        _run(f"ip link set {base} down")
        _run(f"iw dev {base} set type managed")
        _run(f"ip link set {base} up")
    except Exception:
        pass
    try:
        _run("systemctl restart NetworkManager", timeout=15)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════

# SCORING / DEVICE UPDATE

# ══════════════════════════════════════════════════════════════════════

def _score_ap(mac: str, ssid: str = "") -> tuple:
    score, method = 0, ""
    oui = mac.upper()[:8]
    if oui in FLOCK_MAC_PREFIXES:
        score  += SCORES["mac_prefix"]
        method  = "mac_prefix"
    if ssid:
        if re.match(r"^Flock-[0-9A-Fa-f]{4,8}$", ssid, re.I):
            score  += SCORES["ssid_exact"]
            method  = method or "ssid_exact"
        else:
            for pattern in FLOCK_SSID_PATTERNS:
                if re.search(pattern, ssid, re.I):
                    score  += SCORES["ssid_pattern"]
                    method  = method or "ssid_pattern"
                    break
    return score, method

def _update_device(mac: str, rssi: int, name: str, score: int,
                   method: str, extra: dict = None):
    if score <= 0:
        return
    with _lock:
        existing = detected_devices.get(mac, {})
        if existing.get("score", 0) <= score:
            entry = {
                "last_seen": time.time(),
                "rssi":      max(rssi, existing.get("rssi", rssi)),
                "score":     score,
                "name":      name or existing.get("name", ""),
                "method":    method,
            }
            if extra:
                entry.update(extra)
            detected_devices[mac] = entry

# ══════════════════════════════════════════════════════════════════════

# BLE – hcidump raw HCI (primary; catches 0x09C8 mfg ID)

# ══════════════════════════════════════════════════════════════════════

def _estimate_raven_fw(uuids: set) -> str:
    if "a3c87000-0000-1000-8000-00805f9b34fb" in uuids:
        return "1.1.x"
    if "a3c87700-0000-1000-8000-00805f9b34fb" in uuids:
        return "1.2+/1.3+"
    return "unknown"

def _process_hci_adv(mac: str, payload_hex: str):
    """Score a raw HCI advertisement payload."""
    score, method, extra = 0, "", {}
    try:
        raw = bytes.fromhex(payload_hex.replace(" ", ""))
    except Exception:
        raw = b""

    # Manufacturer ID 0x09C8 (XUNTONG / Penguin battery)
    if XUNTONG_LE in raw:
        score  = SCORES["ble_mfg_id"]
        method = "ble_mfg_xuntong"

    # Raven GATT service UUIDs
    raw_hex  = payload_hex.replace(" ", "").lower()
    found_uuids = set()
    for uuid in RAVEN_SERVICE_UUIDS:
        uuid_hex = uuid.replace("-", "")
        if uuid_hex in raw_hex:
            found_uuids.add(uuid)
    if found_uuids:
        score  = max(score, SCORES["ble_raven_uuid"])
        method = "ble_raven_uuid"
        extra["raven_fw"] = _estimate_raven_fw(found_uuids)

    # OUI fallback
    if score == 0 and mac[:8].upper() in FLOCK_MAC_PREFIXES:
        score  = SCORES["mac_ble_prefix"]
        method = "ble_mac_prefix"

    _update_device(mac, -55, "", score, method, extra or None)

def hcidump_ble_thread():
    """
    Parse raw HCI LE advertising events via hcidump -R.
    This is the only way to catch 0x09C8 manufacturer ID from
    Penguin batteries after their Mar 2025 name-stripping firmware update.
    """
    if not _cmd_exists("hcidump"):
        ble_lescan_thread()
        return

    _run("hciconfig hci0 up")
    time.sleep(0.3)

    proc = None
    try:
        proc = subprocess.Popen(
            ["hcidump", "-R", "--raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
    except Exception as e:
        print(f"[BLE] hcidump failed: {e}")
        ble_lescan_thread()
        return

    # hcidump -R lines:  > 04 3E 26 02 01 00 01 AA BB CC DD EE FF 1C ...
    # MAC bytes are at offsets 7-12, reversed (little-endian)
    hci_le_re = re.compile(
        r">\s+04\s+3[Ee]\s+\S+\s+\S+\s+\S+\s+\S+\s+"
        r"([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\s+"
        r"([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})"
    )

    buf     = []
    cur_mac = None

    try:
        while running:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.strip()

            if line.startswith(">"):
                if buf and cur_mac:
                    _process_hci_adv(cur_mac, " ".join(buf))
                buf, cur_mac = [], None
                m = hci_le_re.match(line)
                if m:
                    rev = [m.group(i) for i in range(1, 7)]
                    mac = ":".join(reversed(rev)).upper()
                    if _MAC_RE.match(mac):
                        cur_mac = mac
                buf.append(line)
            elif line.startswith("<"):
                if buf and cur_mac:
                    _process_hci_adv(cur_mac, " ".join(buf))
                buf, cur_mac = [], None
            else:
                buf.append(line)
    finally:
        if buf and cur_mac:
            try:
                _process_hci_adv(cur_mac, " ".join(buf))
            except Exception:
                pass
        _kill(proc)

# ══════════════════════════════════════════════════════════════════════

# BLE – hcitool lescan (name-based fallback)

# ══════════════════════════════════════════════════════════════════════

def ble_lescan_thread():
    """hcitool lescan fallback."""
    _run("hciconfig hci0 up")
    proc = None
    try:
        proc = subprocess.Popen(
            ["sudo", "hcitool", "lescan", "--duplicates"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
    except Exception as e:
        print(f"[BLE] hcitool lescan failed: {e}")
        return

    numeric_re = re.compile(r"^\d{10}$")

    try:
        while running:
            line = proc.stdout.readline()
            if not line:
                break
            stripped = line.strip()
            m = re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", stripped)
            if not m:
                continue
            mac  = m.group(0).upper()
            name = stripped[len(m.group(0)):].strip()

            score, method = 0, ""
            for pat in FLOCK_BLE_NAMES:
                if pat.lower() in name.lower():
                    score  = SCORES["ble_name"]
                    method = "ble_name"
                    break

            # 10-digit numeric serial + known OUI = post-Mar2025 Penguin
            if score == 0 and numeric_re.match(name):
                if mac[:8].upper() in FLOCK_MAC_PREFIXES:
                    score  = SCORES["ble_mfg_id"] - 10
                    method = "ble_numeric_serial"

            if score == 0 and mac[:8].upper() in FLOCK_MAC_PREFIXES:
                score  = SCORES["mac_ble_prefix"]
                method = "ble_mac_prefix"

            _update_device(mac, -55, name, score, method)
    finally:
        _kill(proc)

def ble_thread_launcher():
    """Use hcidump if available, else lescan."""
    if _cmd_exists("hcidump"):
        hcidump_ble_thread()
    else:
        ble_lescan_thread()

# ══════════════════════════════════════════════════════════════════════

# WIFI – tshark (preferred)

# ══════════════════════════════════════════════════════════════════════

def tshark_sniff_thread(mon_iface: str):
    cmd = [
        "tshark", "-i", mon_iface,
        "-Y", "wlan.fc.type_subtype == 0x04 || wlan.fc.type_subtype == 0x08",
        "-T", "fields",
        "-e", "wlan.sa",
        "-e", "wlan.ssid",
        "-e", "radiotap.dbm_antsignal",
        "-l",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
    except Exception as e:
        print(f"[WiFi] tshark failed: {e}")
        return
    try:
        while running:
            line = proc.stdout.readline()
            if not line:
                break
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            mac  = parts[0].upper()
            ssid = parts[1] if len(parts) > 1 else ""
            try:
                rssi = int(parts[2]) if len(parts) > 2 and parts[2] else -70
            except ValueError:
                rssi = -70
            if not _MAC_RE.match(mac):
                continue
            score, method = _score_ap(mac, ssid)
            if score == 0 and ssid:
                for pattern in FLOCK_SSID_PATTERNS:
                    if re.search(pattern, ssid, re.I):
                        score  = SCORES["probe_ssid"]
                        method = "probe_ssid"
                        break
            _update_device(mac, rssi, ssid, score, method)
    finally:
        _kill(proc)

# ══════════════════════════════════════════════════════════════════════

# WIFI – airodump-ng CSV (secondary)

# ══════════════════════════════════════════════════════════════════════

def _parse_airodump_csv(csv_path: str):
    try:
        with open(csv_path, "r", errors="ignore") as fh:
            content = fh.read()
    except OSError:
        return
    blocks = re.split(r"\n\s*\n", content)

    # AP block
    for line in blocks[0].splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 14:
            continue
        mac = parts[0].upper()
        if not _MAC_RE.match(mac):
            continue
        try:
            rssi = int(parts[8])
            if rssi >= 0:
                rssi = -60
        except ValueError:
            rssi = -60
        ssid  = parts[13].strip()
        score, method = _score_ap(mac, ssid)
        _update_device(mac, rssi, ssid, score, method)

    # Station block – catches cameras acting as clients
    if len(blocks) < 2:
        return
    for line in blocks[1].splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        mac = parts[0].upper()
        if not _MAC_RE.match(mac):
            continue
        try:
            rssi = int(parts[3])
            if rssi >= 0:
                rssi = -70
        except ValueError:
            rssi = -70
        ap_mac = parts[5].strip().upper()
        probed = parts[6].strip() if len(parts) > 6 else ""
        score, method = _score_ap(mac, probed)
        if _MAC_RE.match(ap_mac):
            ap_score, _ = _score_ap(ap_mac, "")
            if ap_score > 0 and score == 0:
                score  = SCORES["ap_assoc"]
                method = "ap_assoc"
        _update_device(mac, rssi, probed, score, method)

def airodump_sniff_thread(mon_iface: str):
    tmpdir   = tempfile.mkdtemp(prefix="/tmp/flockU_")
    prefix   = os.path.join(tmpdir, "scan")
    csv_path = prefix + "-01.csv"
    cmd = ["airodump-ng", "--write", prefix, "--output-format", "csv",
           "--write-interval", "3", mon_iface]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[WiFi] airodump-ng failed: {e}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return
    try:
        while running:
            time.sleep(3)
            if os.path.exists(csv_path):
                _parse_airodump_csv(csv_path)
    finally:
        _kill(proc)
        shutil.rmtree(tmpdir, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════

# WIFI – tcpdump (last resort)

# ══════════════════════════════════════════════════════════════════════

def tcpdump_sniff_thread(mon_iface: str):
    filt = "type mgt subtype probe-req or type mgt subtype beacon"
    proc = None
    try:
        proc = subprocess.Popen(
            ["tcpdump", "-i", mon_iface, "-e", "-l", filt],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
    except Exception as e:
        print(f"[WiFi] tcpdump failed: {e}")
        return
    mac_re  = re.compile(r"([\da-fA-F]{2}:){5}[\da-fA-F]{2}")
    ssid_re = re.compile(r"(?:Beacon|Probe (?:Request|Response)) (([^)]+))")
    try:
        while running:
            line = proc.stdout.readline()
            if not line:
                break
            mm = mac_re.search(line)
            if not mm:
                continue
            mac  = mm.group(0).upper()
            sm   = ssid_re.search(line)
            ssid = sm.group(1) if sm else ""
            score, method = _score_ap(mac, ssid)
            if score == 0 and ssid:
                for pattern in FLOCK_SSID_PATTERNS:
                    if re.search(pattern, ssid, re.I):
                        score  = SCORES["probe_ssid"]
                        method = "probe_ssid"
                        break
            _update_device(mac, -65, ssid, score, method)
    finally:
        _kill(proc)

def wifi_sniff_thread(mon_iface: str):
    if _cmd_exists("tshark"):
        tshark_sniff_thread(mon_iface)
    elif _cmd_exists("airodump-ng"):
        airodump_sniff_thread(mon_iface)
    elif _cmd_exists("tcpdump"):
        tcpdump_sniff_thread(mon_iface)
    else:
        print("[WiFi] No sniffer found: install tshark, airodump-ng, or tcpdump")

# ══════════════════════════════════════════════════════════════════════

# FLOCK CORRELATION

# ══════════════════════════════════════════════════════════════════════

def compute_flocks() -> list:
    with _lock:
        devices = dict(detected_devices)
    if not devices:
        return []
    window = 30
    used   = set()
    macs   = list(devices.keys())
    groups = []
    for mac_a in macs:
        if mac_a in used:
            continue
        group = [mac_a]
        ta    = devices[mac_a]["last_seen"]
        for mac_b in macs:
            if mac_b in used or mac_b == mac_a:
                continue
            if abs(ta - devices[mac_b]["last_seen"]) < window:
                group.append(mac_b)
        if len(group) >= 2:
            for m in group:
                used.add(m)
            groups.append({
                "members":    group,
                "size":       len(group),
                "score":      sum(devices[m]["score"] for m in group) // len(group),
                "first_seen": min(devices[m]["last_seen"] for m in group),
            })
    for mac in macs:
        if mac not in used and devices[mac]["score"] >= 60:
            groups.append({
                "members":    [mac],
                "size":       1,
                "score":      devices[mac]["score"],
                "first_seen": devices[mac]["last_seen"],
            })
    groups.sort(key=lambda g: g["score"], reverse=True)
    return groups

# ══════════════════════════════════════════════════════════════════════

# LOOT EXPORT

# ══════════════════════════════════════════════════════════════════════

def export_loot() -> str:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOOT_DIR, f"flock_{ts}.json")
    with _lock:
        snap = dict(detected_devices)
    with open(filepath, "w") as fh:
        json.dump({"timestamp": ts, "devices": snap,
                   "flocks": compute_flocks()}, fh, indent=2, default=str)
    return filepath

# ══════════════════════════════════════════════════════════════════════

# DRAWING

# ══════════════════════════════════════════════════════════════════════

_COL_HIGH = (255,   0,   0)
_COL_MED  = (255, 165,   0)
_COL_LOW  = (255, 220,   0)
CX, CY    = 64, 60
RADIUS    = 52
_TRAIL    = 28
_TRAIL_DEG = 72

def _conf_col(score: int) -> tuple:
    if score >= 70: return _COL_HIGH
    if score >= 40: return _COL_MED
    return _COL_LOW

def _mac_angle(mac: str) -> float:
    return int(hashlib.sha1(mac.encode()).hexdigest()[:8], 16) % 360

def _rssi_r(rssi: int) -> int:
    rssi = max(-95, min(-20, rssi))
    t    = (rssi - (-20)) / (-95.0 - (-20))
    return int(8 + t * (RADIUS - 14))

def _pxy(deg: float, r: float) -> tuple:
    rad = math.radians(deg - 90)
    return CX + r * math.cos(rad), CY + r * math.sin(rad)

def _draw_header(draw, active: bool):
    draw.rectangle((0, 0, W-1, 13), fill=(10, 0, 0))
    draw.text((2, 1), "FLOCK RADAR", font=FONT_MD, fill=(231, 76, 60))
    draw.ellipse((W-12, 2, W-4, 10),
                 fill=(30, 132, 73) if active else (180, 30, 30))

def _draw_footer(draw, text: str):
    draw.rectangle((0, H-12, W-1, H-1), fill=(10, 0, 0))
    draw.text((2, H-10), text[:26], font=FONT_SM, fill="#AAA")

def _show_msg(l1: str, l2: str = "", delay: float = 1.4):
    img  = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((10, 48), l1,       font=FONT_MD, fill=(30, 132, 73))
    if l2:
        draw.text((4,  64), l2[:22], font=FONT_SM, fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(delay)

def draw_list_view(flock_list: list):
    img  = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    with _lock:
        dev_count = len(detected_devices)
    _draw_header(draw, True)
    draw.text((2, 15), f"Dev:{dev_count}  Flocks:{len(flock_list)}",
              font=FONT_SM, fill=(113, 125, 126))
    if not flock_list:
        draw.text((6, 40), "No flocks detected", font=FONT_SM, fill=(86, 101, 115))
        draw.text((6, 52), "Scanning...",         font=FONT_SM, fill=(86, 101, 115))
    else:
        y = 28
        for i, flock in enumerate(flock_list[scroll_pos: scroll_pos + 5]):
            idx    = scroll_pos + i
            prefix = ">" if idx == selected_idx else " "
            raven  = " [R]" if any(
                detected_devices.get(m, {}).get("raven_fw")
                for m in flock["members"]) else ""
            draw.text((1, y),
                      f"{prefix}{flock['size']}d {flock['score']}%{raven}",
                      font=FONT_SM, fill=_conf_col(flock["score"]))
            y += 12
    _draw_footer(draw, "OK:View K2:Radar K2L:Exp")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_flock_detail(flock: dict):
    img  = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W-1, 13), fill=(10, 0, 0))
    draw.text((2, 1),  f"FLOCK ({flock['size']} dev)", font=FONT_MD,
              fill=(231, 76, 60))
    draw.text((2, 15), f"Score: {flock['score']}%",    font=FONT_SM,
              fill="#AAA")
    y = 28
    with _lock:
        snap = dict(detected_devices)
    for mac in flock["members"][:5]:
        info   = snap.get(mac, {})
        fw     = info.get("raven_fw", "")
        tag    = f"[fw{fw}]" if fw else f"[{info.get('method','?')[:8]}]"
        draw.text((2, y), f"{mac[-14:]} {tag}", font=FONT_SM,
                  fill=(171, 178, 185))
        y += 12
    if len(flock["members"]) > 5:
        draw.text((2, y), f"+{len(flock['members'])-5} more",
                  font=FONT_SM, fill=(113, 125, 126))
    _draw_footer(draw, "Any key: back")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_radar_frame():
    """
    Radar frame renderer, optimised for Pi Zero 2W throughput:
    - Single snapshot of detected_devices per frame (one lock acquire)
    - Sweep trail in one pass (no redundant math)
    - Glow outer ring + core blip for visual depth
    - Raven devices marked with purple 'R' tag
    """
    img  = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)

    # Concentric rings
    for i in range(1, 4):
        r = RADIUS * i // 3
        draw.ellipse([(CX-r, CY-r), (CX+r, CY+r)], outline=(0, 45, 0))

    # Crosshairs
    draw.line([(CX, CY - RADIUS), (CX, CY + RADIUS)], fill=(0, 28, 0))
    draw.line([(CX - RADIUS, CY), (CX + RADIUS, CY)], fill=(0, 28, 0))

    # Sweep trail
    for step in range(_TRAIL, 0, -1):
        angle  = sweep_deg - (step * _TRAIL_DEG / _TRAIL)
        bright = int(55 * (1.0 - step / _TRAIL))
        x2, y2 = _pxy(angle, RADIUS)
        draw.line([(CX, CY), (x2, y2)], fill=(0, bright, 0), width=1)

    # Sweep line – 3-pass glow
    sx, sy = _pxy(sweep_deg, RADIUS)
    draw.line([(CX, CY), (sx, sy)], fill=(0,  60, 0), width=3)
    draw.line([(CX, CY), (sx, sy)], fill=(0, 150, 0), width=2)
    draw.line([(CX, CY), (sx, sy)], fill=(0, 255, 0), width=1)

    # Blips – one lock acquire for entire frame
    with _lock:
        snapshot = list(detected_devices.items())

    for mac, info in snapshot:
        angle  = _mac_angle(mac)
        r_px   = _rssi_r(info.get("rssi", -65))
        col    = _conf_col(info["score"])
        delta  = (sweep_deg - angle) % 360
        bright = 1.0 if delta < 6 else max(0.12, 1.0 - (delta / 360.0) * 1.15)
        r, g, b = col
        blip   = (int(r*bright), int(g*bright), int(b*bright))
        px, py = _pxy(angle, r_px)
        px, py = int(px), int(py)

        # Glow halo
        draw.ellipse([(px-3, py-3), (px+3, py+3)],
                     fill=(int(r*bright*0.25), int(g*bright*0.25),
                           int(b*bright*0.25)))
        # Body
        draw.ellipse([(px-2, py-2), (px+2, py+2)], fill=blip)
        # Core
        core = (min(255, int(r*bright*1.6)), min(255, int(g*bright*1.6)),
                min(255, int(b*bright*1.6)))
        draw.ellipse([(px-1, py-1), (px+1, py+1)], fill=core)

        # MAC label
        draw.text((px+3, py-4), mac.replace(":", "")[-4:],
                  font=FONT_SM, fill=(180, 180, 180))

        # Raven indicator
        if info.get("raven_fw"):
            draw.text((px+3, py+4), "R", font=FONT_SM, fill=(180, 80, 255))

    _draw_header(draw, True)
    with _lock:
        dev_count = len(detected_devices)
    _draw_footer(draw, f"Dev:{dev_count} K2:List K2L:Export")
    LCD.LCD_ShowImage(img, 0, 0)

# ══════════════════════════════════════════════════════════════════════

# MAIN

# ══════════════════════════════════════════════════════════════════════

def main():
    global running, view_mode, detail_view, detail_flock
    global scroll_pos, selected_idx, detected_devices, sweep_deg

    def _stop(sig, frame):
        global running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT,  _stop)

    # ── Find interface ──────────────────────────────────────────────────
    iface = find_wifi_iface()
    if not iface:
        _show_msg("No WiFi adapter", "Check wlan0/wlan1", delay=3)
        GPIO.cleanup()
        sys.exit(1)

    # ── Enable monitor mode ─────────────────────────────────────────────
    _show_msg("Monitor mode...", iface)
    mon_iface = enable_monitor_mode(iface)
    if not mon_iface:
        _show_msg("Monitor failed", "Check airmon-ng", delay=3)
        GPIO.cleanup()
        sys.exit(1)

    _show_msg(f"Mon: {mon_iface}", "BLE + WiFi scan...")

    # ── Launch scan threads ─────────────────────────────────────────────
    threading.Thread(target=ble_thread_launcher,          daemon=True).start()
    threading.Thread(target=wifi_sniff_thread,
                     args=(mon_iface,),                   daemon=True).start()

    last_flock_update = 0.0
    flock_list: list  = []

    try:
        while running:
            btn = wait_btn(0.06)

            if btn == "KEY3":
                running = False
                break

            # Detail view
            if detail_view:
                if btn is not None:
                    detail_view = False
                    time.sleep(0.10)
                else:
                    draw_flock_detail(detail_flock)
                continue

            # KEY2 toggle / long export
            if btn == "KEY2":
                if is_long_press("KEY2", hold=2.0):
                    if detected_devices:
                        path = export_loot()
                        _show_msg("Exported!", path[-22:])
                    else:
                        _show_msg("No data yet")
                else:
                    view_mode = "radar" if view_mode == "list" else "list"
                    time.sleep(0.10)

            # Refresh flock correlation every 5 s
            now = time.monotonic()
            if now - last_flock_update > 5.0:
                flock_list        = compute_flocks()
                last_flock_update = now

            # ── List view ───────────────────────────────────────────────
            if view_mode == "list":
                max_sel = max(0, len(flock_list) - 1)
                if btn == "UP":
                    selected_idx = max(0, selected_idx - 1)
                    if selected_idx < scroll_pos:
                        scroll_pos = selected_idx
                elif btn == "DOWN":
                    selected_idx = min(selected_idx + 1, max_sel)
                    if selected_idx >= scroll_pos + 5:
                        scroll_pos = selected_idx - 4
                elif btn == "OK" and selected_idx < len(flock_list):
                    detail_flock = flock_list[selected_idx]
                    detail_view  = True
                elif btn == "KEY1":
                    with _lock:
                        detected_devices = {}
                    flock_list = []
                    _show_msg("Data reset")
                draw_list_view(flock_list)

            # ── Radar view ──────────────────────────────────────────────
            else:
                if btn == "KEY1":
                    with _lock:
                        detected_devices = {}
                    _show_msg("Data reset")
                sweep_deg = (sweep_deg + sweep_speed) % 360
                draw_radar_frame()

            time.sleep(0.03)   # ~25-30 fps on Pi Zero 2W

    # ── Cleanup ─────────────────────────────────────────────────────────
    finally:
        running = False
        time.sleep(0.8)
        try:
            if detected_devices:
                export_loot()
        except Exception:
            pass
        disable_monitor_mode(iface, mon_iface)
        try:
            LCD.LCD_Clear()
        except Exception:
            pass
        GPIO.cleanup()

if __name__ == "__main__":
    main()
