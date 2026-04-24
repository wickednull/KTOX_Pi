#!/usr/bin/env python3
"""
KTOx Payload – WPA/WPA2 Cracker
================================
Author: wickednull

Cracks WPA handshakes (.cap) using aircrack-ng and PMKID hashes
using John the Ripper. Includes a built-in file browser.

Controls:
  OK         – Select file / start cracking
  UP/DOWN    – Scroll lists
  KEY1       – Stop cracking (if running)
  KEY2       – Export cracked key to loot
  KEY3       – Exit / back

Loot: /root/KTOx/loot/CrackedWPA/
"""

import os
import sys
import re
import time
import signal
import threading
import subprocess
from datetime import datetime

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
    print("Hardware not found – exiting")
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

def load_font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

font_sm = load_font(9)
font_md = load_font(11)

# ----------------------------------------------------------------------
# File browser (built-in)
# ----------------------------------------------------------------------
def browse_file(start_path="/", extensions=None):
    """Full-screen file browser – returns selected file path or None."""
    extensions = extensions or []
    current_path = os.path.abspath(start_path)
    history = []
    selected_idx = 0
    scroll = 0
    rows = 8

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

    def draw(entries, sel, sc, path):
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0,0,127,16), fill="#004466")
        header = path if len(path) < 20 else "..." + path[-17:]
        d.text((2,2), header[:20], font=font_sm, fill=(171, 178, 185))
        y = 20
        for i in range(rows):
            idx = sc + i
            if idx >= len(entries):
                break
            name = entries[idx]
            if len(name) > 20:
                name = name[:18] + ".."
            color = "white"
            if idx == sel:
                color = "yellow"
                d.rectangle((0, y-1, WIDTH, y+9), fill="#224466")
            if os.path.isdir(os.path.join(path, name)):
                name = "/" + name
            d.text((4, y), name, font=font_sm, fill=color)
            y += 11
        d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=(10, 0, 0))
        d.text((2, HEIGHT-10), "UP/DOWN OK=sel K3=back", font=font_sm, fill="#AAA")
        LCD.LCD_ShowImage(img, 0, 0)

    def wait_button():
        while True:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    time.sleep(0.05)
                    return name
            time.sleep(0.02)

    while True:
        entries = get_entries(current_path)
        if not entries:
            img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
            d = ImageDraw.Draw(img)
            d.text((4,50), "Empty folder", font=font_sm, fill="red")
            d.text((4,70), "KEY3 to go back", font=font_sm, fill=(86, 101, 115))
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

        draw(entries, selected_idx, scroll, current_path)
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
            if selected_idx >= scroll + rows:
                scroll = selected_idx - rows + 1
        elif btn == "OK":
            selected = entries[selected_idx]
            full = os.path.join(current_path, selected)
            if os.path.isdir(full):
                history.append(current_path)
                current_path = full
                selected_idx = 0
                scroll = 0
            else:
                return full
        time.sleep(0.05)

# ----------------------------------------------------------------------
# Wordlist scanner
# ----------------------------------------------------------------------
def get_wordlists():
    options = []
    default = "/usr/share/john/password.lst"
    rockyou = "/root/KTOx/loot/wordlists/rockyou.txt"
    custom  = "/root/KTOx/loot/wordlists/custom.txt"
    if os.path.isfile(default):
        options.append(("Default", default))
    if os.path.isfile(rockyou):
        options.append(("rockyou", rockyou))
    if os.path.isfile(custom):
        options.append(("Custom", custom))
    if not options:
        options.append(("Default", default))
    return options

# ----------------------------------------------------------------------
# PMKID conversion for John
# ----------------------------------------------------------------------
def convert_pmkid(pmkid_file):
    """Convert hashcat 16800 format to John wpapsk format."""
    try:
        with open(pmkid_file, 'r') as f:
            line = f.readline().strip()
        parts = line.split('*')
        if len(parts) >= 4:
            pmkid = parts[0]
            essid_hex = parts[3]
            essid = bytes.fromhex(essid_hex).decode('utf-8', errors='replace')
            temp = "/dev/shm/ktox_pmkid.txt"
            with open(temp, 'w') as f:
                f.write(f"{essid}:{pmkid}")
            return temp
    except:
        pass
    return None

