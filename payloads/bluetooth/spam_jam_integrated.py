#!/usr/bin/env python3
"""
KTOx *payload* – **Spam Jam BLE/Bluetooth Attack Toolkit**
===========================================================
Integrates the Spam-Jam toolkit (github.com/ekomsSavior/Spam-Jam)
for advanced Bluetooth and BLE attacks.

Features:
- BLE device scanning & enumeration
- BLE spamming attacks
- BLE jamming attacks
- L2Ping attack floods
- RFCOMM connection floods
- BLE Mesh botnet mode

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

SPAM_JAM_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'vendor', 'spam-jam'))
MENU = ["BLE Scan", "BLE Spam All", "BLE Jam All", "L2Ping Attack", "RFCOMM Flood", "Mesh Menu", "Exit"]

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
            draw.text((2, y), f"{'>' if i == selected else ' '} {item}", font=FONT, fill=color)
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
    draw_ui("Cleanup", ["Stopping...", "Powering off BLE..."])
    subprocess.run(["pkill", "-f", "spam_jam"], stderr=subprocess.DEVNULL)
    subprocess.run(["bluetoothctl", "power", "off"], stderr=subprocess.DEVNULL)
    time.sleep(1)
    if HAS_LCD:
        GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def run_spam_jam(script):
    global attack_process
    try:
        draw_ui("Spam Jam", [f"Starting: {script}", "Running..."])
        cmd = ["sudo", "python3", os.path.join(SPAM_JAM_PATH, script)]
        attack_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        start = time.time()
        while attack_process.poll() is None and running:
            elapsed = int(time.time() - start)
            draw_ui("Spam Jam", [f"Mode: {script}", f"Elapsed: {elapsed}s", "KEY3 to exit"])
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
        if menu_idx == 0:
            run_spam_jam("spam_jam.py")
        elif menu_idx == 1:
            draw_ui("Info", ["BLE Spam All", "Use main menu option"])
            time.sleep(2)
        elif menu_idx == 2:
            draw_ui("Info", ["BLE Jam All", "Use main menu option"])
            time.sleep(2)
        elif menu_idx == 3:
            draw_ui("Info", ["L2Ping Attack", "Use main menu option"])
            time.sleep(2)
        elif menu_idx == 4:
            draw_ui("Info", ["RFCOMM Flood", "Use main menu option"])
            time.sleep(2)
        elif menu_idx == 5:
            draw_ui("Info", ["Mesh Botnet", "Run spamjam_mesh.py"])
            time.sleep(2)
        elif menu_idx == 6:
            cleanup()
    elif pin == PINS["KEY3"]:
        cleanup()

def main():
    global menu_idx, running
    if HAS_LCD:
        for pin in PINS.values():
            GPIO.add_event_detect(pin, GPIO.FALLING, callback=lambda p: button_pressed(p), bouncetime=200)
    try:
        while running:
            draw_ui("Spam Jam BLE Kit", menu=MENU, selected=menu_idx)
            time.sleep(0.2)
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()
