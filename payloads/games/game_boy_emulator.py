#!/usr/bin/env python3
"""
KTOx Payload -- Game Boy / Game Boy Color Emulator
----------------------------------------------------
Play .gb and .gbc ROMs on the LCD using PyBoy 2.x.

Place ROM files in /root/KTOx/roms/

Controls:
  UP / DOWN / LEFT / RIGHT  — D-pad
  OK                        — A button
  KEY1                      — B button
  KEY2                      — Start
  KEY3 tap  (<0.6s)         — Select
  KEY3 hold (>0.6s)         — Exit to menu

Requires: pip3 install pyboy  (piwheels pre-built wheel on Pi OS)
"""

import os
import sys
import time
import signal
import logging

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..", "..")))

import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config
from PIL import Image, ImageDraw, ImageFont
from payloads._display_helper import ScaledDraw, scaled_font
from payloads._input_helper import get_button, flush_input

# Suppress PyBoy's verbose startup output
logging.getLogger("pyboy").setLevel(logging.ERROR)

try:
    from pyboy import PyBoy
    PYBOY_OK = True
except ImportError:
    PYBOY_OK = False

# ── Hardware ──────────────────────────────────────────────────────────────────
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for _p in PINS.values():
    GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = LCD.width, LCD.height
font = scaled_font()

# ── Constants ─────────────────────────────────────────────────────────────────
ROMS_DIR       = "/root/KTOx/roms"
ROM_EXTENSIONS = (".gb", ".gbc")
GB_W, GB_H     = 160, 144          # Game Boy native resolution
GB_FPS         = 59.73             # Game Boy clock (frames per second)
FRAME_TIME     = 1.0 / GB_FPS      # ~16.74 ms per frame
RENDER_EVERY   = 3                  # Push 1 in 3 frames to LCD (~20 FPS)
KEY3_HOLD_S    = 0.6               # Hold KEY3 longer than this to exit

# KTOX colour palette
_BG     = (10,  0,   0)
_HDR    = (139, 0,   0)
_BLOOD  = (192, 57,  43)
_EMBER  = (231, 76,  60)
_WHITE  = (242, 243, 244)
_ASH    = (171, 178, 185)
_STEEL  = (113, 125, 126)
_DIM    = (86,  101, 115)
_RUST   = (146, 43,  33)
_YELLOW = (212, 172, 13)
_GOOD   = (30,  132, 73)
_FOOTER = (34,  0,   0)

running = True


def _sig(s, f):
    global running
    running = False


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


# ── Shared drawing helpers ────────────────────────────────────────────────────

def _base_img(title="GAME BOY"):
    """Return a new image with the standard KTOX header already drawn."""
    img = Image.new("RGB", (WIDTH, HEIGHT), _BG)
    d   = ScaledDraw(img)
    d.rectangle((0, 0, 127, 12), fill=_HDR)
    d.text((64, 6), title, font=font, fill=_BLOOD, anchor="mm")
    return img, d


def _show_error(headline, detail="", hint="KEY3 = Back"):
    img, d = _base_img()
    d.text((64, 38), headline, font=font, fill=_EMBER,  anchor="mm")
    if detail:
        d.text((4,  58), detail[:22],   font=font, fill=_ASH)
        d.text((4,  72), detail[22:44], font=font, fill=_STEEL)
    d.rectangle((0, 117, 127, 127), fill=_FOOTER)
    d.text((64, 122), hint, font=font, fill=_DIM, anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)


# ══════════════════════════════════════════════════════════════════════════════
# ROM BROWSER
# ══════════════════════════════════════════════════════════════════════════════

def _list_roms():
    os.makedirs(ROMS_DIR, exist_ok=True)
    return sorted(
        n for n in os.listdir(ROMS_DIR)
        if n.lower().endswith(ROM_EXTENSIONS)
    )


