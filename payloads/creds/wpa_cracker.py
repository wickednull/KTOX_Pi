#!/usr/bin/env python3
"""
KTOx Payload -- WPA/WPA2 Cracker
======================================
Author: wickednull

Cracks WPA handshakes (.cap) using aircrack-ng and PMKID hashes
using John the Ripper. Includes a full file browser to select
target files from any directory.

Controls:
  OK         -- Select file / start cracking
  UP / DOWN  -- Scroll file list / wordlists
  KEY1       -- Stop current crack
  KEY2       -- Export cracked results to loot
  KEY3       -- Exit (kills cracking process)

Loot: /root/KTOx/loot/CrackedWPA/
"""

import os
import sys
import re
import time
import signal
import shutil
import threading
import subprocess
from datetime import datetime

# ----------------------------------------------------------------------
# Hardware & LCD setup (no external helpers)
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not detected – exiting")
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
WIDTH, HEIGHT = 128, 128

# Font loading
def load_font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

font_sm = load_font(9)
font_md = load_font(11)

# ----------------------------------------------------------------------
# File Browser (standalone)
# ----------------------------------------------------------------------
def browse_file(start_path="/", extensions=None, prompt="Select file:"):
    """
    Full-screen file browser using LCD and buttons.
    Returns selected file path or None if cancelled.
    """
    extensions = extensions or []
    current_path = os.path.abspath(start_path)
    history = []  # stack for back navigation
    selected_idx = 0
    scroll = 0
    rows_per_page = 8

    def get_entries(path):
        try:
            items = sorted(os.listdir(path))
            dirs = [d for d in items if os.path.isdir(os.path.join(path, d))]
            files = [f for f in items if os.path.isfile(os.path.join(path, f))]
            if extensions:
                files = [f for f in files if any(f.lower().endswith(ext) for ext in extensions)]
            return dirs + files
        except:
            return []

    def draw_browser(entries, sel, sc, path):
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)
        # Header
        draw.rectangle((0,0,127,16), fill="#004466")
        header = path if len(path) < 20 else "..." + path[-17:]
        draw.text((2,2), header[:20], font=font_sm, fill=(171, 178, 185))
        # List
        y = 20
        for i in range(rows_per_page):
            idx = sc + i
            if idx >= len(entries):
                break
            name = entries[idx]
            if len(name) > 20:
                name = name[:18] + ".."
            color = "white"
            if idx == sel:
                color = "yellow"
                draw.rectangle((0, y-1, WIDTH, y+9), fill="#224466")
            if os.path.isdir(os.path.join(path, name)):
                name = "/" + name
            draw.text((4, y), name, font=font_sm, fill=color)
            y += 11
        # Footer
        draw.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=(10, 0, 0))
        draw.text((2, HEIGHT-10), "UP/DOWN OK=sel K3=back", font=font_sm, fill=(171, 178, 185))
        LCD.LCD_ShowImage(img, 0, 0)

    def wait_button():
        while True:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    time.sleep(0.05)  # debounce
                    return name
            time.sleep(0.02)

    while True:
        entries = get_entries(current_path)
        if not entries:
            # Empty folder: show message, allow back
            img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.text((4,50), "Empty folder", font=font_sm, fill="red")
            draw.text((4,70), "KEY3 to go back", font=font_sm, fill=(86, 101, 115))
            LCD.LCD_ShowImage(img, 0, 0)
            while True:
                btn = wait_button()
                if btn == "KEY3":
                    if history:
                        current_path = history.pop()
                        break
                    else:
                        return None
                time.sleep(0.05)
            continue

        draw_browser(entries, selected_idx, scroll, current_path)
        btn = wait_button()
        if btn == "KEY3":
            if history:
                current_path = history.pop()
                selected_idx = 0
                scroll = 0
            else:
                return None
        elif btn == "UP":
            selected_idx = (selected_idx - 1) % len(entries)
            if selected_idx < scroll:
                scroll = selected_idx
        elif btn == "DOWN":
            selected_idx = (selected_idx + 1) % len(entries)
            if selected_idx >= scroll + rows_per_page:
                scroll = selected_idx - rows_per_page + 1
        elif btn == "OK":
            selected = entries[selected_idx]
            full_path = os.path.join(current_path, selected)
            if os.path.isdir(full_path):
                history.append(current_path)
                current_path = full_path
                selected_idx = 0
                scroll = 0
            else:
                return full_path
        time.sleep(0.05)

