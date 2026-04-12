#!/usr/bin/env python3
"""
KTOX_Pi Payload -- Game Boy Emulator (Controller Enabled)
-----------------------------------------------------------
Play Game Boy / Game Boy Color ROMs on the LCD using PyBoy.

+ Added:
- Bluetooth / USB controller support (8BitDo, Xbox, etc.)
- Works alongside GPIO + WebUI input

Controls:
  Joystick    : D-pad
  OK          : A
  KEY1        : B
  KEY2        : Start
  KEY3 (hold) : Exit
  KEY3 (tap)  : Select
"""

import os
import sys
import time
import signal
import select

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..", "..")))

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image
from payloads._display_helper import ScaledDraw, scaled_font
from payloads._input_helper import get_button, flush_input, get_held_buttons

# ── PyBoy ─────────────────────────────
try:
    from pyboy import PyBoy
    PYBOY_OK = True
except ImportError:
    PYBOY_OK = False

# ── Controller Support ────────────────
try:
    from evdev import InputDevice, ecodes, list_devices
    HAS_CONTROLLER = True
except ImportError:
    HAS_CONTROLLER = False

# ── GPIO ─────────────────────────────
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
for p in PINS.values():
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ── LCD ──────────────────────────────
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = LCD.width, LCD.height
font = scaled_font()

# ── Paths ────────────────────────────
ROMS_DIR = "/root/KTOx/roms"
ROM_EXTENSIONS = (".gb", ".gbc")

# ── Constants ────────────────────────
GB_W, GB_H = 160, 144
running = True

# ── Signals ──────────────────────────
def _sig(s, f):
    global running
    running = False

signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)

# ═════════════════════════════════════
# CONTROLLER
# ═════════════════════════════════════
def _find_controller():
    if not HAS_CONTROLLER:
        return None
    try:
        for path in list_devices():
            dev = InputDevice(path)
            name = dev.name.lower()
            if any(x in name for x in ["gamepad","controller","8bitdo","xbox"]):
                print(f"[+] Controller: {dev.name}")
                dev.grab()
                return dev
    except:
        pass
    return None

def _handle_controller_event(event, pyboy):
    if event.type != ecodes.EV_KEY:
        return

    key = event.code
    val = event.value

    def press(btn):
        pyboy.button_press(btn) if val else pyboy.button_release(btn)

    if key == ecodes.BTN_SOUTH: press("a")
    elif key == ecodes.BTN_EAST: press("b")
    elif key == ecodes.BTN_START: press("start")
    elif key == ecodes.BTN_SELECT: press("select")
    elif key == ecodes.KEY_UP: press("up")
    elif key == ecodes.KEY_DOWN: press("down")
    elif key == ecodes.KEY_LEFT: press("left")
    elif key == ecodes.KEY_RIGHT: press("right")

# ═════════════════════════════════════
# ROM BROWSER
# ═════════════════════════════════════
def _list_roms():
    os.makedirs(ROMS_DIR, exist_ok=True)
    return sorted([f for f in os.listdir(ROMS_DIR) if f.endswith(ROM_EXTENSIONS)])

def _draw_browser(roms, cursor, scroll):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ScaledDraw(img)

    d.text((2,2), "GAME BOY", font=font, fill=(0,255,0))

    for i in range(7):
        idx = scroll + i
        if idx >= len(roms): break
        y = 16 + i*14
        col = (0,255,0) if idx==cursor else (0,120,0)
        d.text((4,y), roms[idx][:18], font=font, fill=col)

    LCD.LCD_ShowImage(img,0,0)

def _rom_browser():
    roms = _list_roms()
    cursor = scroll = 0

    while running:
        _draw_browser(roms, cursor, scroll)
        btn = get_button(PINS, GPIO)

        if btn == "KEY3": return None
        elif btn == "UP": cursor = max(0,cursor-1)
        elif btn == "DOWN": cursor = min(len(roms)-1,cursor+1)
        elif btn == "OK" and roms:
            return os.path.join(ROMS_DIR, roms[cursor])

    return None

# ═════════════════════════════════════
# INPUT
# ═════════════════════════════════════
def _read_buttons():
    pressed = {}
    for n,p in PINS.items():
        if GPIO.input(p)==0:
            pressed[n]=True
    for b in get_held_buttons():
        pressed[b]=True
    return pressed

# ═════════════════════════════════════
# EMULATOR
# ═════════════════════════════════════
def _run_emulator(rom):
    controller = _find_controller()

    pyboy = PyBoy(rom, window="null", sound_emulated=False)

    GB_MAP = {
        "UP":"up","DOWN":"down","LEFT":"left","RIGHT":"right",
        "OK":"a","KEY1":"b","KEY2":"start"
    }

    while running:
        pressed = _read_buttons()

        if "KEY3" in pressed:
            break

        # GPIO input
        for rj, gb in GB_MAP.items():
            if rj in pressed:
                pyboy.button_press(gb)
            else:
                pyboy.button_release(gb)

        # Controller input
        if controller:
            r,_,_ = select.select([controller.fd],[],[],0)
            if r:
                for event in controller.read():
                    _handle_controller_event(event, pyboy)

        pyboy.tick()

        img = pyboy.screen.image.resize((WIDTH,HEIGHT))
        LCD.LCD_ShowImage(img,0,0)

    pyboy.stop(save=True)
    flush_input()

# ═════════════════════════════════════
# MAIN
# ═════════════════════════════════════
def main():
    if not PYBOY_OK:
        print("PyBoy not installed")
        return

    try:
        while running:
            rom = _rom_browser()
            if not rom:
                break
            _run_emulator(rom)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
