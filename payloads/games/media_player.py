#!/usr/bin/env python3
"""
KTOx Video Player – Universal Bluetooth Audio
===============================================
- Auto-detects Bluetooth sinks
- Includes Bluetooth management (scan, pair, connect)
- Smooth 10fps video on LCD
- Clean exit with KEY3
"""

import os, sys, time, subprocess
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Hardware setup
# ----------------------------------------------------------------------
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
VIDEO_EXTS = ('.mp4','.avi','.mkv','.mov','.webm')
START_DIR = "/root/Videos"

GPIO.setmode(GPIO.BCM)
for p in PINS.values(): GPIO.setup(p, GPIO.IN, GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128
try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",9)
except: font = ImageFont.load_default()

def draw_screen(lines, title="VIDEO", title_color="#8B0000"):
    img = Image.new("RGB", (W,H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill=title_color)
    d.text((4,3), title[:20], font=font, fill="#FF3333")
    y = 20
    for line in lines[:6]:
        d.text((4,y), line[:23], font=font, fill="#FFBBBB")
        y += 12
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "UP/DN OK LEFT K2=BT K3=exit", font=font, fill="#FF7777")
    LCD.LCD_ShowImage(img,0,0)

def wait_btn():
    for _ in range(50):
        for n,p in PINS.items():
            if GPIO.input(p)==0:
                time.sleep(0.05)
                return n
        time.sleep(0.01)
    return None

# ----------------------------------------------------------------------
# Bluetooth management
# ----------------------------------------------------------------------
def bt_cmd(cmd):
    subprocess.run(["bluetoothctl", cmd], capture_output=True)

def get_paired_devices():
    out = subprocess.run(["bluetoothctl","devices"], capture_output=True, text=True).stdout
    devs = []
    for line in out.splitlines():
        if line.startswith("Device "):
            parts = line.split(" ",2)
            if len(parts)>=3: devs.append((parts[1], parts[2]))
    return devs

def scan_devices(duration=6):
    bt_cmd("scan off")
    bt_cmd("menu scan"); bt_cmd("transport le"); bt_cmd("back")
    bt_cmd("scan on")
    time.sleep(duration)
    bt_cmd("scan off")
    return get_paired_devices()  # newly discovered appear in devices list

def pair_and_connect(mac):
    bt_cmd(f"pair {mac}"); time.sleep(2)
    bt_cmd(f"trust {mac}")
    bt_cmd(f"connect {mac}"); time.sleep(2)
    # Force A2DP
    cards = subprocess.run("pactl list cards short | grep bluez | cut -f1", shell=True, capture_output=True, text=True).stdout.strip()
    if cards:
        subprocess.run(f"pactl set-card-profile {cards} a2dp-sink", shell=True)
    return True

def get_active_bt_sink():
    """Return the name of the active Bluetooth sink, or None."""
    sinks = subprocess.run("pactl list sinks short", shell=True, capture_output=True, text=True).stdout
    for line in sinks.splitlines():
        if "bluez" in line:
            sink_name = line.split()[1]
            return sink_name
    return None

def bluetooth_menu():
    """Allow user to scan, pair, and connect to Bluetooth speakers."""
    while True:
        devices = get_paired_devices()
        lines = ["BLUETOOTH MENU", "Paired devices:"]
        if devices:
            for i, (mac, name) in enumerate(devices[:4]):
                lines.append(f"{i+1}. {name[:16]}")
        else:
            lines.append("(none)")
        lines.append(""); lines.append("K2=scan  OK=connect  K3=back")
        draw_screen(lines, title="BLUETOOTH", title_color="#004466")
        btn = wait_btn()
        if btn == "KEY3": return
        if btn == "KEY2":
            draw_screen(["Scanning...", "6 sec"], title="SCAN")
            found = scan_devices(6)
            if not found:
                draw_screen(["No new devices"], title="SCAN")
                time.sleep(1.5)
                continue
            # Show found devices and allow pairing
            idx = 0
            while True:
                mac, name = found[idx]
                draw_screen([f"Found:", name[:18], "", f"{idx+1}/{len(found)}", "UP/DOWN OK"], title="PAIR")
                btn2 = wait_btn()
                if btn2 == "UP": idx = (idx-1)%len(found)
                elif btn2 == "DOWN": idx = (idx+1)%len(found)
                elif btn2 == "OK":
                    draw_screen([f"Pairing {name[:15]}..."], title="PAIR")
                    pair_and_connect(mac)
                    draw_screen([f"Connected to {name[:15]}", "Audio ready"], title="SUCCESS")
                    time.sleep(2)
                    return
                elif btn2 == "KEY3": break
        elif btn == "OK" and devices:
            idx = 0
            while True:
                mac, name = devices[idx]
                draw_screen([f"Connect to:", name[:18], "", f"{idx+1}/{len(devices)}", "UP/DOWN OK"], title="CONNECT")
                btn2 = wait_btn()
                if btn2 == "UP": idx = (idx-1)%len(devices)
                elif btn2 == "DOWN": idx = (idx+1)%len(devices)
                elif btn2 == "OK":
                    draw_screen([f"Connecting to {name[:15]}..."], title="CONNECT")
                    bt_cmd(f"connect {mac}")
                    time.sleep(2)
                    pair_and_connect(mac)  # ensures A2DP
                    draw_screen([f"Connected to {name[:15]}", "Audio ready"], title="SUCCESS")
                    time.sleep(2)
                    return
                elif btn2 == "KEY3": break

# ----------------------------------------------------------------------
# File browser
# ----------------------------------------------------------------------
def list_media(path):
    try:
        items = []
        for f in sorted(os.scandir(path), key=lambda x: (not x.is_dir(), x.name.lower())):
            if f.is_dir() or f.name.lower().endswith(VIDEO_EXTS):
                items.append(f)
        return items
    except: return []

def draw_browser(path, entries, sel, scroll):
    lines = [f"Dir: {os.path.basename(path)[:18]}", ""]
    visible = entries[scroll:scroll+5]
    for i,e in enumerate(visible):
        idx = scroll+i
        marker = ">" if idx==sel else " "
        name = e.name[:18] + ("/" if e.is_dir() else "")
        lines.append(f"{marker} {name}")
    if not entries: lines.append("(empty)")
    draw_screen(lines, title="FILE BROWSER", title_color="#004466")

# ----------------------------------------------------------------------
# Video player with auto Bluetooth sink detection
# ----------------------------------------------------------------------
def play_video(path):
    # Ensure A2DP is active
    cards = subprocess.run("pactl list cards short | grep bluez | cut -f1", shell=True, capture_output=True, text=True).stdout.strip()
    if cards:
        subprocess.run(f"pactl set-card-profile {cards} a2dp-sink", shell=True)
        time.sleep(0.5)
    # Get the active Bluetooth sink
    sink = get_active_bt_sink()
    if not sink:
        draw_screen(["No Bluetooth sink", "Connect speaker first", "Press KEY2 for BT menu"])
        time.sleep(2)
        return
    # ffmpeg command: video to LCD, audio to Bluetooth sink
    cmd = ["ffmpeg","-i",path,"-vf","scale=128:128,fps=10","-pix_fmt","rgb24","-f","rawvideo","-","-f","pulse","-device",sink]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_size = 128*128*3
    draw_screen(["Playing...", os.path.basename(path)[:18]], title="VIDEO")
    while True:
        if wait_btn() == "KEY3":
            proc.terminate()
            break
        raw = proc.stdout.read(frame_size)
        if len(raw) < frame_size: break
        try:
            img = Image.frombytes("RGB", (128,128), raw)
            LCD.LCD_ShowImage(img, 0, 0)
        except: pass
    proc.wait()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    # Create default video directory if not exists
    if not os.path.exists(START_DIR):
        os.makedirs(START_DIR, exist_ok=True)
    path = START_DIR
    entries = list_media(path)
    sel = 0
    scroll = 0
    while True:
        draw_browser(path, entries, sel, scroll)
        btn = wait_btn()
        if btn == "KEY3": break
        if btn == "UP" and sel > 0:
            sel -= 1
            if sel < scroll: scroll = sel
        if btn == "DOWN" and entries and sel < len(entries)-1:
            sel += 1
            if sel >= scroll+5: scroll = sel-4
        if btn == "LEFT":
            parent = os.path.dirname(path)
            if parent != path:
                path = parent
                entries = list_media(path)
                sel = 0; scroll = 0
        if btn == "KEY2":
            bluetooth_menu()
            entries = list_media(path)
        if btn == "OK" and entries:
            e = entries[sel]
            if e.is_dir():
                path = e.path
                entries = list_media(path)
                sel = 0; scroll = 0
            else:
                play_video(e.path)
                entries = list_media(path)
    LCD.LCD_Clear()
    GPIO.cleanup()
    sys.exit(0)

if __name__ == "__main__":
    # Check dependencies
    if os.system("which ffmpeg >/dev/null 2>&1") != 0:
        draw_screen(["ffmpeg missing","sudo apt install ffmpeg","KEY3 exit"], title="ERROR")
        while wait_btn() != "KEY3": pass
        sys.exit(1)
    main()
