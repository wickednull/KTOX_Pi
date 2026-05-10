#!/usr/bin/env python3
"""
KTOx Payload – Jam_Fi Wi-Fi Exploitation Toolkit (Interactive)
==============================================================
Complete interactive wireless attack suite with on-screen keyboard.

Features:
  - Deauth attacks & handshake capture
  - WPA cracking
  - Probe request flooding
  - Evil AP with credential logging
  - MITM injection & keylogger
  - CVE vulnerability scanner
  - Auto-Pwn automated chain
  - Router exploitation

Controls:
  UP / DOWN / LEFT / RIGHT  – Navigate keyboard
  OK                        – Press key
  KEY1                      – Delete / Back
  KEY3                      – Exit tool
"""

import os
import sys
import time
import signal
import subprocess
import threading
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT2 = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ROOT3 = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ROOT2, _ROOT3):
    if _p not in sys.path:
        sys.path.append(_p)

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

try:
    from _darksec_keyboard import DarkSecKeyboard
except ImportError:
    from payloads._darksec_keyboard import DarkSecKeyboard

# Hardware setup
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for _p in PINS.values():
    GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Get screen rotation (0, 90, 180, 270 degrees)
ROTATION = 0
try:
    if os.path.exists("/root/KTOx/gui_conf.json"):
        with open("/root/KTOx/gui_conf.json") as f:
            conf = json.load(f)
            ROTATION = conf.get("rotation", 0)
except:
    pass

def _rotate_button(btn, rotation):
    """Map button input based on screen rotation."""
    if rotation == 0 or not btn:
        return btn
    rotations = {
        90: {"UP": "LEFT", "DOWN": "RIGHT", "LEFT": "DOWN", "RIGHT": "UP"},
        180: {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"},
        270: {"UP": "RIGHT", "DOWN": "LEFT", "LEFT": "UP", "RIGHT": "DOWN"},
    }
    return rotations.get(rotation, {}).get(btn, btn)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = LCD.width, LCD.height

JAM_FI_PATH = "/root/Jam_Fi"
running = True
proc = None

def _sig(s, f):
    global running, proc
    running = False
    if proc:
        try:
            proc.stdin.close()
            proc.terminate()
        except:
            pass

signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)

def _display_output(lines):
    """Display tool output on LCD with scrolling."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 127, 12), fill=(139, 0, 0))
    draw.text((4, 1), "JAM_FI", font=ImageFont.load_default(), fill=(192, 57, 43))

    y = 16
    for line in lines[-7:]:
        text = line[:20]
        draw.text((2, y), text, font=ImageFont.load_default(), fill=(242, 243, 244))
        y += 12

    draw.rectangle((0, 117, 127, 127), fill=(34, 0, 0))
    draw.text((4, 120), "Use keyboard", font=ImageFont.load_default(), fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)

def main():
    global proc, running

    try:
        proc = subprocess.Popen(
            ["sudo", "python3", f"{JAM_FI_PATH}/jam_fi.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
    except Exception as e:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((4, 20), f"Error: {str(e)[:30]}", fill=(242, 243, 244))
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        GPIO.cleanup()
        return 1

    kb = DarkSecKeyboard(
        width=WIDTH,
        height=HEIGHT,
        lcd=LCD,
        gpio_pins=PINS,
        gpio_module=GPIO,
    )

    output_lines = []
    input_buffer = ""

    def read_output():
        nonlocal output_lines
        try:
            while proc.poll() is None and running:
                try:
                    line = proc.stdout.readline()
                    if line:
                        output_lines.append(line.strip())
                        if len(output_lines) > 50:
                            output_lines = output_lines[-50:]
                        _display_output(output_lines + [f"> {input_buffer}"])
                except:
                    pass
                time.sleep(0.1)
        except:
            pass

    reader_thread = threading.Thread(target=read_output, daemon=True)
    reader_thread.start()

    try:
        while running and proc.poll() is None:
            kb.draw()
            _display_output(output_lines + [f"> {input_buffer}"])

            btn = kb._get_gpio_action()
            if btn:
                btn = _rotate_button(btn, ROTATION)

            if btn == "KEY3":
                break
            elif btn == "UP":
                kb.row = max(-1, kb.row - 1)
            elif btn == "DOWN":
                kb.row = min(len(kb._current_kb()) - 1, kb.row + 1)
            elif btn == "LEFT":
                kb.col = max(0, kb.col - 1)
            elif btn == "RIGHT":
                kb.col = min(len(kb._current_kb()[kb.row]) - 1, kb.col + 1)
            elif btn == "OK" and kb.row >= 0:
                key = kb._current_kb()[kb.row][kb.col]
                if key == "ENT":
                    if input_buffer:
                        proc.stdin.write(input_buffer + "\n")
                        proc.stdin.flush()
                        output_lines.append(f"> {input_buffer}")
                        input_buffer = ""
                elif key == "BS":
                    input_buffer = input_buffer[:-1]
                elif key == "SPC":
                    input_buffer += " "
                elif key == "TAB":
                    input_buffer += "  "
                elif key == "CLR":
                    input_buffer = ""
                elif key not in ("abc", "ABC", "123", "TOOL", "SYM", "C-C"):
                    input_buffer += key

            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        if proc:
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=2)
            except:
                pass
        LCD.LCD_Clear()
        GPIO.cleanup()

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
