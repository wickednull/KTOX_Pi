#!/usr/bin/env python3
"""
KTOx *payload* – **DNS Spoofing Cleanup**
=============================================
This payload is designed to forcefully stop any lingering `ettercap` and `php`
processes that might have been left running by a previous DNS Spoofing attack
payload. It provides a simple interface on the 1.44-inch LCD to confirm the cleanup.

This is useful if the main UI or the DNS Spoofing payload crashed, leaving
background processes active.

Controls:
- KEY3: Exit Payload
"""

import sys
import os
import time
import signal
import subprocess

# ----------------------------
# KTOx PATH and ROOT check
# ----------------------------
def is_root():
    return os.geteuid() == 0

# Prefer /root/KTOx for imports; fallback to repo-relative KTOx sibling
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

# ----------------------------
# Third-party library imports 
# ----------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"ERROR: A required library is not found. {e}", file=sys.stderr)
    print("Please run 'sudo pip3 install RPi.GPIO spidev Pillow'.", file=sys.stderr)
    sys.exit(1)

PINS: dict[str, int] = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

running = True

def draw(lines, color="lime"):
    """Clear the screen and draw text lines, centering each line."""
    if isinstance(lines, str):
        lines = [lines]
    
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    y_offset = (HEIGHT - len(lines) * 15) // 2 # Center vertically
    
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2 # Center horizontally
        d.text((x, y_offset), line, font=FONT_TITLE, fill=color)
        y_offset += 15 # Line spacing
    
    LCD.LCD_ShowImage(img, 0, 0)

def cleanup_processes():
    """Forcefully kill ettercap and php processes."""
    killed_ettercap = False
    killed_php = False

    draw(["Cleaning up...", "ettercap & php"], "yellow")
    
    # Kill ettercap
    try:
        # Use pgrep to find PIDs and then kill them
        ettercap_pids = subprocess.check_output(["pgrep", "ettercap"]).decode().strip().split('\n')
        for pid in ettercap_pids:
            if pid:
                subprocess.run(["sudo", "kill", "-9", pid], check=True)
                killed_ettercap = True
        if killed_ettercap:
            print("Ettercap processes killed.")
        else:
            print("No ettercap processes found.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("No ettercap processes found or pgrep/kill failed.")
    except Exception as e:
        print(f"Error killing ettercap: {e}", file=sys.stderr)

    # Kill php
    try:
        php_pids = subprocess.check_output(["pgrep", "php"]).decode().strip().split('\n')
        for pid in php_pids:
            if pid:
                subprocess.run(["sudo", "kill", "-9", pid], check=True)
                killed_php = True
        if killed_php:
            print("PHP processes killed.")
        else:
            print("No php processes found.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("No php processes found or pgrep/kill failed.")
    except Exception as e:
        print(f"Error killing php: {e}", file=sys.stderr)

    return killed_ettercap or killed_php

def main():
    if not is_root():
        draw(["ERROR:", "Root privileges", "required."], "red")
        time.sleep(3)
        sys.exit(1)

    draw(["DNS Cleanup", "Ready", "Press OK to clean"])
    
    while running:
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                while GPIO.input(pin) == 0:
                    time.sleep(0.05)
                break
        
        if btn == "OK":
            cleaned = cleanup_processes()
            if cleaned:
                draw(["Cleanup Complete!", "Processes stopped."], "green")
            else:
                draw(["No processes", "to clean."], "yellow")
            time.sleep(2)
            running = False # Exit after cleanup
        elif btn == "KEY3":
            running = False
        
        time.sleep(0.05)

if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw([f"CRITICAL ERROR:", f"{str(e)[:20]}"], "red")
        time.sleep(3)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("DNS Spoofing Cleanup payload finished.")
