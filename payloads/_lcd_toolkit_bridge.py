#!/usr/bin/env python3
"""LCD toolkit bridge for interactive command-line payloads."""

import errno
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import threading
import time

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

from _darksec_keyboard import DarkSecKeyboard

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

ROTATION_MAPS = {
    90: {"UP": "LEFT", "DOWN": "RIGHT", "LEFT": "DOWN", "RIGHT": "UP"},
    180: {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"},
    270: {"UP": "RIGHT", "DOWN": "LEFT", "LEFT": "UP", "RIGHT": "DOWN"},
}

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

COLORS = {
    "BG": (6, 0, 0),
    "PANEL": (30, 0, 0),
    "HEADER": (95, 0, 0),
    "SELECT": (139, 0, 0),
    "ACCENT": (231, 76, 60),
    "TEXT": (242, 243, 244),
    "DIM": (113, 125, 126),
    "GOOD": (46, 204, 113),
    "WARN": (245, 176, 65),
}


def first_existing_dir(paths):
    """Return the first existing directory from *paths*, or the first path."""
    for path in paths:
        if os.path.isdir(path):
            return path
    return paths[0]


def load_rotation(config_path="/root/KTOx/gui_conf.json"):
    """Load the configured LCD rotation in degrees."""
    try:
        with open(config_path, encoding="utf-8") as fh:
            rotation = int(json.load(fh).get("rotation", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        rotation = 0
    return rotation if rotation in ROTATION_MAPS else 0


def rotate_button(name, rotation):
    """Translate a physical button name into the active screen orientation."""
    return ROTATION_MAPS.get(rotation, {}).get(name, name)


def rotated_gpio_pins(rotation):
    """Return GPIO pins keyed by logical direction for rotated keyboard input."""
    if rotation not in ROTATION_MAPS:
        return dict(PINS)
    logical = dict(PINS)
    for physical, mapped in ROTATION_MAPS[rotation].items():
        logical[mapped] = PINS[physical]
    return logical


def clean_output(text):
    """Make terminal output compact and readable on the LCD."""
    return ANSI_RE.sub("", text).replace("\x1b", "").replace("\r", "\n")


class LCDToolkitBridge:
    """Run an interactive CLI program with LCD quick commands and keyboard input."""

    def __init__(self, title, command, cwd, quick_commands, exit_patterns=None):
        self.title = title[:18]
        self.command = command
        self.cwd = cwd
        self.quick_commands = quick_commands
        self.exit_patterns = exit_patterns or ("0", "q", "quit", "exit")
        self.running = True
        self.proc = None
        self.pty_master = None
        self.lines = []
        self.selected = 0
        self.menu_top = 0
        self.mode = "menu"
        self.scroll = 0
        self.partial_line = ""
        self.lock = threading.Lock()
        self.rotation = load_rotation()
        self.keyboard_pins = rotated_gpio_pins(self.rotation)

        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self.lcd = LCD_1in44.LCD()
        self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        self.width = self.lcd.width
        self.height = self.lcd.height
        self.font = ImageFont.load_default()
        self.tiny = ImageFont.load_default()
        self.keyboard = DarkSecKeyboard(
            width=self.width,
            height=self.height,
            lcd=self.lcd,
            gpio_pins=self.keyboard_pins,
            gpio_module=GPIO,
            on_ctrl_c=self.send_interrupt,
        )

        self._last_state = {name: False for name in PINS}
        self._last_time = {name: 0.0 for name in PINS}
        self._refresh_button_state()

    def _refresh_button_state(self):
        """Prime edge-detection state from the currently held physical buttons."""
        for name, pin in PINS.items():
            self._last_state[name] = GPIO.input(pin) == 0

    def get_button(self):
        now = time.time()
        for name, pin in PINS.items():
            pressed = GPIO.input(pin) == 0
            if pressed and not self._last_state[name]:
                self._last_state[name] = True
                if now - self._last_time[name] >= 0.18:
                    self._last_time[name] = now
                    return rotate_button(name, self.rotation)
            elif not pressed and self._last_state[name]:
                self._last_state[name] = False
        return None

    def add_line(self, line):
        text = line.rstrip("\r\n")
        if not text:
            return
        with self.lock:
            self.lines.append(text)
            self.lines = self.lines[-200:]

    def send_text(self, text, echo=True):
        if not self.proc or self.proc.poll() is not None or self.pty_master is None:
            self.add_line("[not running]")
            return
        try:
            os.write(self.pty_master, text.encode())
            if echo:
                self.add_line(f"> {text.rstrip()}")
        except OSError:
            self.add_line("[stdin closed]")

    def send_interrupt(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            self.add_line("^C")

    def draw(self, footer=None):
        img = Image.new("RGB", (self.width, self.height), COLORS["BG"])
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, self.width, 13), fill=COLORS["HEADER"])
        status = "RUN" if self.proc and self.proc.poll() is None else "DONE"
        status_color = COLORS["GOOD"] if status == "RUN" else COLORS["WARN"]
        draw.text((3, 2), self.title, font=self.tiny, fill=COLORS["TEXT"])
        draw.text((104, 2), status, font=self.tiny, fill=status_color)

        if self.mode == "output":
            self._draw_output(draw)
            footer = footer or "K2=Menu K1=Keys K3=Exit"
        else:
            self._draw_menu(draw)
            footer = footer or "OK=Send K1=Keys K2=Out"

        draw.rectangle((0, self.height - 11, self.width, self.height), fill=COLORS["PANEL"])
        draw.text((2, self.height - 10), footer[:21], font=self.tiny, fill=COLORS["DIM"])
        self.lcd.LCD_ShowImage(img, 0, 0)

    def _visible_menu_rows(self):
        """Return how many quick-command rows fit above the status tail."""
        return 7

    def _ensure_selected_visible(self):
        """Keep the quick-command viewport aligned with the selected item."""
        total = len(self.quick_commands)
        if total <= 0:
            self.selected = 0
            self.menu_top = 0
            return
        visible = self._visible_menu_rows()
        self.selected %= total
        max_top = max(0, total - visible)
        if self.selected < self.menu_top:
            self.menu_top = self.selected
        elif self.selected >= self.menu_top + visible:
            self.menu_top = self.selected - visible + 1
        self.menu_top = min(max(0, self.menu_top), max_top)

    def _move_selection(self, delta):
        """Move through every quick command while keeping the viewport in sync."""
        if not self.quick_commands:
            return
        self.selected = (self.selected + delta) % len(self.quick_commands)
        self._ensure_selected_visible()

    def _draw_menu(self, draw):
        self._ensure_selected_visible()
        visible = self._visible_menu_rows()
        total = len(self.quick_commands)
        start = self.menu_top
        end = min(total, start + visible)
        y = 16
        for idx in range(start, end):
            label, _value = self.quick_commands[idx]
            selected = idx == self.selected
            if selected:
                draw.rectangle((1, y - 1, self.width - 2, y + 10), fill=COLORS["SELECT"])
            marker = "> " if selected else "  "
            draw.text((3, y), marker + label[:17], font=self.font,
                      fill=COLORS["TEXT"] if selected else COLORS["DIM"])
            y += 12

        if total > visible:
            if start > 0:
                draw.text((116, 15), "^", font=self.tiny, fill=COLORS["ACCENT"])
            if end < total:
                draw.text((116, 90), "v", font=self.tiny, fill=COLORS["ACCENT"])
            counter = f"{self.selected + 1}/{total}"
            draw.text((self.width - 6 * len(counter) - 2, 101), counter,
                      font=self.tiny, fill=COLORS["DIM"])

        with self.lock:
            tail = self.lines[-2:]
        y = 101
        for line in tail:
            draw.text((3, y), line[:16], font=self.tiny, fill=COLORS["ACCENT"])
            y += 8

    def _draw_output(self, draw):
        with self.lock:
            lines = list(self.lines)
        visible = 9
        max_scroll = max(0, len(lines) - visible)
        self.scroll = min(self.scroll, max_scroll)
        start = max(0, len(lines) - visible - self.scroll)
        y = 16
        for line in lines[start:start + visible]:
            draw.text((2, y), line[:21], font=self.tiny, fill=COLORS["TEXT"])
            y += 10

    def open_keyboard(self):
        try:
            text = self.keyboard.run()
            if text is not None:
                self.send_text(text + "\n")
        finally:
            self._refresh_button_state()
            self.mode = "menu"

    def activate_selected(self):
        _label, value = self.quick_commands[self.selected]
        if value == "__keyboard__":
            self.open_keyboard()
        elif value == "__ctrl_c__":
            self.send_interrupt()
        else:
            self.send_text(value + "\n")

    def start_process(self):
        if not os.path.isdir(self.cwd):
            self.add_line(f"Missing: {self.cwd}")
            return False
        self.add_line("Starting toolkit...")
        master_fd, slave_fd = pty.openpty()
        try:
            self.proc = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "xterm"},
            )
        except OSError as exc:
            os.close(master_fd)
            self.add_line(f"Start failed: {exc.strerror or exc}")
            return False
        finally:
            os.close(slave_fd)
        self.pty_master = master_fd
        threading.Thread(target=self._read_output, daemon=True).start()
        return True

    def _append_output_text(self, text):
        text = clean_output(text)
        parts = text.split("\n")
        for part in parts[:-1]:
            combined = self.partial_line + part
            if self.partial_line:
                with self.lock:
                    if self.lines and self.lines[-1].startswith("…"):
                        self.lines.pop()
            self.partial_line = ""
            self.add_line(combined)
        if parts[-1]:
            self.partial_line += parts[-1]
            with self.lock:
                if self.lines and self.lines[-1].startswith("…"):
                    self.lines[-1] = "…" + self.partial_line
                else:
                    self.lines.append("…" + self.partial_line)
                    self.lines = self.lines[-200:]

    def _read_output(self):
        while self.running and self.proc and self.pty_master is not None:
            try:
                ready, _, _ = select.select([self.pty_master], [], [], 0.1)
                if not ready:
                    if self.proc.poll() is not None:
                        break
                    continue
                chunk = os.read(self.pty_master, 4096)
                if not chunk:
                    break
                self._append_output_text(chunk.decode(errors="replace"))
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                raise
        if self.partial_line:
            line = self.partial_line
            with self.lock:
                if self.lines and self.lines[-1].startswith("…"):
                    self.lines.pop()
            self.partial_line = ""
            self.add_line(line)
        if self.proc:
            self.add_line(f"[exit {self.proc.poll()}]")

    def stop(self):
        self.running = False
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.pty_master is not None:
            try:
                os.close(self.pty_master)
            except OSError:
                pass
            self.pty_master = None
        try:
            self.lcd.LCD_Clear()
        finally:
            GPIO.cleanup()

    def run(self):
        signal.signal(signal.SIGTERM, lambda _s, _f: self.stop())
        signal.signal(signal.SIGINT, lambda _s, _f: self.stop())
        if not self.start_process():
            self.mode = "output"
            self.draw("Startup failed")
            time.sleep(2)
            self.stop()
            return 1
        exit_code = 0
        try:
            while self.running:
                self.draw()
                btn = self.get_button()
                if btn == "KEY3":
                    break
                if btn == "KEY1":
                    self.open_keyboard()
                elif btn == "KEY2":
                    self.mode = "output" if self.mode == "menu" else "menu"
                elif self.mode == "output":
                    if btn == "UP":
                        self.scroll += 1
                    elif btn == "DOWN":
                        self.scroll = max(0, self.scroll - 1)
                    elif btn == "OK":
                        self.mode = "menu"
                else:
                    if btn == "UP":
                        self._move_selection(-1)
                    elif btn == "DOWN":
                        self._move_selection(1)
                    elif btn == "LEFT":
                        self.mode = "output"
                    elif btn == "RIGHT":
                        self.open_keyboard()
                    elif btn == "OK":
                        self.activate_selected()
                if self.proc and self.proc.poll() is not None:
                    self.mode = "output"
                    self.draw("Process exited")
                    exit_code = self.proc.returncode or 0
                    time.sleep(2)
                    break
                time.sleep(0.05)
        finally:
            self.stop()
        return exit_code
