#!/usr/bin/env python3
"""
KTOx *payload* – **Rowhammer Attack**
==========================================
This payload performs a Rowhammer attack, which is a hardware-level
attack that allows an attacker to flip bits in a target device's
memory.

**NOTE:** This is a very advanced and difficult attack that requires a
deep understanding of memory architecture and a lot of luck.

Features:
- Uses a generic tool to test for Rowhammer vulnerabilities.
- The attack runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the attack.
    - KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import threading

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

running = True
attack_thread = None

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

def cleanup(*_):
    global running
    running = False
    
    # Kill all the processes
    subprocess.run("killall rowhammer-test", shell=True)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Rowhammer Attack", font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

    if message_lines:
        if isinstance(message_lines, str):
            message_lines = [message_lines]
        y_offset = (128 - len(message_lines) * 12) // 2
        for line in message_lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (128 - w) // 2
            d.text((x, y_offset), line, font=FONT, fill=(212, 172, 13))
            y_offset += 12
    elif screen_state == "main":
        d.text((5, 30), "Press OK to start the", font=FONT, fill=(242, 243, 244))
        d.text((5, 45), "Rowhammer attack.", font=FONT, fill=(242, 243, 244))
        d.text((5, 100), "OK=Start", font=FONT, fill=(171, 178, 185))
        d.text((5, 110), "KEY3=Exit", font=FONT, fill=(171, 178, 185))
    elif screen_state == "attacking":
        d.text((5, 50), "Running attack...", font=FONT_TITLE, fill=(212, 172, 13))

    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    draw_ui("attacking")
    
    # Command to execute
    command = [
        "/path/to/rowhammer-test"
    ]
    
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=3600) # 1 hour timeout
        
        if process.returncode == 0:
            draw_ui(message_lines=["Attack successful!", "Check output."])
            
            # Save the output to a loot file
            loot_dir = os.path.join(KTOX_ROOT, "loot", "rowhammer")
            os.makedirs(loot_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            loot_file = os.path.join(loot_dir, f"rowhammer_{timestamp}.txt")
            with open(loot_file, "w") as f:
                f.write(stdout)
        else:
            draw_ui(message_lines=["Attack failed!", "Check console."])
            print(stderr)
            
    except subprocess.TimeoutExpired:
        draw_ui(message_lines=["Attack timed out!"])
    except Exception as e:
        draw_ui(message_lines=["Attack failed!", str(e)])
        
    time.sleep(3)

if __name__ == "__main__":
    try:
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                attack_thread = threading.Thread(target=run_attack)
                attack_thread.start()
                time.sleep(0.3)

            if GPIO.input(PINS["KEY3"]) == 0:
                cleanup()
                break
            
            time.sleep(0.1)
            
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Rowhammer Attack payload finished.")
