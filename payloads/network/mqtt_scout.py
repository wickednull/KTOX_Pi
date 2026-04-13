#!/usr/bin/env python3
"""
KTOx payload — MQTT Scout
==========================
Scans the local subnet for open (unauthenticated) MQTT brokers on port 1883.
Connects, subscribes to ALL topics (#), and streams messages live on the LCD.

Optional log saving to /root/KTOx/loot/MQTTScout/ with size monitoring —
logs can grow fast, so the logger warns at 10 MB and auto-stops at 50 MB.

Controls
--------
  UP / DOWN   scroll broker list  |  scroll message buffer when connected
  OK          connect to selected broker
  KEY1        toggle file logging on / off
  KEY2        disconnect and rescan
  KEY3        exit

Author: wickednull
"""

import os, sys, time, socket, threading, subprocess, re
from datetime import datetime
from pathlib import Path
from collections import deque

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))
if "/root/KTOx" not in sys.path:
    sys.path.insert(0, "/root/KTOx")

try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

from _input_helper import get_button, flush_input

# ── paho-mqtt ─────────────────────────────────────────────────────────────────
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

# ── constants ─────────────────────────────────────────────────────────────────
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
W, H = 128, 128

LOOT_DIR      = Path("/root/KTOx/loot/MQTTScout")
MQTT_PORT     = 1883
SCAN_TIMEOUT  = 0.4          # seconds per host
SCAN_WORKERS  = 64           # parallel socket checks
MSG_BUFFER    = 200          # messages kept in RAM
LOG_WARN_MB   = 10           # warn when log exceeds this
LOG_STOP_MB   = 50           # stop logging when log exceeds this

# ── Game Boy DMG colour palette ───────────────────────────────────────────────
GB_BG    = "#0f380f"   # darkest  — background
GB_DARK  = "#306230"   # dark     — title bars, borders
GB_MID   = "#8bac0f"   # medium   — dim text, footer hints
GB_LIGHT = "#9bbc0f"   # light    — active text, highlights
GB_WHITE = "#e0f8d0"   # lightest — bright / important text
GB_ERR   = "#7a1a1a"   # error title bar
GB_ERRT  = "#c04040"   # error body text

# ── LCD helpers ───────────────────────────────────────────────────────────────

def _font(size=8):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except Exception:
        return ImageFont.load_default()

FONT_SM = _font(8)
FONT_MD = _font(9)

lcd_hw = None

if HAS_HW:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for _p in PINS.values():
            GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        lcd_hw = LCD_1in44.LCD()
        lcd_hw.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        lcd_hw.LCD_Clear()
    except Exception as _e:
        print(f"LCD init: {_e}")


def lcd_draw(draw_fn):
    img  = Image.new("RGB", (W, H), GB_BG)
    draw = ImageDraw.Draw(img)
    draw_fn(img, draw)
    if lcd_hw:
        try:
            lcd_hw.LCD_ShowImage(img, 0, 0)
        except Exception:
            pass


def lcd_simple(title, lines, tc=None, lc=None):
    tc = tc or GB_DARK
    lc = lc or GB_WHITE
    def _draw(img, draw):
        draw.rectangle((0, 0, W, 14), fill=tc)
        draw.text((3, 2), title[:20], fill=GB_WHITE, font=FONT_MD)
        y = 18
        for ln in (lines or []):
            draw.text((3, y), str(ln)[:21], fill=lc, font=FONT_SM)
            y += 11
            if y > H - 8:
                break
    lcd_draw(_draw)
    if not HAS_HW:
        print(f"[{title}]", " | ".join(str(l) for l in (lines or [])))


# ── network helpers ───────────────────────────────────────────────────────────

def _local_subnet():
    """Return list of host IPs in the local /24 subnet, or empty list."""
    try:
        out = subprocess.check_output(
            ["ip", "route", "show"], text=True, timeout=5)
        for line in out.splitlines():
            m = re.match(r"(\d+\.\d+\.\d+)\.\d+/\d+\s", line)
            if m:
                base = m.group(1)
                return [f"{base}.{i}" for i in range(1, 255)]
    except Exception:
        pass
    return []


