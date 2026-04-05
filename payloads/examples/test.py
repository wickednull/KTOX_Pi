#!/usr/bin/env python3
"""
KTOX Shadow - Live Credential Harvester
=======================================
Stealth keylogger + network credential mirror
Dark red ghost style with live scrolling captures
"""

import os
import time
import subprocess
import random
import threading

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not detected")

# ── Constants ────────────────────────────────────────────────────────────────
W, H = 128, 128
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

# ── Globals ──────────────────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font_sm = None

RUNNING = True
shadow_running = False
captured_creds = []   # list of "user:pass" or "domain login"

def init_hw():
    global LCD, _image, _draw, _font_sm
    if not HAS_HW:
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        for p in PINS.values():
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        _image = Image.new("RGB", (W, H), "black")
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

# ── Dark Red Ghost UI ────────────────────────────────────────────────────────
def draw_shadow_screen():
    _draw.rectangle((0,0,W,H), fill="#0A0000")
    _draw.rectangle((0,0,W,18), fill="#8B0000")
    _draw.text((4,3), "KTOX SHADOW", font=_font_sm, fill="#FF3333")

    status = "CAPTURING" if shadow_running else "IDLE"
    color = "#00FF88" if shadow_running else "#FF6666"
    _draw.text((5,22), status, font=_font_sm, fill=color)

    # Live captured credentials (scroll up like a real logger)
    y = 36
    for cred in captured_creds[-5:]:   # show last 5
        _draw.text((5, y), cred[:20], font=_font_sm, fill="#FF5555")
        y += 11

    if shadow_running:
        ghost = "👻" * ((int(time.time()) % 3) + 1)
        _draw.text((5, 100), ghost, font=_font_sm, fill="#FFAA00")

    _draw.rectangle((0,117,W,128), fill="#220000")
    _draw.text((4,118), "K1=Toggle  K3=Exit", font=_font_sm, fill="#FF7777")
    push()

# ── Background Capture Simulation ────────────────────────────────────────────
def capture_thread():
    global captured_creds
    fake_creds = [
        "admin:password123",
        "user@gmail.com:letmein",
        "banklogin:Secret2026",
        "root:toor",
        "victim:123456"
    ]
    while shadow_running and RUNNING:
        if random.random() < 0.4:   # simulate capture
            cred = random.choice(fake_creds)
            if cred not in captured_creds:
                captured_creds.append(cred)
                if len(captured_creds) > 15:
                    captured_creds.pop(0)
        time.sleep(1.5)

# ── Control Functions ────────────────────────────────────────────────────────
def start_shadow():
    global shadow_running
    draw_shadow_screen()
    shadow_running = True
    threading.Thread(target=capture_thread, daemon=True).start()
    draw_shadow_screen()

def stop_shadow():
    global shadow_running
    shadow_running = False
    draw_shadow_screen(["Shadow stopped"], "KTOX SHADOW")

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    global RUNNING
    hw_ok = init_hw()
    draw_shadow_screen(["Press K1 to activate Shadow"])

    held = {}
    while RUNNING:
        pressed = {name: GPIO.input(pin) == 0 for name, pin in PINS.items()}
        now = time.time()
        for n, down in pressed.items():
            if down and n not in held:
                held[n] = now
            elif not down:
                held.pop(n, None)

        def just_pressed(n):
            return pressed.get(n) and (now - held.get(n, 0)) < 0.2

        if just_pressed("KEY3"):
            break

        if just_pressed("KEY1"):
            if shadow_running:
                stop_shadow()
            else:
                start_shadow()
            time.sleep(0.4)

        if shadow_running:
            draw_shadow_screen()
        time.sleep(0.6)

    RUNNING = False
    stop_shadow()
    if HAS_HW:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    print("KTOX Shadow payload exited.")

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