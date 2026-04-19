#!/usr/bin/env python3
"""
KTOx Payload – RF Scanner (hackrf_sweep)
=========================================
Author: wickednull

- Scans frequency ranges using hackrf_sweep
- Detects signal peaks and rising trends
- Triggers a relay (GPIO 17) on persistent signals
- Logs detections to /root/KTOx/loot/RFScanner/
- LCD interface with menu and real-time display

Controls:
  UP/DOWN   – navigate menu / adjust values
  OK        – start/stop scanning / confirm setting
  KEY1      – show detection report
  KEY2      – enter settings menu
  KEY3      – exit payload

Dependencies: hackrf_sweep (hackrf-tools), RPi.GPIO, PIL
Install: apt install hackrf
"""

import os
import sys
import time
import json
import threading
import subprocess
import signal
import re
import math
from datetime import datetime
from collections import deque

# ----------------------------------------------------------------------
# Hardware & LCD
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("KTOx hardware not found")
    sys.exit(1)

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

f9 = font(9)
f11 = font(11)

# ----------------------------------------------------------------------
# Relay control (GPIO 17)
# ----------------------------------------------------------------------
RELAY_PIN = 17
GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)

def relay_on():
    GPIO.output(RELAY_PIN, GPIO.LOW)  # Assuming active low

def relay_off():
    GPIO.output(RELAY_PIN, GPIO.HIGH)

