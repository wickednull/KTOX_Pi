#!/usr/bin/env python3
# NAME: DarkSec Micro Shell

"""
DarkSec KTOx Micro Shell – v3.0
Interactive /bin/bash PTY on 1.44" LCD.
USB keyboard + on‑screen keyboard + GPIO buttons.
"""

import os, sys, time, signal, select, fcntl, pty, re, struct, termios
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))

import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont

try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

from payloads._input_helper import get_virtual_button
import LCD_1in44, LCD_Config

# ----------------------------------------------------------------------
# 1) Persistent LCD
# ----------------------------------------------------------------------
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
image = Image.new("RGB", (WIDTH, HEIGHT), "#1a0000")
draw  = ImageDraw.Draw(image)

def flush():
    LCD.LCD_ShowImage(image, 0, 0)

# ----------------------------------------------------------------------
# 2) Font management
# ----------------------------------------------------------------------
FONT_MIN, FONT_MAX = 6, 10
FONT_SIZE = 8
font = None
CHAR_W = CHAR_H = COLS = ROWS = 0

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

def set_font(size: int):
    global FONT_SIZE, font, CHAR_W, CHAR_H, COLS, ROWS
    FONT_SIZE = max(FONT_MIN, min(FONT_MAX, size))
    font = load_font(FONT_SIZE)
    # measure character size
    test_img = Image.new("RGB", (10, 10))
    test_draw = ImageDraw.Draw(test_img)
    try:
        bbox = test_draw.textbbox((0, 0), "M", font=font)
        CHAR_W = bbox[2] - bbox[0]
        CHAR_H = bbox[3] - bbox[1]
    except AttributeError:
        CHAR_W, CHAR_H = test_draw.textsize("M", font=font)
    CHAR_W = max(CHAR_W, 1)
    CHAR_H = max(CHAR_H, 1)
    COLS = WIDTH // CHAR_W
    ROWS = HEIGHT // CHAR_H

set_font(FONT_SIZE)

# ----------------------------------------------------------------------
# 3) GPIO keys (with debounce)
# ----------------------------------------------------------------------
KEY1_PIN, KEY2_PIN, KEY3_PIN = 21, 20, 16
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for p in (KEY1_PIN, KEY2_PIN, KEY3_PIN):
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
_prev_state = {p: 1 for p in (KEY1_PIN, KEY2_PIN)}

# ----------------------------------------------------------------------
# 4) USB keyboard detection (non‑blocking)
# ----------------------------------------------------------------------
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
    new_kbd = find_keyboard()
    if new_kbd is None and keyboard is not None:
        # keyboard unplugged
        poller.unregister(keyboard.fd)
        keyboard = None
    elif new_kbd is not None and keyboard is None:
        keyboard = new_kbd
        poller.register(keyboard.fd, select.POLLIN)

# ----------------------------------------------------------------------
# 5) PTY bash spawn + window size
# ----------------------------------------------------------------------
pid, master_fd = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["bash", "--login"])

