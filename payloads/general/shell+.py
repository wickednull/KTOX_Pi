#!/usr/bin/env python3
"""
DarkSec KTOx Micro Shell – v1.7
====================================
Interactive /bin/bash PTY on 1.44-inch Waveshare LCD.
USB keyboard + GPIO keys for zoom/quit, full DarkSec branding.

Quit: ESC key, KEY3 on HAT, or virtual button KEY3.

Requirements:
    sudo apt install python3-evdev python3-pil
"""

# ---------------------------------------------------------
# 0) Imports
# ---------------------------------------------------------
import os, sys, time, signal, select, fcntl, pty, re, subprocess
from pathlib import Path

import RPi.GPIO as GPIO
from evdev import InputDevice, categorize, ecodes, list_devices
from PIL import Image, ImageDraw, ImageFont

# Shared input helper (WebUI virtual)
from payloads._input_helper import get_virtual_button

# Waveshare LCD
import LCD_1in44, LCD_Config

# ---------------------------------------------------------
# 1) LCD init
# ---------------------------------------------------------
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128

# ---------------------------------------------------------
# 2) Fonts
# ---------------------------------------------------------
FONT_MIN, FONT_MAX = 6, 10
FONT_SIZE = 8

def load_font(size: int):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size
        )
    except Exception:
        return ImageFont.load_default()

font = None
CHAR_W = CHAR_H = COLS = ROWS = 0

def set_font(size: int):
    global FONT_SIZE, font, CHAR_W, CHAR_H, COLS, ROWS
    FONT_SIZE = max(FONT_MIN, min(FONT_MAX, size))
    font = load_font(FONT_SIZE)
    img = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(img)
    CHAR_W, CHAR_H = d.textsize("M", font=font)
    COLS, ROWS = WIDTH // CHAR_W, HEIGHT // CHAR_H

set_font(FONT_SIZE)

# ---------------------------------------------------------
# 3) GPIO keys
# ---------------------------------------------------------
KEY1_PIN, KEY2_PIN, KEY3_PIN = 21, 20, 16
GPIO.setmode(GPIO.BCM)
for p in (KEY1_PIN, KEY2_PIN, KEY3_PIN):
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
_prev_state = {p: 1 for p in (KEY1_PIN, KEY2_PIN)}

# ---------------------------------------------------------
# 4) Find USB keyboard
# ---------------------------------------------------------
def find_keyboard() -> InputDevice:
    for path in list_devices():
        dev = InputDevice(path)
        if ecodes.EV_KEY in dev.capabilities():
            return dev
    raise RuntimeError("No USB keyboard detected – plug one via OTG?")

keyboard = find_keyboard()
if hasattr(keyboard, "set_blocking"):
    keyboard.set_blocking(False)
elif hasattr(keyboard, "setblocking"):
    keyboard.setblocking(False)
else:
    fcntl.fcntl(keyboard.fd, fcntl.F_SETFL, os.O_NONBLOCK)

