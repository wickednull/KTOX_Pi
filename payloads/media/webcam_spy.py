#!/usr/bin/env python3
"""
KTOx *payload* – **Webcam Spy**
==================================
This payload allows the user to capture images from a connected USB webcam.
It uses the `fswebcam` utility to take a picture and saves it to the
KTOx's loot directory.

Features:
- Captures a still image from the default USB webcam.
- Saves the captured image with a timestamp to the `loot/Webcam_Spy` directory.
- Displays status messages on the LCD.
- Verifies `fswebcam` installation.

Controls:
- OK: Capture an image.
- KEY3: Exit Payload.
"""
import sys
import os
import time
import signal
import subprocess
# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
import RPi.GPIO as GPIO
import LCD_Config
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

LOOT_DIR = os.path.join(KTOX_ROOT, "loot", "Webcam_Spy")

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
    y = 40
    for line in lines:
        d.text((5, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def run_capture():
    show_message(["Capturing image..."])
    
    try:
        os.makedirs(LOOT_DIR, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(LOOT_DIR, f"webcam_{timestamp}.jpg")
        
        command = f"fswebcam -r 1280x720 --no-banner {output_file}"
        
        proc = subprocess.run(command, shell=True, check=True, capture_output=True, text=True, timeout=15)
        
        if os.path.exists(output_file):
            show_message(["Image captured!", "Saved to loot."], "lime")
        else:
            raise Exception("File not created.")

    except subprocess.TimeoutExpired:
        show_message(["Capture timed out!", "Is webcam busy?"], "red")
    except Exception as e:
        show_message(["Capture FAILED!", "Is webcam", "connected?"], "red")
        print(f"Webcam capture failed: {e}", file=sys.stderr)
        if 'proc' in locals(): print(proc.stderr, file=sys.stderr)

if __name__ == '__main__':
    try:
        if subprocess.run("which fswebcam", shell=True, capture_output=True).returncode != 0:
            show_message(["fswebcam", "not found!"], "red")
            time.sleep(3)
        else:
            show_message(["Webcam Spy", "Press OK to", "capture image."])
            
            last_button_press_time = 0
            BUTTON_DEBOUNCE_TIME = 0.3 # seconds

            while running:
                current_time = time.time()
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    break
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    run_capture()
                    time.sleep(4)
                    show_message(["Ready."])
                time.sleep(0.1)
            
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Webcam Spy payload finished.")