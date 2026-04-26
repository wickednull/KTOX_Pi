#!/usr/bin/env python3
"""
KTOx payload – Micro Shell on 1.44‑inch LCD (v2.0)
======================================================
Hand‑held Linux terminal: interactive /bin/bash in a PTY, rendered on a
128×128 Waveshare LCD.  Input via OTG keyboard (optional) + WebUI virtual
buttons.

Controls
--------
  KEY1 (HAT)    zoom in  (larger font, fewer columns)
  KEY2 (HAT)    zoom out (smaller font, more columns)
  KEY3 (HAT)    quit
  Esc  (kbd)    quit
  All other keys forwarded to bash as-is.

No keyboard attached?  The shell still starts — use WebUI virtual buttons.
"""

# ---------------------------------------------------------
# 0) Imports & path tweaks
# ---------------------------------------------------------
import os, sys, time, signal, select, fcntl, pty, re, struct, termios
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO

# Optional evdev (USB keyboard support)
try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

from _input_helper import get_virtual_button

# ---------------------------------------------------------
# 1) LCD initialisation
# ---------------------------------------------------------
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128

# ---------------------------------------------------------
# 2) Font management
# ---------------------------------------------------------
FONT_MIN, FONT_MAX = 6, 10
FONT_SIZE = 8

def load_font(size: int):
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

font = None
CHAR_W = CHAR_H = COLS = ROWS = 0

def set_font(size: int):
    global FONT_SIZE, font, CHAR_W, CHAR_H, COLS, ROWS
    FONT_SIZE = max(FONT_MIN, min(FONT_MAX, size))
    font = load_font(FONT_SIZE)
    _img = Image.new("RGB", (10, 10))
    _d   = ImageDraw.Draw(_img)
    try:
        _bbox = _d.textbbox((0, 0), "M", font=font)
        CHAR_W, CHAR_H = _bbox[2] - _bbox[0], _bbox[3] - _bbox[1]
    except AttributeError:
        CHAR_W, CHAR_H = FONT_SIZE, FONT_SIZE + 2
    CHAR_W  = max(CHAR_W, 1)
    CHAR_H  = max(CHAR_H, 1)
    COLS    = WIDTH  // CHAR_W
    ROWS    = HEIGHT // CHAR_H

set_font(FONT_SIZE)

# ---------------------------------------------------------
# 3) GPIO pins
# ---------------------------------------------------------
KEY1_PIN, KEY2_PIN, KEY3_PIN = 21, 20, 16
GPIO.setmode(GPIO.BCM)
for p in (KEY1_PIN, KEY2_PIN, KEY3_PIN):
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
_prev_state = {p: 1 for p in (KEY1_PIN, KEY2_PIN)}

# ---------------------------------------------------------
# 4) Locate USB keyboard (non-fatal)
# ---------------------------------------------------------

def find_keyboard():
    """Return the first evdev device with EV_KEY, or None."""
    if not HAS_EVDEV:
        return None
    try:
        for path in list_devices():
            try:
                dev = InputDevice(path)
                if ecodes.EV_KEY in dev.capabilities():
                    return dev
            except Exception:
                pass
    except Exception:
        pass
    return None

keyboard = find_keyboard()
if keyboard is None:
    # Show a brief notice but keep going — WebUI / buttons still work
    pass

# ---------------------------------------------------------
# 5) Screen drawing
# ---------------------------------------------------------
scrollback: list[str] = []
current_line: str     = ""

def draw_buffer(lines: list[str], partial: str = "") -> None:
    img     = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d       = ImageDraw.Draw(img)
    visible = lines[-(ROWS - 1):] + [partial]
    y = 0
    for line in visible:
        d.text((0, y), line[:COLS], font=font, fill=(30, 132, 73))
        y += CHAR_H
    LCD.LCD_ShowImage(img, 0, 0)

# ---------------------------------------------------------
# 6) Spawn bash in PTY  +  set correct window size
# ---------------------------------------------------------
pid, master_fd = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["bash", "--login"])