def _draw_browser(roms, cursor, scroll):
    img, d = _base_img()
    d.text((80, 6), f"{len(roms)} ROMs", font=font, fill=_STEEL, anchor="lm")

    if not roms:
        d.text((4, 32), "No ROMs found!",       font=font, fill=_EMBER)
        d.text((4, 48), "Place .gb/.gbc files", font=font, fill=_STEEL)
        d.text((4, 62), "in /root/KTOx/roms/",  font=font, fill=_ASH)
    else:
        visible = 7
        for i in range(min(visible, len(roms) - scroll)):
            idx    = scroll + i
            y      = 16 + i * 14
            is_sel = idx == cursor

            if is_sel:
                d.rectangle((0, y - 1, 127, y + 11), fill=(60, 0, 0))
                d.rectangle((0, y - 1, 2,   y + 11), fill=_BLOOD)

            name    = roms[idx]
            display = os.path.splitext(name)[0][:18]
            d.text((5, y), display, font=font,
                   fill=_WHITE if is_sel else _ASH)

            if name.lower().endswith(".gbc"):
                d.text((114, y), "C", font=font, fill=_EMBER)

        # Scrollbar
        if len(roms) > visible:
            bar_h = max(5, int(100 * visible / len(roms)))
            bar_y = 16 + int((100 - bar_h) * scroll / max(1, len(roms) - visible))
            d.rectangle((125, bar_y, 127, bar_y + bar_h), fill=_RUST)

    d.rectangle((0, 117, 127, 127), fill=_FOOTER)
    d.text((2, 122), "OK=Play  K1=Refresh  K3=Exit", font=font, fill=_DIM)
    LCD.LCD_ShowImage(img, 0, 0)


def _rom_browser():
    """ROM picker. Returns full path or None."""
    roms   = _list_roms()
    cursor = 0
    scroll = 0

    while running:
        _draw_browser(roms, cursor, scroll)
        btn = get_button(PINS, GPIO)

        if btn == "KEY3":
            return None
        elif btn == "UP":
            cursor = max(0, cursor - 1)
            if cursor < scroll:
                scroll = cursor
        elif btn == "DOWN":
            if roms:
                cursor = min(len(roms) - 1, cursor + 1)
                if cursor >= scroll + 7:
                    scroll = cursor - 6
        elif btn == "OK" and roms:
            return os.path.join(ROMS_DIR, roms[cursor])
        elif btn == "KEY1":
            roms   = _list_roms()
            cursor = min(cursor, max(0, len(roms) - 1))
            scroll = 0

    return None


# ══════════════════════════════════════════════════════════════════════════════
# EMULATOR
# ══════════════════════════════════════════════════════════════════════════════

def _draw_loading(rom_name):
    img, d = _base_img()
    d.text((64, 40), "Loading...", font=font, fill=_BLOOD,  anchor="mm")
    name = os.path.splitext(os.path.basename(rom_name))[0][:16]
    d.text((64, 58), name,          font=font, fill=_WHITE,  anchor="mm")
    d.text((64, 78), "Please wait", font=font, fill=_DIM,    anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)


def _read_buttons_noblock():
    """Non-blocking: returns set of currently pressed button names."""
    pressed = set()
    for name, pin in PINS.items():
        if GPIO.input(pin) == 0:
            pressed.add(name)
    try:
        from payloads._input_helper import get_held_buttons
        pressed.update(get_held_buttons())
    except Exception:
        pass
    return pressed


def _run_emulator(rom_path):
    global running

    # Local import so auto-install during this session is visible
    try:
        from pyboy import PyBoy
    except ImportError as exc:
        _show_error("PyBoy import failed", str(exc)[:44])
        while running:
            if get_button(PINS, GPIO) == "KEY3":
                return
        return

    _draw_loading(rom_path)

    # PyBoy 2.x constructor — no sound_emulated / log_level kwargs
    try:
        pyboy = PyBoy(rom_path, window="null")
    except Exception as exc:
        _show_error("ROM load failed", str(exc)[:44])
        while running:
            if get_button(PINS, GPIO) == "KEY3":
                return
        return

    # Pre-compute scaling geometry once
    ratio    = min(WIDTH / GB_W, HEIGHT / GB_H)
    sw, sh   = int(GB_W * ratio), int(GB_H * ratio)
    ox, oy   = (WIDTH - sw) // 2, (HEIGHT - sh) // 2
    resample = Image.NEAREST if ratio >= 1.0 else Image.LANCZOS
    canvas   = Image.new("RGB", (WIDTH, HEIGHT), _BG)
    draw_bg  = ImageDraw.Draw(canvas)

    # Button map: KTOX button → PyBoy 2.x button string
    GB_MAP = {
        "UP":    "up",
        "DOWN":  "down",
        "LEFT":  "left",
        "RIGHT": "right",
        "OK":    "a",
        "KEY1":  "b",
        "KEY2":  "start",
    }

    frame_count   = 0
    key3_down_at  = None   # timestamp KEY3 was first pressed
    key3_was_held = False   # True once we've committed to exit

    try:
        while running:
            t0 = time.time()

            pressed = _read_buttons_noblock()

            # ── KEY3: tap = select, hold = exit ──────────────────────────────
            if "KEY3" in pressed:
                if key3_down_at is None:
                    key3_down_at = t0
                elif t0 - key3_down_at >= KEY3_HOLD_S and not key3_was_held:
                    key3_was_held = True
                    break                     # exit emulator
            else:
                if key3_down_at is not None and not key3_was_held:
                    # Short tap — fire select
                    pyboy.button("select")
                key3_down_at  = None
                key3_was_held = False

            # ── D-pad + face buttons ──────────────────────────────────────────
            for rj, gb in GB_MAP.items():
                if rj in pressed:
                    pyboy.button_press(gb)
                else:
                    pyboy.button_release(gb)

            # ── Tick emulator (PyBoy 2.x returns True while running) ──────────
            render_this = (frame_count % RENDER_EVERY == 0)
            still_going = pyboy.tick(1, render_this)
            frame_count += 1

            if not still_going:
                break   # ROM signalled end (e.g. power-off opcode)

            # ── Push frame to LCD ─────────────────────────────────────────────
            if render_this:
                gb_img = pyboy.screen.image.copy()   # copy before next tick overwrites buffer
                scaled = gb_img.resize((sw, sh), resample)
                if ox or oy:                         # clear letterbox bars
                    draw_bg.rectangle((0, 0, WIDTH, HEIGHT), fill=_BG)
                canvas.paste(scaled, (ox, oy))
                LCD.LCD_ShowImage(canvas, 0, 0)

            # ── Frame-rate cap (~59.73 fps) ───────────────────────────────────
            elapsed = time.time() - t0
            if elapsed < FRAME_TIME:
                time.sleep(FRAME_TIME - elapsed)

    finally:
        try:
            pyboy.stop()          # PyBoy 2.x: stop() saves by default
        except Exception:
            pass
        flush_input()
        time.sleep(0.4)
        flush_input()


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-INSTALL
# ══════════════════════════════════════════════════════════════════════════════

