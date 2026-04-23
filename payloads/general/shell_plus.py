#!/usr/bin/env python3
# NAME: DarkSec Micro Shell

import os, sys, time, signal, select, fcntl, pty, re, struct, termios
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont

try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

from payloads._input_helper import get_virtual_button
import LCD_1in44, LCD_Config

# ------------------------------------------------------------
# Persistent LCD
# ------------------------------------------------------------
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
image = Image.new("RGB", (WIDTH, HEIGHT), "#1a0000")
draw = ImageDraw.Draw(image)

def flush():
    LCD.LCD_ShowImage(image, 0, 0)

# ------------------------------------------------------------
# Font
# ------------------------------------------------------------
FONT_MIN, FONT_MAX = 6, 10
FONT_SIZE = 8
font = None
CHAR_W = CHAR_H = COLS = ROWS = 0

def load_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                pass
    return ImageFont.load_default()

def set_font(size):
    global FONT_SIZE, font, CHAR_W, CHAR_H, COLS, ROWS
    FONT_SIZE = max(FONT_MIN, min(FONT_MAX, size))
    font = load_font(FONT_SIZE)
    test_img = Image.new("RGB", (10,10))
    test_draw = ImageDraw.Draw(test_img)
    try:
        bbox = test_draw.textbbox((0,0), "M", font=font)
        CHAR_W, CHAR_H = bbox[2]-bbox[0], bbox[3]-bbox[1]
    except:
        CHAR_W, CHAR_H = test_draw.textsize("M", font=font)
    CHAR_W = max(CHAR_W, 1)
    CHAR_H = max(CHAR_H, 1)
    COLS = WIDTH // CHAR_W
    ROWS = HEIGHT // CHAR_H

set_font(FONT_SIZE)

# ------------------------------------------------------------
# GPIO
# ------------------------------------------------------------
KEY1_PIN, KEY2_PIN, KEY3_PIN = 21, 20, 16
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for p in (KEY1_PIN, KEY2_PIN, KEY3_PIN):
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ------------------------------------------------------------
# USB keyboard detection
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
            except:
                pass
    except:
        pass
    return None

def refresh_keyboard():
    global keyboard
    new = find_keyboard()
    if new and keyboard is None:
        keyboard = new
        poller.register(keyboard.fd, select.POLLIN)
    elif not new and keyboard is not None:
        poller.unregister(keyboard.fd)
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
        winsize = struct.pack("HHHH", ROWS, COLS, WIDTH, HEIGHT)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except:
        pass
set_pty_size()

# ------------------------------------------------------------
# Poller
# ------------------------------------------------------------
poller = select.poll()
poller.register(master_fd, select.POLLIN)
refresh_keyboard()  # initial

