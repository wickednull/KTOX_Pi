#!/usr/bin/env python3
"""
KTOx *payload* – **Jam_Fi Wi-Fi Exploitation Toolkit**
=======================================================
Integrates the Jam_Fi toolkit (github.com/ekomsSavior/Jam_Fi)
for comprehensive wireless network attacks and exploitation.

Features:
- Deauthentication attacks & handshake capture
- WPA handshake cracking
- Probe request & junk frame flooding
- Evil twin access points with credential logging
- Karma responder beacon spoofing
- MITM injection with keylogger & payload delivery
- Custom captive portals
- CVE vulnerability scanner & exploit launcher
- Auto-Pwn automated exploitation chain
- Router exploitation (OTA & IP-based)
- Ngrok support for remote payload delivery

Controls:
- UP/DOWN: Navigate menu
- OK: Execute attack
- KEY3: Exit payload
"""

import sys
import os
import time
import signal
import subprocess
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_LCD = True
except (ImportError, RuntimeError):
    HAS_LCD = False

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
LCD, FONT, FONT_TITLE = None, None, None
WIDTH, HEIGHT = 128, 128

if HAS_LCD:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    FONT = ImageFont.load_default()
    try:
        FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except:
        FONT_TITLE = FONT

JAM_FI_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'vendor', 'jam-fi'))
MENU = [
    "Scan APs & Clients",
    "Deauth Attack",
    "Handshake Capture",
    "Probe Spam",
    "Evil AP",
    "MITM Injection",
    "CVE Scanner",
    "Auto-Pwn",
    "Router Exploits",
    "Chaos Mode",
    "Exit"
]

running, attack_process, menu_idx = True, None, 0

def draw_ui(title="", lines=None, menu=None, selected=0):
    if not HAS_LCD:
        return
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(img)
    y = 2
    if title:
        draw.text((2, y), title, font=FONT_TITLE, fill="white")
        y += 14
    if lines:
        for line in lines:
            draw.text((2, y), line[:20], font=FONT, fill="white")
            y += 10
    if menu:
        for i, item in enumerate(menu):
            color = "yellow" if i == selected else "white"
            text = f"{'>' if i == selected else ' '} {item[:17]}"
            draw.text((2, y), text, font=FONT, fill=color)
            y += 11
    LCD.LCD_ShowImage(img)

def cleanup(*_):
    global running, attack_process
    running = False
    if attack_process:
        try:
            attack_process.terminate()
            attack_process.wait(timeout=2)
        except:
            try:
                attack_process.kill()
            except:
                pass
    draw_ui("Cleanup", ["Stopping Jam_Fi...", "Restoring WiFi..."])
    subprocess.run(["pkill", "-f", "jam_fi"], stderr=subprocess.DEVNULL)
    subprocess.run(["airmon-ng", "stop", "wlan0mon"], stderr=subprocess.DEVNULL)
    time.sleep(1)
    if HAS_LCD:
        GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def run_jam_fi():
    global attack_process
    try:
        draw_ui("Jam_Fi WiFi Toolkit", ["Starting main menu...", "Please wait..."])
        cmd = ["sudo", "python3", os.path.join(JAM_FI_PATH, "jam_fi.py")]
        attack_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        start = time.time()
        while attack_process.poll() is None and running:
            elapsed = int(time.time() - start)
            draw_ui("Jam_Fi", [f"Running...", f"Time: {elapsed}s", "KEY3 to exit"])
            time.sleep(1)
    except Exception as e:
        draw_ui("Error", [str(e)[:30]])
        time.sleep(2)
    finally:
        attack_process = None

def button_pressed(pin):
    global menu_idx, running
    if pin == PINS["DOWN"]:
        menu_idx = (menu_idx + 1) % len(MENU)
    elif pin == PINS["UP"]:
        menu_idx = (menu_idx - 1) % len(MENU)
    elif pin == PINS["OK"]:
        if menu_idx == 10:
            cleanup()
        else:
            run_jam_fi()
    elif pin == PINS["KEY3"]:
        cleanup()

def main():
    global menu_idx, running
    if HAS_LCD:
        for pin in PINS.values():
            GPIO.add_event_detect(pin, GPIO.FALLING, callback=lambda p: button_pressed(p), bouncetime=200)
    try:
        while running:
            draw_ui("Jam_Fi WiFi Kit", menu=MENU, selected=menu_idx)
            time.sleep(0.2)
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()
