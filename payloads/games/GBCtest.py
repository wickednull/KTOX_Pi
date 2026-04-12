#!/usr/bin/env python3
import os
import sys
import time
import signal
import evdev
from evdev import ecodes

# ... [Existing sys.path and LCD imports] ...
import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config
from PIL import Image, ImageDraw, ImageFont
from payloads._display_helper import ScaledDraw, scaled_font
from payloads._input_helper import get_button, flush_input

try:
    from pyboy import PyBoy
    PYBOY_OK = True
except ImportError:
    PYBOY_OK = False

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
# Standard Mapping: RaspyJack -> Game Boy
GB_MAP = {"UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right", "OK": "a", "KEY1": "b", "KEY2": "start"}

# ═══════════════════════════════════════════════════════════════
# CONTROLLER MANAGER
# ═══════════════════════════════════════════════════════════════

class GamepadManager:
    def __init__(self):
        self.devices = []
        self.refresh_devices()
        # Map common Linux input codes to PyBoy buttons
        self.btn_map = {
            ecodes.BTN_SOUTH: "a",      # Xbox A / 8BitDo B
            ecodes.BTN_EAST: "b",       # Xbox B / 8BitDo A
            ecodes.BTN_START: "start",
            ecodes.BTN_SELECT: "select",
            ecodes.BTN_MODE: "select",   # Xbox Button
            # Some controllers map D-pad to keys instead of axes
            ecodes.KEY_UP: "up", ecodes.KEY_DOWN: "down",
            ecodes.KEY_LEFT: "left", ecodes.KEY_RIGHT: "right",
        }

    def refresh_devices(self):
        self.devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                name = dev.name.lower()
                # Target common controller strings
                if any(x in name for x in ["xbox", "8bitdo", "wireless controller", "gamepad"]):
                    self.devices.append(dev)
                    print(f"[+] Found Controller: {dev.name}")
            except: pass

    def handle_input(self, pyboy):
        for dev in self.devices:
            try:
                for event in dev.read():
                    if event.type == ecodes.EV_KEY:
                        gb_btn = self.btn_map.get(event.code)
                        if gb_btn:
                            if event.value == 1: pyboy.button_press(gb_btn)
                            elif event.value == 0: pyboy.button_release(gb_btn)
                    
                    elif event.type == ecodes.EV_ABS:
                        # D-Pad (Hat switches)
                        if event.code == ecodes.ABS_HAT0X: # Left/Right
                            if event.value == -1: pyboy.button_press("left")
                            elif event.value == 1: pyboy.button_press("right")
                            else: [pyboy.button_release(b) for b in ["left", "right"]]
                        elif event.code == ecodes.ABS_HAT0Y: # Up/Down
                            if event.value == -1: pyboy.button_press("up")
                            elif event.value == 1: pyboy.button_press("down")
                            else: [pyboy.button_release(b) for b in ["up", "down"]]
            except (BlockingIOError, OSError): pass

# ═══════════════════════════════════════════════════════════════
# EMULATOR ENGINE
# ═══════════════════════════════════════════════════════════════

def _run_emulator(rom_path):
    global running
    _draw_loading(rom_path)
    gp = GamepadManager()

    try:
        pyboy = PyBoy(rom_path, window="null", sound_emulated=False, log_level="ERROR")
    except Exception as e:
        # ... [Error display logic from your original script] ...
        return

    frame_count = 0
    RENDER_EVERY = 4 
    _canvas = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    
    # Calculate scaling for the 1.44" LCD
    _ratio = min(WIDTH / 160, HEIGHT / 144)
    _sw, _sh = int(160 * _ratio), int(144 * _ratio)
    _ox, _oy = (WIDTH - _sw) // 2, (HEIGHT - _sh) // 2

    try:
        while running:
            # 1. Check On-board Buttons (GPIO)
            pressed = _read_buttons_noblock()
            if "KEY3" in pressed: break # Exit
            
            for rj_btn, gb_btn in GB_MAP.items():
                if rj_btn in pressed: pyboy.button_press(gb_btn)
                else: pyboy.button_release(gb_btn)

            # 2. Check External Controllers (USB/BT)
            gp.handle_input(pyboy)

            # 3. Tick Emulator
            render_this = (frame_count % RENDER_EVERY == 0)
            pyboy.tick(count=1, render=render_this)
            
            if render_this:
                gb_img = pyboy.screen.image
                scaled = gb_img.resize((_sw, _sh), Image.NEAREST)
                _canvas.paste((0, 0, 0), (0, 0, WIDTH, HEIGHT))
                _canvas.paste(scaled, (_ox, _oy))
                LCD.LCD_ShowImage(_canvas, 0, 0)
            
            frame_count += 1
    finally:
        pyboy.stop(save=True)
        flush_input()

# ... [Rest of your main() and browser code remains the same] ...