# ----------------------------------------------------------------------
# Cracker constants & state
# ----------------------------------------------------------------------
AIRCRACK_BIN = shutil.which("aircrack-ng") or "/usr/bin/aircrack-ng"
JOHN_BIN = shutil.which("john") or "/usr/sbin/john"
DEFAULT_WORDLIST = "/usr/share/john/password.lst"
ROCKYOU_WORDLIST = "/root/KTOx/loot/wordlists/rockyou.txt"
CUSTOM_WORDLIST = "/root/KTOx/loot/wordlists/custom.txt"
LOOT_DIR = "/root/KTOx/loot/CrackedWPA"
ROWS_VISIBLE = 6
ROW_H = 12

lock = threading.Lock()
target_file = None       # dict {path, name, ftype}
wordlists = []           # [{name, path}]
phase = "browser"        # browser | wordlist | cracking | results
selected_idx = 0
scroll_pos = 0
wl_idx = 0
status_msg = "Select a target file"
keys_tested = 0
speed_kps = ""
elapsed_secs = 0
found_key = ""
_running = True
_crack_proc = None

def build_wordlist_options():
    options = []
    if os.path.isfile(DEFAULT_WORDLIST):
        options.append({"name": "Default", "path": DEFAULT_WORDLIST})
    if os.path.isfile(ROCKYOU_WORDLIST):
        options.append({"name": "rockyou", "path": ROCKYOU_WORDLIST})
    if os.path.isfile(CUSTOM_WORDLIST):
        options.append({"name": "Custom", "path": CUSTOM_WORDLIST})
    if not options:
        options.append({"name": "Default", "path": DEFAULT_WORDLIST})
    return options

# ----------------------------------------------------------------------
# PMKID conversion helper (John expects ESSID:PMKID)
# ----------------------------------------------------------------------
def convert_pmkid_for_john(pmkid_file):
    """
    Convert hashcat 16800 format (PMKID*AP_MAC*STA_MAC*ESSID_hex)
    to John wpapsk format: ESSID:PMKID
    Returns a temporary file path or None if conversion fails.
    """
    try:
        with open(pmkid_file, 'r') as f:
            line = f.readline().strip()
        # Format: PMKID*AP_MAC*STA_MAC*ESSID_hex
        parts = line.split('*')
        if len(parts) >= 4:
            pmkid = parts[0]
            essid_hex = parts[3]
            # Convert hex ESSID to string
            essid = bytes.fromhex(essid_hex).decode('utf-8', errors='replace')
            john_line = f"{essid}:{pmkid}"
            temp_file = "/dev/shm/ktox_pmkid_john.txt"
            with open(temp_file, 'w') as f:
                f.write(john_line)
            return temp_file
    except Exception:
        pass
    return None

# ----------------------------------------------------------------------
# Cracking threads
# ----------------------------------------------------------------------
def crack_cap_thread(capfile, wordlist_path):
    global _crack_proc, keys_tested, speed_kps, elapsed_secs, found_key, phase, status_msg, _running
    if not os.path.isfile(AIRCRACK_BIN):
        with lock:
            status_msg = "aircrack-ng not found"
            phase = "results"
        return
    start = time.time()
    with lock:
        keys_tested = 0; speed_kps = ""; elapsed_secs = 0; found_key = ""
        status_msg = "Starting aircrack-ng..."
    cmd = [AIRCRACK_BIN, "-w", wordlist_path, capfile]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        _crack_proc = proc
        key_re = re.compile(r"KEY FOUND!\s*\[\s*(.+?)\s*\]")
        prog_re = re.compile(r"\[\d+:\d+:\d+\]\s+([\d,]+)(?:/[\d,]+)?\s+keys?\s+tested\s+\(([^\)]+)\)")
        while _running:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            with lock:
                elapsed_secs = int(time.time() - start)
            m = key_re.search(line)
            if m:
                with lock:
                    found_key = m.group(1)
                    status_msg = "KEY FOUND!"
                continue
            m = prog_re.search(line)
            if m:
                raw = m.group(1).replace(",", "")
                with lock:
                    try:
                        keys_tested = int(raw)
                    except:
                        pass
                    speed_kps = m.group(2).strip()
                    status_msg = "Cracking..."
        proc.wait(timeout=5)
    except Exception as e:
        with lock:
            status_msg = f"Error: {str(e)[:18]}"
    finally:
        _crack_proc = None
        with lock:
            elapsed_secs = int(time.time() - start)
            if phase == "cracking":
                phase = "results"
                if found_key:
                    status_msg = "KEY FOUND!"
                else:
                    status_msg = "Done. Key not found"

