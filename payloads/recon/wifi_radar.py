#!/usr/bin/env python3
"""
KTOx *payload* – **WiFi Radar**
=================================
Real-time animated radar display showing nearby WiFi access points as
sonar-style blips on a rotating sweep.  Each AP is plotted at a position
derived from its signal strength (distance from centre) and BSSID (angle),
so the same network always appears in the same direction.  Blips light up
as the sweep line passes over them and fade between rotations — exactly
like a real radar scope.

Colour legend
  Red    – Open (no encryption)
  Yellow – WPA / WPA-Personal
  Green  – WPA2
  Cyan   – WPA3
  Grey   – Unknown

Controls:
  OK     : Start / Pause scanning
  UP     : Increase sweep speed
  DOWN   : Decrease sweep speed
  KEY1   : Cycle info overlay (AP count → top-signal SSID → channel map)
  KEY3   : Exit
"""

import sys
import os
import time
import math
import hashlib
import signal
import threading
import subprocess
import re

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from _input_helper import get_button

# ── Hardware ──────────────────────────────────────────────────────────────────
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
WIDTH, HEIGHT = 128, 128

GPIO.setmode(GPIO.BCM)
for _p in PINS.values():
    GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

try:
    FONT_SM = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
    FONT_MD = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 9)
except Exception:
    FONT_SM = ImageFont.load_default()
    FONT_MD = FONT_SM

# ── Radar geometry ────────────────────────────────────────────────────────────
CX, CY   = 64, 60        # radar centre (slightly above mid to leave room for text)
RADIUS   = 52             # outer ring radius in pixels
N_RINGS  = 3              # concentric rings
TRAIL_STEPS = 24          # ghost lines behind sweep (degrees each)
TRAIL_DEG   = 70          # total arc of the trailing glow

# ── Colour palette ────────────────────────────────────────────────────────────
COL_BG        = (0,   0,   0)
COL_RING      = (0,  40,   0)
COL_SWEEP     = (0, 255,   0)
COL_XHAIR     = (0,  30,   0)
COL_OPEN      = (255,  60,  60)    # red   – open
COL_WPA       = (255, 200,   0)    # amber – WPA
COL_WPA2      = ( 80, 255,  80)    # green – WPA2
COL_WPA3      = (  0, 220, 255)    # cyan  – WPA3
COL_UNKNOWN   = (160, 160, 160)    # grey
COL_TXT_DIM   = ( 80,  80,  80)
COL_TXT_HI    = (200, 200, 200)

# ── State ─────────────────────────────────────────────────────────────────────
ap_lock   = threading.Lock()
detected  = {}           # bssid → {ssid, dbm, security, angle_deg, r_px, last_seen, sweep_hit_age}
scanning  = True
sweep_deg = 0.0          # current sweep angle (0 = up / north, clockwise)
sweep_speed = 2.5        # degrees per frame increment
running   = True
overlay_mode = 0         # 0=count+strongest, 1=channel histogram
scan_iface   = 'wlan0'

# ── Interface selection ───────────────────────────────────────────────────────
def _pick_iface() -> str:
    for iface in ['wlan1', 'wlan0']:
        if os.path.exists(f'/sys/class/net/{iface}'):
            return iface
    return 'wlan0'

scan_iface = _pick_iface()

# ── AP geometry helpers ───────────────────────────────────────────────────────
def _bssid_angle(bssid: str) -> float:
    """Deterministic angle 0–360 from BSSID so same AP is always same direction."""
    digest = int(hashlib.sha1(bssid.encode()).hexdigest()[:8], 16)
    return digest % 360

def _dbm_to_radius(dbm: int) -> int:
    """Map signal strength to pixel distance from centre.
    Stronger (-30 dBm) → near centre; weaker (-90 dBm) → near edge."""
    dbm = max(-95, min(-20, dbm))
    t = (dbm - (-20)) / (-95.0 - (-20))   # 0.0 at -20, 1.0 at -95
    inner = 8
    outer = RADIUS - 6
    return int(inner + t * (outer - inner))

def _sec_color(security: str) -> tuple:
    s = security.upper()
    if 'WPA3' in s:
        return COL_WPA3
    if 'WPA2' in s:
        return COL_WPA2
    if 'WPA' in s:
        return COL_WPA
    if 'OPEN' in s or s == '':
        return COL_OPEN
    return COL_UNKNOWN

def _polar_to_xy(angle_deg: float, r: float):
    """Convert radar polar (0°=up, clockwise) to pixel (x, y)."""
    rad = math.radians(angle_deg - 90)
    return (CX + r * math.cos(rad), CY + r * math.sin(rad))