fcntl.fcntl(master_fd, fcntl.F_SETFL,
            fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

def _set_pty_size():
    try:
        winsize = struct.pack("HHHH", ROWS, COLS, WIDTH, HEIGHT)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass
_set_pty_size()

# ----------------------------------------------------------------------
# 6) Poller
# ----------------------------------------------------------------------
poller = select.poll()
poller.register(master_fd, select.POLLIN)

# ----------------------------------------------------------------------
# 7) ANSI escape stripper
# ----------------------------------------------------------------------
ansi_escape = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z@`]'          # CSI (incl. ?-prefix)
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)' # OSC
    r'|[PX^][^\x1b]*\x1b\\'          # DCS / PM / APC
    r'|[^[\]]'                       # single-char escapes
    r')'
)

# ----------------------------------------------------------------------
# 8) Screen buffer
# ----------------------------------------------------------------------
scrollback: list[str] = []
current_line: str = ""

def draw_buffer(lines: list, partial: str = "", keyboard_mode: str = ""):
    draw.rectangle((0,0,WIDTH,HEIGHT), fill="#1a0000")
    # status bar (top line)
    status = f"{keyboard_mode} Z{FONT_SIZE} "
    draw.text((2, 2), status, font=load_font(8), fill="#ffaa00")
    # visible lines
    visible = lines[-(ROWS - 2):] + [partial]
    y = 12
    for line in visible:
        draw.text((2, y), line[:COLS], font=font, fill=(231, 76, 60))
        y += CHAR_H
    flush()

# ----------------------------------------------------------------------
# 9) Write to PTY
# ----------------------------------------------------------------------
def write_byte(s: str):
    try:
        os.write(master_fd, s.encode())
    except OSError:
        pass

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
            current_line = ""          # CR resets line (prompt overwrite)
        elif ch in ("\x08", "\x7f"):
            current_line = current_line[:-1]
        elif ord(ch) < 32:
            pass
        else:
            current_line += ch
            while len(current_line) > COLS:
                scrollback.append(current_line[:COLS])
                current_line = current_line[COLS:]
    if len(scrollback) > 512:
        scrollback = scrollback[-512:]

# ----------------------------------------------------------------------
# 10) USB keyboard handler
# ----------------------------------------------------------------------
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

shift = False

def handle_usb_key(event):
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
    char = SHIFT_MAP.get(key_name) if shift else KEYMAP.get(key_name)
    if char:
        write_byte(char)

# ----------------------------------------------------------------------
# 11) On‑screen keyboard (virtual)
# ----------------------------------------------------------------------
VKB_LAYOUT = [
    ['`','1','2','3','4','5','6','7','8','9','0','-','='],
    ['q','w','e','r','t','y','u','i','o','p','[',']','\\'],
    ['a','s','d','f','g','h','j','k','l',';','\'','←','⌫'],
    ['z','x','c','v','b','n','m',',','.','/','SPC','ENT'],
    ['SHIFT','CTRL','ALT','MODE','↑','↓','←','→','OK','ESC']
]
# Simplified for small screen – we'll use a compact version
VKB_SIMPLE = [
    ['q','w','e','r','t','y','u','i','o','p'],
    ['a','s','d','f','g','h','j','k','l','←'],
    ['z','x','c','v','b','n','m','SPC','ENT','⌫'],
    ['↑','↓','←','→','OK','ESC']
]

vkb_active = (keyboard is None)  # start with on-screen if no USB keyboard
vkb_row, vkb_col = 0, 0

def draw_vkb():
    draw.rectangle((0,0,WIDTH,HEIGHT), fill="#1a0000")
    y = 4
    for r, row in enumerate(VKB_SIMPLE):
        x = 2
        for c, key in enumerate(row):
            if r == vkb_row and c == vkb_col:
                draw.rectangle((x-1, y-1, x+11, y+11), fill="#8B0000")
                draw.text((x, y), key, font=load_font(8), fill="#fff")
            else:
                draw.text((x, y), key, font=load_font(8), fill="#c8c8c8")
            x += 13
        y += 13
    flush()

def vkb_input():
    """Return a string entered via virtual keyboard, or None if cancelled."""
    global vkb_row, vkb_col
    vkb_row, vkb_col = 0, 0
    result = ""
    while True:
        draw_vkb()
        btn = get_virtual_button() or _wait_gpio()
        if btn == "UP": vkb_row = max(0, vkb_row-1)
        elif btn == "DOWN": vkb_row = min(len(VKB_SIMPLE)-1, vkb_row+1)
        elif btn == "LEFT": vkb_col = max(0, vkb_col-1)
        elif btn == "RIGHT": vkb_col = min(len(VKB_SIMPLE[vkb_row])-1, vkb_col+1)
        elif btn == "OK":
            key = VKB_SIMPLE[vkb_row][vkb_col]
            if key == '←': result = result[:-1]
            elif key == '⌫': result = ""
            elif key == 'SPC': result += ' '
            elif key == 'ENT':
                write_byte(result + "\r")
                return True
            elif key == 'ESC':
                return False
            elif key in ('↑','↓','←','→','OK'):
                pass  # navigation keys do nothing here
            else:
                result += key
        elif btn == "KEY2":  # back / cancel
            return False
        elif btn == "KEY3":
            return False

