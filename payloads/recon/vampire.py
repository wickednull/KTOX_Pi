#!/usr/bin/env python3
"""
KTOX SDR Waterfall
=================================================
Real-time waterfall on the small LCD. Dark red KTOx style.
"""

import os
import sys
import time
import subprocess
import random
from datetime import datetime
from pathlib import Path

# Auto-install dependencies for Kali
def install_dependencies():
    required = ["hackrf", "modemmanager"]
    to_install = []
    for pkg in required:
        if subprocess.run(["dpkg", "-l", pkg], capture_output=True, text=True).returncode != 0:
            to_install.append(pkg)

    if to_install:
        print(f"Installing: {to_install}")
        try:
            subprocess.run(["apt-get", "update", "-qq"], check=True, capture_output=True)
            subprocess.run(["apt-get", "install", "-y", "-qq"] + to_install, check=True, capture_output=True)
            print("Dependencies installed.")
        except Exception as e:
            print(f"Auto-install failed: {e}. Run manually: sudo apt install hackrf modemmanager")

install_dependencies()

# KTOx paths
KTOX_ROOT = "/root/KTOx"
sys.path.append(KTOX_ROOT)
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware libraries not found")

from _input_helper import get_button, flush_input

# ── Constants ────────────────────────────────────────────────────────────────
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
W, H = 128, 128

LOOT_DIR = Path("/root/KTOx/loot/SDRWaterfall")
LOOT_DIR.mkdir(parents=True, exist_ok=True)

# Dark Red KTOx Palette
BG_COLOR = "#0A0000"
HEADER   = "#8B0000"
ACCENT   = "#FF3333"
TEXT     = "#FFBBBB"
WATER    = "#00FFAA"   # waterfall highlight
WEAK     = "#FF5555"

# ── LCD Setup ────────────────────────────────────────────────────────────────
lcd_hw = None
FONT_SM = None
FONT_MD = None

if HAS_HW:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for p in PINS.values():
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        lcd_hw = LCD_1in44.LCD()
        lcd_hw.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        lcd_hw.LCD_Clear()

        try:
            FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
            FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 9)
        except:
            FONT_SM = FONT_MD = ImageFont.load_default()
    except Exception as e:
        print(f"LCD init failed: {e}")

def _push(img):
    if lcd_hw:
        try:
            lcd_hw.LCD_ShowImage(img, 0, 0)
        except:
            pass

def lcd_status(title, lines):
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, W, 16), fill=HEADER)
    draw.text((4, 2), title[:20], fill=(242, 243, 244), font=FONT_MD)

    y = 20
    for line in lines[:8]:
        draw.text((4, y), str(line)[:22], fill=TEXT, font=FONT_SM)
        y += 11

    draw.rectangle((0, 116, W, 128), fill="#220000")
    draw.text((4, 118), "K2=Scan  K1=Waterfall  K3=Exit", fill=ACCENT, font=FONT_SM)

    _push(img)

    if not HAS_HW:
        print(f"[{title}]", *lines)

# ── Global State ─────────────────────────────────────────────────────────────
hackrf_detected = False
spectrum_buffer = []   # list of power values for waterfall

# ── Helpers ──────────────────────────────────────────────────────────────────
def _run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except:
        return ""

def detect_hackrf():
    global hackrf_detected
    out = _run("hackrf_info 2>/dev/null")
    hackrf_detected = "HackRF" in out
    return hackrf_detected

def hackrf_waterfall():
    global spectrum_buffer
    if not hackrf_detected:
        lcd_status("NO HACKRF", ["Plug in HackRF One", "then press K1"])
        time.sleep(3)
        return

    lcd_status("SDR WATERFALL", ["Starting HackRF sweep...", "Live spectrum..."])

    spectrum_buffer = []
    try:
        proc = subprocess.Popen(
            ["hackrf_sweep", "-f", "400:6000", "-w", "1000000", "-N", "1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        start = time.time()
        while time.time() - start < 3.0:   # short safe sweep
            line = proc.stdout.readline()
            if not line:
                break
            parts = line.strip().split()
            if len(parts) > 5:
                try:
                    power = float(parts[5])
                    spectrum_buffer.append(power)
                    if len(spectrum_buffer) > W:
                        spectrum_buffer.pop(0)
                except:
                    pass
        proc.terminate()
    except Exception as e:
        print(f"HackRF error: {e}")

    lcd_status("WATERFALL ACTIVE", ["K1 = toggle live mode", "Peaks captured"])

def draw_waterfall():
    if not HAS_HW or not lcd_hw:
        return

    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, W, 16), fill=HEADER)
    draw.text((4, 2), "SDR WATERFALL", fill=(242, 243, 244), font=FONT_MD)

    # Draw waterfall bars
    if spectrum_buffer:
        min_p = min(spectrum_buffer) if spectrum_buffer else -100
        max_p = max(spectrum_buffer) if spectrum_buffer else -30
        range_p = max_p - min_p if max_p > min_p else 1

        for x in range(min(W, len(spectrum_buffer))):
            power = spectrum_buffer[x]
            normalized = max(0, min(1, (power - min_p) / range_p))
            height = int(normalized * (H - 30))
            color_val = int(normalized * 255)
            color = (color_val, int(color_val * 0.6), 0)   # red-orange waterfall
            draw.line((x, H - 14 - height, x, H - 14), fill=color)

    # Status footer
    draw.rectangle((0, 116, W, 128), fill="#220000")
    draw.text((4, 118), "K1=Toggle  K2=Scan  K3=Exit", fill=ACCENT, font=FONT_SM)

    _push(img)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    global hackrf_detected
    flush_input()

    detect_hackrf()
    hackrf_msg = "HackRF detected" if hackrf_detected else "HackRF not found"

    lcd_status("SDR WATERFALL", ["KTOx Spectrum Viewer", hackrf_msg, "K2 = Scan   K1 = Waterfall"])
    time.sleep(2)

    waterfall_active = False

    while True:
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                break

        if btn == "KEY3":
            break

        elif btn == "KEY2":
            hackrf_waterfall()

        elif btn == "KEY1":
            waterfall_active = not waterfall_active
            if waterfall_active:
                lcd_status("WATERFALL LIVE", ["Real-time spectrum...", "Press K1 to stop"])
            else:
                lcd_status("WATERFALL PAUSED", ["Press K1 to resume"])

        # Update display
        if waterfall_active and spectrum_buffer:
            draw_waterfall()
        else:
            # Idle screen with status
            lcd_status("SDR WATERFALL", ["Ready", hackrf_msg, "K2=Scan  K1=Live"])

        time.sleep(0.15)   # responsive loop

    lcd_status("SDR WATERFALL", ["Shutting down...", "Goodbye"])
    time.sleep(2)

    if HAS_HW:
        try:
            GPIO.cleanup()
        except:
            pass
    print("KTOX SDR Waterfall exited.")

if __name__ == "__main__":
    main()
