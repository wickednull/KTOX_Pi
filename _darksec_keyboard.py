#!/usr/bin/env python3
"""
Shell Plus Standard Virtual Keyboard Module.

This module is the shared keyboard implementation for LCD payloads and mirrors
the keyboard behavior used by `payloads/general/shell_plus.py`.

Usage:
    from _darksec_keyboard import DarkSecKeyboard
    kb = DarkSecKeyboard(width=128, height=128, lcd=LCD)
    result = kb.run()  # returns typed text or None
"""

import os
import sys
import time
import fcntl
import select

HAS_EVDEV = False
try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    HAS_EVDEV = True
except ImportError:
    pass

from PIL import Image, ImageDraw, ImageFont


# shell_plus.py-aligned color palette
COLORS = {
    "BG": "#0a0000",
    "FG": (171, 178, 185),
    "DIM": (113, 125, 126),
    "ACCENT": (231, 76, 60),
    "PANEL": (34, 0, 0),
    "HILITE": (139, 0, 0),
    "WHITE": (255, 255, 255),
}


class DarkSecKeyboard:
    """Virtual keyboard with USB fallback and command history."""

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

    def __init__(
        self,
        width=128,
        height=128,
        lcd=None,
        gpio_pins=None,
        gpio_module=None,
        on_ctrl_c=None,
    ):
        """
        Initialize keyboard.

        Args:
            width: Display width (default 128)
            height: Display height (default 128)
            lcd: LCD display object (if available)
            gpio_pins: Dict of button pins (UP, DOWN, LEFT, RIGHT, OK, KEY1, KEY2, KEY3)
            gpio_module: RPi.GPIO module (if available)
            on_ctrl_c: optional callback invoked for C-C tool key
        """
        self.width = width
        self.height = height
        self.lcd = lcd
        self.gpio_pins = gpio_pins or {}
        self.GPIO = gpio_module
        self.on_ctrl_c = on_ctrl_c

        # Font setup
        self.font_size = 8
        self.font = self._load_font(self.font_size)
        self.ui_font = self._load_font(8)
        self.tiny_font = self._load_font(7)

        # Keyboard state
        self.page = 0
        self.row = -1
        self.col = 0
        self.history = []
        self.history_idx = None
        self.usb_keyboard = None
        self.shift = False
        self.ctrl = False

        # Input state
        self._last_press_time = {}
        self._last_pressed_state = {}
        for name in self.gpio_pins.keys():
            self._last_press_time[name] = 0.0
            self._last_pressed_state[name] = False

        if HAS_EVDEV:
            self.usb_keyboard = self._find_keyboard()

    def _load_font(self, size):
        """Load TrueType font with fallback."""
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

    def _find_keyboard(self):
        """Find first USB keyboard device."""
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

    def _get_gpio_action(self, timeout=0.12):
        """Check GPIO buttons and return pressed button name or None."""
        if not self.GPIO:
            return None

        now = time.time()
        for name, pin in self.gpio_pins.items():
            pressed = (self.GPIO.input(pin) == 0)

            if pressed and not self._last_pressed_state.get(name, False):
                self._last_pressed_state[name] = True
                min_gap = 0.18
                if now - self._last_press_time.get(name, 0) >= min_gap:
                    self._last_press_time[name] = now
                    return name
            elif not pressed and self._last_pressed_state.get(name, False):
                self._last_pressed_state[name] = False

        return None

    def _current_kb(self):
        """Get current keyboard page."""
        return self.KB_PAGES[self.page]

    def _normalize_cursor(self):
        """Ensure cursor is within bounds of current row."""
        if self.row >= 0:
            row = self._current_kb()[self.row]
            self.col = min(self.col, len(row) - 1)

    def _add_history(self, cmd):
        """Add command to history."""
        cmd = cmd.strip()
        if not cmd:
            return
        if not self.history or self.history[-1] != cmd:
            self.history.append(cmd)
        if len(self.history) > 60:
            self.history = self.history[-60:]

    def _history_prev(self, current_compose):
        """Get previous history item."""
        if not self.history:
            return current_compose
        if self.history_idx is None:
            self.history_idx = len(self.history) - 1
        else:
            self.history_idx = max(0, self.history_idx - 1)
        return self.history[self.history_idx]

    def _history_next(self, current_compose):
        """Get next history item."""
        if not self.history:
            return current_compose
        if self.history_idx is None:
            return current_compose
        self.history_idx += 1
        if self.history_idx >= len(self.history):
            self.history_idx = None
            return ""
        return self.history[self.history_idx]

    def _draw_keyboard(self, compose):
        """Draw on-screen keyboard."""
        if not self.lcd:
            return

        image = Image.new("RGB", (self.width, self.height), COLORS["BG"])
        draw = ImageDraw.Draw(image)

        # Header
        draw.rectangle((0, 0, self.width, 12), fill=COLORS["PANEL"])
        draw.text((2, 2), f"VKB {self.KB_PAGE_NAMES[self.page]}",
                  font=self.tiny_font, fill=COLORS["ACCENT"])
        draw.text((78, 2), "K2/K3 exit", font=self.tiny_font, fill=COLORS["DIM"])

        # Compose area
        comp_selected = (self.row == -1)
        draw.rounded_rectangle(
            (2, 14, self.width - 3, 32),
            radius=2,
            outline=COLORS["ACCENT"] if comp_selected else COLORS["HILITE"],
            fill=COLORS["HILITE"] if comp_selected else "#220000"
        )
        preview = compose[-18:] if compose else "_"
        draw.text((4, 19), preview, font=self.ui_font, fill=COLORS["WHITE"])
        if self.history_idx is not None and self.history:
            draw.text((self.width - 24, 19), "H", font=self.ui_font, fill=COLORS["ACCENT"])

        # Keyboard
        kb = self._current_kb()
        top = 36
        row_h = 18

        for r, row in enumerate(kb):
            gap = 2
            x = 2
            y1 = top + r * row_h
            y2 = y1 + 15

            for c, key in enumerate(row):
                selected = (r == self.row and c == self.col)

                if len(key) <= 2:
                    w = 11
                elif len(key) == 3:
                    w = 16
                else:
                    w = 22

                draw.rounded_rectangle(
                    (x, y1, x + w, y2),
                    radius=2,
                    fill=COLORS["HILITE"] if selected else COLORS["PANEL"],
                    outline=COLORS["ACCENT"] if selected else COLORS["DIM"]
                )

                # Abbreviate labels
                label = {
                    "SPC": "SP", "TAB": "TB", "ENT": "OK", "ESC": "EX",
                    "CLR": "CL", "ABC": "AB", "abc": "ab", "SYM": "#+"
                }.get(key, key)

                try:
                    bbox = draw.textbbox((0, 0), label, font=self.tiny_font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                except Exception:
                    tw, th = 8, 8

                tx = x + max(1, (w - tw) // 2)
                ty = y1 + max(0, (15 - th) // 2 - 1)
                draw.text((tx, ty), label, font=self.tiny_font,
                          fill=COLORS["WHITE"] if selected else COLORS["FG"])

                x += w + gap

        # Footer
        draw.rectangle((0, self.height - 12, self.width, self.height), fill=COLORS["PANEL"])
        draw.text((2, self.height - 10), "U/D hist  OK key",
                  font=self.tiny_font, fill=COLORS["DIM"])

        self.lcd.LCD_ShowImage(image, 0, 0)

    def _apply_key(self, compose, key):
        """Apply keyboard key press to composition."""
        self.history_idx = None

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
            if callable(self.on_ctrl_c):
                self.on_ctrl_c()
            return "", False

        # Page switches
        if key == "ABC":
            self.page = 1
            return compose, False
        if key == "abc":
            self.page = 0
            return compose, False
        if key == "SYM":
            self.page = 2
            return compose, False
        if key == "TOOL":
            self.page = 3
            return compose, False

        # Command shortcuts
        token = key
        if key in ("ls", "cd", "pwd", "cat", "grep", "echo"):
            token = key + " "
        elif key in ("|", ">", ">>", "&&"):
            token = " " + key + " "
        elif key == "-la":
            token = " -la"

        return compose + token, False

    def run(self):
        """Run the keyboard and return typed text or None."""
        compose = ""
        self.page = 0
        self.row = -1
        self.col = 0
        self.history_idx = None

        # Prime button state to handle case where button is already pressed
        if self.GPIO:
            for name, pin in self.gpio_pins.items():
                self._last_pressed_state[name] = (self.GPIO.input(pin) == 0)

        while True:
            self._normalize_cursor()
            self._draw_keyboard(compose)

            btn = self._get_gpio_action(0.15)
            if btn is None and self.usb_keyboard:
                # USB keyboard handling would go here
                pass

            if btn is None:
                time.sleep(0.01)
                continue

            if btn == "UP":
                if self.row == -1:
                    compose = self._history_prev(compose)
                else:
                    self.row = max(-1, self.row - 1)
                    self._normalize_cursor()

            elif btn == "DOWN":
                if self.row == -1:
                    if self.history_idx is not None:
                        compose = self._history_next(compose)
                    else:
                        self.row = 0
                        self._normalize_cursor()
                else:
                    self.row = min(len(self._current_kb()) - 1, self.row + 1)
                    self._normalize_cursor()

            elif btn == "LEFT":
                if self.row >= 0:
                    self.col = max(0, self.col - 1)

            elif btn == "RIGHT":
                if self.row >= 0:
                    self.col = min(len(self._current_kb()[self.row]) - 1, self.col + 1)

            elif btn == "OK":
                if self.row == -1:
                    return compose
                key = self._current_kb()[self.row][self.col]
                compose, done = self._apply_key(compose, key)
                if compose is None:
                    return None
                if done:
                    if compose.strip():
                        self._add_history(compose)
                    return compose

            elif btn in ("KEY2", "KEY3"):
                return None