def _check_mqtt(host):
    """Return host if port 1883 is open, else None."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(SCAN_TIMEOUT)
        if s.connect_ex((host, MQTT_PORT)) == 0:
            s.close()
            return host
        s.close()
    except Exception:
        pass
    return None


def scan_for_brokers(progress_cb=None):
    """Scan local /24 for open port 1883. Returns list of IPs."""
    hosts  = _local_subnet()
    found  = []
    done   = [0]
    total  = len(hosts)
    lock   = threading.Lock()

    def worker(h):
        result = _check_mqtt(h)
        with lock:
            done[0] += 1
            if result:
                found.append(result)
            if progress_cb:
                progress_cb(done[0], total)

    threads = []
    for h in hosts:
        t = threading.Thread(target=worker, args=(h,), daemon=True)
        threads.append(t)
        t.start()
        if len([x for x in threads if x.is_alive()]) >= SCAN_WORKERS:
            time.sleep(0.01)

    for t in threads:
        t.join()

    return found


# ── log management ────────────────────────────────────────────────────────────

_log_file   = None
_log_path   = None
_log_lock   = threading.Lock()
_log_bytes  = 0


def _open_log():
    global _log_file, _log_path, _log_bytes
    LOOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_path = LOOT_DIR / f"mqtt_{ts}.log"
    _log_file = open(_log_path, "w", buffering=1)
    _log_bytes = 0


def _close_log():
    global _log_file
    if _log_file:
        try:
            _log_file.close()
        except Exception:
            pass
        _log_file = None


def _write_log(line):
    global _log_bytes, _log_file
    if not _log_file:
        return "off"
    with _log_lock:
        try:
            _log_file.write(line + "\n")
            _log_bytes += len(line) + 1
        except Exception:
            pass
    mb = _log_bytes / 1_048_576
    if mb >= LOG_STOP_MB:
        _close_log()
        return "stopped"
    if mb >= LOG_WARN_MB:
        return "warn"
    return "ok"


def _log_size_str():
    if _log_file is None:
        return "OFF"
    mb = _log_bytes / 1_048_576
    if mb < 1:
        return f"{_log_bytes//1024}KB"
    return f"{mb:.1f}MB"


# ── MQTT client state ─────────────────────────────────────────────────────────

_msgs      = deque(maxlen=MSG_BUFFER)
_msgs_lock = threading.Lock()
_total_rx  = 0
_client    = None
_connected = False
_broker_ip = ""
_log_on    = False


def _on_connect(client, userdata, flags, rc):
    global _connected
    if rc == 0:
        _connected = True
        client.subscribe("#")
    else:
        _connected = False


def _on_disconnect(client, userdata, rc):
    global _connected
    _connected = False


def _on_message(client, userdata, msg):
    global _total_rx, _log_on
    _total_rx += 1
    try:
        payload = msg.payload.decode("utf-8", "replace")
    except Exception:
        payload = repr(msg.payload)
    payload_short = payload if len(payload) <= 120 else payload[:117] + "..."
    ts = datetime.now().strftime("%H:%M:%S")
    entry = (ts, msg.topic, payload_short)
    with _msgs_lock:
        _msgs.append(entry)
    if _log_on:
        line = f"[{ts}] {msg.topic}: {payload}"
        _write_log(line)


def _connect_broker(ip):
    global _client, _connected, _broker_ip, _total_rx
    _disconnect_broker()
    _broker_ip = ip
    _total_rx  = 0
    _connected = False

    c = mqtt.Client(client_id=f"ktox_{os.getpid()}")
    c.on_connect    = _on_connect
    c.on_disconnect = _on_disconnect
    c.on_message    = _on_message

    try:
        c.connect(ip, MQTT_PORT, keepalive=60)
        c.loop_start()
        _client = c
    except Exception as e:
        return str(e)
    for _ in range(30):
        if _connected:
            return None
        time.sleep(0.1)
    return "Timeout connecting"


def _disconnect_broker():
    global _client, _connected
    if _client:
        try:
            _client.loop_stop()
            _client.disconnect()
        except Exception:
            pass
        _client = None
    _connected = False


# ── screen renderers ──────────────────────────────────────────────────────────

def render_scan_progress(done, total):
    pct = int(done / max(total, 1) * 100)
    bar = int((W - 6) * pct / 100)

    def _draw(img, draw):
        draw.rectangle((0, 0, W, 14), fill=GB_DARK)
        draw.text((3, 2), "MQTT SCOUT", fill=GB_WHITE, font=FONT_MD)
        draw.text((3, 18), "Scanning subnet...", fill=GB_LIGHT, font=FONT_SM)
        draw.text((3, 30), f"{done}/{total} hosts", fill=GB_WHITE, font=FONT_SM)
        draw.rectangle((3, 46, W - 3, 56), outline=GB_DARK, fill=GB_BG)
        if bar:
            draw.rectangle((3, 46, 3 + bar, 56), fill=GB_LIGHT)
        draw.text((3, 60), f"{pct}%", fill=GB_LIGHT, font=FONT_SM)

    lcd_draw(_draw)


def render_broker_list(brokers, cursor):
    def _draw(img, draw):
        draw.rectangle((0, 0, W, 14), fill=GB_DARK)
        draw.text((3, 2), "MQTT BROKERS", fill=GB_WHITE, font=FONT_MD)
        if not brokers:
            draw.text((3, 20), "No open brokers", fill=GB_ERRT, font=FONT_SM)
            draw.text((3, 32), "found on subnet.", fill=GB_ERRT, font=FONT_SM)
            draw.text((3, 50), "KEY2 to rescan",  fill=GB_MID,  font=FONT_SM)
            draw.text((3, 62), "KEY3 to exit",    fill=GB_MID,  font=FONT_SM)
        else:
            y = 18
            visible = 6
            scroll  = max(0, cursor - visible + 1)
            for i in range(scroll, min(scroll + visible, len(brokers))):
                sel  = (i == cursor)
                text = f"{'>' if sel else ' '} {brokers[i]}"
                col  = GB_WHITE if sel else GB_LIGHT
                if sel:
                    draw.rectangle((0, y, W, y + 10), fill=GB_DARK)
                draw.text((3, y), text[:21], fill=col, font=FONT_SM)
                y += 11
            draw.line((0, H - 22, W, H - 22), fill=GB_DARK)
            draw.text((3, H - 20), "OK=connect  K2=rescan", fill=GB_MID, font=FONT_SM)
            draw.text((3, H - 10), "K3=exit",               fill=GB_MID, font=FONT_SM)

    lcd_draw(_draw)
    if not HAS_HW:
        for i, b in enumerate(brokers):
            print(f"  {'>' if i == cursor else ' '} {b}")


def render_live(scroll_offset):
    """Render the live message view."""
    log_col   = GB_LIGHT if _log_on else GB_MID
    log_lbl   = f"LOG:{_log_size_str()}"
    title_col = GB_DARK

    with _msgs_lock:
        msg_list = list(_msgs)

    LINES = 6
    flat = []
    for ts, topic, payload in msg_list:
        flat.append((f"  {topic[:19]}",   GB_LIGHT))
        flat.append((f"  {payload[:19]}", GB_WHITE))

    total_lines = len(flat)
    end    = max(total_lines - scroll_offset, 0)
    start  = max(end - LINES, 0)
    window = flat[start:end]

    def _draw(img, draw):
        draw.rectangle((0, 0, W, 14), fill=title_col)
        draw.text((3, 2),  f"MQTT {_broker_ip}", fill=GB_WHITE, font=FONT_SM)
        draw.text((90, 3), log_lbl[:8],           fill=log_col,  font=FONT_SM)

        draw.text((3, 16), f"rx:{_total_rx}", fill=GB_MID, font=FONT_SM)
        draw.line((0, 26, W, 26), fill=GB_DARK)

        y = 29
        if not window:
            draw.text((3, y), "Waiting for msgs...", fill=GB_MID, font=FONT_SM)
        else:
            for txt, col in window:
                draw.text((3, y), txt, fill=col, font=FONT_SM)
                y += 11
                if y > H - 12:
                    break

        draw.line((0, H - 12, W, H - 12), fill=GB_DARK)
        draw.text((3, H - 10), "K1=log K2=scan K3=exit", fill=GB_MID, font=FONT_SM)

    lcd_draw(_draw)
    if not HAS_HW:
        print(f"[LIVE {_broker_ip}] rx={_total_rx} log={'on' if _log_on else 'off'}")
        for txt, _ in (window or []):
            print(txt)


# ── main ──────────────────────────────────────────────────────────────────────

def _install_paho():
    lcd_simple("INSTALLING", ["paho-mqtt...", "Please wait."])
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "paho-mqtt", "-q"],
            timeout=120, check=True)
        return True
    except Exception as e:
        lcd_simple("INSTALL FAIL", [str(e)[:40]], tc=GB_ERR, lc=GB_ERRT)
        time.sleep(3)
        return False


def main():
    global _log_on

    flush_input()

    # ── paho-mqtt check ───────────────────────────────────────────────────────
    if not HAS_MQTT:
        lcd_simple("DEPENDENCY",
                   ["paho-mqtt missing.", "", "KEY1: install now", "KEY3: exit"],
                   lc=GB_LIGHT)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            btn = get_button(PINS, GPIO) if HAS_HW else None
            if btn == "KEY1":
                if _install_paho():
                    lcd_simple("INSTALLED", ["paho-mqtt ready.", "Restarting..."],
                               lc=GB_LIGHT)
                    time.sleep(1.5)
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                return
            if btn == "KEY3":
                return
            time.sleep(0.1)
        return

    # ── initial scan ──────────────────────────────────────────────────────────
    brokers = []

    def do_scan():
        nonlocal brokers
        brokers = []
        render_scan_progress(0, 254)

        def on_progress(done, total):
            render_scan_progress(done, total)

        brokers = scan_for_brokers(progress_cb=on_progress)

    do_scan()

    cursor        = 0
    scroll_offset = 0
    state         = "LIST"
    last_btn      = 0.0
    last_render   = 0.0

    render_broker_list(brokers, cursor)

    while True:
        now = time.monotonic()
        btn = get_button(PINS, GPIO) if HAS_HW else None

        if btn and (now - last_btn) > 0.22:
            last_btn = now

            if state == "LIST":
                if btn == "UP" and cursor > 0:
                    cursor -= 1
                    render_broker_list(brokers, cursor)
                elif btn == "DOWN" and cursor < len(brokers) - 1:
                    cursor += 1
                    render_broker_list(brokers, cursor)
                elif btn == "OK" and brokers:
                    ip = brokers[cursor]
                    lcd_simple("CONNECTING", [ip, "", "Subscribing to #..."])
                    err = _connect_broker(ip)
                    if err:
                        lcd_simple("CONN ERROR", [ip, "", err[:40]],
                                   tc=GB_ERR, lc=GB_ERRT)
                        time.sleep(2)
                        render_broker_list(brokers, cursor)
                    else:
                        scroll_offset = 0
                        state = "LIVE"
                        render_live(scroll_offset)
                elif btn == "KEY2":
                    do_scan()
                    cursor = 0
                    render_broker_list(brokers, cursor)
                elif btn == "KEY3":
                    break

            elif state == "LIVE":
                if btn == "UP":
                    with _msgs_lock:
                        max_off = max(0, len(_msgs) * 2 - 6)
                    scroll_offset = min(scroll_offset + 2, max_off)
                    render_live(scroll_offset)
                elif btn == "DOWN":
                    scroll_offset = max(0, scroll_offset - 2)
                    render_live(scroll_offset)
                elif btn == "KEY1":
                    _log_on = not _log_on
                    if _log_on:
                        _open_log()
                        lcd_simple("LOG ON", [str(_log_path.name)[:21],
                                              f"warn>{LOG_WARN_MB}MB",
                                              f"stop>{LOG_STOP_MB}MB"],
                                   lc=GB_LIGHT)
                        time.sleep(1.5)
                    else:
                        _close_log()
                        lcd_simple("LOG OFF", ["Logging stopped."], lc=GB_MID)
                        time.sleep(1)
                    render_live(scroll_offset)
                elif btn == "KEY2":
                    _disconnect_broker()
                    if _log_on:
                        _close_log()
                        _log_on = False
                    state = "LIST"
                    do_scan()
                    cursor = 0
                    render_broker_list(brokers, cursor)
                elif btn == "KEY3":
                    break

        if state == "LIVE" and (now - last_render) > 0.5:
            last_render = now
            if _log_on and _log_bytes >= LOG_STOP_MB * 1_048_576:
                _log_on = False
                lcd_simple("LOG STOPPED",
                           [f"Reached {LOG_STOP_MB}MB limit.", "Log saved to loot."],
                           lc=GB_MID)
                time.sleep(2)
            render_live(scroll_offset)

        time.sleep(0.05)

    # ── cleanup ───────────────────────────────────────────────────────────────
    _disconnect_broker()
    if _log_on:
        _close_log()
        _log_on = False

    if LOOT_DIR.exists():
        logs = sorted(LOOT_DIR.glob("mqtt_*.log"))
        if logs:
            sizes = [f"{p.name}: {p.stat().st_size//1024}KB" for p in logs[-3:]]
            lcd_simple("SAVED LOGS", sizes, lc=GB_MID)
            time.sleep(2)

    lcd_simple("EXIT", ["MQTT Scout closed."], lc=GB_MID)
    time.sleep(1)

    if HAS_HW:
        try:
            GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
