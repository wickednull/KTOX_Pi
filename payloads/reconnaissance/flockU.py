#!/usr/bin/env python3
"""
KTOx Payload – FlockU
author wickednull
================================================================
Real‑time animated radar display for Flock Safety cameras and related devices.
Uses BLE scanning + WiFi promiscuous sniffing, with confidence scoring.

Automatically enables monitor mode on the selected WiFi interface and cleans up on exit.

Controls:
  KEY2 short  – toggle list/radar view
  KEY2 long   – export data to JSON
  KEY1        – reset all detection data
  UP/DOWN     – scroll flocks (list view)
  OK          – view flock members (list view)
  KEY3        – exit

Loot: /root/KTOx/loot/FlockDetect/
"""

import os
import sys
import json
import time
import math
import hashlib
import signal
import threading
import subprocess
import re
from datetime import datetime

# KTOx hardware
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# GPIO & LCD setup
# ----------------------------------------------------------------------
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
FONT_SM = font(8)
FONT_MD = font(9)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def is_long_press(btn_name, hold=2.0):
    pin = PINS[btn_name]
    if GPIO.input(pin) == 0:
        start = time.time()
        while GPIO.input(pin) == 0:
            time.sleep(0.05)
            if time.time() - start >= hold:
                while GPIO.input(pin) == 0:
                    time.sleep(0.05)
                return True
    return False

# ----------------------------------------------------------------------
# Paths & constants
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/FlockDetect"
os.makedirs(LOOT_DIR, exist_ok=True)

# ======================================================================
# DETECTION DATABASES (from research)
# ======================================================================

# Known Flock Safety MAC OUIs
FLOCK_MAC_PREFIXES = [
    "00:0C:43",  # Axis Communications (Flock hardware)
    "00:40:8C",  # Axis
    "AC:CC:8E",  # Axis
    "00:1E:C7",  # Hikvision
    "4C:11:AE",  # Hikvision
    "70:E4:22",  # Hikvision
    "00:12:C9",  # Dahua
    "4C:54:99",  # Dahua
    "9C:8E:CD",  # Dahua
    "B8:27:EB",  # Raspberry Pi (Flock compute boxes)
    "DC:A6:32",  # Raspberry Pi
    "E4:5F:01",  # Raspberry Pi
    "00:14:2A",  # Sony
    "08:00:46",  # Sony
    "00:0F:53",  # Panasonic
    "00:80:5F",  # Panasonic
    "00:0B:5D",  # Bosch
    "00:07:5F",  # Bosch
    "00:1C:F0",  # FLIR
    "00:1E:3D",  # FLIR
]

# Known Flock SSID patterns
FLOCK_SSID_PATTERNS = [
    r"^Flock-",           # Flock-XXXX format
    r"^Flock_",
    r"^FS Ext Battery",
    r"(?i)flock",
    r"(?i)penguin",
    r"(?i)raven",
    r"(?i)pigvision",
]

# Known BLE device name patterns
FLOCK_BLE_NAME_PATTERNS = [
    "FS Ext Battery",
    "Flock",
    "Penguin",
    "Pigvision",
    "Raven",
]

# Known BLE manufacturer IDs
FLOCK_MANUFACTURER_IDS = [0x09C8]  # XUNTONG

# Scoring weights
SCORES = {
    "mac_prefix": 40,
    "ssid_pattern": 50,
    "ssid_format": 65,        # exact Flock-XXXX
    "ble_name": 45,
    "ble_mfg_id": 60,
    "raven_uuid": 80,         # (not implemented fully, placeholder)
    "wifi_probe": 30,
}

# ----------------------------------------------------------------------
# Shared state
# ----------------------------------------------------------------------
lock = threading.RLock()     # RLock: safe for reentrant calls (e.g. draw_list_view -> compute_flocks)
running = True
view_mode = "radar"          # start on radar so scanning activity is visible
detail_view = False
detail_flock = None
scroll_pos = 0
selected_idx = 0

# Detected devices: {mac: {"last_seen": float, "rssi": int, "score": int, "name": str, "method": str}}
detected_devices = {}
flocks = []                  # computed from correlation

# Radar geometry (same as WiFi radar)
CX, CY = 64, 60
RADIUS = 52
TRAIL_STEPS = 24
TRAIL_DEG = 70
sweep_deg = 0.0
sweep_speed = 2.5            # degrees per frame

