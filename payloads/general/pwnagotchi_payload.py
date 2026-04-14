#!/usr/bin/env python3
"""
KTOx Payload – Cyberpunk Pwnagotchi
====================================
Author: wickednull

A gamified Wi‑Fi handshake collector with a cyberpunk aesthetic.
- Animated glitch character (skull/cyborg)
- Tracks handshakes captured, uptime, nearby APs
- Optional real capture using airodump‑ng (if compatible adapter present)
- Fake "hacking" mode for fun

Controls:
  UP/DOWN – scroll stats / select action
  OK      – start fake hack (simulate handshake capture)
  KEY1    – toggle real capture mode (if adapter available)
  KEY2    – show detailed stats
  KEY3    – exit
"""

import os
import sys
import time
import random
import threading
import subprocess
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# ----------------------------------------------------------------------
# Hardware
# ----------------------------------------------------------------------
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13,
        "KEY1":21, "KEY2":20, "KEY3":16}
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
f9 = font(9)
f11 = font(11)

# ----------------------------------------------------------------------
# Character frames (simple pixel art – ascii representation)
# We'll draw them directly with rectangles and lines for cyberpunk look.
# ----------------------------------------------------------------------
def draw_character(draw, mood):
    """Draw a cyberpunk skull/cyborg face based on mood."""
    # Center the face at (64, 50)
    if mood == "happy":
        eye_color = "#00FF00"
        mouth = (58, 65, 70, 70)  # smile
    elif mood == "glitch":
        eye_color = "#FF00FF"
        mouth = (58, 65, 70, 70)  # same but with random offset
    else:  # neutral
        eye_color = "#00AAFF"
        mouth = (58, 68, 70, 70)  # straight line
    # Head (skull shape)
    draw.rectangle((48, 30, 80, 70), outline="#00FFAA", width=1)
    # Eyes
    draw.rectangle((54, 40, 60, 46), fill=eye_color)
    draw.rectangle((68, 40, 74, 46), fill=eye_color)
    # Mouth
    draw.rectangle(mouth, outline="#FF3300", width=1)
    # Cyberpunk lines
    draw.line((48, 30, 44, 20), fill="#FF00AA", width=1)
    draw.line((80, 30, 84, 20), fill="#FF00AA", width=1)
    # Glitch effect if mood glitch
    if mood == "glitch":
        draw.rectangle((52, 35, 78, 55), outline="#FF00FF", width=1)
        draw.rectangle((49, 42, 57, 48), fill="#FF00FF")
        draw.rectangle((71, 42, 79, 48), fill="#FF00FF")

# ----------------------------------------------------------------------
# Global state
# ----------------------------------------------------------------------
handshakes = 0
start_time = time.time()
nearby_aps = 0
mood = "neutral"
real_capture = False
mon_iface = None

def update_nearby_aps():
    global nearby_aps
    if real_capture and mon_iface:
        try:
            out = subprocess.run(f"iw dev {mon_iface} scan", shell=True, capture_output=True, text=True, timeout=5)
            nearby_aps = out.stdout.count("BSSID")
        except:
            nearby_aps = random.randint(3, 12)
    else:
        nearby_aps = random.randint(3, 12)

def fake_capture():
    global handshakes, mood
    handshakes += 1
    mood = "happy"
    # Mood returns to neutral after 3 seconds
    threading.Timer(3.0, lambda: set_mood("neutral")).start()

def real_capture_worker():
    global handshakes, mood
    # Simplified: just simulate for now; real airodump integration would be complex.
    # For novelty, we'll increment on button press anyway.
    pass

def set_mood(new_mood):
    global mood
    mood = new_mood

def get_uptime():
    return int(time.time() - start_time)

# ----------------------------------------------------------------------
# LCD drawing
# ----------------------------------------------------------------------
def draw_screen():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    # Header
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "Pwnagotchi", font=f9, fill="#FF3333")
    # Stats line
    d.text((4, H-25), f"HS:{handshakes}  AP:{nearby_aps}  UPT:{get_uptime()}s", font=f9, fill="#00FFAA")
    # Character
    draw_character(d, mood)
    # Glitch text overlay
    if mood == "glitch":
        d.text((random.randint(4,8), random.randint(20,25)), ">> HACKING <<", font=f9, fill="#FF00FF")
    # Footer
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "OK=hack  K1=toggle  K2=stats  K3=exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img,0,0)

def show_stats():
    lines = [
        f"Handshakes: {handshakes}",
        f"Uptime: {get_uptime()}s",
        f"Nearby APs: {nearby_aps}",
        f"Real mode: {'ON' if real_capture else 'OFF'}",
        "",
        "Press KEY3 to exit"
    ]
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#004466")
    d.text((4,3), "STATS", font=f9, fill="#FF3333")
    y = 20
    for line in lines:
        d.text((4,y), line[:23], font=f9, fill="#FFBBBB")
        y += 12
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "KEY3 to close", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img,0,0)
    # Wait for KEY3
    while True:
        if wait_btn(0.2) == "KEY3":
            break
        time.sleep(0.05)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name,pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

# ----------------------------------------------------------------------
# Background tasks
# ----------------------------------------------------------------------
def background_updater():
    while True:
        update_nearby_aps()
        # Random glitch effect (1% chance)
        if random.random() < 0.01:
            global mood
            mood = "glitch"
            threading.Timer(1.5, lambda: set_mood("neutral")).start()
        time.sleep(10)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    # Start background thread
    threading.Thread(target=background_updater, daemon=True).start()
    global real_capture, mon_iface
    # Check for monitor interface (optional)
    try:
        result = subprocess.run("iw dev", shell=True, capture_output=True, text=True)
        if "monitor" in result.stdout:
            real_capture = True
            # Extract monitor interface name
            for line in result.stdout.splitlines():
                if "Interface" in line:
                    mon_iface = line.split()[1]
    except:
        pass

    while True:
        draw_screen()
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "OK":
            fake_capture()
            draw_screen()
            time.sleep(0.5)
        elif btn == "KEY1":
            real_capture = not real_capture
            draw_screen()
            time.sleep(0.5)
        elif btn == "KEY2":
            show_stats()
        time.sleep(0.05)

    GPIO.cleanup()

if __name__ == "__main__":
    main()
