#!/usr/bin/env python3
"""
KTOX SDR Ghost Waterfall - Integrated KTOx_Pi Payload
=====================================================
Real-time HackRF spectrum waterfall visualization and 
persistent loot management. Compatible with ktox_device.py.
"""

import os
import sys
import time
import subprocess
import random
import threading
import json
from datetime import datetime
from pathlib import Path
import collections

# ── KTOx Environment Setup ───────────────────────────────────────────────────
KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
LOOT_DIR = Path(os.environ.get("KTOX_LOOT_DIR", f"{KTOX_DIR}/loot/SDRGhost"))
LOOT_DB  = LOOT_DIR / "loot_gallery.json"

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    import LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# KTOx standard input helper
try:
    from _input_helper import get_button, flush_input
except ImportError:
    def get_button(pins, gpio): return None
    def flush_input(): pass

# ── Constants & Palette ──────────────────────────────────────────────────────
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
W, H = 128, 128

# KTOx Blood Red Palette
BG_COLOR = "#0A0000"
HEADER   = "#8B0000"
ACCENT   = "#FF3333"
TEXT     = "#FFBBBB"
GOOD     = "#00FF00"
WATER    = "#00FFAA"

LOOT_DIR.mkdir(parents=True, exist_ok=True)

# ── LCD & Drawing ────────────────────────────────────────────────────────────
lcd_hw = None
FONT_SM = None
FONT_MD = None
draw_lock = threading.Lock()

if HAS_HW:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for p in PINS.values():
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        lcd_hw = LCD_1in44.LCD()
        lcd_hw.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        
        try:
            FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
            FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
        except:
            FONT_SM = FONT_MD = ImageFont.load_default()
    except Exception as e:
        print(f"LCD init failed: {e}")

def _push(img, x=0, y=0):
    if lcd_hw:
        with draw_lock:
            try: lcd_hw.LCD_ShowImage(img, x, y)
            except: pass

def lcd_status(title, lines, tc=None, lc=None):
    tc = tc or HEADER
    lc = lc or TEXT
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, W, 14), fill=tc)
    draw.text((3, 2), title[:20], fill="#FFFFFF", font=FONT_MD)

    y = 18
    for ln in (lines or []):
        draw.text((3, y), str(ln)[:21], fill=lc, font=FONT_SM)
        y += 11
        if y > H - 14: break
    
    draw.rectangle((0, 116, W, 128), fill="#150000")
    draw.text((3, 118), "K1=Waterfall K2=Scan K3=Exit", fill=ACCENT, font=FONT_SM)
    _push(img)

# ── Global State ─────────────────────────────────────────────────────────────
hackrf_detected = False
spectrum_buffer = collections.deque(maxlen=W)
spectrum_lock = threading.Lock()
tower_log = []

# ── RF Engine ────────────────────────────────────────────────────────────────
def detect_hackrf():
    global hackrf_detected
    try:
        out = subprocess.check_output("hackrf_info", shell=True, stderr=subprocess.STDOUT, text=True)
        hackrf_detected = "HackRF" in out
    except:
        hackrf_detected = False
    return hackrf_detected

