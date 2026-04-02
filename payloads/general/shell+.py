#!/usr/bin/env python3
"""
KTOx Terminal OS Core – DarkSec Edition v1.8
---------------------------------------------
Full interactive PTY shell on 1.44" LCD.
Supports wired/Bluetooth keyboards + optional GPIO buttons
for scroll/zoom/quit.
"""

import os
import sys
import time
import threading
import select
import pty
import tty
import termios
import signal
import fcntl
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# Optional: helper to read GPIO buttons
try:
    from payloads._input_helper import get_button
except ImportError:
    get_button = lambda pins, gpio: None

# --- GPIO Buttons ---
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

GPIO.setmode(GPIO.BCM)
for p in PINS.values():
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# --- LCD & Font ---
WIDTH, HEIGHT = 128, 128
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

# Font zoom
FONT_MIN, FONT_MAX = 6, 12
FONT_SIZE = 10

def load_font(size):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except:
        return ImageFont.load_default()

FONT = load_font(FONT_SIZE)
CHAR_W, CHAR_H = FONT.getsize("M")
COLS, ROWS = WIDTH // CHAR_W, (HEIGHT - 14) // CHAR_H

# Colors
BG = (5, 5, 5)
TXT = (0, 255, 65)
HDR = (255, 0, 0)
WARN = (255, 200, 0)

# --- Shell State ---
pty_fd = None
pty_pid = None
pty_output = ""
output_lock = threading.Lock()
scroll_offset = 0
running = True
busy = False

# --- Cleanup ---
def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# --- PTY Shell ---
def spawn_shell():
    global pty_fd, pty_pid
    pty_pid, pty_fd = pty.fork()
    if pty_pid == 0:
        os.execv("/bin/bash", ["bash", "--login"])
    else:
        # make PTY non-blocking
        flags = fcntl.fcntl(pty_fd, fcntl.F_GETFL)
        fcntl.fcntl(pty_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

# --- Read PTY output ---
def read_pty():
    global pty_output
    while running:
        if pty_fd is None:
            time.sleep(0.05)
            continue
        try:
            data = os.read(pty_fd, 1024).decode(errors="ignore")
            if data:
                with output_lock:
                    pty_output += data
                    # cap scrollback ~256 lines
                    lines = pty_output.splitlines()
                    if len(lines) > 256:
                        pty_output = "\n".join(lines[-256:])
        except OSError:
            time.sleep(0.05)
        except Exception:
            pass

# --- Draw LCD ---
def draw_lcd():
    global scroll_offset
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    # Header
    d.rectangle((0, 0, WIDTH, 12), fill=HDR)
    d.text((2, 1), " KTOX OS SHELL ", fill=(255, 255, 255), font=FONT)
    # Output
    with output_lock:
        lines = pty_output.splitlines()
    visible = lines[-ROWS - scroll_offset: len(lines) - scroll_offset]
    y = 14
    for line in visible:
        d.text((0, y), line[:COLS], fill=TXT, font=FONT)
        y += CHAR_H
    # Busy indicator
    if busy:
        d.text((WIDTH-32, 1), "RUN", fill=WARN, font=FONT)
    # Cursor blink
    cursor_x = 0
    cursor_y = 14 + (len(visible)-1)*CHAR_H
    if int(time.time()*2) % 2:
        d.rectangle((cursor_x, cursor_y, cursor_x+CHAR_W, cursor_y+CHAR_H), fill=TXT)
    LCD.LCD_ShowImage(img, 0, 0)

# --- Keyboard Input ---
def handle_keyboard():
    while running:
        rlist, _, _ = select.select([sys.stdin, pty_fd], [], [], 0.05)
        for fd in rlist:
            if fd == sys.stdin:
                try:
                    data = os.read(sys.stdin.fileno(), 1024)
                    if data:
                        os.write(pty_fd, data)
                except Exception:
                    pass
            elif fd == pty_fd:
                try:
                    data = os.read(pty_fd, 1024).decode(errors="ignore")
                    if data:
                        with output_lock:
                            pty_output += data
                except Exception:
                    pass

# --- GPIO Buttons ---
def handle_buttons():
    global scroll_offset, FONT_SIZE, FONT, CHAR_W, CHAR_H, COLS, ROWS
    _prev = {p: 1 for p in PINS.values()}
    while running:
        btn = get_button(PINS, GPIO)
        # Zoom
        for pin, delta in [(PINS["KEY1"], +1), (PINS["KEY2"], -1)]:
            state = GPIO.input(pin)
            if _prev[pin] == 1 and state == 0:  # falling edge
                FONT_SIZE = max(FONT_MIN, min(FONT_MAX, FONT_SIZE + delta))
                FONT = load_font(FONT_SIZE)
                CHAR_W, CHAR_H = FONT.getsize("M")
                COLS, ROWS = WIDTH // CHAR_W, (HEIGHT - 14) // CHAR_H
            _prev[pin] = state
        # Scroll & Quit
        if btn == "UP":
            scroll_offset = max(0, scroll_offset + 1)
        elif btn == "DOWN":
            scroll_offset = max(0, scroll_offset - 1)
        elif btn == "KEY3":
            cleanup()
        time.sleep(0.05)

# --- Main ---
def main():
    spawn_shell()
    threading.Thread(target=read_pty, daemon=True).start()
    threading.Thread(target=handle_keyboard, daemon=True).start()
    threading.Thread(target=handle_buttons, daemon=True).start()

    while running:
        draw_lcd()
        time.sleep(0.05)

    LCD.LCD_Clear()
    GPIO.cleanup()
    if pty_fd:
        os.close(pty_fd)

if __name__ == "__main__":
    # make stdin raw for PTY input
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    try:
        main()
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