# ── WiFi scanner thread ───────────────────────────────────────────────────────
_CELL_RE   = re.compile(r'Cell \d+ - Address:\s*([\dA-Fa-f:]{17})')
_SSID_RE   = re.compile(r'ESSID:"([^"]*)"')
_SIGNAL_RE = re.compile(r'Signal level=(-?\d+)\s*dBm')
_QUALITY_RE = re.compile(r'Quality=(\d+)/(\d+)')
_CHAN_RE    = re.compile(r'Channel[:\s]+(\d+)')
_ENC_RE    = re.compile(r'Encryption key:(on|off)')
_WPA_RE    = re.compile(r'IE:.*?(WPA2|WPA3|WPA)', re.IGNORECASE)

def _parse_iwlist(output: str):
    """Parse iwlist scan output, return list of AP dicts."""
    aps = []
    current: dict | None = None
    for line in output.splitlines():
        line = line.strip()
        m = _CELL_RE.search(line)
        if m:
            if current:
                aps.append(current)
            current = {'bssid': m.group(1).upper(), 'ssid': '',
                       'dbm': -90, 'security': 'UNKNOWN', 'channel': 0}
            continue
        if current is None:
            continue
        m = _SSID_RE.search(line)
        if m:
            current['ssid'] = m.group(1)
            continue
        m = _SIGNAL_RE.search(line)
        if m:
            current['dbm'] = int(m.group(1))
            continue
        m = _QUALITY_RE.search(line)
        if m and current['dbm'] == -90:
            q = int(m.group(1)) / int(m.group(2))
            current['dbm'] = int(-100 + q * 70)
            continue
        m = _CHAN_RE.search(line)
        if m:
            current['channel'] = int(m.group(1))
            continue
        m = _ENC_RE.search(line)
        if m:
            if m.group(1) == 'off':
                current['security'] = 'OPEN'
            continue
        m = _WPA_RE.search(line)
        if m:
            t = m.group(1).upper()
            if 'WPA3' in t:
                current['security'] = 'WPA3'
            elif 'WPA2' in t and current['security'] not in ('WPA3',):
                current['security'] = 'WPA2'
            elif 'WPA' in t and current['security'] not in ('WPA3', 'WPA2'):
                current['security'] = 'WPA'
            continue
    if current:
        aps.append(current)
    return aps


def _scan_loop():
    global scanning
    while running:
        if not scanning:
            time.sleep(0.5)
            continue
        try:
            result = subprocess.run(
                ['iwlist', scan_iface, 'scan'],
                capture_output=True, text=True, timeout=10
            )
            aps = _parse_iwlist(result.stdout)
            now = time.time()
            with ap_lock:
                seen_bssids = set()
                for ap in aps:
                    b = ap['bssid']
                    seen_bssids.add(b)
                    if b not in detected:
                        detected[b] = {
                            'ssid':     ap['ssid'],
                            'dbm':      ap['dbm'],
                            'security': ap['security'],
                            'channel':  ap['channel'],
                            'angle_deg': _bssid_angle(b),
                            'r_px':     _dbm_to_radius(ap['dbm']),
                            'last_seen': now,
                            'sweep_hit_age': 999.0,
                        }
                    else:
                        entry = detected[b]
                        entry['ssid']     = ap['ssid']
                        entry['dbm']      = ap['dbm']
                        entry['security'] = ap['security']
                        entry['channel']  = ap['channel']
                        entry['r_px']     = _dbm_to_radius(ap['dbm'])
                        entry['last_seen'] = now
                # Expire APs not seen for >30 s
                stale = [b for b, e in detected.items()
                         if now - e['last_seen'] > 30]
                for b in stale:
                    del detected[b]
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        time.sleep(3)


