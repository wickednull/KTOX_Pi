#!/usr/bin/env python3
"""
KTOx *payload* – **System Information**
==========================================
This payload displays key system information on the LCD, providing a quick
overview of the KTOx's operational status.

Features:
- Displays CPU load average.
- Shows memory usage percentage.
- Reports disk usage percentage for the root filesystem.
- Displays the primary IP address.
- Updates information periodically.

Controls:
- KEY3: Exit Payload.
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

PINS = { "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True

def cleanup_handler(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup_handler)
signal.signal(signal.SIGTERM, cleanup_handler)

def get_info():
    info = {}
    try:
        info['CPU Load'] = f"{os.getloadavg()[0]:.2f}"
    except:
        info['CPU Load'] = "N/A"
    try:
        mem_info = subprocess.check_output("free -m | awk 'NR==2{printf \"%.0f%%\", $3*100/$2 }'", shell=True).decode("utf-8")
        info['Memory'] = mem_info
    except:
        info['Memory'] = "N/A"
    try:
        disk_info = subprocess.check_output("df -h / | awk 'NR==2{printf \"%s\", $5}'", shell=True).decode("utf-8")
        info['Disk'] = disk_info
    except:
        info['Disk'] = "N/A"
    try:
        ip = subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True).decode("utf-8").strip()
        info['IP'] = ip
    except:
        info['IP'] = "N/A"
    return info

def draw_ui(info):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "System Information", font=FONT_TITLE, fill="cyan")
    d.line([(0, 22), (128, 22)], fill="cyan", width=1)
    
    y_pos = 30
    for key, value in info.items():
        d.text((5, y_pos), f"{key}: {value}", font=FONT, fill="white")
        y_pos += 15
        
    d.text((5, 115), "Press KEY3 to Exit", font=FONT, fill="yellow")
    LCD.LCD_ShowImage(img, 0, 0)

if __name__ == '__main__':
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            system_info = get_info()
            draw_ui(system_info)
            
            start_wait = time.time()
            while running and (time.time() - start_wait < 5.0):
                current_time = time.time()
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    raise SystemExit
                time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("System Info payload finished.")