def _auto_install():
    """Show install screen and run install_pyboy.sh."""
    import subprocess

    _here          = os.path.abspath(os.path.join(__file__, "..", "..", ".."))
    install_script = os.path.join(_here, "scripts", "install_pyboy.sh")
    if not os.path.isfile(install_script):
        install_script = "/root/KTOx/scripts/install_pyboy.sh"

    img, d = _base_img()
    d.text((64, 30), "PyBoy not found",   font=font, fill=_YELLOW, anchor="mm")
    d.text((64, 48), "Auto-installing…",  font=font, fill=_BLOOD,  anchor="mm")
    d.text((64, 64), "May take 2-5 min",  font=font, fill=_DIM,    anchor="mm")
    d.text((64, 78), "on Pi Zero 2 W",    font=font, fill=_DIM,    anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)

    try:
        result = subprocess.run(
            ["sudo", "bash", install_script],
            capture_output=True, text=True, timeout=360,
        )
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or result.stdout).strip()[-80:] or "script failed"
            )

        verify = subprocess.run(
            ["python3", "-c", "from pyboy import PyBoy"],
            capture_output=True, timeout=15,
        )
        if verify.returncode != 0:
            raise RuntimeError("import check failed after install")

        img, d = _base_img()
        d.text((64, 50), "Installed OK!",  font=font, fill=_GOOD,  anchor="mm")
        d.text((64, 68), "Loading…",       font=font, fill=_DIM,   anchor="mm")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(1.5)
        return True

    except subprocess.TimeoutExpired:
        err = "Timed out (>6 min)"
    except Exception as exc:
        err = str(exc)[-44:]

    img, d = _base_img()
    d.text((64, 26), "Install failed",       font=font, fill=_EMBER, anchor="mm")
    d.text((4,  42), err[:22],               font=font, fill=_ASH)
    d.text((4,  55), err[22:44],             font=font, fill=_STEEL)
    d.text((4,  72), "Run manually:",         font=font, fill=_STEEL)
    d.text((4,  84), "sudo bash scripts/",   font=font, fill=_ASH)
    d.text((4,  96), "install_pyboy.sh",     font=font, fill=_ASH)
    d.rectangle((0, 117, 127, 127), fill=_FOOTER)
    d.text((64, 122), "KEY3 = Back",         font=font, fill=_DIM, anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)

    while True:
        if get_button(PINS, GPIO) == "KEY3":
            break
    return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global PYBOY_OK

    if not PYBOY_OK:
        if not _auto_install():
            GPIO.cleanup()
            return 0
        try:
            from pyboy import PyBoy  # confirm importable in this process
            PYBOY_OK = True
        except ImportError:
            GPIO.cleanup()
            return 0

    try:
        while running:
            rom = _rom_browser()
            if rom is None:
                break
            _run_emulator(rom)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
