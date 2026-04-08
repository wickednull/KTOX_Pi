#!/usr/bin/env python3
"""
KTOX Tor Payload - Animated Status + One-Tap Toggle
===================================================
Dark red style | Auto-start | Shows real Tor IP
"""

import os
import time
import subprocess
import threading
import sys

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not detected")

# ── Globals ──────────────────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font_sm = None

RUNNING = True
tor_status = "Starting..."   # Will be updated live
tor_ip = "Checking..."

animation_frame = 0

def init_hw():
    global LCD, _image, _draw, _font_sm
    if not HAS_HW:
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        for pin in [6,19,5,26,13,21,20,16]:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        _image = Image.new("RGB", (128, 128), "black")
        _draw = ImageDraw.Draw(_image)
        try:
            _font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        except:
            _font_sm = ImageFont.load_default()
        return True
    except:
        return False

def push():
    if LCD and _image:
        LCD.LCD_ShowImage(_image, 0, 0)

# ── Dark Red UI with Animation ───────────────────────────────────────────────
def draw_tor_screen():
    global animation_frame
    _draw.rectangle((0,0,128,128), fill="#0A0000")
    _draw.rectangle((0,0,128,18), fill="#8B0000")
    _draw.text((5,3), "KTOX TOR", font=_font_sm, fill="#FF3333")

    # Status line
    status_color = "#00FF88" if "ON" in tor_status else "#FF6666"
    _draw.text((5,25), tor_status, font=_font_sm, fill=status_color)

    # Tor IP (if connected)
    if tor_ip and tor_ip != "Checking...":
        _draw.text((5,38), f"IP: {tor_ip}", font=_font_sm, fill="#FFBBBB")

    # Animated indicator
    dots = "." * ((animation_frame % 4) + 1)
    anim_text = "Tor" + dots if "Starting" in tor_status or "Connecting" in tor_status else ""
    _draw.text((5,52), anim_text, font=_font_sm, fill="#FFAA00")

    _draw.rectangle((0,117,128,128), fill="#220000")
    _draw.text((5,118), "K1=Toggle  K3=Exit", font=_font_sm, fill="#FF7777")
    push()
    animation_frame += 1

# ── Tor Control ──────────────────────────────────────────────────────────────
def is_tor_running():
    try:
        return subprocess.run(["pidof", "tor"], capture_output=True).returncode == 0
    except:
        return False

def get_tor_ip():
    try:
        # Use tor's built-in check or a simple curl through tor
        out = subprocess.getoutput("curl -s --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip")
        if "true" in out.lower():
            import json
            data = json.loads(out)
            return data.get("IP", "Unknown")
        return "Tor active"
    except:
        return "Checking..."

def start_tor():
    global tor_status, tor_ip
    draw_tor_screen()  # show starting animation
    try:
        subprocess.run(["sudo", "systemctl", "start", "tor"], capture_output=True)
        time.sleep(3)   # give Tor time to bootstrap
        tor_status = "Tor ON"
        tor_ip = get_tor_ip()
    except:
        tor_status = "Start failed"

def stop_tor():
    global tor_status, tor_ip
    draw_tor_screen()
    try:
        subprocess.run(["sudo", "systemctl", "stop", "tor"], capture_output=True)
        tor_status = "Tor OFF"
        tor_ip = ""
    except:
        tor_status = "Stop failed"

# ── Main Loop ────────────────────────────────────────────────────────────────
def main():
    global RUNNING, tor_status
    hw_ok = init_hw()

    # Auto-start Tor on launch
    if not is_tor_running():
        tor_status = "Starting Tor..."
        start_tor()
    else:
        tor_status = "Tor ON"
        tor_ip = get_tor_ip()

    draw_tor_screen()

    held = {}
    while RUNNING:
        pressed = {name: GPIO.input(pin) == 0 for name, pin in {"KEY1":21, "KEY3":16}.items()}
        now = time.time()
        for n, down in pressed.items():
            if down and n not in held:
                held[n] = now
            elif not down:
                held.pop(n, None)

        if pressed.get("KEY3") and (now - held.get("KEY3", 0)) < 0.3:
            break

        if pressed.get("KEY1") and (now - held.get("KEY1", 0)) < 0.3:
            if is_tor_running():
                stop_tor()
            else:
                start_tor()
            time.sleep(0.5)

        # Refresh screen every 0.6s for animation
        draw_tor_screen()
        time.sleep(0.6)

    RUNNING = False
    if HAS_HW:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    print("KTOX Tor payload closed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        if HAS_HW:
            try:
                GPIO.cleanup()
            except:
                pass