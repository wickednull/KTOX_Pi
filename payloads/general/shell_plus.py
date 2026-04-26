#!/usr/bin/env python3
# NAME: DarkSec Micro Shell

import os
import sys
import time
import signal
import select
import fcntl
import pty
import re
import struct
import termios

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont

try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

from _input_helper import get_virtual_button
import LCD_1in44
import LCD_Config

# ------------------------------------------------------------
# Display constants
# ------------------------------------------------------------
WIDTH, HEIGHT = 128, 128
BG = "#120000"
FG = (231, 76, 60)
DIM = (150, 90, 90)
ACCENT = (255, 170, 0)
PANEL = (45, 0, 0)
HILITE = (139, 0, 0)
WHITE = (245, 245, 245)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

image = Image.new("RGB", (WIDTH, HEIGHT), BG)
draw = ImageDraw.Draw(image)

def flush():
    LCD.LCD_ShowImage(image, 0, 0)

# ------------------------------------------------------------
# Fonts
# ------------------------------------------------------------
FONT_MIN, FONT_MAX = 6, 10
FONT_SIZE = 8
font = None
ui_font = None
tiny_font = None
CHAR_W = CHAR_H = COLS = ROWS = 0

def load_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def set_font(size):
    global FONT_SIZE, font, ui_font, tiny_font, CHAR_W, CHAR_H, COLS, ROWS
    FONT_SIZE = max(FONT_MIN, min(FONT_MAX, size))
    font = load_font(FONT_SIZE)
    ui_font = load_font(8)
    tiny_font = load_font(7)

    test_img = Image.new("RGB", (10, 10))
    test_draw = ImageDraw.Draw(test_img)
    try:
        bbox = test_draw.textbbox((0, 0), "M", font=font)
        CHAR_W = max(1, bbox[2] - bbox[0])
        CHAR_H = max(1, bbox[3] - bbox[1] + 1)
    except Exception:
        CHAR_W, CHAR_H = test_draw.textsize("M", font=font)
        CHAR_W = max(1, CHAR_W)
        CHAR_H = max(1, CHAR_H)

    COLS = max(8, WIDTH // CHAR_W)
    ROWS = max(4, (HEIGHT - 12) // CHAR_H)

set_font(FONT_SIZE)

# ------------------------------------------------------------
# GPIO
# ------------------------------------------------------------
PINS = {
    "UP": 6,
    "DOWN": 19,
    "LEFT": 5,
    "RIGHT": 26,
    "OK": 13,
    "KEY1": 21,
    "KEY2": 20,
    "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ------------------------------------------------------------
# Debounce
# ------------------------------------------------------------
DEBOUNCE_BY_BUTTON = {
    "UP": 0.14,
    "DOWN": 0.14,
    "LEFT": 0.14,
    "RIGHT": 0.14,
    "OK": 0.20,
    "KEY1": 0.22,
    "KEY2": 0.20,
    "KEY3": 0.20,
}

_last_press_time = {name: 0.0 for name in PINS}
_last_pressed_state = {name: False for name in PINS}
_last_virtual = None
_last_virtual_time = 0.0

# ------------------------------------------------------------
# USB keyboard
# ------------------------------------------------------------
keyboard = None

def find_keyboard():
    if not HAS_EVDEV:
        return None
    try:
        for path in list_devices():
            try:
                dev = InputDevice(path)
                if ecodes.EV_KEY in dev.capabilities():
                    dev.set_blocking(False)
                    return dev
            except Exception:
                pass
    except Exception:
        pass
    return None

def refresh_keyboard():
    global keyboard
    new = find_keyboard()
    if new and keyboard is None:
        keyboard = new
        try:
            poller.register(keyboard.fd, select.POLLIN)
        except Exception:
            pass
    elif not new and keyboard is not None:
        try:
            poller.unregister(keyboard.fd)
        except Exception:
            pass
        keyboard = None

# ------------------------------------------------------------
# PTY
# ------------------------------------------------------------
pid, master_fd = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["bash", "--login"])

fcntl.fcntl(master_fd, fcntl.F_SETFL,
            fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

def set_pty_size():
    try:
        winsize = struct.pack("HHHH", ROWS - 1, COLS, WIDTH, HEIGHT)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass

set_pty_size()

# ------------------------------------------------------------
# Poller
# ------------------------------------------------------------
poller = select.poll()
poller.register(master_fd, select.POLLIN)
refresh_keyboard()

# ------------------------------------------------------------
# ANSI cleanup
# ------------------------------------------------------------
ansi_escape = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z@`~]'
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'
    r'|[PX^_][^\x1b]*\x1b\\'
    r'|[@-Z\\-_]'
    r')'
)

# ------------------------------------------------------------
# Shell buffer
# ------------------------------------------------------------
scrollback = []
current_line = ""
running = True

def trim_scrollback():
    global scrollback
    if len(scrollback) > 700:
        scrollback = scrollback[-700:]

def draw_shell(lines, partial="", mode="USB"):
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=BG)

    draw.rectangle((0, 0, WIDTH, 10), fill=PANEL)
    draw.text((2, 1), f"{mode} Z{FONT_SIZE}", font=tiny_font, fill=ACCENT)
    draw.text((74, 1), "K1+/hold", font=tiny_font, fill=DIM)

    visible_rows = max(1, (HEIGHT - 12) // CHAR_H)
    visible = lines[-(visible_rows - 1):] + [partial]

    y = 11
    for line in visible[-visible_rows:]:
        draw.text((1, y), line[:COLS], font=font, fill=FG)
        y += CHAR_H

    flush()

def process_output():
    global current_line, scrollback
    try:
        data = os.read(master_fd, 4096).decode(errors="replace")
    except Exception:
        return
    if not data:
        return

    clean = ansi_escape.sub("", data)

    for ch in clean:
        if ch == "\n":
            scrollback.append(current_line)
            current_line = ""
        elif ch == "\r":
            current_line = ""
        elif ch in ("\x08", "\x7f"):
            current_line = current_line[:-1]
        elif ord(ch) < 32:
            pass
        else:
            current_line += ch
            while len(current_line) > COLS:
                scrollback.append(current_line[:COLS])
                current_line = current_line[COLS:]

    trim_scrollback()

def write_pty(s):
    try:
        os.write(master_fd, s.encode())
    except Exception:
        pass

# ------------------------------------------------------------
# Unified input helpers
# ------------------------------------------------------------
VIRT_MAP = {
    "KEY_UP": "UP",
    "KEY_DOWN": "DOWN",
    "KEY_LEFT": "LEFT",
    "KEY_RIGHT": "RIGHT",
    "KEY_PRESS": "OK",
}

def get_virtual_action():
    global _last_virtual, _last_virtual_time

    v = get_virtual_button()
    if not v:
        _last_virtual = None
        return None

    v = VIRT_MAP.get(v, v)
    if v not in PINS:
        return None

    now = time.time()
    min_gap = DEBOUNCE_BY_BUTTON.get(v, 0.18)
    if v == _last_virtual and (now - _last_virtual_time) < min_gap:
        return None

    _last_virtual = v
    _last_virtual_time = now
    return v

def read_gpio_action():
    now = time.time()

    for name, pin in PINS.items():
        pressed = (GPIO.input(pin) == 0)

        if pressed and not _last_pressed_state[name]:
            _last_pressed_state[name] = True
            min_gap = DEBOUNCE_BY_BUTTON.get(name, 0.18)
            if now - _last_press_time[name] >= min_gap:
                _last_press_time[name] = now
                return name

        elif not pressed and _last_pressed_state[name]:
            _last_pressed_state[name] = False

    return None

def wait_release(name):
    if name in PINS:
        while GPIO.input(PINS[name]) == 0:
            time.sleep(0.01)

def wait_action(timeout=0.12):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = get_virtual_action()
        if v in PINS:
            return v

        g = read_gpio_action()
        if g:
            return g

        time.sleep(0.01)
    return None

# ------------------------------------------------------------
# USB keyboard
# ------------------------------------------------------------
SHIFT_KEYS = {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}
CTRL_KEYS = {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}

KEYMAP = {
    **{f"KEY_{c}": c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{f"KEY_{i}": str(i) for i in range(10)},
    "KEY_SPACE": " ",
    "KEY_ENTER": "\r",
    "KEY_KPENTER": "\r",
    "KEY_BACKSPACE": "\x7f",
    "KEY_TAB": "\t",
    "KEY_ESC": "\x1b",
    "KEY_UP": "\x1b[A",
    "KEY_DOWN": "\x1b[B",
    "KEY_RIGHT": "\x1b[C",
    "KEY_LEFT": "\x1b[D",
    "KEY_MINUS": "-",
    "KEY_EQUAL": "=",
    "KEY_LEFTBRACE": "[",
    "KEY_RIGHTBRACE": "]",
    "KEY_BACKSLASH": "\\",
    "KEY_SEMICOLON": ";",
    "KEY_APOSTROPHE": "'",
    "KEY_GRAVE": "`",
    "KEY_COMMA": ",",
    "KEY_DOT": ".",
    "KEY_SLASH": "/",
}

SHIFT_MAP = {
    **{f"KEY_{c}": c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    "KEY_1": "!",
    "KEY_2": "@",
    "KEY_3": "#",
    "KEY_4": "$",
    "KEY_5": "%",
    "KEY_6": "^",
    "KEY_7": "&",
    "KEY_8": "*",
    "KEY_9": "(",
    "KEY_0": ")",
    "KEY_MINUS": "_",
    "KEY_EQUAL": "+",
    "KEY_LEFTBRACE": "{",
    "KEY_RIGHTBRACE": "}",
    "KEY_BACKSLASH": "|",
    "KEY_SEMICOLON": ":",
    "KEY_APOSTROPHE": '"',
    "KEY_GRAVE": "~",
    "KEY_COMMA": "<",
    "KEY_DOT": ">",
    "KEY_SLASH": "?",
}

shift = False
ctrl = False

def ctrl_char(ch):
    if len(ch) == 1 and "a" <= ch.lower() <= "z":
        return chr(ord(ch.lower()) - 96)
    return None

def handle_usb_key(event):
    global shift, ctrl, running

    key_name = event.keycode if isinstance(event.keycode, str) else event.keycode[0]

    if key_name in SHIFT_KEYS:
        shift = (event.keystate == event.key_down)
        return
    if key_name in CTRL_KEYS:
        ctrl = (event.keystate == event.key_down)
        return
    if event.keystate != event.key_down:
        return

    if key_name == "KEY_F12":
        running = False
        return

    ch = SHIFT_MAP.get(key_name) if shift else KEYMAP.get(key_name)
    if not ch:
        return

    if ctrl and len(ch) == 1 and ch.isalpha():
        cc = ctrl_char(ch)
        if cc:
            write_pty(cc)
            return

    write_pty(ch)

# ------------------------------------------------------------
# On-screen keyboard
# ------------------------------------------------------------
KB_LOWER = [
    ["q","w","e","r","t","y","u","i","o","p"],
    ["a","s","d","f","g","h","j","k","l","BS"],
    ["z","x","c","v","b","n","m","-","/","."],
    ["ABC","SYM","TAB","SPC","ENT"],
]

KB_UPPER = [
    ["Q","W","E","R","T","Y","U","I","O","P"],
    ["A","S","D","F","G","H","J","K","L","BS"],
    ["Z","X","C","V","B","N","M","_","?","!"],
    ["abc","SYM","TAB","SPC","ENT"],
]

KB_SYMBOL = [
    ["1","2","3","4","5","6","7","8","9","0"],
    ["@","#","$","%","&","*","(",")","[","]"],
    ["{","}","=","+",";",":","'","\"","\\","|"],
    ["abc","TOOL","CLR","SPC","ENT"],
]

KB_TOOLS = [
    ["ls","cd","..","/","~"],
    ["pwd","cat","grep","echo","-la"],
    ["|",">",">>","&&","*"],
    ["abc","SYM","C-C","ESC","ENT"],
]

KB_PAGES = [KB_LOWER, KB_UPPER, KB_SYMBOL, KB_TOOLS]
KB_PAGE_NAMES = ["abc", "ABC", "123", "TOOL"]

vkb_page = 0
vkb_row = -1
vkb_col = 0
history = []
history_idx = None

def current_kb():
    return KB_PAGES[vkb_page]

def normalize_vkb_cursor():
    global vkb_col
    if vkb_row >= 0:
        row = current_kb()[vkb_row]
        vkb_col = min(vkb_col, len(row) - 1)

def add_history(cmd):
    global history
    cmd = cmd.strip()
    if not cmd:
        return
    if not history or history[-1] != cmd:
        history.append(cmd)
    if len(history) > 60:
        history = history[-60:]

def history_prev(current_compose):
    global history_idx
    if not history:
        return current_compose
    if history_idx is None:
        history_idx = len(history) - 1
    else:
        history_idx = max(0, history_idx - 1)
    return history[history_idx]

def history_next(current_compose):
    global history_idx
    if not history:
        return current_compose
    if history_idx is None:
        return current_compose
    history_idx += 1
    if history_idx >= len(history):
        history_idx = None
        return ""
    return history[history_idx]

def draw_vkb(compose):
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=BG)

    draw.rectangle((0, 0, WIDTH, 12), fill=PANEL)
    draw.text((2, 2), f"VKB {KB_PAGE_NAMES[vkb_page]}", font=tiny_font, fill=ACCENT)
    draw.text((78, 2), "K2/K3 exit", font=tiny_font, fill=DIM)

    comp_selected = (vkb_row == -1)
    draw.rounded_rectangle(
        (2, 14, WIDTH - 3, 32),
        radius=2,
        outline=ACCENT if comp_selected else HILITE,
        fill=HILITE if comp_selected else "#220000"
    )
    preview = compose[-18:] if compose else "_"
    draw.text((4, 19), preview, font=ui_font, fill=WHITE)
    if history_idx is not None and history:
        draw.text((WIDTH - 24, 19), "H", font=ui_font, fill=ACCENT)

    kb = current_kb()
    top = 36
    row_h = 18

    for r, row in enumerate(kb):
        gap = 2
        x = 2
        y1 = top + r * row_h
        y2 = y1 + 15

        for c, key in enumerate(row):
            selected = (r == vkb_row and c == vkb_col)

            if len(key) <= 2:
                w = 11
            elif len(key) == 3:
                w = 16
            else:
                w = 22

            draw.rounded_rectangle(
                (x, y1, x + w, y2),
                radius=2,
                fill=HILITE if selected else PANEL,
                outline=ACCENT if selected else DIM
            )

            label = key
            if key == "SPC":
                label = "SP"
            elif key == "TAB":
                label = "TB"
            elif key == "ENT":
                label = "OK"
            elif key == "ESC":
                label = "EX"
            elif key == "CLR":
                label = "CL"
            elif key == "ABC":
                label = "AB"
            elif key == "abc":
                label = "ab"
            elif key == "SYM":
                label = "#+"
            elif key == "TOOL":
                label = "TL"

            try:
                bbox = draw.textbbox((0, 0), label, font=tiny_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except Exception:
                tw, th = 8, 8

            tx = x + max(1, (w - tw) // 2)
            ty = y1 + max(0, (15 - th) // 2 - 1)
            draw.text((tx, ty), label, font=tiny_font,
                      fill=WHITE if selected else FG)

            x += w + gap

    draw.rectangle((0, HEIGHT - 12, WIDTH, HEIGHT), fill=PANEL)
    draw.text((2, HEIGHT - 10), "U/D hist  OK key", font=tiny_font, fill=DIM)

    flush()

def vkb_apply_key(compose, key):
    global vkb_page, history_idx

    history_idx = None

    if key == "BS":
        return compose[:-1], False
    if key == "CLR":
        return "", False
    if key == "SPC":
        return compose + " ", False
    if key == "TAB":
        return compose + "\t", False
    if key == "ENT":
        return compose, True
    if key == "ESC":
        return None, True
    if key == "C-C":
        write_pty("\x03")
        return "", False

    if key == "ABC":
        vkb_page = 1
        return compose, False
    if key == "abc":
        vkb_page = 0
        return compose, False
    if key == "SYM":
        vkb_page = 2
        return compose, False
    if key == "TOOL":
        vkb_page = 3
        return compose, False

    token = key
    if key in ("ls", "cd", "pwd", "cat", "grep", "echo"):
        token = key + " "
    elif key in ("|", ">", ">>", "&&"):
        token = " " + key + " "
    elif key == "-la":
        token = " -la"

    return compose + token, False

def run_vkb():
    global vkb_page, vkb_row, vkb_col, history_idx

    compose = ""
    vkb_page = 0
    vkb_row = -1
    vkb_col = 0
    history_idx = None

    while True:
        normalize_vkb_cursor()
        draw_vkb(compose)

        btn = wait_action(0.15)
        if btn is None:
            continue

        if btn == "UP":
            if vkb_row == -1:
                compose = history_prev(compose)
            else:
                vkb_row -= 1
                if vkb_row < -1:
                    vkb_row = -1
                normalize_vkb_cursor()

        elif btn == "DOWN":
            if vkb_row == -1:
                if history_idx is not None:
                    compose = history_next(compose)
                else:
                    vkb_row = 0
                    normalize_vkb_cursor()
            else:
                vkb_row = min(len(current_kb()) - 1, vkb_row + 1)
                normalize_vkb_cursor()

        elif btn == "LEFT":
            if vkb_row >= 0:
                vkb_col = max(0, vkb_col - 1)

        elif btn == "RIGHT":
            if vkb_row >= 0:
                vkb_col = min(len(current_kb()[vkb_row]) - 1, vkb_col + 1)

        elif btn == "OK":
            if vkb_row == -1:
                return compose
            key = current_kb()[vkb_row][vkb_col]
            compose, done = vkb_apply_key(compose, key)
            if compose is None:
                return None
            if done:
                return compose

        elif btn in ("KEY2", "KEY3"):
            return None

# ------------------------------------------------------------
# Main helpers
# ------------------------------------------------------------
vkb_mode = (keyboard is None)
last_key1_time = 0.0

def redraw():
    draw_shell(scrollback, current_line, "VKB" if vkb_mode else "USB")

def handle_key1_press():
    global vkb_mode, last_key1_time

    start = time.time()
    while GPIO.input(PINS["KEY1"]) == 0:
        time.sleep(0.03)
        if time.time() - start >= 0.9:
            vkb_mode = not vkb_mode
            redraw()
            wait_release("KEY1")
            last_key1_time = time.time()
            return

    set_font(FONT_SIZE + 1)
    set_pty_size()
    redraw()
    last_key1_time = time.time()

def launch_vkb():
    if GPIO.input(PINS["OK"]) == 0:
        wait_release("OK")
    typed = run_vkb()
    redraw()
    if typed is not None:
        if typed.strip():
            add_history(typed)
        write_pty(typed + "\r")

# ------------------------------------------------------------
# Startup
# ------------------------------------------------------------
redraw()
time.sleep(0.4)

# ------------------------------------------------------------
# Main loop
# ------------------------------------------------------------
try:
    while running:
        refresh_keyboard()
        if keyboard is None and not vkb_mode:
            vkb_mode = True
            redraw()

        events = poller.poll(40)
        for fd, _ in events:
            if fd == master_fd:
                process_output()
                redraw()
            elif keyboard is not None and fd == keyboard.fd:
                try:
                    for ev in keyboard.read():
                        if ev.type == ecodes.EV_KEY:
                            handle_usb_key(categorize(ev))
                except OSError:
                    try:
                        poller.unregister(keyboard.fd)
                    except Exception:
                        pass
                    keyboard = None
                    vkb_mode = True
                    redraw()

        if GPIO.input(PINS["KEY1"]) == 0 and (time.time() - last_key1_time > DEBOUNCE_BY_BUTTON["KEY1"]):
            handle_key1_press()

        if GPIO.input(PINS["KEY2"]) == 0:
            wait_release("KEY2")
            set_font(FONT_SIZE - 1)
            set_pty_size()
            redraw()
            time.sleep(0.1)

        if GPIO.input(PINS["KEY3"]) == 0:
            running = False
            break

        virt = get_virtual_action()
        if virt == "KEY1":
            set_font(FONT_SIZE + 1)
            set_pty_size()
            redraw()
        elif virt == "KEY2":
            set_font(FONT_SIZE - 1)
            set_pty_size()
            redraw()
        elif virt == "KEY3":
            running = False
            break

        if vkb_mode:
            ok_pressed = (GPIO.input(PINS["OK"]) == 0) or (virt == "OK")
            if ok_pressed:
                launch_vkb()
                time.sleep(0.12)

except Exception as e:
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=BG)
    draw.text((2, 20), "ERR", font=ui_font, fill=ACCENT)
    draw.text((2, 36), str(e)[:18], font=tiny_font, fill=FG)
    flush()
    time.sleep(2)

finally:
    try:
        LCD.LCD_Clear()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass
    try:
        os.close(master_fd)
    except Exception:
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
