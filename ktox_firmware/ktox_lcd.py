#!/usr/bin/env python3
# ktox_lcd.py — KTOx LCD Interface
# Waveshare 1.44" LCD HAT (ST7735S, 128x128, SPI)
# Raspberry Pi Zero 2W
#
# Display: 128x128 pixels, SPI
# Controls: 1x joystick (UP/DOWN/LEFT/RIGHT/CENTER), 3x buttons (KEY1/KEY2/KEY3)
#
# GPIO pin mapping (Waveshare 1.44" HAT):
#   LCD SPI:  MOSI=19, SCLK=23, CS=24, DC=25, RST=27, BL=24
#   Joystick: UP=6, DOWN=19, LEFT=5, RIGHT=26, CENTER=13
#   Keys:     KEY1=21, KEY2=20, KEY3=16
#
# Requires: pip3 install pillow spidev RPi.GPIO

import os
import sys
import time
import threading
import subprocess
import textwrap

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import spidev
    HAS_HARDWARE = True
except ImportError:
    HAS_HARDWARE = False
    print("[LCD] Hardware libs not found — running in headless/sim mode")

# ── GPIO Pin Definitions ──────────────────────────────────────────────────────

LCD_RST  = 27
LCD_DC   = 25
LCD_BL   = 24
LCD_CS   = 8    # CE0
LCD_MOSI = 10
LCD_SCLK = 11

JOY_UP    = 6
JOY_DOWN  = 19
JOY_LEFT  = 5
JOY_RIGHT = 26
JOY_CTR   = 13
KEY1      = 21
KEY2      = 20
KEY3      = 16

# ── Display Constants ─────────────────────────────────────────────────────────

LCD_W = 128
LCD_H = 128

# ── Colour palette ────────────────────────────────────────────────────────────

BLACK   = (0,   0,   0)
WHITE   = (240, 237, 232)
RED     = (192, 57,  43)
DARK_RED= (100, 20,  10)
RUST    = (123, 36,  28)
GREEN   = (30,  132, 73)
YELLOW  = (212, 172, 13)
ORANGE  = (202, 111, 30)
GRAY    = (60,  60,  60)
DIM     = (90,  90,  90)
BLUE    = (93,  173, 226)


