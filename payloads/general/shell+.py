#!/usr/bin/env python3
"""
KTOx Terminal OS Core – DarkSec Edition
"""

import sys
import os
import time
import threading
import subprocess
import signal
import getpass

# --- KTOx Path ---
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(
    os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from payloads._input_helper import get_button

# --- Hardware ---
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

WIDTH, HEIGHT = 128, 128

GPIO.setmode(GPIO.BCM)
for p in PINS.values():
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

# --- Fonts ---
try:
    FONT = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
except:
    FONT = ImageFont.load_default()

# --- Colors ---
BG = (5, 5, 5)
TXT = (0, 255, 65)
HDR = (255, 0, 0)
WARN = (255, 200, 0)

# --- State ---
lines = []
max_lines = 8
scroll_offset = 0

cmd_input = ""
cursor_pos = 0

history = []
history_index = -1

running = True
busy = False

# --- Helpers ---
def add_line(text):
    wrapped = [text[i:i+20] for i in range(0, len(text), 20)]
    lines.extend(wrapped)

def clear():
    global lines
    lines = []

# --- Command Engine ---
def run_cmd(cmd):
    global busy
    busy = True
    add_line(f"# {cmd}")

    # --- Built-in commands ---
    if cmd == "clear":
        clear()
        busy = False
        return

    if cmd == "exit":
        cleanup()
        return

    if cmd == "help":
        add_line("Built-ins:")
        add_line("scan | clear | exit")
        busy = False
        return

    if cmd == "scan":
        try:
            res = subprocess.run(
                ["iwlist", "wlan0", "scan"],
                capture_output=True, text=True, timeout=10
            )
            for l in res.stdout.splitlines()[:20]:
                add_line(l.strip())
        except:
            add_line("SCAN FAILED")
        busy = False
        return

    # --- External commands ---
    try:
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        for line in proc.stdout:
            add_line(line.strip())

    except:
        add_line("ERR")

    busy = False

def start_cmd(cmd):
    global history, history_index

    if not cmd.strip():
        return

    history.append(cmd)
    history_index = len(history)

    threading.Thread(target=run_cmd, args=(cmd,), daemon=True).start()

# --- Render ---
def draw():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    # Header
    d.rectangle((0, 0, WIDTH, 12), fill=HDR)
    d.text((2, 1), " KTOX OS ", fill=(255, 255, 255), font=FONT)

    # Output
    y = 14
    visible = lines[-max_lines - scroll_offset: len(lines) - scroll_offset]

    for line in visible:
        d.text((2, y), line, fill=TXT, font=FONT)
        y += 12

    # Input line
    cursor = "_" if int(time.time()*2) % 2 else " "
    display_input = cmd_input[:cursor_pos] + cursor + cmd_input[cursor_pos:]
    d.text((2, HEIGHT-12), display_input[:20], fill=TXT, font=FONT)

    # Busy
    if busy:
        d.text((90, 1), "RUN", fill=WARN, font=FONT)

    LCD.LCD_ShowImage(img, 0, 0)

# --- Input Handling ---
def handle_input(btn):
    global cmd_input, cursor_pos, scroll_offset, history_index

    if btn == "UP":
        if history:
            history_index = max(0, history_index - 1)
            cmd_input = history[history_index]
            cursor_pos = len(cmd_input)

    elif btn == "DOWN":
        if history:
            history_index = min(len(history)-1, history_index + 1)
            cmd_input = history[history_index]
            cursor_pos = len(cmd_input)

    elif btn == "LEFT":
        cursor_pos = max(0, cursor_pos - 1)

    elif btn == "RIGHT":
        cursor_pos = min(len(cmd_input), cursor_pos + 1)

    elif btn == "OK":
        start_cmd(cmd_input)
        cmd_input = ""
        cursor_pos = 0

    elif btn == "KEY1":
        cmd_input += " "  # placeholder typing

    elif btn == "KEY2":
        cmd_input = cmd_input[:-1]
        cursor_pos = len(cmd_input)

    elif btn == "KEY3":
        cleanup()

# --- Cleanup ---
def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# --- Main ---
def main():
    add_line("KTOX OS BOOT")
    add_line(f"USER: {getpass.getuser()}")
    add_line("TYPE 'help'")

    frame_time = 0.05

    while running:
        t0 = time.time()

        btn = get_button(PINS, GPIO)
        if btn:
            handle_input(btn)

        draw()

        dt = time.time() - t0
        if dt < frame_time:
            time.sleep(frame_time - dt)

    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()