def continuous_sweep():
    """Background thread for real-time spectrum data."""
    if not hackrf_detected: return
    while True:
        try:
            proc = subprocess.Popen(
                ["hackrf_sweep", "-f", "400:6000", "-w", "1000000", "-l", "16", "-g", "20"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            for line in iter(proc.stdout.readline, ""):
                parts = line.strip().split()
                if len(parts) > 5:
                    try:
                        p = float(parts[5])
                        with spectrum_lock:
                            spectrum_buffer.append(p)
                    except: pass
            proc.terminate()
        except: pass
        time.sleep(0.2)

# ── Loot Management ──────────────────────────────────────────────────────────
def save_loot(loot_type, data):
    entry = {"ts": datetime.now().isoformat(), "type": loot_type, "data": data}
    all_loot = []
    if LOOT_DB.exists():
        try: all_loot = json.loads(LOOT_DB.read_text())
        except: pass
    all_loot.append(entry)
    LOOT_DB.write_text(json.dumps(all_loot, indent=2))

def scan_towers():
    lcd_status("HUNTING TOWERS", ["Polling ModemManager...", "Seeking cells..."])
    try:
        out = subprocess.check_output("mmcli -m any --signal-get", shell=True, text=True, timeout=5)
        lines = [l.strip() for l in out.splitlines() if any(k in l for k in ["MCC", "CID", "signal"])]
        if lines:
            save_loot("cell_tower", lines)
            tower_log.extend(lines)
            lcd_status("TOWERS FOUND", lines[:6])
        else:
            lcd_status("SCAN FAILED", ["No towers visible", "Check antenna"])
    except:
        lcd_status("MODEM ERROR", ["No modem detected", "or mmcli missing"])
    time.sleep(2)

def view_loot():
    if not LOOT_DB.exists():
        lcd_status("LOOT GALLERY", ["No loot captured yet."])
        time.sleep(1.5)
        return

    try:
        all_loot = json.loads(LOOT_DB.read_text())
        if not all_loot:
            lcd_status("LOOT GALLERY", ["No loot captured yet."])
            time.sleep(1.5)
            return
        
        summary = []
        for entry in all_loot[-5:]:
            ts = entry["ts"].split("T")[1][:8]
            summary.append(f"{ts} | {entry['type']}")
        lcd_status("RECENT LOOT", summary)
        time.sleep(3)
    except:
        lcd_status("ERROR", ["Failed to read loot DB"])
        time.sleep(1.5)

# ── Visualizer ───────────────────────────────────────────────────────────────
def draw_waterfall():
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, W, 14), fill=HEADER)
    draw.text((3, 2), "SDR WATERFALL", fill="#FFFFFF", font=FONT_MD)

    with spectrum_lock:
        if spectrum_buffer:
            data = list(spectrum_buffer)
            min_p, max_p = min(data), max(data)
            range_p = max(1, max_p - min_p)

            for x, p in enumerate(data):
                norm = max(0, min(1, (p - min_p) / range_p))
                h_bar = int(norm * (H - 30))
                c_val = int(norm * 255)
                # SDR Ghost style orange-red gradient
                color = (c_val, int(c_val * 0.5), 0)
                draw.line((x, H - 14 - h_bar, x, H - 14), fill=color)

    draw.rectangle((0, 116, W, 128), fill="#150000")
    draw.text((3, 118), "K1=Pause K2=Scan K3=Exit", fill=ACCENT, font=FONT_SM)
    _push(img)

# ── Main Loop ────────────────────────────────────────────────────────────────
def main():
    flush_input()
    
    detect_hackrf()
    h_msg = "HackRF: OK" if hackrf_detected else "HackRF: MISSING"
    lcd_status("SDR GHOST", ["KTOx Spectrum Viewer", h_msg, "", "K2 to start scan"])
    time.sleep(1.5)

    if hackrf_detected:
        threading.Thread(target=continuous_sweep, daemon=True).start()

    active = True
    
    while True:
        btn = get_button(PINS, GPIO) if HAS_HW else None
        
        if btn == "KEY3": break
        
        elif btn == "KEY2":
            scan_towers()
            active = True
            
        elif btn == "KEY1":
            active = not active
            if not active:
                lcd_status("PAUSED", ["Waterfall frozen", "K1 to resume"])
                time.sleep(1)
        
        elif btn == "UP":
            view_loot()

        if active:
            draw_waterfall()
            time.sleep(0.1)
        else:
            time.sleep(0.2)

    lcd_status("SDR GHOST", ["Shutting down...", "Goodbye"])
    time.sleep(1.5)
    if HAS_HW: GPIO.cleanup()

if __name__ == "__main__":
    main()
