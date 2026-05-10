#!/usr/bin/env python3
"""
KTOx Payload – Wifite WiFi Auditor (LCD Optimized)
===================================================
Interactive WiFi auditing and cracking using wifite, optimized for small LCD.

Features:
  - Real-time WiFi network scanning
  - WPA/WPA2 cracking with multiple attacks
  - Handshake capture and analysis
  - Display optimized for 128x128 LCD
  - Full keyboard control

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
import re

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

# Get screen rotation
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

def _strip_ansi(text):
    """Remove ANSI color codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def _display_output(lines, title="WIFITE"):
    """Display tool output on LCD with scrolling."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 127, 12), fill=(139, 0, 0))
    draw.text((4, 1), title, font=ImageFont.load_default(), fill=(192, 57, 43))

    y = 16
    for line in lines[-7:]:
        text = _strip_ansi(line)[:20]
        draw.text((2, y), text, font=ImageFont.load_default(), fill=(242, 243, 244))
        y += 12

    draw.rectangle((0, 117, 127, 127), fill=(34, 0, 0))
    draw.text((4, 120), "Use keyboard", font=ImageFont.load_default(), fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)

def main():
    global proc, running

    try:
        proc = subprocess.Popen(
            ["sudo", "wifite", "-h"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        proc.terminate()
        proc.wait(timeout=1)
    except Exception:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((4, 20), "Wifite not found", fill=(242, 243, 244))
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
    scanning = False

    def run_wifite():
        global proc, running
        try:
            cmd = ["sudo", "wifite"] + input_buffer.split()
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
        except Exception as e:
            return [f"Error: {str(e)[:40]}"]

        nonlocal output_lines
        try:
            while proc.poll() is None and running:
                try:
                    line = proc.stdout.readline()
                    if line:
                        output_lines.append(line.strip())
                        if len(output_lines) > 50:
                            output_lines = output_lines[-50:]
                        _display_output(output_lines)
                except:
                    pass
                time.sleep(0.05)
        except:
            pass

    try:
        while running:
            kb.draw()
            if scanning:
                _display_output(output_lines)
            else:
                img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.rectangle((0, 0, 127, 12), fill=(139, 0, 0))
                draw.text((4, 1), "WIFITE", font=ImageFont.load_default(), fill=(192, 57, 43))
                draw.text((2, 20), "Args:", font=ImageFont.load_default(), fill=(242, 243, 244))
                draw.text((2, 40), input_buffer[:20], font=ImageFont.load_default(), fill=(170, 170, 255))
                draw.text((2, 100), "OK=Start KEY3=Exit", font=ImageFont.load_default(), fill=(113, 125, 126))
                LCD.LCD_ShowImage(img, 0, 0)

            btn = kb._get_gpio_action()
            if btn:
                btn = _rotate_button(btn, ROTATION)

            if btn == "KEY3":
                break
            elif not scanning:
                if btn == "UP":
                    kb.row = max(-1, kb.row - 1)
                elif btn == "DOWN":
                    kb.row = min(len(kb._current_kb()) - 1, kb.row + 1)
                elif btn == "LEFT":
                    kb.col = max(0, kb.col - 1)
                elif btn == "RIGHT":
                    kb.col = min(len(kb._current_kb()[kb.row]) - 1, kb.col + 1)
                elif btn == "OK":
                    if kb.row >= 0:
                        key = kb._current_kb()[kb.row][kb.col]
                        if key == "ENT":
                            scanning = True
                            output_lines = []
                            reader = threading.Thread(target=run_wifite, daemon=True)
                            reader.start()
                        elif key == "BS":
                            input_buffer = input_buffer[:-1]
                        elif key == "SPC":
                            input_buffer += " "
                        elif key == "CLR":
                            input_buffer = ""
                        elif key not in ("abc", "ABC", "123", "TOOL", "SYM", "C-C"):
                            input_buffer += key
            else:
                if btn == "KEY3":
                    if proc:
                        try:
                            proc.terminate()
                            proc.wait(timeout=2)
                        except:
                            pass
                    scanning = False

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