# ------------------------------------------------------------
# ANSI stripper
# ------------------------------------------------------------
ansi_escape = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z@`]'
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'
    r'|[PX^][^\x1b]*\x1b\\'
    r'|[^[\]]'
    r')'
)

# ------------------------------------------------------------
# Screen buffer
# ------------------------------------------------------------
scrollback = []
current_line = ""

def draw_buffer(lines, partial="", mode=""):
    draw.rectangle((0,0,WIDTH,HEIGHT), fill="#1a0000")
    # status line
    status = f"{mode} Z{FONT_SIZE}"
    draw.text((2,2), status, font=load_font(8), fill="#ffaa00")
    visible = lines[-(ROWS-2):] + [partial]
    y = 12
    for line in visible:
        draw.text((2, y), line[:COLS], font=font, fill=(231,76,60))
        y += CHAR_H
    flush()

def process_output():
    global current_line, scrollback
    try:
        data = os.read(master_fd, 2048).decode(errors="replace")
    except:
        return
    if not data:
        return
    clean = ansi_escape.sub("", data)
    for ch in clean:
        if ch == '\n':
            scrollback.append(current_line)
            current_line = ""
        elif ch == '\r':
            current_line = ""
        elif ch in ('\x08','\x7f'):
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

def write_pty(s):
    try:
        os.write(master_fd, s.encode())
    except:
        pass

# ------------------------------------------------------------
# USB keyboard handler
# ------------------------------------------------------------
SHIFT_KEYS = {"KEY_LEFTSHIFT","KEY_RIGHTSHIFT"}
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
        write_pty(char)

# ------------------------------------------------------------
# On‑screen keyboard (simple, reliable)
# ------------------------------------------------------------
VKB_KEYS = [
    ['q','w','e','r','t','y','u','i','o','p'],
    ['a','s','d','f','g','h','j','k','l','←'],
    ['z','x','c','v','b','n','m',' ',',','.'],
    ['SPC','ENT','ESC']
]

vkb_row, vkb_col = 0, 0

def draw_vkb():
    draw.rectangle((0,0,WIDTH,HEIGHT), fill="#1a0000")
    y = 4
    for r, row in enumerate(VKB_KEYS):
        x = 4
        for c, key in enumerate(row):
            if r == vkb_row and c == vkb_col:
                draw.rectangle((x-1, y-1, x+11, y+11), fill="#8B0000")
                draw.text((x, y), key, font=load_font(8), fill="#fff")
            else:
                draw.text((x, y), key, font=load_font(8), fill="#c8c8c8")
            x += 13
        y += 13
    flush()

def run_vkb():
    """Modal virtual keyboard – returns string entered (or None on ESC)."""
    global vkb_row, vkb_col
    vkb_row, vkb_col = 0, 0
    result = ""
    while True:
        draw_vkb()
        btn = None
        # check GPIO buttons
        for name, pin in [("UP",6),("DOWN",19),("LEFT",5),("RIGHT",26),("OK",13),("KEY2",20),("KEY3",16)]:
            if GPIO.input(pin) == 0:
                btn = name
                time.sleep(0.05)
                break
        if btn is None:
            time.sleep(0.05)
            continue
        if btn == "UP": vkb_row = max(0, vkb_row-1)
        elif btn == "DOWN": vkb_row = min(len(VKB_KEYS)-1, vkb_row+1)
        elif btn == "LEFT": vkb_col = max(0, vkb_col-1)
        elif btn == "RIGHT": vkb_col = min(len(VKB_KEYS[vkb_row])-1, vkb_col+1)
        elif btn == "OK":
            key = VKB_KEYS[vkb_row][vkb_col]
            if key == '←':
                result = result[:-1]
            elif key == 'SPC':
                result += ' '
            elif key == 'ENT':
                return result
            elif key == 'ESC':
                return None
            else:
                result += key
        elif btn == "KEY2":  # cancel
            return None
        elif btn == "KEY3":  # cancel
            return None

# ------------------------------------------------------------
# Main loop
# ------------------------------------------------------------
running = True
vkb_mode = (keyboard is None)  # start with VKB if no USB keyboard
last_long_press = 0

draw_buffer([], "KTOx Shell   KEY3=quit", "VKB" if vkb_mode else "USB")
time.sleep(1)

try:
    while running:
        # Refresh keyboard hotplug
        if not vkb_mode:
            refresh_keyboard()
            if keyboard is None:
                vkb_mode = True
                draw_buffer(scrollback, current_line, "VKB")
        else:
            # if a USB keyboard appears while in VKB mode, switch automatically
            if find_keyboard() is not None:
                vkb_mode = False
                refresh_keyboard()
                draw_buffer(scrollback, current_line, "USB")

        # Poll PTY and USB keyboard
        events = poller.poll(50)
        for fd, _ in events:
            if fd == master_fd:
                process_output()
                draw_buffer(scrollback, current_line, "VKB" if vkb_mode else "USB")
            elif keyboard is not None and fd == keyboard.fd:
                try:
                    for ev in keyboard.read():
                        if ev.type == ecodes.EV_KEY:
                            handle_usb_key(categorize(ev))
                except OSError:
                    keyboard = None
                    vkb_mode = True
                    draw_buffer(scrollback, current_line, "VKB")

        # GPIO buttons: zoom, quit, toggle VKB (long press KEY1)
        # Zoom
        if GPIO.input(KEY1_PIN) == 0:
            if time.time() - last_long_press > 0.5:
                # short press? but we use long press for VKB toggle
                # We'll implement: short press = zoom in, long press (1s) = toggle VKB
                start = time.time()
                while GPIO.input(KEY1_PIN) == 0:
                    time.sleep(0.05)
                    if time.time() - start > 1.0:
                        # long press – toggle VKB
                        vkb_mode = not vkb_mode
                        draw_buffer(scrollback, current_line, "VKB" if vkb_mode else "USB")
                        # wait for release
                        while GPIO.input(KEY1_PIN) == 0:
                            time.sleep(0.01)
                        last_long_press = time.time()
                        break
                else:
                    # short press – zoom in
                    set_font(FONT_SIZE + 1)
                    set_pty_size()
                    draw_buffer(scrollback, current_line, "VKB" if vkb_mode else "USB")
                last_long_press = time.time()
        if GPIO.input(KEY2_PIN) == 0:
            set_font(FONT_SIZE - 1)
            set_pty_size()
            draw_buffer(scrollback, current_line, "VKB" if vkb_mode else "USB")
            time.sleep(0.2)

        # Virtual buttons from WebUI
        virt = get_virtual_button()
        if virt == "KEY1":
            set_font(FONT_SIZE + 1)
            set_pty_size()
            draw_buffer(scrollback, current_line, "VKB" if vkb_mode else "USB")
        elif virt == "KEY2":
            set_font(FONT_SIZE - 1)
            set_pty_size()
            draw_buffer(scrollback, current_line, "VKB" if vkb_mode else "USB")
        elif virt == "KEY3":
            running = False

        # On‑screen keyboard input (when VKB mode active)
        if vkb_mode and keyboard is None:
            # Check if OK button is pressed (without blocking shell)
            if GPIO.input(13) == 0:
                time.sleep(0.05)
                if GPIO.input(13) == 0:
                    # Launch VKB input modal
                    typed = run_vkb()
                    if typed is not None:
                        write_pty(typed + "\r")
                    # redraw shell screen
                    draw_buffer(scrollback, current_line, "VKB")
                    # wait for release
                    while GPIO.input(13) == 0:
                        time.sleep(0.01)

        # Quit on KEY3
        if GPIO.input(KEY3_PIN) == 0 or virt == "KEY3":
            running = False

except Exception as e:
    draw_buffer([], f"ERR: {str(e)[:COLS]}")
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
