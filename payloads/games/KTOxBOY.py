#!/usr/bin/env python3
"""
KTOx Payload – Game Boy / Game Boy Color Emulator
--------------------------------------------------
Play .gb and .gbc ROMs on the LCD using PyBoy 2.x.

Place ROM files in /root/KTOx/roms/

Controls:
  UP / DOWN / LEFT / RIGHT  – D-pad
  OK                        – A button
  KEY1                      – B button
  KEY2                      – Start
  KEY3 tap  (<0.6s)         – Select
  KEY3 hold (>0.6s)         – Exit to menu

Requires (Pi OS Bookworm / externally-managed env):
  pip install pyboy --extra-index-url https://www.piwheels.org/simple --break-system-packages
  OR: sudo bash scripts/install_pyboy.sh
"""

import os
import sys
import time
import signal
import logging
import traceback

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

# Setup logging to file for debugging
LOG_FILE = "/tmp/ktoxboy.log"
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

import LCD_1in44
import LCD_Config
from PIL import Image, ImageDraw, ImageFont
from _display_helper import ScaledDraw, scaled_font
from _input_helper import get_button, flush_input

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
if GPIO is not None:
    GPIO.setmode(GPIO.BCM)
    for _p in PINS.values():
        GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = LCD.width, LCD.height
font = scaled_font()
small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8) if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") else font

# ── Constants ─────────────────────────────────────────────────────────────────
ROMS_DIR       = "/root/KTOx/roms"
ROM_EXTENSIONS = (".gb", ".gbc")
GB_W, GB_H     = 160, 144
RENDER_EVERY   = 3                  # Push 1 in 3 frames to LCD (~20 FPS)
KEY3_HOLD_S    = 0.6

# KTOx colour palette (red/black)
_BG     = (10,  0,   0)    # very dark red-black
_HDR    = (139, 0,   0)    # dark red
_BLOOD  = (192, 57,  43)   # bright red
_EMBER  = (231, 76,  60)   # orange-red
_WHITE  = (242, 243, 244)
_ASH    = (171, 178, 185)  # light grey
_STEEL  = (113, 125, 126)  # medium grey
_DIM    = (86,  101, 115)  # dark grey
_RUST   = (146, 43,  33)   # rust red
_YELLOW = (212, 172, 13)
_GOOD   = (30,  132, 73)   # green
_FOOTER = (34,  0,   0)    # very dark footer

running = True


def _sig(s, f):
    global running
    running = False


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


# ── Drawing helpers ──────────────────────────────────────────────────────────
def _base_img(title="GAME BOY"):
    img = Image.new("RGB", (WIDTH, HEIGHT), _BG)
    d = ScaledDraw(img)
    # Header bar
    d.rectangle((0, 0, 127, 12), fill=_HDR)
    d.text((4, 1), title, font=font, fill=_BLOOD)
    return img, d


def _show_message(lines, footer="", timeout=0):
    img, d = _base_img()
    y = 20
    for line in lines[:6]:
        d.text((64, y), line, font=font, fill=_WHITE, anchor="mm")
        y += 12
    if footer:
        d.rectangle((0, 117, 127, 127), fill=_FOOTER)
        d.text((64, 122), footer, font=small_font, fill=_DIM, anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)
    if timeout:
        time.sleep(timeout)


# ══════════════════════════════════════════════════════════════════════════════
# ROM BROWSER
# ══════════════════════════════════════════════════════════════════════════════
def _list_roms():
    os.makedirs(ROMS_DIR, exist_ok=True)
    return sorted(n for n in os.listdir(ROMS_DIR) if n.lower().endswith(ROM_EXTENSIONS))


def _draw_browser(roms, cursor, scroll):
    img, d = _base_img("KTOx GAME BOY")
    # ROM count in top-right
    d.text((122, 1), f"{len(roms)}", font=small_font, fill=_STEEL, anchor="rt")

    if not roms:
        d.text((64, 32), "No ROMs found!", font=font, fill=_EMBER, anchor="mm")
        d.text((64, 48), "Place .gb/.gbc files", font=small_font, fill=_STEEL, anchor="mm")
        d.text((64, 62), "in /root/KTOx/roms/", font=small_font, fill=_ASH, anchor="mm")
    else:
        visible = 6          # show 6 ROMs at a time
        for i in range(min(visible, len(roms) - scroll)):
            idx = scroll + i
            y = 16 + i * 14
            is_sel = (idx == cursor)

            if is_sel:
                d.rectangle((0, y-1, 127, y+11), fill=(60, 0, 0))
                d.rectangle((0, y-1, 2, y+11), fill=_BLOOD)

            name = roms[idx]
            display = os.path.splitext(name)[0][:18]
            d.text((5, y), display, font=font, fill=_WHITE if is_sel else _ASH)

            if name.lower().endswith(".gbc"):
                d.text((115, y), "C", font=small_font, fill=_EMBER)

        # Scrollbar
        if len(roms) > visible:
            bar_h = max(5, int(100 * visible / len(roms)))
            bar_y = 16 + int((100 - bar_h) * scroll / max(1, len(roms) - visible))
            d.rectangle((125, bar_y, 127, bar_y+bar_h), fill=_RUST)

    d.rectangle((0, 117, 127, 127), fill=_FOOTER)
    d.text((4, 120), "OK=Play  K1=Refresh  K3=Exit", font=small_font, fill=_DIM)
    LCD.LCD_ShowImage(img, 0, 0)