# ---------------------------------------------------------
# 5) PTY bash spawn
# ---------------------------------------------------------
pid, master_fd = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["bash", "--login"])
fcntl.fcntl(master_fd, fcntl.F_SETFL, fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

# ---------------------------------------------------------
# 6) Poller
# ---------------------------------------------------------
poller = select.poll()
poller.register(master_fd, select.POLLIN)
poller.register(keyboard.fd, select.POLLIN)

# ---------------------------------------------------------
# 7) Keymaps
# ---------------------------------------------------------
SHIFT_KEYS = {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}
KEYMAP = {**{f"KEY_{c}": c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
          "KEY_SPACE":" ","KEY_ENTER":"\n","KEY_KPENTER":"\n",
          "KEY_BACKSPACE":"\x7f","KEY_TAB":"\t","KEY_MINUS":"-",
          "KEY_EQUAL":"=","KEY_LEFTBRACE":"[","KEY_RIGHTBRACE":"]",
          "KEY_BACKSLASH":"\\","KEY_SEMICOLON":";","KEY_APOSTROPHE":"'","KEY_GRAVE":"`",
          "KEY_COMMA":",","KEY_DOT":".","KEY_SLASH":"/",
          **{f"KEY_{i}": str(i) for i in range(10)}}
SHIFT_MAP = {**{f"KEY_{c}": c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
             "KEY_1":"!","KEY_2":"@","KEY_3":"#","KEY_4":"$","KEY_5":"%",
             "KEY_6":"^","KEY_7":"&","KEY_8":"*","KEY_9":"(","KEY_0":")",
             "KEY_MINUS":"_","KEY_EQUAL":"+","KEY_LEFTBRACE":"{","KEY_RIGHTBRACE":"}",
             "KEY_BACKSLASH":"|","KEY_SEMICOLON":":","KEY_APOSTROPHE":"\"",
             "KEY_GRAVE":"~","KEY_COMMA":"<","KEY_DOT":">","KEY_SLASH":"?"}
ansi_escape = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")

# ---------------------------------------------------------
# 8) Screen helpers
# ---------------------------------------------------------
scrollback = []
current_line = ""

def draw_buffer(lines: list, partial: str=""):
    img = Image.new("RGB", (WIDTH, HEIGHT), "#330000")  # DarkSec red background
    d = ImageDraw.Draw(img)
    visible = lines[-(ROWS-1):] + [partial]
    y = 0
    for line in visible:
        d.text((0, y), line.ljust(COLS)[:COLS], font=font, fill="#FF4444")  # Light red text
        y += CHAR_H
    LCD.LCD_ShowImage(img, 0, 0)

def write_byte(s: str):
    os.write(master_fd, s.encode())

def process_shell_output():
    global current_line, scrollback
    try:
        data = os.read(master_fd, 1024).decode(errors="ignore")
    except BlockingIOError:
        return
    if not data:
        return
    clean = ansi_escape.sub("", data)
    for ch in clean:
        if ch == "\n":
            scrollback.append(current_line)
            current_line = ""
        elif ch == "\r":
            continue
        elif ch in ("\x08","\x7f"):
            current_line = current_line[:-1]
        else:
            current_line += ch
            while len(current_line) > COLS:
                scrollback.append(current_line[:COLS])
                current_line = current_line[COLS:]
    if len(scrollback) > 512:
        scrollback = scrollback[-512:]
    draw_buffer(scrollback, current_line)

# ---------------------------------------------------------
# 9) Main loop
# ---------------------------------------------------------
shift = False
running = True

def handle_key(event):
    global shift, running
    key_name = event.keycode if isinstance(event.keycode, str) else event.keycode[0]
    if key_name in SHIFT_KEYS:
        shift = event.keystate == event.key_down
        return
    if event.keystate != event.key_down:
        return
    if key_name == "KEY_ESC" or GPIO.input(KEY3_PIN)==0 or get_virtual_button()=="KEY3":
        running = False
        return
    char = SHIFT_MAP.get(key_name) if shift else KEYMAP.get(key_name)
    if char:
        write_byte(char)

draw_buffer([], "KTOx Micro Shell ready – KEY1/KEY2 zoom ±")

try:
    while running:
        for fd, _ in poller.poll(50):
            if fd == master_fd:
                process_shell_output()
            elif fd == keyboard.fd:
                for ev in keyboard.read():
                    if ev.type == ecodes.EV_KEY:
                        handle_key(categorize(ev))
        virtual = get_virtual_button()
        # Zoom
        for pin, delta in ((KEY1_PIN,+1),(KEY2_PIN,-1)):
            state = GPIO.input(pin)
            if _prev_state[pin]==1 and state==0:
                set_font(FONT_SIZE+delta)
                draw_buffer(scrollback, current_line)
                time.sleep(0.15)
            _prev_state[pin]=state
        if virtual in ("KEY1","KEY2"):
            delta = 1 if virtual=="KEY1" else -1
            set_font(FONT_SIZE+delta)
            draw_buffer(scrollback, current_line)
            time.sleep(0.15)
        if GPIO.input(KEY3_PIN)==0 or virtual=="KEY3":
            running=False
except Exception as exc:
    print(f"[ERROR] {exc}", file=sys.stderr)
finally:
    LCD.LCD_Clear()
    GPIO.cleanup()
    try: os.close(master_fd)
    except: pass
