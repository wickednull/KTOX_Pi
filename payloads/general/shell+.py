#!/usr/bin/env python3
"""
KTOx Terminal OS Core – DarkSec Edition v1.9
--------------------------------------------
Fully interactive micro shell for Waveshare 1.44" LCD
Supports USB/Bluetooth keyboards and GPIO buttons
"""

import os
import sys
import time
import threading
import fcntl
import pty
import select
import re
import signal

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from evdev import InputDevice, categorize, ecodes, list_devices

# --- LCD Setup ---
WIDTH, HEIGHT = 128, 128
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

# --- Fonts ---
FONT_SIZE = 8
FONT_MIN, FONT_MAX = 6, 12
try:
    FONT = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", FONT_SIZE)
except:
    FONT = ImageFont.load_default()

CHAR_W, CHAR_H = 8, 10
COLS, ROWS = WIDTH // CHAR_W, HEIGHT // CHAR_H

def set_font(size):
    global FONT, CHAR_W, CHAR_H, COLS, ROWS, FONT_SIZE
    FONT_SIZE = max(FONT_MIN, min(FONT_MAX, size))
    try:
        FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", FONT_SIZE)
    except:
        FONT = ImageFont.load_default()
    _img = Image.new("RGB", (10, 10))
    _d = ImageDraw.Draw(_img)
    _bbox = _d.textbbox((0,0), "M", font=FONT)
    CHAR_W, CHAR_H = _bbox[2]-_bbox[0], _bbox[3]-_bbox[1]
    COLS, ROWS = WIDTH // CHAR_W, HEIGHT // CHAR_H

set_font(FONT_SIZE)

# --- GPIO Buttons ---
PINS = {"KEY1":21, "KEY2":20, "KEY3":16}
GPIO.setmode(GPIO.BCM)
for p in PINS.values():
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
_prev_state = {p:1 for p in PINS.values()}

# --- Evdev Keyboard ---
def find_keyboard():
    for path in list_devices():
        dev = InputDevice(path)
        if ecodes.EV_KEY in dev.capabilities():
            return dev
    raise RuntimeError("No keyboard found")

keyboard = find_keyboard()
keyboard.grab()
fcntl.fcntl(keyboard.fd, fcntl.F_SETFL, fcntl.fcntl(keyboard.fd, fcntl.F_GETFL) | os.O_NONBLOCK)

SHIFT_KEYS = {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}
KEYMAP = {**{f"KEY_{c}": c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
          "KEY_SPACE":" ", "KEY_ENTER":"\n","KEY_KPENTER":"\n",
          "KEY_BACKSPACE":"\x7f","KEY_TAB":"\t",
          "KEY_MINUS":"-","KEY_EQUAL":"=","KEY_LEFTBRACE":"[",
          "KEY_RIGHTBRACE":"]","KEY_BACKSLASH":"\\","KEY_SEMICOLON":";",
          "KEY_APOSTROPHE":"'","KEY_GRAVE":"`","KEY_COMMA":",",
          "KEY_DOT":".","KEY_SLASH":"/",
          "KEY_1":"1","KEY_2":"2","KEY_3":"3","KEY_4":"4",
          "KEY_5":"5","KEY_6":"6","KEY_7":"7","KEY_8":"8",
          "KEY_9":"9","KEY_0":"0"}
SHIFT_MAP = {"KEY_1":"!","KEY_2":"@","KEY_3":"#","KEY_4":"$","KEY_5":"%",
             "KEY_6":"^","KEY_7":"&","KEY_8":"*","KEY_9":"(","KEY_0":")",
             "KEY_MINUS":"_","KEY_EQUAL":"+","KEY_LEFTBRACE":"{","KEY_RIGHTBRACE":"}",
             "KEY_BACKSLASH":"|","KEY_SEMICOLON":":","KEY_APOSTROPHE":'"',
             "KEY_GRAVE":"~","KEY_COMMA":"<","KEY_DOT":">","KEY_SLASH":"?",
             **{f"KEY_{c}": c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}}
ansi_escape = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")

# --- PTY Shell ---
pid, master_fd = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["bash", "--login"])
fcntl.fcntl(master_fd, fcntl.F_SETFL, fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

poller = select.poll()
poller.register(master_fd, select.POLLIN)
poller.register(keyboard.fd, select.POLLIN)

scrollback = []
current_line = ""
shift = False
running = True

def write_byte(s):
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
        if ch=="\n":
            scrollback.append(current_line)
            current_line=""
        elif ch in ("\x08","\x7f"):
            current_line=current_line[:-1]
        elif ch=="\r":
            continue
        else:
            current_line+=ch
            while len(current_line)>COLS:
                scrollback.append(current_line[:COLS])
                current_line=current_line[COLS:]
    if len(scrollback)>256:
        scrollback = scrollback[-256:]
    draw_buffer()

def draw_buffer():
    img = Image.new("RGB",(WIDTH,HEIGHT),"black")
    d = ImageDraw.Draw(img)
    visible = scrollback[-(ROWS-1):] + [current_line]
    y=0
    for line in visible:
        d.text((0,y), line.ljust(COLS)[:COLS], font=FONT, fill="#00FF00")
        y+=CHAR_H
    LCD.LCD_ShowImage(img,0,0)

def handle_key(event):
    global shift
    key_name = event.keycode if isinstance(event.keycode,str) else event.keycode[0]
    if key_name in SHIFT_KEYS:
        shift = event.keystate==event.key_down
        return
    if event.keystate!=event.key_down:
        return
    if key_name=="KEY_ESC" or GPIO.input(PINS["KEY3"])==0:
        cleanup()
        return
    char = SHIFT_MAP.get(key_name) if shift else KEYMAP.get(key_name)
    if char is not None:
        write_byte(char)

def handle_buttons():
    global FONT_SIZE
    for pin, delta in ((PINS["KEY1"],+1),(PINS["KEY2"],-1)):
        state = GPIO.input(pin)
        if _prev_state[pin]==1 and state==0:
            set_font(FONT_SIZE+delta)
        _prev_state[pin]=state
    if GPIO.input(PINS["KEY3"])==0:
        cleanup()

def cleanup(*_):
    global running
    running=False

signal.signal(signal.SIGINT,cleanup)
signal.signal(signal.SIGTERM,cleanup)

def main():
    draw_buffer()
    try:
        while running:
            for fd,_ in poller.poll(50):
                if fd==master_fd:
                    process_shell_output()
                elif fd==keyboard.fd:
                    for ev in keyboard.read():
                        if ev.type==ecodes.EV_KEY:
                            handle_key(categorize(ev))
            handle_buttons()
            time.sleep(0.02)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        try: os.close(master_fd)
        except: pass

if __name__=="__main__":
    main()