def _rom_browser():
    roms = _list_roms()
    cursor = 0
    scroll = 0

    while running:
        try:
            _draw_browser(roms, cursor, scroll)
        except Exception as e:
            logger.error(f"Error drawing browser: {e}")
            logger.error(traceback.format_exc())
            continue

        try:
            btn = get_button(PINS, GPIO)
        except Exception as e:
            logger.error(f"Error getting button: {e}")
            logger.error(traceback.format_exc())
            btn = None

        if btn == "KEY3":
            return None
        elif btn == "UP":
            cursor = max(0, cursor-1)
            if cursor < scroll:
                scroll = cursor
        elif btn == "DOWN":
            if roms:
                cursor = min(len(roms)-1, cursor+1)
                if cursor >= scroll + 6:
                    scroll = cursor - 5
        elif btn == "OK" and roms:
            return os.path.join(ROMS_DIR, roms[cursor])
        elif btn == "KEY1":
            roms = _list_roms()
            cursor = min(cursor, max(0, len(roms)-1))
            scroll = 0


# ══════════════════════════════════════════════════════════════════════════════
# EMULATOR
# ══════════════════════════════════════════════════════════════════════════════
def _run_emulator(rom_path):
    global running

    # Show loading screen
    img, d = _base_img()
    d.text((64, 40), "Loading...", font=font, fill=_BLOOD, anchor="mm")
    name = os.path.splitext(os.path.basename(rom_path))[0][:16]
    d.text((64, 58), name, font=font, fill=_WHITE, anchor="mm")
    d.text((64, 78), "Please wait", font=small_font, fill=_DIM, anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)

    try:
        pyboy = PyBoy(rom_path, window="null")
    except Exception as e:
        _show_message(["Load Error!", str(e)[:22], str(e)[22:44]], footer="KEY3 = Back")
        while running:
            if get_button(PINS, GPIO) == "KEY3":
                return
        return

    # Scaling geometry
    ratio = min(WIDTH / GB_W, HEIGHT / GB_H)
    sw, sh = int(GB_W * ratio), int(GB_H * ratio)
    ox, oy = (WIDTH - sw) // 2, (HEIGHT - sh) // 2
    resample = Image.NEAREST if ratio >= 1.0 else Image.LANCZOS
    canvas = Image.new("RGB", (WIDTH, HEIGHT), _BG)
    draw_bg = ImageDraw.Draw(canvas)

    # Button mapping
    GB_MAP = {
        "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right",
        "OK": "a", "KEY1": "b", "KEY2": "start",
    }

    frame_count = 0
    key3_down_at = None
    key3_was_held = False

    try:
        while running:
            pressed = set()
            if GPIO is not None:
                for name, pin in PINS.items():
                    if GPIO.input(pin) == 0:
                        pressed.add(name)

            # KEY3 tap/hold logic
            if "KEY3" in pressed:
                if key3_down_at is None:
                    key3_down_at = time.time()
                elif not key3_was_held and (time.time() - key3_down_at) >= KEY3_HOLD_S:
                    key3_was_held = True
                    break
            else:
                if key3_down_at is not None and not key3_was_held:
                    pyboy.button_press("select")
                    pyboy.button_release("select")
                key3_down_at = None
                key3_was_held = False

            # D-pad and buttons
            for rj, gb in GB_MAP.items():
                if rj in pressed:
                    pyboy.button_press(gb)
                else:
                    pyboy.button_release(gb)

            # Tick emulator – render only every RENDER_EVERY frames
            render_this = (frame_count % RENDER_EVERY == 0)
            still_going = pyboy.tick(1, render_this)
            frame_count += 1

            if not still_going:
                break

            if render_this:
                gb_img = pyboy.screen.image
                scaled = gb_img.resize((sw, sh), resample)
                draw_bg.rectangle((0, 0, WIDTH, HEIGHT), fill=_BG)
                canvas.paste(scaled, (ox, oy))
                LCD.LCD_ShowImage(canvas, 0, 0)

            # Small delay to prevent 100% CPU (optional, not frame-rate capped)
            time.sleep(0.001)

    finally:
        try:
            pyboy.stop(save=True)
        except:
            pass
        flush_input()
        time.sleep(0.2)
        flush_input()
        if GPIO is not None:
            GPIO.cleanup()


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-INSTALL
# ══════════════════════════════════════════════════════════════════════════════
def _auto_install():
    import subprocess
    # Search for install script: beside the repo root first, then legacy paths
    _here = os.path.dirname(os.path.abspath(__file__))
    _repo_root = os.path.normpath(os.path.join(_here, "..", ".."))
    _script_rel = os.path.join(_repo_root, "scripts", "install_pyboy.sh")
    _candidates = [
        _script_rel,
        "/root/KTOx/scripts/install_pyboy.sh",
        "/root/Raspyjack/scripts/install_pyboy.sh",
    ]
    install_script = next((p for p in _candidates if os.path.isfile(p)), None)

    logger.info(f"PyBoy not found. Install script: {install_script}")
    _show_message(["PyBoy not found", "Auto-installing...", "May take 2-5 min", "on Pi Zero 2W"], footer="Please wait")
    try:
        if install_script:
            logger.info(f"Running install script: {install_script}")
            result = subprocess.run(
                ["sudo", "bash", install_script],
                capture_output=True, text=True, timeout=360,
            )
            if result.returncode != 0:
                err_msg = (result.stderr or result.stdout).strip()
                logger.error(f"Install script failed: {err_msg}")
                raise RuntimeError(err_msg[-80:])
        else:
            # Script not found — run the confirmed working pip command directly
            logger.info("No install script found, trying pip directly...")
            result = subprocess.run(
                ["pip", "install", "pyboy",
                 "--extra-index-url", "https://www.piwheels.org/simple",
                 "--break-system-packages"],
                capture_output=True, text=True, timeout=360,
            )
            if result.returncode != 0:
                logger.info("pip failed, trying python3 -m pip...")
                # Try python3 -m pip as fallback
                result = subprocess.run(
                    ["python3", "-m", "pip", "install", "pyboy",
                     "--extra-index-url", "https://www.piwheels.org/simple",
                     "--break-system-packages"],
                    capture_output=True, text=True, timeout=360,
                )
                if result.returncode != 0:
                    err_msg = (result.stderr or result.stdout).strip()
                    logger.error(f"pip install failed: {err_msg}")
                    raise RuntimeError(err_msg[-80:])
        logger.info("Verifying PyBoy installation...")
        subprocess.run(["python3", "-c", "from pyboy import PyBoy"], capture_output=True, timeout=15, check=True)
        logger.info("PyBoy installed successfully!")
        _show_message(["Installed OK!", "Loading..."], timeout=1.5)
        return True
    except Exception as e:
        logger.error(f"Auto-install failed: {e}")
        _show_message(
            ["Install failed", str(e)[:22],
             "Run manually:",
             "pip install pyboy",
             "--extra-index-url piwheels",
             "--break-system-packages"],
            footer="KEY3 = Back",
        )
        while True:
            if get_button(PINS, GPIO) == "KEY3":
                break
        return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    global PYBOY_OK

    logger.info(f"PYBOY_OK={PYBOY_OK}")

    if not PYBOY_OK:
        logger.info("PyBoy not available, attempting auto-install...")
        if not _auto_install():
            logger.error("Auto-install failed")
            if GPIO is not None:
                GPIO.cleanup()
            return 1
        try:
            from pyboy import PyBoy
            PYBOY_OK = True
            logger.info("PyBoy imported successfully after install")
        except ImportError as e:
            logger.error(f"Failed to import PyBoy after install: {e}")
            if GPIO is not None:
                GPIO.cleanup()
            return 1

    try:
        while running:
            logger.info("Starting ROM browser...")
            rom = _rom_browser()
            if rom is None:
                logger.info("User exited ROM browser")
                break
            logger.info(f"Running emulator for ROM: {rom}")
            _run_emulator(rom)
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
        logger.error(traceback.format_exc())
    finally:
        try:
            LCD.LCD_Clear()
        except Exception as e:
            logger.warning(f"Failed to clear LCD: {e}")
        if GPIO is not None:
            try:
                GPIO.cleanup()
            except Exception as e:
                logger.warning(f"Failed to cleanup GPIO: {e}")

    return 0


if __name__ == "__main__":
    try:
        logger.info("KTOxBOY starting...")
        exit_code = main()
        logger.info(f"KTOxBOY exited with code {exit_code}")
        raise SystemExit(exit_code)
    except Exception as e:
        logger.error(f"KTOxBOY crashed: {e}")
        logger.error(traceback.format_exc())
        if GPIO is not None:
            try:
                GPIO.cleanup()
            except:
                pass
        raise SystemExit(1)