# ----------------------------------------------------------------------
# Cracking threads
# ----------------------------------------------------------------------
cracking = False
crack_proc = None
result = ""
status = "Ready"
selected_file = None
file_type = None   # "CAP" or "PMKID"
wordlist_path = ""
keys_tested = 0
elapsed = 0

def crack_cap(filepath, wl):
    global cracking, result, status, keys_tested, elapsed, crack_proc
    start = time.time()
    status = "Cracking (aircrack)..."
    cmd = ["aircrack-ng", "-w", wl, filepath]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        crack_proc = proc
        key_re = re.compile(r"KEY FOUND!\s*\[\s*(.+?)\s*\]")
        prog_re = re.compile(r"\[\d+:\d+:\d+\]\s+([\d,]+)(?:/[\d,]+)?\s+keys?\s+tested")
        while cracking:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            elapsed = int(time.time() - start)
            m = key_re.search(line)
            if m:
                result = m.group(1)
                status = "KEY FOUND!"
                break
            m = prog_re.search(line)
            if m:
                raw = m.group(1).replace(",", "")
                try:
                    keys_tested = int(raw)
                except:
                    pass
        proc.wait(timeout=2)
    except Exception as e:
        status = f"Error: {str(e)[:18]}"
    finally:
        crack_proc = None
        if not result:
            status = "Key not found"
        cracking = False

def crack_pmkid(filepath, wl):
    global cracking, result, status, elapsed, crack_proc
    start = time.time()
    status = "Converting PMKID..."
    john_input = convert_pmkid(filepath)
    if not john_input:
        status = "Unsupported PMKID"
        cracking = False
        return
    status = "Cracking (John)..."
    cmd = ["john", "--format=wpapsk", f"--wordlist={wl}", john_input]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        crack_proc = proc
        crack_re = re.compile(r"^(.+?)\s+\(.+?\)\s*$")
        while cracking:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            elapsed = int(time.time() - start)
            m = crack_re.match(line.rstrip())
            if m:
                result = m.group(1).strip()
                status = "KEY FOUND!"
                break
        proc.wait(timeout=2)
    except Exception as e:
        status = f"Error: {str(e)[:18]}"
    finally:
        crack_proc = None
        if not result:
            status = "Key not found"
        cracking = False

def start_cracking():
    global cracking, result, keys_tested, elapsed, status
    if not selected_file:
        status = "No file selected"
        return
    wl = wordlist_path
    if not os.path.exists(wl):
        status = "Wordlist missing"
        return
    cracking = True
    result = ""
    keys_tested = 0
    elapsed = 0
    if file_type == "CAP":
        threading.Thread(target=crack_cap, args=(selected_file, wl), daemon=True).start()
    else:
        threading.Thread(target=crack_pmkid, args=(selected_file, wl), daemon=True).start()

def stop_cracking():
    global cracking, crack_proc
    cracking = False
    if crack_proc:
        try:
            os.kill(crack_proc.pid, signal.SIGTERM)
            crack_proc.wait(timeout=2)
        except:
            pass
        crack_proc = None