# Colour mapping for confidence
COL_HIGH = (255, 0, 0)       # red   – high confidence (≥70)
COL_MED  = (255, 165, 0)     # orange – medium (40-69)
COL_LOW  = (255, 255, 0)     # yellow – low (<40)

# ----------------------------------------------------------------------
# Monitor mode management (from Auto Crack Pipeline)
# ----------------------------------------------------------------------
def run_cmd(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except:
        return ""

def get_wlan():
    for iface in ["wlan0", "wlan1"]:
        if os.path.exists(f"/sys/class/net/{iface}"):
            return iface
    return None

def enable_monitor_mode(iface):
    """Enable monitor mode on the given interface, return monitor interface name."""
    run_cmd("airmon-ng check kill")
    out = run_cmd(f"airmon-ng start {iface}")
    mon = f"{iface}mon"
    if os.path.exists(f"/sys/class/net/{mon}"):
        return mon
    # Fallback: try to set monitor on the interface itself
    run_cmd(f"ip link set {iface} down")
    run_cmd(f"iw dev {iface} set type monitor")
    run_cmd(f"ip link set {iface} up")
    return iface

def disable_monitor_mode(iface):
    """Disable monitor mode and restore managed mode."""
    run_cmd(f"airmon-ng stop {iface}mon")
    run_cmd(f"ip link set {iface} down")
    run_cmd(f"iw dev {iface} set type managed")
    run_cmd(f"ip link set {iface} up")
    run_cmd("systemctl restart NetworkManager")

# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
def bssid_angle(bssid: str) -> float:
    """Deterministic angle from MAC address."""
    digest = int(hashlib.sha1(bssid.encode()).hexdigest()[:8], 16)
    return digest % 360

def rssi_to_radius(rssi: int) -> int:
    """Map RSSI (dBm) to pixel distance from centre.
       Stronger signal → closer to centre."""
    rssi = max(-95, min(-20, rssi))
    t = (rssi - (-20)) / (-95.0 - (-20))   # 0.0 at -20, 1.0 at -95
    inner = 8
    outer = RADIUS - 6
    return int(inner + t * (outer - inner))

def polar_to_xy(angle_deg: float, r: float):
    rad = math.radians(angle_deg - 90)
    return (CX + r * math.cos(rad), CY + r * math.sin(rad))

def confidence_color(score: int):
    if score >= 70:
        return COL_HIGH
    elif score >= 40:
        return COL_MED
    else:
        return COL_LOW

# ----------------------------------------------------------------------
# BLE scanning thread
# ----------------------------------------------------------------------
def _kill_proc(proc):
    """Terminate a subprocess and wait; escalate to SIGKILL if needed."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    except Exception:
        pass

def ble_scan_thread():
    """Run hcitool lescan to capture BLE advertisements."""
    proc = None
    try:
        proc = subprocess.Popen(
            ["sudo", "hcitool", "lescan", "--duplicates"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1
        )
    except Exception as e:
        print(f"BLE scan failed: {e}")
        return
    try:
        while running:
            line = proc.stdout.readline()
            if not line:
                break
            parts = line.strip().split()
            if len(parts) >= 2:
                mac = parts[0].upper()
                name = " ".join(parts[1:])
                now = time.time()
                score = 0
                method = ""
                for pattern in FLOCK_BLE_NAME_PATTERNS:
                    if pattern.lower() in name.lower():
                        score += SCORES["ble_name"]
                        method = "ble_name"
                        break
                if score > 0:
                    with lock:
                        if mac not in detected_devices or detected_devices[mac]["score"] < score:
                            detected_devices[mac] = {
                                "last_seen": now,
                                "rssi": -50,
                                "score": score,
                                "name": name,
                                "method": method,
                            }
    finally:
        _kill_proc(proc)

# ----------------------------------------------------------------------
# Scoring helper
# ----------------------------------------------------------------------
def _score_ap(mac, essid=""):
    """Return (score, method) for a given MAC and optional SSID."""
    score = 0
    method = ""
    for prefix in FLOCK_MAC_PREFIXES:
        if mac.startswith(prefix.upper()):
            score += SCORES["mac_prefix"]
            method = "mac_prefix"
            break
    if essid:
        for pattern in FLOCK_SSID_PATTERNS:
            if re.search(pattern, essid, re.I):
                score += SCORES["ssid_pattern"]
                method = method or "ssid_pattern"
                if re.match(r"^Flock-[0-9A-F]{4,6}$", essid, re.I):
                    score += SCORES["ssid_format"]
                break
    return score, method

def _update_device(mac, rssi, essid, score, method):
    if score <= 0:
        return
    with lock:
        existing = detected_devices.get(mac, {})
        if existing.get("score", 0) <= score:
            detected_devices[mac] = {
                "last_seen": time.time(),
                "rssi": rssi,
                "score": score,
                "name": essid,
                "method": method,
            }

# ----------------------------------------------------------------------
# WiFi scanning thread (monitor mode)
# Uses airodump-ng CSV output; falls back to tcpdump if unavailable.
# ----------------------------------------------------------------------
def wifi_sniff_thread(mon_iface):
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp(prefix="/tmp/flockU_")
    prefix = os.path.join(tmpdir, "scan")
    csv_path = prefix + "-01.csv"
    cmd = ["airodump-ng", "--write", prefix, "--output-format", "csv",
           "--write-interval", "3", mon_iface]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        _tcpdump_sniff(mon_iface)
        return
    try:
        while running:
            time.sleep(3)
            if os.path.exists(csv_path):
                try:
                    _parse_airodump_csv(csv_path)
                except Exception:
                    pass
    finally:
        _kill_proc(proc)
        shutil.rmtree(tmpdir, ignore_errors=True)

def _parse_airodump_csv(csv_path):
    with open(csv_path, "r", errors="ignore") as f:
        content = f.read()
    # APs are in the first block before the blank-line Station header
    ap_block = re.split(r"\n\s*\n", content)[0]
    for line in ap_block.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 14:
            continue
        mac = parts[0].upper()
        if not re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac):
            continue
        try:
            rssi = int(parts[8])
            if rssi >= 0:
                rssi = -60
        except ValueError:
            rssi = -60
        essid = parts[13].strip()
        score, method = _score_ap(mac, essid)
        _update_device(mac, rssi, essid, score, method)

def _tcpdump_sniff(mon_iface):
    # tcpdump 802.11 filter: each alternative needs its own type qualifier
    filt = "type mgt subtype probe-req or type mgt subtype beacon"
    cmd = ["tcpdump", "-i", mon_iface, "-e", "-l", filt]
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)
    except Exception as e:
        print(f"tcpdump fallback failed: {e}")
        return
    try:
        while running:
            line = proc.stdout.readline()
            if not line:
                break
            mac_match = re.search(r"([\da-fA-F]{2}:){5}[\da-fA-F]{2}", line, re.I)
            if not mac_match:
                continue
            mac = mac_match.group(0).upper()
            # tcpdump formats SSID as: Beacon (ESSID) or Probe Request (ESSID)
            ssid_m = re.search(r"(?:Beacon|Probe (?:Request|Response)) \(([^)]+)\)", line)
            essid = ssid_m.group(1) if ssid_m else ""
            score, method = _score_ap(mac, essid)
            _update_device(mac, -60, essid, score, method)
    finally:
        _kill_proc(proc)

# ----------------------------------------------------------------------
# Flock correlation (group devices that appear together)
# ----------------------------------------------------------------------
def compute_flocks():
    """Group devices that were seen within a 30-second window."""
    with lock:
        devices = dict(detected_devices)
    if len(devices) < 2:
        return []
    now = time.time()
    window = 30
    used = set()
    macs = list(devices.keys())
    groups = []
    for i, mac_a in enumerate(macs):
        if mac_a in used:
            continue
        group = [mac_a]
        ta = devices[mac_a]["last_seen"]
        for j, mac_b in enumerate(macs):
            if mac_b in used or mac_b == mac_a:
                continue
            tb = devices[mac_b]["last_seen"]
            if abs(ta - tb) < window:
                group.append(mac_b)
        if len(group) >= 2:
            for m in group:
                used.add(m)
            avg_score = sum(devices[m]["score"] for m in group) // len(group)
            groups.append({
                "members": group,
                "size": len(group),
                "score": avg_score,
                "first_seen": min(devices[m]["last_seen"] for m in group),
            })
    return groups

# ----------------------------------------------------------------------
# Loot export
# ----------------------------------------------------------------------
def export_loot():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOOT_DIR, f"flock_{ts}.json")
    with lock:
        devices_snapshot = dict(detected_devices)
    data = {
        "timestamp": ts,
        "devices": devices_snapshot,
        "flocks": compute_flocks(),
    }
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return filepath

# ----------------------------------------------------------------------
# Drawing helpers
# ----------------------------------------------------------------------
def draw_header(draw, active):
    draw.rectangle((0, 0, W-1, 13), fill=(10, 0, 0))
    draw.text((2, 1), "FLOCK RADAR", font=FONT_MD, fill=(231, 76, 60))
    draw.ellipse((W-12, 2, W-4, 10), fill=(30, 132, 73) if active else "#FF0000")

def draw_footer(draw, text):
    draw.rectangle((0, H-12, W-1, H-1), fill=(10, 0, 0))
    draw.text((2, H-10), text[:24], font=FONT_SM, fill="#AAA")

def show_message(line1, line2=""):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((10, 50), line1, font=FONT_MD, fill=(30, 132, 73))
    if line2:
        draw.text((4, 65), line2, font=FONT_SM, fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1.5)

# ----------------------------------------------------------------------
# List view
# ----------------------------------------------------------------------
def draw_list_view():
    img = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    with lock:
        devices = list(detected_devices.items())
        flock_list = compute_flocks()
        sel = selected_idx
        sc = scroll_pos
    draw_header(draw, True)
    draw.text((2, 15), f"Devices:{len(devices)}  Flocks:{len(flock_list)}", font=FONT_SM, fill=(113, 125, 126))
    if not flock_list:
        draw.text((6, 40), "No flocks detected", font=FONT_SM, fill=(86, 101, 115))
        draw.text((6, 52), "Waiting for data...", font=FONT_SM, fill=(86, 101, 115))
    else:
        visible = flock_list[sc:sc+5]
        y = 28
        for i, flock in enumerate(visible):
            idx = sc + i
            prefix = ">" if idx == sel else " "
            color = "#00FF00" if flock["score"] >= 70 else "#FFAA00" if flock["score"] >= 40 else "#FF4444"
            draw.text((1, y), f"{prefix}{flock['size']}dev {flock['score']}%", font=FONT_SM, fill=color)
            y += 12
    draw_footer(draw, f"Flocks:{len(flock_list)} OK:View K2:Radar")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_flock_detail(flock):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W-1, 13), fill=(10, 0, 0))
    draw.text((2, 1), f"FLOCK ({flock['size']} dev)", font=FONT_MD, fill=(231, 76, 60))
    draw.text((2, 16), f"Score: {flock['score']}%", font=FONT_SM, fill="#AAA")
    members = flock["members"]
    y = 30
    for mac in members[:6]:
        draw.text((2, y), mac[-15:], font=FONT_SM, fill=(171, 178, 185))
        y += 12
    if len(members) > 6:
        draw.text((2, y), f"+{len(members)-6} more", font=FONT_SM, fill=(113, 125, 126))
    draw_footer(draw, "Any key: back")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Radar view (adapted from WiFi radar)
# ----------------------------------------------------------------------
def draw_radar_frame():
    img = Image.new("RGB", (W, H), (10, 0, 0))
    draw = ImageDraw.Draw(img)

    # Concentric rings
    for i in range(1, 4):
        r = RADIUS * i // 3
        draw.ellipse([(CX - r, CY - r), (CX + r, CY + r)], outline=(0,40,0), width=1)

    # Crosshairs
    draw.line([(CX, CY - RADIUS), (CX, CY + RADIUS)], fill=(0,30,0), width=1)
    draw.line([(CX - RADIUS, CY), (CX + RADIUS, CY)], fill=(0,30,0), width=1)

    # Sweep trail
    for step in range(TRAIL_STEPS, 0, -1):
        trail_angle = sweep_deg - (step * TRAIL_DEG / TRAIL_STEPS)
        alpha = int(60 * (1.0 - step / TRAIL_STEPS))
        x2, y2 = polar_to_xy(trail_angle, RADIUS)
        draw.line([(CX, CY), (x2, y2)], fill=(0, alpha, 0), width=1)

    # Sweep line
    sx, sy = polar_to_xy(sweep_deg, RADIUS)
    for w, bright in ((3,60), (2,140), (1,255)):
        draw.line([(CX, CY), (sx, sy)], fill=(0, bright, 0), width=w)

    # Draw devices
    with lock:
        for mac, info in detected_devices.items():
            angle = bssid_angle(mac)
            r_px = rssi_to_radius(info.get("rssi", -60))
            color = confidence_color(info["score"])
            # Brightness based on angular distance to sweep
            delta = (sweep_deg - angle) % 360
            if delta < 5:
                brightness = 1.0
            else:
                brightness = max(0.15, 1.0 - (delta / 360.0) * 1.1)
            r, g, b = color
            blip_col = (int(r * brightness), int(g * brightness), int(b * brightness))
            px, py = polar_to_xy(angle, r_px)
            px, py = int(px), int(py)
            draw.ellipse([(px-2, py-2), (px+2, py+2)], fill=blip_col)
            draw.ellipse([(px-1, py-1), (px+1, py+1)], fill=(min(255, int(r*brightness*1.4)),
                                                             min(255, int(g*brightness*1.4)),
                                                             min(255, int(b*brightness*1.4))))
            # Short label
            label = mac.replace(":", "")[-4:]
            draw.text((px+3, py-3), label, font=FONT_SM, fill=(200,200,200))

    # Header / footer
    draw_header(draw, True)
    with lock:
        dev_count = len(detected_devices)
    draw_footer(draw, f"Devices:{dev_count}  K2:List  LongK2:Export")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def main():
    global running, view_mode, detail_view, detail_flock
    global scroll_pos, selected_idx, detected_devices, sweep_deg

    # Catch SIGTERM/SIGINT so the finally block always runs
    def _stop(sig, frame):
        global running
        running = False
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # Find wireless interface
    iface = get_wlan()
    if not iface:
        show_message("No wireless card", "Check wlan0/wlan1")
        return

    # Enable monitor mode
    show_message(f"Enabling monitor mode on {iface}...")
    mon_iface = enable_monitor_mode(iface)
    if not mon_iface:
        show_message("Monitor mode failed", "Check airmon-ng")
        return
    show_message(f"Monitor: {mon_iface}", "Starting detection...")

    # Start detection threads
    threading.Thread(target=ble_scan_thread, daemon=True).start()
    threading.Thread(target=wifi_sniff_thread, args=(mon_iface,), daemon=True).start()

    last_flock_update = 0
    flock_list = []

    try:
        while running:
            btn = wait_btn(0.08)

            if btn == "KEY3":
                running = False
                if detected_devices:
                    export_loot()
                break

            # Detail view (list mode only)
            if detail_view:
                if btn is not None:
                    detail_view = False
                    time.sleep(0.2)
                else:
                    draw_flock_detail(detail_flock)
                continue

            # Handle view switching and export
            if btn == "KEY2":
                if is_long_press("KEY2", hold=2.0):
                    if detected_devices:
                        path = export_loot()
                        show_message("Exported!", path[-20:])
                    else:
                        show_message("No data yet")
                else:
                    view_mode = "radar" if view_mode == "list" else "list"
                    time.sleep(0.2)

            # Update flocks periodically
            now = time.time()
            if now - last_flock_update > 5.0:
                flock_list = compute_flocks()
                last_flock_update = now

            if view_mode == "list":
                # List view navigation
                if btn == "UP":
                    selected_idx = max(0, selected_idx-1)
                    if selected_idx < scroll_pos:
                        scroll_pos = selected_idx
                elif btn == "DOWN":
                    max_sel = max(0, len(flock_list)-1)
                    selected_idx = min(selected_idx+1, max_sel)
                    if selected_idx >= scroll_pos + 5:
                        scroll_pos = selected_idx - 4
                elif btn == "OK":
                    if selected_idx < len(flock_list):
                        detail_flock = flock_list[selected_idx]
                        detail_view = True
                elif btn == "KEY1":
                    with lock:
                        detected_devices = {}
                    show_message("Data reset")
                draw_list_view()
            else:
                # Radar view
                if btn == "KEY1":
                    with lock:
                        detected_devices = {}
                    show_message("Data reset")
                sweep_deg = (sweep_deg + sweep_speed) % 360
                draw_radar_frame()

            time.sleep(0.05)

    finally:
        running = False
        # Let scan threads see running=False and terminate their processes
        time.sleep(0.8)
        disable_monitor_mode(iface)
        LCD.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
