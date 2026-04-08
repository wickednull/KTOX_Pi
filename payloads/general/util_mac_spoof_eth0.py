#!/usr/bin/env python3
"""
KTOx *payload* – **MAC Spoof (eth0)**
========================================
This payload changes the MAC address of the `eth0` network interface to a
randomly generated one. MAC address spoofing can be used for privacy,
bypassing MAC-based filtering, or impersonating other devices on a network.

Features:
- Changes the MAC address of `eth0` to a random MAC.
- Uses `macchanger` utility.
- Displays success or failure messages on the LCD.
- Verifies `macchanger` installation.

Usage:
- This payload is designed to be executed directly.
- No interactive controls after launch, it performs its function and exits.
"""
import sys
import os
import time
import signal
import subprocess
import random
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

INTERFACE = "eth0"
NEW_MAC = "RANDOM" 

PINS = { "OK": 13, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        d.text((5, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def run_spoof():
    show_message(["Spoofing MAC...", f"on {INTERFACE}"])
    
    try:
        mac_to_set = NEW_MAC
        if mac_to_set == "RANDOM":
            mac_to_set = f"02:00:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"

        command = f"ifconfig {INTERFACE} down; macchanger -m {mac_to_set} {INTERFACE}; ifconfig {INTERFACE} up"
        
        proc = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        
        new_mac_line = [line for line in proc.stdout.split('\n') if "New MAC" in line]
        if new_mac_line:
            final_mac = new_mac_line[0].split()[-1]
            show_message(["Success!", f"New MAC:", final_mac[:20]], "lime")
        else:
            raise Exception("macchanger failed")

    except Exception as e:
        show_message(["Spoof FAILED!", str(e)[:20]], "red")
        print(f"MAC Spoof failed: {e}", file=sys.stderr)

if __name__ == '__main__':
    try:
        if subprocess.run("which macchanger", shell=True, capture_output=True).returncode != 0:
            show_message(["macchanger", "not found!"], "red")
            time.sleep(3)
        else:
            run_spoof()
            time.sleep(5)
            
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("MAC Spoof payload finished.")