#!/usr/bin/env python3
"""
KTOx *payload* – **Self-Destruct**
=====================================
This payload performs a destructive operation, deleting all collected loot
and all other payloads from the KTOx device. This is an irreversible
action intended for situations where sensitive data needs to be purged
or the device needs to be reset to a minimal state.

Features:
- Prompts user for multiple confirmations before proceeding.
- Deletes all files and subdirectories within the `loot` directory.
- Deletes all other Python payloads from the `payloads` directory,
  excluding itself.
- Displays status messages on the LCD during the process.

Controls:
- OK: Confirm destructive actions.
- KEY3: Abort self-destruct sequence.
"""
import sys
import os
import time
import signal
import subprocess
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

KTOX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOOT_DIR = os.path.join(KTOX_DIR, "loot")
PAYLOADS_DIR = os.path.join(KTOX_DIR, "payloads")
SELF_NAME = os.path.basename(__file__)

PINS = { "OK": 13, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

running = True

def cleanup_handler(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup_handler)
signal.signal(signal.SIGTERM, cleanup_handler)

def show_message(lines, color="red"):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    y = 20
    for line in lines:
        d.text((5, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def run_self_destruct():
    show_message(["!!! WARNING !!!", "Self-Destruct", "is irreversible.", "Press OK again", "to confirm."])
    
    last_button_press_time = 0
    BUTTON_DEBOUNCE_TIME = 0.3 # seconds

    start_wait = time.time()
    while running and (time.time() - start_wait < 5.0):
        current_time = time.time()
        if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            show_message(["Aborted."])
            return
        if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            break
        time.sleep(0.1)
    else:
        if running: # Only show aborted if not interrupted by signal
            show_message(["Aborted."])
        return

    show_message(["Deleting loot..."])
    if os.path.isdir(LOOT_DIR):
        subprocess.run(f"rm -rf {LOOT_DIR}/*", shell=True)
    time.sleep(1)

    show_message(["Deleting other", "payloads..."])
    if os.path.isdir(PAYLOADS_DIR):
        for filename in os.listdir(PAYLOADS_DIR):
            if filename != SELF_NAME and filename.endswith(".py"):
                os.remove(os.path.join(PAYLOADS_DIR, filename))
    time.sleep(1)
    
    show_message(["Self-Destruct", "Complete."], "lime")

if __name__ == '__main__':
    try:
        run_self_destruct()
        time.sleep(3)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Self-Destruct payload finished.")