# ══════════════════════════════════════════════════════════════════════════════
# ── ST7735S LCD Driver ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class ST7735:
    """Minimal ST7735S SPI driver for Waveshare 1.44" HAT."""

    def __init__(self):
        if not HAS_HARDWARE:
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(LCD_RST, GPIO.OUT)
        GPIO.setup(LCD_DC,  GPIO.OUT)
        GPIO.setup(LCD_BL,  GPIO.OUT)
        GPIO.output(LCD_BL, GPIO.HIGH)

        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 9000000
        self.spi.mode = 0

        self._reset()
        self._init_sequence()

    def _reset(self):
        GPIO.output(LCD_RST, GPIO.HIGH)
        time.sleep(0.1)
        GPIO.output(LCD_RST, GPIO.LOW)
        time.sleep(0.1)
        GPIO.output(LCD_RST, GPIO.HIGH)
        time.sleep(0.1)

    def _cmd(self, cmd):
        GPIO.output(LCD_DC, GPIO.LOW)
        self.spi.xfer2([cmd])

    def _data(self, data):
        GPIO.output(LCD_DC, GPIO.HIGH)
        if isinstance(data, int):
            self.spi.xfer2([data])
        else:
            for i in range(0, len(data), 4096):
                self.spi.xfer2(list(data[i:i+4096]))

    def _init_sequence(self):
        """ST7735S initialisation for Waveshare 1.44" 128x128."""
        self._cmd(0x01)  # SWRESET
        time.sleep(0.15)
        self._cmd(0x11)  # SLPOUT
        time.sleep(0.50)

        self._cmd(0xB1); self._data([0x01,0x2C,0x2D])
        self._cmd(0xB2); self._data([0x01,0x2C,0x2D])
        self._cmd(0xB3); self._data([0x01,0x2C,0x2D,0x01,0x2C,0x2D])
        self._cmd(0xB4); self._data([0x07])
        self._cmd(0xC0); self._data([0xA2,0x02,0x84])
        self._cmd(0xC1); self._data([0xC5])
        self._cmd(0xC2); self._data([0x0A,0x00])
        self._cmd(0xC3); self._data([0x8A,0x2A])
        self._cmd(0xC4); self._data([0x8A,0xEE])
        self._cmd(0xC5); self._data([0x0E])
        self._cmd(0x20)  # INVOFF
        self._cmd(0x36); self._data([0xC8])  # MADCTL — row/col order
        self._cmd(0x3A); self._data([0x05])  # COLMOD 16bit

        # Gamma
        self._cmd(0xE0)
        self._data([0x0f,0x1a,0x0f,0x18,0x2f,0x28,0x20,0x22,
                    0x1f,0x1b,0x23,0x37,0x00,0x07,0x02,0x10])
        self._cmd(0xE1)
        self._data([0x0f,0x1b,0x0f,0x17,0x33,0x2c,0x29,0x2e,
                    0x30,0x30,0x39,0x3f,0x00,0x07,0x03,0x10])

        self._cmd(0x2A); self._data([0x00,0x00,0x00,0x7F])
        self._cmd(0x2B); self._data([0x00,0x00,0x00,0x9F])
        self._cmd(0xF0); self._data([0x01])
        self._cmd(0xF6); self._data([0x00])
        self._cmd(0x13)  # NORON
        time.sleep(0.10)
        self._cmd(0x29)  # DISPON
        time.sleep(0.10)

    def display(self, image):
        """Push a 128x128 PIL image to the LCD."""
        if not HAS_HARDWARE:
            return
        self._cmd(0x2A); self._data([0x00,0x02,0x00,0x81])
        self._cmd(0x2B); self._data([0x00,0x01,0x00,0xA0])
        self._cmd(0x2C)

        img = image.convert("RGB")
        pixels = []
        for y in range(LCD_H):
            for x in range(LCD_W):
                r, g, b = img.getpixel((x, y))
                color = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                pixels.extend([color >> 8, color & 0xFF])
        self._data(bytes(pixels))

    def clear(self, color=BLACK):
        img = Image.new("RGB", (LCD_W, LCD_H), color)
        self.display(img)

    def backlight(self, on=True):
        if HAS_HARDWARE:
            GPIO.output(LCD_BL, GPIO.HIGH if on else GPIO.LOW)

    def cleanup(self):
        if HAS_HARDWARE:
            self.backlight(False)
            self.spi.close()
            GPIO.cleanup()


# ══════════════════════════════════════════════════════════════════════════════
# ── Button Handler ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class ButtonHandler:
    """
    Non-blocking GPIO button reader with debounce.
    Puts button events into a queue for the menu to consume.
    """

    BUTTONS = {
        "UP":    JOY_UP,
        "DOWN":  JOY_DOWN,
        "LEFT":  JOY_LEFT,
        "RIGHT": JOY_RIGHT,
        "CTR":   JOY_CTR,
        "KEY1":  KEY1,
        "KEY2":  KEY2,
        "KEY3":  KEY3,
    }

    def __init__(self):
        self._queue = []
        self._lock  = threading.Lock()
        if not HAS_HARDWARE:
            return
        # Pull-up all button pins
        for name, pin in self.BUTTONS.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                pin, GPIO.FALLING,
                callback=lambda ch, n=name: self._on_press(n),
                bouncetime=200
            )

    def _on_press(self, name):
        with self._lock:
            self._queue.append(name)

    def get(self):
        """Return next button press or None."""
        with self._lock:
            if self._queue:
                return self._queue.pop(0)
        return None

    def wait(self, timeout=None):
        """Block until a button is pressed. Returns button name."""
        start = time.time()
        while True:
            btn = self.get()
            if btn:
                return btn
            if timeout and (time.time() - start) > timeout:
                return None
            time.sleep(0.05)

    def sim_press(self, name):
        """Simulate a button press (for headless testing)."""
        with self._lock:
            self._queue.append(name)


# ══════════════════════════════════════════════════════════════════════════════
# ── LCD Menu Renderer ─────────────────────────────────────────────════════════
# ══════════════════════════════════════════════════════════════════════════════

