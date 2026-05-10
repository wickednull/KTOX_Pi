#!/usr/bin/env python3
"""LCD command bridge for interactive command-line payload toolkits."""

import os
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


class LCDCliBridge:
    """Run an interactive CLI program with LCD quick commands and keyboard input."""

    def __init__(self, title, command, cwd, quick_commands, exit_patterns=None):
        self.title = title[:18]
        self.command = command
        self.cwd = cwd
        self.quick_commands = quick_commands
        self.exit_patterns = exit_patterns or ("0", "q", "quit", "exit")
        self.running = True
        self.proc = None
        self.lines = []
        self.selected = 0
        self.mode = "menu"
        self.scroll = 0
        self.lock = threading.Lock()

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
            gpio_pins=PINS,
            gpio_module=GPIO,
            on_ctrl_c=self.send_interrupt,
        )

        self._last_state = {name: False for name in PINS}
        self._last_time = {name: 0.0 for name in PINS}

    def get_button(self):
        now = time.time()
        for name, pin in PINS.items():
            pressed = GPIO.input(pin) == 0
            if pressed and not self._last_state[name]:
                self._last_state[name] = True
                if now - self._last_time[name] >= 0.18:
                    self._last_time[name] = now
                    return name
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
        if not self.proc or self.proc.poll() is not None or self.proc.stdin is None:
            self.add_line("[not running]")
            return
        try:
            self.proc.stdin.write(text)
            self.proc.stdin.flush()
            if echo:
                self.add_line(f"> {text.rstrip()}")
        except BrokenPipeError:
            self.add_line("[stdin closed]")

    def send_interrupt(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
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

    def _draw_menu(self, draw):
        visible = 7
        start = min(max(0, self.selected - visible + 1), max(0, len(self.quick_commands) - visible))
        y = 16
        for idx in range(start, min(len(self.quick_commands), start + visible)):
            label, _value = self.quick_commands[idx]
            selected = idx == self.selected
            if selected:
                draw.rectangle((1, y - 1, self.width - 2, y + 10), fill=COLORS["SELECT"])
            draw.text((3, y), ("> " if selected else "  ") + label[:17], font=self.font,
                      fill=COLORS["TEXT"] if selected else COLORS["DIM"])
            y += 12

        with self.lock:
            tail = self.lines[-2:]
        y = 101
        for line in tail:
            draw.text((3, y), line[:20], font=self.tiny, fill=COLORS["ACCENT"])
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
        text = self.keyboard.run()
        if text is not None:
            self.send_text(text + "\n")
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
        self.proc = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        threading.Thread(target=self._read_output, daemon=True).start()
        return True

    def _read_output(self):
        while self.running and self.proc and self.proc.stdout:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            self.add_line(line)
        if self.proc:
            self.add_line(f"[exit {self.proc.poll()}]")

    def stop(self):
        self.running = False
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            self.lcd.LCD_Clear()
        finally:
            GPIO.cleanup()

    def run(self):
        signal.signal(signal.SIGTERM, lambda _s, _f: self.stop())
        signal.signal(signal.SIGINT, lambda _s, _f: self.stop())
        self.start_process()
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
                        self.selected = (self.selected - 1) % len(self.quick_commands)
                    elif btn == "DOWN":
                        self.selected = (self.selected + 1) % len(self.quick_commands)
                    elif btn == "LEFT":
                        self.mode = "output"
                    elif btn == "RIGHT":
                        self.open_keyboard()
                    elif btn == "OK":
                        self.activate_selected()
                if self.proc and self.proc.poll() is not None:
                    self.mode = "output"
                time.sleep(0.05)
        finally:
            self.stop()
        return 0
