#!/usr/bin/env python3
"""
KTOx *payload* – **Reboot Device**
=====================================
This payload provides a simple interface to safely reboot the KTOx device.
It prompts the user for confirmation before executing the reboot command.

Features:
- Prompts user for confirmation before rebooting.
- Displays status messages on the LCD.
- Graceful exit if reboot is cancelled or interrupted.

Controls:
- OK: Confirm reboot.
- KEY3: Cancel reboot.
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

def show_message(lines, color="yellow"):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        d.text((5, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

if __name__ == '__main__':
    try:
        show_message(["Reboot device?", "", "Press OK to", "confirm."])
        
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        start_wait = time.time()
        while running and (time.time() - start_wait < 5.0):
            current_time = time.time()
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                show_message(["Aborted."])
                time.sleep(2)
                raise SystemExit
            if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                show_message(["Rebooting now..."])
                time.sleep(1)
                subprocess.run("reboot", shell=True)
                time.sleep(5)
                break
            time.sleep(0.1)
            
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Reboot payload finished.")