def export_result():
    if not result:
        return None
    os.makedirs("/root/KTOx/loot/CrackedWPA", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"/root/KTOx/loot/CrackedWPA/cracked_{ts}.txt"
    with open(out, "w") as f:
        f.write(f"File: {selected_file}\nKey: {result}\nDate: {datetime.now().isoformat()}\n")
    return out

# ----------------------------------------------------------------------
# UI drawing
# ----------------------------------------------------------------------
def draw_main():
    img = Image.new("RGB", (WIDTH, HEIGHT), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,127,17), fill="#8B0000")
    d.text((4,3), "WPA CRACKER", font=font_sm, fill=(231, 76, 60))
    d.text((4,20), f"File: {os.path.basename(selected_file) if selected_file else 'None'}", font=font_sm, fill=(171, 178, 185))
    d.text((4,32), f"Type: {file_type if file_type else '-'}", font=font_sm, fill=(171, 178, 185))
    d.text((4,44), f"Wordlist: {os.path.basename(wordlist_path) if wordlist_path else 'None'}", font=font_sm, fill=(171, 178, 185))
    d.text((4,56), f"Status: {status}", font=font_sm, fill=(171, 178, 185))
    if cracking:
        d.text((4,68), f"Keys: {keys_tested}  Time: {elapsed}s", font=font_sm, fill=(171, 178, 185))
    if result:
        d.text((4,84), f"KEY: {result[:16]}", font=font_sm, fill="#88FF88")
    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill="#220000")
    d.text((4, HEIGHT-10), "K1=Sel K2=Crack K3=Exit", font=font_sm, fill="#FF7777")
    if cracking:
        d.text((70, HEIGHT-10), "K1=Stop", font=font_sm, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_wordlist_menu(wl_list, sel_idx):
    img = Image.new("RGB", (WIDTH, HEIGHT), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,127,17), fill="#8B0000")
    d.text((4,3), "SELECT WORDLIST", font=font_sm, fill=(231, 76, 60))
    y = 24
    for i, (name, _) in enumerate(wl_list):
        color = "#FF5555" if i == sel_idx else "#FFAAAA"
        d.text((8, y), f"{'>' if i==sel_idx else ' '} {name}", font=font_sm, fill=color)
        y += 12
    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill="#220000")
    d.text((4, HEIGHT-10), "UP/DOWN  OK  K3=Cancel", font=font_sm, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def main():
    global selected_file, file_type, wordlist_path, status, cracking
    # Initial state
    draw_main()
    state = "main"  # main, wordlist_sel

    while True:
        # Read button
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                time.sleep(0.05)
                break
        if not btn:
            time.sleep(0.05)
            continue

        # Global exit
        if btn == "KEY3":
            if state == "wordlist_sel":
                state = "main"
                draw_main()
                continue
            else:
                break

        if state == "main":
            if btn == "KEY1":
                if cracking:
                    stop_cracking()
                    status = "Stopped"
                    draw_main()
                else:
                    # File browser
                    ext = [".cap", ".pcap", ".pmkid", ".16800", ".txt"]
                    f = browse_file("/root/KTOx/loot", extensions=ext)
                    if f:
                        selected_file = f
                        if f.lower().endswith(".cap"):
                            file_type = "CAP"
                        else:
                            file_type = "PMKID"
                        status = "File selected"
                        # Now ask for wordlist
                        wl_list = get_wordlists()
                        if wl_list:
                            state = "wordlist_sel"
                            wl_idx = 0
                            draw_wordlist_menu(wl_list, wl_idx)
                            # Inner loop for wordlist selection
                            while state == "wordlist_sel":
                                btn2 = None
                                for n, p in PINS.items():
                                    if GPIO.input(p) == 0:
                                        btn2 = n
                                        time.sleep(0.05)
                                        break
                                if not btn2:
                                    time.sleep(0.05)
                                    continue
                                if btn2 == "KEY3":
                                    state = "main"
                                    draw_main()
                                    break
                                elif btn2 == "UP":
                                    wl_idx = (wl_idx - 1) % len(wl_list)
                                    draw_wordlist_menu(wl_list, wl_idx)
                                elif btn2 == "DOWN":
                                    wl_idx = (wl_idx + 1) % len(wl_list)
                                    draw_wordlist_menu(wl_list, wl_idx)
                                elif btn2 == "OK":
                                    wordlist_path = wl_list[wl_idx][1]
                                    status = "Wordlist set"
                                    state = "main"
                                    draw_main()
                                    break
                        else:
                            status = "No wordlists"
                            draw_main()
                    else:
                        draw_main()
            elif btn == "KEY2":
                if not cracking and selected_file and wordlist_path:
                    start_cracking()
                    draw_main()
                elif cracking:
                    # Already cracking, ignore
                    pass
                else:
                    status = "Select file & wordlist first"
                    draw_main()
            draw_main()

        time.sleep(0.05)

    # Cleanup
    stop_cracking()
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