# ── Render ────────────────────────────────────────────────────────────────────
def _draw_frame():
    img = Image.new("RGB", (WIDTH, HEIGHT), COL_BG)
    d   = ImageDraw.Draw(img)

    # ── Concentric rings ──────────────────────────────────────────────────────
    for i in range(1, N_RINGS + 1):
        r = RADIUS * i // N_RINGS
        d.ellipse([(CX - r, CY - r), (CX + r, CY + r)],
                  outline=COL_RING, width=1)

    # ── Crosshairs ────────────────────────────────────────────────────────────
    d.line([(CX, CY - RADIUS), (CX, CY + RADIUS)], fill=COL_XHAIR, width=1)
    d.line([(CX - RADIUS, CY), (CX + RADIUS, CY)], fill=COL_XHAIR, width=1)

    # ── Sweep trail (fading arcs of green) ───────────────────────────────────
    for step in range(TRAIL_STEPS, 0, -1):
        trail_angle = sweep_deg - (step * TRAIL_DEG / TRAIL_STEPS)
        alpha = int(60 * (1.0 - step / TRAIL_STEPS))
        col = (0, alpha, 0)
        x2, y2 = _polar_to_xy(trail_angle, RADIUS)
        d.line([(CX, CY), (x2, y2)], fill=col, width=1)

    # ── Sweep line ────────────────────────────────────────────────────────────
    sx, sy = _polar_to_xy(sweep_deg, RADIUS)
    # Glowing sweep: draw 3 lines, widths 3→1, brightness 60→255
    for w, bright in ((3, 60), (2, 140), (1, 255)):
        d.line([(CX, CY), (sx, sy)], fill=(0, bright, 0), width=w)

    # ── AP blips ──────────────────────────────────────────────────────────────
    with ap_lock:
        ap_snapshot = list(detected.items())

    for bssid, entry in ap_snapshot:
        ap_angle = entry['angle_deg']
        r_px     = entry['r_px']
        color    = _sec_color(entry['security'])

        # Angular distance from sweep line (mod 360, behind = 0..360)
        delta = (sweep_deg - ap_angle) % 360
        # Blip is brightest just after sweep passes (delta ≈ 0..5)
        # and fades over the next 355 degrees back to dim
        if delta < 5:
            brightness = 1.0
        else:
            brightness = max(0.15, 1.0 - (delta / 360.0) * 1.1)

        r, g, b = color
        blip_col = (int(r * brightness), int(g * brightness), int(b * brightness))

        px, py = _polar_to_xy(ap_angle, r_px)
        px, py = int(px), int(py)
        # Draw blip: 3px dot with bright 1px centre
        d.ellipse([(px-2, py-2), (px+2, py+2)], fill=blip_col)
        d.ellipse([(px-1, py-1), (px+1, py+1)],
                  fill=(min(255, int(r * brightness * 1.4)),
                        min(255, int(g * brightness * 1.4)),
                        min(255, int(b * brightness * 1.4))))

    # ── Text overlay ─────────────────────────────────────────────────────────
    with ap_lock:
        count = len(detected)
        sorted_aps = sorted(detected.values(), key=lambda e: e['dbm'], reverse=True)

    # Bottom bar
    bar_y = HEIGHT - 18
    d.rectangle([(0, bar_y), (WIDTH, HEIGHT)], fill=(0, 0, 15))

    if overlay_mode == 0:
        # AP count + strongest SSID
        count_str = f"{count} AP{'s' if count != 1 else ''}"
        d.text((3, bar_y + 1), count_str, font=FONT_SM, fill=COL_SWEEP)
        if sorted_aps:
            best = sorted_aps[0]
            ssid = (best['ssid'] or best.get('bssid', '??')[:11])[:12]
            dbm  = best['dbm']
            d.text((3, bar_y + 9), f"{ssid} {dbm}dBm", font=FONT_SM,
                   fill=COL_TXT_HI)
        else:
            state = "Scanning..." if scanning else "Paused (OK)"
            d.text((3, bar_y + 9), state, font=FONT_SM, fill=COL_TXT_DIM)

    else:
        # Channel histogram (2.4 GHz channels 1–13)
        ch_counts = {}
        with ap_lock:
            for e in detected.values():
                ch = e.get('channel', 0)
                if 1 <= ch <= 13:
                    ch_counts[ch] = ch_counts.get(ch, 0) + 1
        if ch_counts:
            max_ch = max(ch_counts.values())
            bar_h  = 12
            x      = 2
            for ch in range(1, 14):
                cnt = ch_counts.get(ch, 0)
                h   = int(bar_h * cnt / max_ch) if max_ch else 0
                col = (255, 80, 0) if cnt else (30, 30, 30)
                d.rectangle(
                    [(x, bar_y + bar_h - h + 1), (x + 7, bar_y + bar_h)],
                    fill=col
                )
                x += 9
        else:
            d.text((3, bar_y + 4), "No ch data yet", font=FONT_SM,
                   fill=COL_TXT_DIM)

    # Scanning indicator dot (top-right)
    if scanning:
        dot_col = COL_SWEEP if int(time.time() * 2) % 2 == 0 else (0, 100, 0)
        d.ellipse([(119, 2), (125, 8)], fill=dot_col)

    LCD.LCD_ShowImage(img, 0, 0)


# ── Signal handlers ───────────────────────────────────────────────────────────
def _cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, _cleanup)
signal.signal(signal.SIGTERM, _cleanup)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global running, scanning, sweep_deg, sweep_speed, overlay_mode

    scan_thread = threading.Thread(target=_scan_loop, daemon=True)
    scan_thread.start()

    frame_interval = 0.05   # ~20 fps

    while running:
        t0 = time.time()

        btn = get_button(PINS, GPIO)
        if btn == "KEY3":
            break
        elif btn == "OK":
            scanning = not scanning
        elif btn == "UP":
            sweep_speed = min(8.0, sweep_speed + 0.5)
        elif btn == "DOWN":
            sweep_speed = max(0.5, sweep_speed - 0.5)
        elif btn == "KEY1":
            overlay_mode = (overlay_mode + 1) % 2

        # Advance sweep
        sweep_deg = (sweep_deg + sweep_speed) % 360

        _draw_frame()

        elapsed = time.time() - t0
        if elapsed < frame_interval:
            time.sleep(frame_interval - elapsed)

    LCD.LCD_Clear()
    GPIO.cleanup()


if __name__ == "__main__":
    main()