def _wait_gpio():
    """Wait for GPIO button press (non‑blocking poll)."""
    for name, pin in [("UP",6),("DOWN",19),("LEFT",5),("RIGHT",26),("OK",13),
                      ("KEY1",21),("KEY2",20),("KEY3",16)]:
        if GPIO.input(pin) == 0:
            time.sleep(0.05)
            return name
    return None

# ----------------------------------------------------------------------
# 12) Main loop
# ----------------------------------------------------------------------
running = True
last_vkb_toggle = 0

def toggle_vkb():
    global vkb_active, keyboard
    vkb_active = not vkb_active
    if vkb_active:
        # temporarily ignore USB keyboard
        if keyboard:
            poller.unregister(keyboard.fd)
    else:
        refresh_keyboard()
        if keyboard:
            poller.register(keyboard.fd, select.POLLIN)
    draw_buffer(scrollback, current_line, "VKB" if vkb_active else "USB")

# initial welcome
draw_buffer([], "KTOx Shell+  KEY3=quit", "USB" if keyboard else "VKB")
time.sleep(1.5)

try:
    while running:
        # refresh keyboard hotplug
        if not vkb_active:
            refresh_keyboard()

        # poll PTY and keyboard (if any)
        events = poller.poll(50)
        for fd, _ in events:
            if fd == master_fd:
                process_shell_output()
                draw_buffer(scrollback, current_line, "VKB" if vkb_active else "USB")
            elif keyboard is not None and fd == keyboard.fd:
                try:
                    for ev in keyboard.read():
                        if ev.type == ecodes.EV_KEY:
                            handle_usb_key(categorize(ev))
                except OSError:
                    # keyboard disappeared
                    poller.unregister(keyboard.fd)
                    keyboard = None
                    vkb_active = True
                    draw_buffer(scrollback, current_line, "VKB")

        # GPIO buttons (zoom, quit, toggle VKB)
        # Zoom
        for pin, delta in ((KEY1_PIN, +1), (KEY2_PIN, -1)):
            state = GPIO.input(pin)
            if _prev_state[pin] == 1 and state == 0:
                set_font(FONT_SIZE + delta)
                _set_pty_size()
                draw_buffer(scrollback, current_line, "VKB" if vkb_active else "USB")
                time.sleep(0.15)
            _prev_state[pin] = state

        # Virtual buttons from WebUI
        virt = get_virtual_button()
        if virt == "KEY1":
            set_font(FONT_SIZE + 1)
            _set_pty_size()
            draw_buffer(scrollback, current_line, "VKB" if vkb_active else "USB")
        elif virt == "KEY2":
            set_font(FONT_SIZE - 1)
            _set_pty_size()
            draw_buffer(scrollback, current_line, "VKB" if vkb_active else "USB")
        elif virt == "KEY3":
            running = False

        # Toggle on‑screen keyboard: long press KEY1+KEY2 (1 second)
        if GPIO.input(KEY1_PIN) == 0 and GPIO.input(KEY2_PIN) == 0:
            if time.time() - last_vkb_toggle > 1.0:
                toggle_vkb()
                last_vkb_toggle = time.time()

        # If VKB active and no USB keyboard, handle VKB input when OK pressed
        if vkb_active and keyboard is None:
            # we need to capture OK press without interfering with shell
            # Use a non‑blocking check: if OK is pressed, launch VKB input
            if GPIO.input(13) == 0:  # OK pin
                time.sleep(0.05)
                if GPIO.input(13) == 0:  # debounce
                    vkb_input()
                    draw_buffer(scrollback, current_line, "VKB")
                    while GPIO.input(13) == 0:
                        time.sleep(0.01)

        # Quit on KEY3
        if GPIO.input(KEY3_PIN) == 0 or virt == "KEY3":
            running = False

except Exception as exc:
    draw_buffer([], f"ERR: {str(exc)[:COLS]}")
    time.sleep(2)
finally:
    LCD.LCD_Clear()
    GPIO.cleanup()
    try:
        os.close(master_fd)
    except:
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except:
        pass