def crack_pmkid_thread(pmkid_file, wordlist_path):
    global _crack_proc, keys_tested, speed_kps, elapsed_secs, found_key, phase, status_msg, _running
    if not os.path.isfile(JOHN_BIN):
        with lock:
            status_msg = "john not found"
            phase = "results"
        return
    start = time.time()
    with lock:
        keys_tested = 0; speed_kps = ""; elapsed_secs = 0; found_key = ""
        status_msg = "Converting PMKID..."
    # Convert to John format
    john_input = convert_pmkid_for_john(pmkid_file)
    if not john_input:
        with lock:
            status_msg = "Unsupported PMKID format"
            phase = "results"
        return
    with lock:
        status_msg = "Starting John (wpapsk)..."
    cmd = [JOHN_BIN, "--format=wpapsk", f"--wordlist={wordlist_path}", john_input]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        _crack_proc = proc
        crack_re = re.compile(r"^(.+?)\s+\((.+?)\)\s*$")
        while _running:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            with lock:
                elapsed_secs = int(time.time() - start)
            m = crack_re.match(line.rstrip())
            if m:
                with lock:
                    found_key = m.group(1).strip()
                    status_msg = "KEY FOUND!"
        proc.wait(timeout=5)
    except Exception as e:
        with lock:
            status_msg = f"Error: {str(e)[:18]}"
    finally:
        _crack_proc = None
        with lock:
            elapsed_secs = int(time.time() - start)
            if phase == "cracking":
                phase = "results"
                if found_key:
                    status_msg = "KEY FOUND!"
                else:
                    status_msg = "Done. Key not found"

def kill_crack_proc():
    global _crack_proc
    if _crack_proc:
        try:
            os.kill(_crack_proc.pid, signal.SIGTERM)
            _crack_proc.wait(timeout=5)
        except:
            try:
                os.kill(_crack_proc.pid, signal.SIGKILL)
            except:
                pass
        _crack_proc = None

# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
def export_result(target_name):
    with lock:
        key = found_key
    if not key:
        return None
    os.makedirs(LOOT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(LOOT_DIR, f"cracked_{ts}.txt")
    with open(out_file, "w") as f:
        f.write(f"Target: {target_name}\nKey: {key}\nDate: {datetime.now().isoformat()}\n")
    return os.path.basename(out_file)

# ----------------------------------------------------------------------
# Drawing routines
# ----------------------------------------------------------------------
def fmt_elapsed(secs):
    m, s = divmod(secs, 60)
    return f"{m:02d}:{s:02d}"

def fmt_keys(count):
    if count >= 1_000_000:
        return f"{count/1_000_000:.1f}M"
    if count >= 1000:
        return f"{count/1000:.1f}K"
    return str(count)

def draw_header(draw, title):
    draw.rectangle((0,0,127,13), fill=(10, 0, 0))
    draw.text((2,1), title, font=font_sm, fill="#00AAFF")
    with lock:
        active = phase == "cracking"
    draw.ellipse((118,3,122,7), fill=(30, 132, 73) if active else "#444")

def draw_footer(draw, text):
    draw.rectangle((0,116,127,127), fill=(10, 0, 0))
    draw.text((2,117), text[:24], font=font_sm, fill=(113, 125, 126))

def draw_browser_view():
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_header(draw, "WPA CRACKER")
    draw.text((2,16), status_msg[:24], font=font_sm, fill=(171, 178, 185))
    draw.text((2,28), "Press OK to select file", font=font_sm, fill=(113, 125, 126))
    draw_footer(draw, "K3:Exit")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_wordlist_view():
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_header(draw, "WPA CRACKER")
    if target_file:
        draw.text((2,16), f"Target: {target_file['name'][:18]}", font=font_sm, fill=(212, 172, 13))
        draw.text((2,28), f"Type: {target_file['ftype']}", font=font_sm, fill=(113, 125, 126))
    draw.text((2,44), "Select wordlist:", font=font_sm, fill=(171, 178, 185))
    with lock:
        wl = wordlists
        sel = selected_idx
    for i, w in enumerate(wl):
        y = 56 + i * ROW_H
        prefix = ">" if i == sel else " "
        color = "#00FF00" if i == sel else "#CCCCCC"
        draw.text((2, y), f"{prefix}{w['name']}", font=font_sm, fill=color)
    draw_footer(draw, "OK:Start UP/DN:Sel K3:Back")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_cracking_view():
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_header(draw, "WPA CRACKER")
    with lock:
        msg = status_msg
        tested = keys_tested
        spd = speed_kps
        elapsed = elapsed_secs
        key = found_key
        cur_phase = phase
    if target_file:
        draw.text((2,16), f"{target_file['name'][:22]}", font=font_sm, fill=(113, 125, 126))
    color = "#00FF00" if key else ("#FFAA00" if cur_phase == "cracking" else "#FF4444")
    draw.text((2,30), msg[:22], font=font_sm, fill=color)
    draw.text((2,46), f"Time: {fmt_elapsed(elapsed)}", font=font_sm, fill=(242, 243, 244))
    draw.text((2,58), f"Keys: {fmt_keys(tested)}", font=font_sm, fill=(171, 178, 185))
    if spd:
        draw.text((2,70), f"Speed: {spd[:16]}", font=font_sm, fill=(171, 178, 185))
    if key:
        draw.text((2,86), "PASSWORD:", font=font_sm, fill=(113, 125, 126))
        draw.text((2,98), key[:22], font=font_sm, fill=(30, 132, 73))
    if cur_phase == "cracking":
        draw_footer(draw, "K1:Stop K3:Exit")
    else:
        draw_footer(draw, "K2:Export OK:Back K3:X")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    global _running, phase, target_file, wordlists, selected_idx, scroll_pos, wl_idx, status_msg

    # Initial screen
    draw_browser_view()

    while _running:
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                time.sleep(0.05)  # debounce
                break
        if not btn:
            time.sleep(0.05)
            continue

        # Global exit (any phase)
        if btn == "KEY3":
            if phase in ("wordlist", "results"):
                phase = "browser"
                kill_crack_proc()
                with lock:
                    target_file = None
                    status_msg = "Select a target file"
                draw_browser_view()
                continue
            else:
                break

        # ---- File browser phase ----
        if phase == "browser":
            if btn == "OK":
                # Launch file browser
                ext = [".cap", ".pcap", ".txt", ".pmkid", ".16800"]
                selected = browse_file("/root/KTOx/loot", extensions=ext)
                if selected:
                    ftype = "CAP" if selected.lower().endswith(".cap") else "PMKID"
                    with lock:
                        target_file = {"path": selected, "name": os.path.basename(selected), "ftype": ftype}
                        wordlists = build_wordlist_options()
                        selected_idx = 0
                        phase = "wordlist"
                    draw_wordlist_view()
                else:
                    draw_browser_view()
            # No other buttons in browser phase
            else:
                draw_browser_view()

        # ---- Wordlist selection phase ----
        elif phase == "wordlist":
            if btn == "OK" and target_file:
                with lock:
                    wl = wordlists[selected_idx] if selected_idx < len(wordlists) else wordlists[0]
                phase = "cracking"
                kill_crack_proc()
                with lock:
                    status_msg = "Starting crack..."
                if target_file["ftype"] == "CAP":
                    threading.Thread(target=crack_cap_thread, args=(target_file["path"], wl["path"]), daemon=True).start()
                else:
                    threading.Thread(target=crack_pmkid_thread, args=(target_file["path"], wl["path"]), daemon=True).start()
                draw_cracking_view()
            elif btn == "UP":
                with lock:
                    selected_idx = max(0, selected_idx - 1)
                draw_wordlist_view()
            elif btn == "DOWN":
                with lock:
                    selected_idx = min(selected_idx + 1, max(0, len(wordlists) - 1))
                draw_wordlist_view()
            elif btn == "KEY3":
                phase = "browser"
                with lock:
                    target_file = None
                    status_msg = "Select a target file"
                draw_browser_view()

        # ---- Cracking / results phase ----
        elif phase in ("cracking", "results"):
            if btn == "KEY1" and phase == "cracking":
                kill_crack_proc()
                with lock:
                    status_msg = "Stopped by user"
                    phase = "results"
                draw_cracking_view()
            elif btn == "KEY2" and phase == "results":
                if target_file:
                    fname = export_result(target_file["name"])
                    with lock:
                        status_msg = f"Saved: {fname[:18]}" if fname else "No key to export"
                    draw_cracking_view()
                time.sleep(0.3)
            elif btn == "OK" and phase == "results":
                phase = "browser"
                kill_crack_proc()
                with lock:
                    target_file = None
                    status_msg = "Select a target file"
                draw_browser_view()
            else:
                draw_cracking_view()

    # Cleanup
    kill_crack_proc()
    LCD.LCD_Clear()
    GPIO.cleanup()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