# Parent — non-blocking reads
fcntl.fcntl(master_fd, fcntl.F_SETFL,
            fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

# Tell bash the real terminal dimensions so line-wrapping is correct
def _set_pty_size():
    try:
        winsize = struct.pack("HHHH", ROWS, COLS, WIDTH, HEIGHT)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass

_set_pty_size()

# ---------------------------------------------------------
# 7) Build poller
# ---------------------------------------------------------
poller = select.poll()
poller.register(master_fd, select.POLLIN)
if keyboard is not None:
    if hasattr(keyboard, "set_blocking"):
        keyboard.set_blocking(False)
    else:
        fcntl.fcntl(keyboard.fd, fcntl.F_SETFL, os.O_NONBLOCK)
    poller.register(keyboard.fd, select.POLLIN)

# ---------------------------------------------------------
# 8) Keycode maps
# ---------------------------------------------------------
SHIFT_KEYS = {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}
KEYMAP = {
    **{f"KEY_{c}": c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    "KEY_SPACE": " ", "KEY_ENTER": "\r", "KEY_KPENTER": "\r",
    "KEY_BACKSPACE": "\x7f", "KEY_TAB": "\t",
    "KEY_UP": "\x1b[A", "KEY_DOWN": "\x1b[B",
    "KEY_RIGHT": "\x1b[C", "KEY_LEFT": "\x1b[D",
    "KEY_MINUS": "-", "KEY_EQUAL": "=",
    "KEY_LEFTBRACE": "[", "KEY_RIGHTBRACE": "]",
    "KEY_BACKSLASH": "\\", "KEY_SEMICOLON": ";",
    "KEY_APOSTROPHE": "'", "KEY_GRAVE": "`",
    "KEY_COMMA": ",", "KEY_DOT": ".", "KEY_SLASH": "/",
    **{f"KEY_{i}": str(i) for i in range(10)},
}
SHIFT_MAP = {
    **{f"KEY_{c}": c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    "KEY_1": "!", "KEY_2": "@", "KEY_3": "#", "KEY_4": "$", "KEY_5": "%",
    "KEY_6": "^", "KEY_7": "&", "KEY_8": "*", "KEY_9": "(", "KEY_0": ")",
    "KEY_MINUS": "_", "KEY_EQUAL": "+",
    "KEY_LEFTBRACE": "{", "KEY_RIGHTBRACE": "}",
    "KEY_BACKSLASH": "|", "KEY_SEMICOLON": ":",
    "KEY_APOSTROPHE": '"', "KEY_GRAVE": "~",
    "KEY_COMMA": "<", "KEY_DOT": ">", "KEY_SLASH": "?",
}

# Comprehensive ANSI / VT escape stripper:
#   · CSI sequences:  ESC [ ... final-byte  (including ? prefix)
#   · OSC sequences:  ESC ] ... BEL or ST
#   · DCS/PM/APC:     ESC P/X/^ ... ST
#   · Single-char:    ESC followed by any non-[ character
ansi_escape = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z@`]'   # CSI
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC
    r'|[PX^][^\x1b]*\x1b\\'   # DCS / PM / APC
    r'|[^[\]]'                 # single-char (ESC = ESC > etc.)
    r')'
)

# ---------------------------------------------------------
# 9) Shell output processor
# ---------------------------------------------------------

def process_shell_output():
    global current_line, scrollback
    try:
        data = os.read(master_fd, 2048).decode(errors="replace")
    except (BlockingIOError, OSError):
        return
    if not data:
        return
    clean = ansi_escape.sub("", data)
    for ch in clean:
        if ch == "\n":
            scrollback.append(current_line)
            current_line = ""
        elif ch == "\r":
            # CR without LF → move to start of line (overwrite prompt)
            current_line = ""
        elif ch in ("\x08", "\x7f"):
            current_line = current_line[:-1]
        elif ch == "\x00" or ord(ch) < 32:
            pass  # skip other control chars
        else:
            current_line += ch
            while len(current_line) > COLS:
                scrollback.append(current_line[:COLS])
                current_line = current_line[COLS:]
    if len(scrollback) > 512:
        scrollback = scrollback[-512:]
    draw_buffer(scrollback, current_line)

# ---------------------------------------------------------
# 10) Key handler
# ---------------------------------------------------------
shift   = False
running = True

def write_byte(s: str):
    try:
        os.write(master_fd, s.encode())
    except OSError:
        pass

def handle_key(event):
    global shift, running
    key_name = event.keycode if isinstance(event.keycode, str) else event.keycode[0]
    if key_name in SHIFT_KEYS:
        shift = (event.keystate == event.key_down)
        return
    if event.keystate != event.key_down:
        return
    if key_name == "KEY_ESC":
        running = False
        return
    # Ctrl combos
    if key_name.startswith("KEY_") and len(key_name) == 5:
        letter = key_name[4]
        try:
            from evdev import ecodes as _ec
            if _ec.keys.get(event.scancode) and \
               (event.keystate == event.key_down):
                pass
        except Exception:
            pass
    char = SHIFT_MAP.get(key_name) if shift else KEYMAP.get(key_name)
    if char is not None:
        write_byte(char)

# ---------------------------------------------------------
# 11) Main loop
# ---------------------------------------------------------
if keyboard is None:
    draw_buffer([], "No keyboard found")
    time.sleep(1.5)

draw_buffer([], "Shell ready  KEY3=quit")

try:
    while running:
        for fd, event_mask in poller.poll(50):
            if fd == master_fd:
                process_shell_output()
            elif keyboard is not None and fd == keyboard.fd:
                try:
                    for ev in keyboard.read():
                        if ev.type == ecodes.EV_KEY:
                            handle_key(categorize(ev))
                except OSError:
                    # Keyboard unplugged
                    poller.unregister(keyboard.fd)
                    keyboard = None

        virtual = get_virtual_button()

        # HAT zoom buttons
        for pin, delta in ((KEY1_PIN, +1), (KEY2_PIN, -1)):
            state = GPIO.input(pin)
            if _prev_state[pin] == 1 and state == 0:
                set_font(FONT_SIZE + delta)
                _set_pty_size()
                draw_buffer(scrollback, current_line)
                time.sleep(0.15)
            _prev_state[pin] = state
        if virtual in ("KEY1", "KEY2"):
            delta = 1 if virtual == "KEY1" else -1
            set_font(FONT_SIZE + delta)
            _set_pty_size()
            draw_buffer(scrollback, current_line)

        # Quit
        if GPIO.input(KEY3_PIN) == 0 or virtual == "KEY3":
            running = False

except Exception as exc:
    draw_buffer([], f"ERR: {exc}"[:COLS])
    time.sleep(2)
finally:
    LCD.LCD_Clear()
    GPIO.cleanup()
    try:
        os.close(master_fd)
    except Exception:
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
