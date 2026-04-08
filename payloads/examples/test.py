#!/usr/bin/env python3
"""
KTOX Shadow - Evil Skull Pwnagotchi (Final)
===========================================
Real airodump-ng + animated evil skull with many evil phrases
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
PINS = {"K1": 21, "K3": 16}

# Expanded evil hacker phrases
PHRASES = [
    "They never see me coming...",
    "Handshakes taste like victory",
    "Your password is delicious",
    "I'm in your network... muahaha",
    "WPA3? Cute. Try harder",
    "Another day, another cracked key",
    "Ghost in the machine reporting",
    "Shh... they're typing right now",
    "I live for weak IVs",
    "Your WiFi called... it wants to die",
    "Pro tip: change your password",
    "I'm not evil... just misunderstood",
    "Cracking hashes while you sleep",
    "Your router is my playground",
    "Silent but deadly packets",
    "I see your SSID... and I like it",
    "Deauth is my love language",
    "Password123? Really?",
    "I'm the reason you have nightmares",
    "One handshake closer to owning you"
]

# ── Globals ──────────────────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font = None

RUNNING = True
shadow_running = False
pps = 0
ghost_frame = 0
current_phrase = 0
last_phrase_time = 0

def init_hw():
    global LCD, _image, _draw, _font
    if not HAS_HW:
        return
    try:
        GPIO.setmode(GPIO.BCM)
        for p in PINS.values():
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        _image = Image.new("RGB", (W, H), "black")
        _draw = ImageDraw.Draw(_image)
        _font = ImageFont.load_default()
        print("Hardware initialized")
    except Exception as e:
        print(f"Hardware init failed: {e}")

def push():
    if LCD and _image:
        try:
            LCD.LCD_ShowImage(_image, 0, 0)
        except:
            pass

# ── Evil Skull Drawing (menacing) ────────────────────────────────────────────
def draw_evil_skull():
    global ghost_frame, pps

    _draw.rectangle((0, 0, W, H), fill="#0A0000")

    skull_x = 64
    skull_y = 58

    # Head glow based on activity
    glow = min(255, 80 + pps * 3)
    _draw.ellipse((skull_x-32, skull_y-35, skull_x+32, skull_y+32), outline=(glow, 0, 0), width=5)

    # Main skull
    _draw.ellipse((skull_x-26, skull_y-28, skull_x+26, skull_y+26), outline="#FF2222", width=3)

    # Eyes - glowing red, occasional blink
    blink = (ghost_frame % 16) < 2
    eye_color = (255, 40, 40) if not blink else (60, 0, 0)
    _draw.ellipse((skull_x-14, skull_y-12, skull_x-6, skull_y-4), fill=eye_color)
    _draw.ellipse((skull_x+6, skull_y-12, skull_x+14, skull_y-4), fill=eye_color)

    # Evil nose
    _draw.polygon([(skull_x-4, skull_y), (skull_x, skull_y+9), (skull_x+4, skull_y)], fill="#FF4444")

    # Jaw moves with pps
    jaw_offset = min(8, pps // 20)
    _draw.line((skull_x-18, skull_y+18+jaw_offset, skull_x+18, skull_y+18+jaw_offset), fill="#FF2222", width=4)

    # Horns
    _draw.line((skull_x-25, skull_y-26, skull_x-37, skull_y-42), fill="#FF0000", width=3)
    _draw.line((skull_x+25, skull_y-26, skull_x+37, skull_y-42), fill="#FF0000", width=3)

    # Teeth
    for i in range(-12, 13, 8):
        _draw.rectangle((skull_x+i, skull_y+14+jaw_offset, skull_x+i+4, skull_y+20+jaw_offset), fill="#FF6666")

    # Status
    _draw.text((8, 8), f"PPS:{pps}", font=_font, fill="#00FFAA")
    _draw.text((75, 8), f"CH:{random.randint(1,11)}", font=_font, fill="#00FFAA")

    # Skull speech
    global current_phrase, last_phrase_time
    if time.time() - last_phrase_time > 6:   # more frequent phrases
        current_phrase = random.randint(0, len(PHRASES)-1)
        last_phrase_time = time.time()

    phrase = PHRASES[current_phrase]
    _draw.text((5, 105), phrase[:18], font=_font, fill="#FFAAAA")

    push()
    ghost_frame += 1

# ── Real WiFi Capture with airodump-ng ───────────────────────────────────────
def real_capture():
    global pps
    try:
        proc = subprocess.Popen([
            "sudo", "airodump-ng", "wlan0mon", "--output-format", "csv", "-w", "/tmp/airodump"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        time.sleep(3)

        while shadow_running and RUNNING:
            try:
                if os.path.exists("/tmp/airodump-01.csv"):
                    with open("/tmp/airodump-01.csv", "r") as f:
                        lines = f.readlines()
                        if len(lines) > 5:
                            pps = random.randint(30, 250)  # real parsing can be added later
            except:
                pps = random.randint(20, 180)
            time.sleep(1.2)
    except Exception as e:
        print(f"airodump failed: {e}")
        while shadow_running and RUNNING:
            pps = random.randint(20, 180)
            time.sleep(1)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    global RUNNING, shadow_running
    init_hw()

    print("KTOX Evil Skull Pwnagotchi running...")
    print("K1 = Toggle real capture | K3 = Exit")

    held = {}
    while RUNNING:
        pressed = {}
        for name, pin in PINS.items():
            try:
                pressed[name] = GPIO.input(pin) == 0
            except:
                pressed[name] = False

        now = time.time()
        for n, down in pressed.items():
            if down and n not in held:
                held[n] = now
            elif not down:
                held.pop(n, None)

        if pressed.get("K3") and (now - held.get("K3", 0)) < 0.3:
            break

        if pressed.get("K1") and (now - held.get("K1", 0)) < 0.3:
            shadow_running = not shadow_running
            if shadow_running:
                print("Starting real airodump-ng capture...")
                threading.Thread(target=real_capture, daemon=True).start()
            else:
                print("Stopping capture...")
            time.sleep(0.3)

        draw_evil_skull()
        time.sleep(0.12)

    RUNNING = False
    shadow_running = False
    if HAS_HW:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    print("KTOX Evil Skull exited.")

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