class LCDMenu:
    """
    Renders menus on the 128x128 LCD.
    Uses a KTOx blood-red cyberpunk aesthetic adapted for tiny screen.
    """

    def __init__(self, lcd: ST7735):
        self.lcd = lcd
        # Try to load a small monospace font
        self._font_sm = self._load_font(9)
        self._font_md = self._load_font(11)
        self._font_lg = self._load_font(14)
        self._font_xl = self._load_font(18)

    def _load_font(self, size):
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ]
        from PIL import ImageFont as IF
        for p in paths:
            try:
                return IF.truetype(p, size)
            except:
                pass
        return IF.load_default()

    def _new_canvas(self, bg=BLACK):
        img = Image.new("RGB", (LCD_W, LCD_H), bg)
        d   = ImageDraw.Draw(img)
        return img, d

    def splash(self):
        """KTOx boot splash screen."""
        img, d = self._new_canvas(BLACK)

        # Red horizontal rule
        d.rectangle([0, 0, LCD_W, 2], fill=RED)
        d.rectangle([0, LCD_H-3, LCD_W, LCD_H], fill=RED)

        # ASCII logo (very small)
        lines = [
            "▐ KTOX ▌",
            "Network",
            "PenTest",
            "Suite",
        ]
        y = 22
        d.text((LCD_W//2 - 28, y), lines[0], font=self._font_lg, fill=RED)
        y += 20
        for line in lines[1:]:
            w = d.textlength(line, font=self._font_sm)
            d.text((LCD_W//2 - w//2, y), line, font=self._font_sm, fill=WHITE)
            y += 13

        d.text((4, LCD_H-16), "authorized", font=self._font_sm, fill=RUST)
        d.text((4, LCD_H-26), "eyes only", font=self._font_sm, fill=RUST)

        self.lcd.display(img)

    def menu(self, title, items, selected=0, status=""):
        """
        Render a scrollable menu.
        title    — header text
        items    — list of (label, icon_char) tuples
        selected — currently highlighted index
        status   — small status string bottom right
        """
        img, d = self._new_canvas(BLACK)

        # Header bar
        d.rectangle([0, 0, LCD_W, 16], fill=DARK_RED)
        d.text((3, 2), title[:16], font=self._font_sm, fill=WHITE)
        if status:
            sw = int(d.textlength(status, font=self._font_sm))
            d.text((LCD_W - sw - 2, 2), status, font=self._font_sm, fill=GREEN)

        # Rule under header
        d.rectangle([0, 16, LCD_W, 18], fill=RUST)

        # Menu items — show up to 6 items, scroll window around selected
        visible  = 6
        start    = max(0, min(selected - 2, len(items) - visible))
        end      = min(start + visible, len(items))
        y        = 20

        for i in range(start, end):
            label, icon = items[i]
            is_sel = (i == selected)

            if is_sel:
                d.rectangle([0, y-1, LCD_W, y+13], fill=RED)
                text_col = WHITE
            else:
                text_col = WHITE if (i % 2 == 0) else (200, 200, 200)

            # Index number
            d.text((2, y), f"{i+1:>2}", font=self._font_sm,
                   fill=YELLOW if is_sel else RUST)
            # Icon
            d.text((20, y), icon, font=self._font_sm, fill=text_col)
            # Label (truncated)
            d.text((32, y), label[:13], font=self._font_sm, fill=text_col)
            y += 15

        # Scroll indicator
        if len(items) > visible:
            pct = selected / max(1, len(items) - 1)
            bar_h = int((LCD_H - 20) * pct)
            d.rectangle([LCD_W-3, 20, LCD_W, LCD_H], fill=GRAY)
            d.rectangle([LCD_W-3, 20+bar_h-4, LCD_W, 20+bar_h+4], fill=RED)

        # Bottom hint bar
        d.rectangle([0, LCD_H-10, LCD_W, LCD_H], fill=GRAY)
        d.text((2, LCD_H-10), "↕nav ●sel ▸run", font=self._font_sm, fill=DIM)

        self.lcd.display(img)

    def confirm(self, title, message, yes_focused=True):
        """Yes/No confirmation dialog."""
        img, d = self._new_canvas(BLACK)
        d.rectangle([0, 0, LCD_W, 14], fill=DARK_RED)
        d.text((3, 2), title[:16], font=self._font_sm, fill=WHITE)
        d.rectangle([0, 14, LCD_W, 16], fill=RUST)

        # Word-wrap message
        lines = textwrap.wrap(message, 18)
        y = 20
        for line in lines[:4]:
            d.text((3, y), line, font=self._font_sm, fill=WHITE)
            y += 12

        # YES / NO buttons
        if yes_focused:
            d.rectangle([10, 96, 54, 112], fill=RED)
            d.rectangle([74, 96, 118, 112], fill=GRAY)
        else:
            d.rectangle([10, 96, 54, 112], fill=GRAY)
            d.rectangle([74, 96, 118, 112], fill=RED)

        d.text((20, 98), "YES", font=self._font_md, fill=WHITE)
        d.text((84, 98), "NO",  font=self._font_md, fill=WHITE)
        self.lcd.display(img)

    def running(self, title, status_lines=None, elapsed=0):
        """
        'Attack running' screen.
        Shows title, animated status, elapsed time, and KEY3=stop hint.
        """
        img, d = self._new_canvas(BLACK)
        d.rectangle([0, 0, LCD_W, 14], fill=DARK_RED)
        d.text((3, 2), title[:16], font=self._font_sm, fill=WHITE)
        d.rectangle([0, 14, LCD_W, 16], fill=RUST)

        # Animated pulse dot
        pulse = "●" if (elapsed % 2 == 0) else "○"
        d.text((LCD_W-12, 2), pulse, font=self._font_sm, fill=RED)

        y = 22
        if status_lines:
            for line in status_lines[:5]:
                col = GREEN if line.startswith("✔") else \
                      RED   if line.startswith("✖") else \
                      YELLOW if line.startswith("!") else WHITE
                d.text((3, y), line[:20], font=self._font_sm, fill=col)
                y += 12

        # Elapsed time
        d.text((3, LCD_H-22), f"Elapsed: {elapsed}s", font=self._font_sm, fill=DIM)

        # Stop hint
        d.rectangle([0, LCD_H-12, LCD_W, LCD_H], fill=GRAY)
        d.text((2, LCD_H-11), "KEY3=stop  KEY1=pause", font=self._font_sm, fill=WHITE)
        self.lcd.display(img)

    def result(self, title, lines, color=GREEN):
        """Show result / summary screen after an operation."""
        img, d = self._new_canvas(BLACK)
        d.rectangle([0, 0, LCD_W, 14], fill=DARK_RED)
        d.text((3, 2), title[:16], font=self._font_sm, fill=WHITE)
        d.rectangle([0, 14, LCD_W, 16], fill=RUST)

        y = 20
        for line in lines[:7]:
            col = GREEN  if line.startswith("+") else \
                  RED    if line.startswith("!") else \
                  YELLOW if line.startswith("~") else WHITE
            d.text((3, y), line[:20], font=self._font_sm, fill=col)
            y += 12

        d.rectangle([0, LCD_H-12, LCD_W, LCD_H], fill=GRAY)
        d.text((2, LCD_H-11), "CTR=back  KEY3=loot", font=self._font_sm, fill=DIM)
        self.lcd.display(img)

    def status_bar(self, iface="", gateway="", hosts=0, mode="READY"):
        """Persistent status overlay — shown on idle/home screen."""
        img, d = self._new_canvas(BLACK)
        d.rectangle([0, 0, LCD_W, 2], fill=RED)

        # Mode badge
        mode_col = GREEN if mode == "READY" else RED if "ATK" in mode else YELLOW
        d.rectangle([0, 4, LCD_W, 20], fill=DARK_RED)
        mw = int(d.textlength(mode, font=self._font_md))
        d.text((LCD_W//2 - mw//2, 4), mode, font=self._font_md, fill=mode_col)

        d.rectangle([0, 21, LCD_W, 23], fill=RUST)

        y = 28
        for label, val in [("IF:", iface[:14]), ("GW:", gateway[:14]),
                            ("HOSTS:", str(hosts))]:
            d.text((3, y), label, font=self._font_sm, fill=RUST)
            lw = int(d.textlength(label, font=self._font_sm))
            d.text((3 + lw + 4, y), val, font=self._font_sm, fill=WHITE)
            y += 13

        d.rectangle([0, LCD_H-2, LCD_W, LCD_H], fill=RED)
        self.lcd.display(img)

    def message(self, text, color=WHITE, duration=2):
        """Flash a brief full-screen message."""
        img, d = self._new_canvas(BLACK)
        lines = textwrap.wrap(text, 16)
        total = len(lines) * 14
        y = (LCD_H - total) // 2
        for line in lines:
            w = int(d.textlength(line, font=self._font_md))
            d.text((LCD_W//2 - w//2, y), line, font=self._font_md, fill=color)
            y += 14
        self.lcd.display(img)
        if duration:
            time.sleep(duration)