def relay_trigger(hold_sec=5):
    relay_on()
    time.sleep(hold_sec)
    relay_off()

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
CONFIG_DIR = "/root/KTOx/loot/RFScanner"
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_DIR = os.path.join(CONFIG_DIR, "history")
os.makedirs(HISTORY_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    "ranges": [
        {"active": True, "start": 400, "end": 500},
        {"active": False, "start": 1200, "end": 1300},
        {"active": False, "start": 2400, "end": 2500},
        {"active": False, "start": 5700, "end": 5900}
    ],
    "threshold_db": -40.0,
    "trend_k": 3,
    "relay_hold_sec": 5,
    "freq_tol_mhz": 5.0,
    "alpha_freq": 0.4,
    "beta_pwr": 0.5
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            # Merge with defaults
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

# ----------------------------------------------------------------------
# Global state
# ----------------------------------------------------------------------
running = False
proc = None
last_line_time = 0
trend_tracks = []  # list of Track objects
stats_lock = threading.Lock()
detection_history = []  # list of (timestamp, freq, db)
MAX_HISTORY = 100

class Track:
    __slots__ = ("freq_mhz", "p_ewma", "hist", "last_seen", "triggered")
    def __init__(self, freq_mhz, db):
        self.freq_mhz = freq_mhz
        self.p_ewma = db
        self.hist = [db]
        self.last_seen = time.time()
        self.triggered = False
    def update(self, freq_mhz, db, alpha_freq, beta_pwr):
        self.freq_mhz = alpha_freq * freq_mhz + (1 - alpha_freq) * self.freq_mhz
        self.p_ewma = beta_pwr * db + (1 - beta_pwr) * self.p_ewma
        self.hist.append(db)
        self.last_seen = time.time()
        if len(self.hist) > 48:
            self.hist = self.hist[-48:]
    def ok_trend(self, K):
        if len(self.hist) < K:
            return False
        window = self.hist[-K:]
        return all(window[i] < window[i+1] for i in range(len(window)-1))

# ----------------------------------------------------------------------
# Scanning thread
# ----------------------------------------------------------------------
def get_active_range(cfg):
    active = [r for r in cfg["ranges"] if r["active"]]
    if not active:
        return (100, 6000)
    start = min(r["start"] for r in active)
    end = max(r["end"] for r in active)
    return (start, end)

def is_in_active_range(freq_mhz, cfg):
    for r in cfg["ranges"]:
        if r["active"] and r["start"] <= freq_mhz <= r["end"]:
            return True
    return False

def reader_thread(cfg):
    global running, proc, last_line_time, trend_tracks
    start_mhz, end_mhz = get_active_range(cfg)
    cmd = ["hackrf_sweep", "-f", f"{start_mhz:.0f}:{end_mhz:.0f}"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, preexec_fn=os.setsid)
        last_line_time = time.time()
    except Exception as e:
        update_status(f"Error: {e}")
        return

    for line in proc.stdout:
        if not running:
            break
        line = line.strip()
        if not line or "sweeps" in line:
            continue
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            hz_low = int(parts[2])
            bin_hz = float(parts[4])
            bins = [float(x) for x in parts[6:] if x]
            if not bins:
                continue
            peak = max(bins)
            if peak <= cfg["threshold_db"]:
                continue
            peak_idx = bins.index(peak)
            trig_hz = hz_low + int((float(peak_idx) + 0.5) * bin_hz)
            freq_mhz = trig_hz / 1e6
            if not is_in_active_range(freq_mhz, cfg):
                continue

            # Update trend tracking
            f_tol = max(2.0 * (bin_hz / 1e6), cfg["freq_tol_mhz"])
            now_ts = time.time()
            # Remove old tracks
            trend_tracks = [t for t in trend_tracks if (now_ts - t.last_seen) < 10.0]

            # Find closest track
            best_idx = -1
            best_dist = None
            for i, t in enumerate(trend_tracks):
                dist = abs(t.freq_mhz - freq_mhz)
                if dist <= f_tol and (best_dist is None or dist < best_dist):
                    best_idx = i
                    best_dist = dist

            if best_idx >= 0:
                t = trend_tracks[best_idx]
                t.update(freq_mhz, peak, cfg["alpha_freq"], cfg["beta_pwr"])
                # Log growth
                if len(t.hist) >= 2 and t.hist[-1] > t.hist[-2]:
                    log_msg(f"Rise: {t.freq_mhz:.2f} MHz  {t.hist[-1]:.1f} dB")
                else:
                    log_msg(f"Signal: {t.freq_mhz:.2f} MHz  {t.hist[-1]:.1f} dB")
            else:
                t = Track(freq_mhz, peak)
                trend_tracks.append(t)
                log_msg(f"New signal: {t.freq_mhz:.2f} MHz  {t.hist[-1]:.1f} dB")
                # Log to history (non-trigger)
                save_history(freq_mhz, peak, triggered=False)

            # Check trend
            if t.ok_trend(cfg["trend_k"]) and not t.triggered:
                t.triggered = True
                log_msg(f"!!! TRIGGER: {t.freq_mhz:.2f} MHz  {t.hist[-1]:.1f} dB")
                save_history(t.freq_mhz, t.hist[-1], triggered=True)
                # Trigger relay in background thread (non-blocking)
                threading.Thread(target=relay_trigger, args=(cfg["relay_hold_sec"],), daemon=True).start()
                update_display_trigger(t.freq_mhz, t.hist[-1])

            # Update LCD with current peak
            update_display_peak(freq_mhz, peak)

            last_line_time = now_ts

        except Exception as e:
            log_msg(f"Parse error: {e}")

    proc = None

def supervisor_thread(cfg):
    global running, proc
    while running:
        if proc is None or proc.poll() is not None:
            # Restart scanner
            threading.Thread(target=reader_thread, args=(cfg,), daemon=True).start()
        else:
            # Check for dead process
            if time.time() - last_line_time > 5:
                if proc:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except:
                        pass
                    proc = None
        time.sleep(2)

# ----------------------------------------------------------------------
# Logging and history
# ----------------------------------------------------------------------
def log_msg(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(os.path.join(CONFIG_DIR, "scanner.log"), "a") as f:
        f.write(f"[{ts}] {msg}\n")

def save_history(freq_mhz, db, triggered):
    now = datetime.now()
    fname = f"history_{now.strftime('%Y%m%d')}.csv"
    fpath = os.path.join(HISTORY_DIR, fname)
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')};{freq_mhz:.6f};{db:.1f};{1 if triggered else 0}\n"
    with open(fpath, "a") as f:
        f.write(line)
    with stats_lock:
        detection_history.append((now, freq_mhz, db, triggered))
        while len(detection_history) > MAX_HISTORY:
            detection_history.pop(0)

def get_history(days=5):
    rows = []
    now = datetime.now().date()
    for i in range(days):
        d = now - timedelta(days=i)
        fname = f"history_{d.strftime('%Y%m%d')}.csv"
        fpath = os.path.join(HISTORY_DIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) >= 3:
                    rows.append((parts[0], float(parts[1]), float(parts[2]), parts[3] == "1"))
    rows.sort(key=lambda x: x[0], reverse=True)
    return rows

# ----------------------------------------------------------------------
# LCD display and menu
# ----------------------------------------------------------------------
current_peak_freq = 0.0
current_peak_db = 0.0
trigger_freq = 0.0
trigger_db = 0.0
trigger_active = False
status_text = "Stopped"
menu_state = "main"  # main, settings

def update_display_peak(freq, db):
    global current_peak_freq, current_peak_db
    current_peak_freq = freq
    current_peak_db = db

def update_display_trigger(freq, db):
    global trigger_freq, trigger_db, trigger_active
    trigger_freq = freq
    trigger_db = db
    trigger_active = True
    threading.Timer(5.0, lambda: globals().update(trigger_active=False)).start()

def update_status(msg):
    global status_text
    status_text = msg

def draw_main_screen():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#8B0000")
    d.text((4, 3), "RF SCANNER", font=f9, fill="#FF3333")
    y = 20
    d.text((4, y), f"Peak: {current_peak_freq:.2f} MHz", font=f9, fill="#FFBBBB"); y += 12
    d.text((4, y), f"dB: {current_peak_db:.1f}", font=f9, fill="#FFBBBB"); y += 12
    if trigger_active:
        d.text((4, y), f"TRIGGER: {trigger_freq:.2f} MHz", font=f9, fill="#00FF00"); y += 12
        d.text((4, y), f"dB: {trigger_db:.1f}", font=f9, fill="#00FF00"); y += 12
    else:
        d.text((4, y), "Status: " + status_text, font=f9, fill="#AAAAAA"); y += 12
    d.text((4, H-30), "K1=Report K2=Settings", font=f9, fill="#FF7777")
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "OK=Start/Stop K3=Exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_settings_menu(cfg, selected, page=0):
    items = [
        f"Threshold: {cfg['threshold_db']:.1f} dB",
        f"Trend K: {cfg['trend_k']}",
        f"Relay hold: {cfg['relay_hold_sec']} s",
        f"Freq tol: {cfg['freq_tol_mhz']} MHz",
        "Ranges: " + ("ON" if any(r["active"] for r in cfg["ranges"]) else "OFF")
    ]
    lines = ["SETTINGS", ""]
    for i, item in enumerate(items):
        marker = ">" if i == selected else " "
        lines.append(f"{marker} {item}")
    lines.append("")
    lines.append("UP/DN OK to edit")
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#004466")
    d.text((4, 3), "SETTINGS", font=f9, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        d.text((4, y), line[:23], font=f9, fill="#FFBBBB")
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "K3=Back", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ranges_menu(cfg, selected_range, selected_field):
    lines = ["RANGES", ""]
    for i, r in enumerate(cfg["ranges"]):
        active = "✓" if r["active"] else "✗"
        lines.append(f"{i+1}. {active} {r['start']}-{r['end']} MHz")
    lines.append("")
    lines.append("UP/DN OK K3=Back")
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#004466")
    d.text((4, 3), "RANGES", font=f9, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        d.text((4, y), line[:23], font=f9, fill="#FFBBBB")
        y += 12
    LCD.LCD_ShowImage(img, 0, 0)

def show_report():
    # Show last 10 detections on LCD
    with stats_lock:
        recent = detection_history[-10:]
    lines = ["RECENT DETECTIONS", ""]
    for ts, freq, db, trig in reversed(recent):
        lines.append(f"{ts.strftime('%H:%M:%S')} {freq:.1f}MHz {db:.0f}dB")
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#004466")
    d.text((4, 3), "REPORT", font=f9, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        d.text((4, y), line[:23], font=f9, fill="#FFBBBB")
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "Any key to exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)
    while True:
        if wait_btn(0.1) is not None:
            break
        time.sleep(0.05)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    global running, menu_state, status_text
    cfg = load_config()

    # Start background threads
    def start_scanner():
        global running
        if running:
            return
        running = True
        threading.Thread(target=supervisor_thread, args=(cfg,), daemon=True).start()
        update_status("Running")

    def stop_scanner():
        global running, proc
        running = False
        if proc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except:
                pass
            proc = None
        update_status("Stopped")

    menu_state = "main"
    settings_selected = 0
    ranges_selected = 0
    ranges_field = 0  # 0=active, 1=start, 2=end
    held = {}

    while True:
        if menu_state == "main":
            draw_main_screen()
            btn = wait_btn(0.5)
            if btn == "KEY3":
                break
            elif btn == "KEY1":
                show_report()
            elif btn == "KEY2":
                menu_state = "settings"
                settings_selected = 0
            elif btn == "OK":
                if running:
                    stop_scanner()
                else:
                    start_scanner()
        elif menu_state == "settings":
            draw_settings_menu(cfg, settings_selected)
            btn = wait_btn(0.5)
            if btn == "KEY3":
                menu_state = "main"
            elif btn == "UP":
                settings_selected = (settings_selected - 1) % 5
            elif btn == "DOWN":
                settings_selected = (settings_selected + 1) % 5
            elif btn == "OK":
                if settings_selected == 0:  # Threshold
                    # Simple increment/decrement using UP/DOWN after OK
                    val = cfg["threshold_db"]
                    while True:
                        draw_settings_menu(cfg, settings_selected)
                        btn2 = wait_btn(0.5)
                        if btn2 == "KEY3":
                            break
                        elif btn2 == "UP":
                            val += 1.0
                            cfg["threshold_db"] = val
                            save_config(cfg)
                        elif btn2 == "DOWN":
                            val -= 1.0
                            cfg["threshold_db"] = val
                            save_config(cfg)
                elif settings_selected == 1:  # Trend K
                    val = cfg["trend_k"]
                    while True:
                        draw_settings_menu(cfg, settings_selected)
                        btn2 = wait_btn(0.5)
                        if btn2 == "KEY3":
                            break
                        elif btn2 == "UP":
                            val += 1
                            cfg["trend_k"] = val
                            save_config(cfg)
                        elif btn2 == "DOWN":
                            val = max(1, val - 1)
                            cfg["trend_k"] = val
                            save_config(cfg)
                elif settings_selected == 2:  # Relay hold
                    val = cfg["relay_hold_sec"]
                    while True:
                        draw_settings_menu(cfg, settings_selected)
                        btn2 = wait_btn(0.5)
                        if btn2 == "KEY3":
                            break
                        elif btn2 == "UP":
                            val += 1
                            cfg["relay_hold_sec"] = val
                            save_config(cfg)
                        elif btn2 == "DOWN":
                            val = max(1, val - 1)
                            cfg["relay_hold_sec"] = val
                            save_config(cfg)
                elif settings_selected == 3:  # Freq tol
                    val = cfg["freq_tol_mhz"]
                    while True:
                        draw_settings_menu(cfg, settings_selected)
                        btn2 = wait_btn(0.5)
                        if btn2 == "KEY3":
                            break
                        elif btn2 == "UP":
                            val += 0.5
                            cfg["freq_tol_mhz"] = val
                            save_config(cfg)
                        elif btn2 == "DOWN":
                            val = max(0.5, val - 0.5)
                            cfg["freq_tol_mhz"] = val
                            save_config(cfg)
                elif settings_selected == 4:  # Ranges
                    menu_state = "ranges"
                    ranges_selected = 0
        elif menu_state == "ranges":
            draw_ranges_menu(cfg, ranges_selected, 0)
            btn = wait_btn(0.5)
            if btn == "KEY3":
                menu_state = "settings"
            elif btn == "UP":
                ranges_selected = (ranges_selected - 1) % len(cfg["ranges"])
            elif btn == "DOWN":
                ranges_selected = (ranges_selected + 1) % len(cfg["ranges"])
            elif btn == "OK":
                # Toggle active state
                r = cfg["ranges"][ranges_selected]
                r["active"] = not r["active"]
                save_config(cfg)
        time.sleep(0.05)

    # Cleanup
    stop_scanner()
    relay_off()
    GPIO.cleanup()
    LCD.LCD_Clear()
    os._exit(0)

if __name__ == "__main__":
    main()
