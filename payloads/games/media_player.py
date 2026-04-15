#!/usr/bin/env python3
"""
KTOx Payload – Video Player with Bluetooth Audio
=================================================
- Plays videos on the 128x128 LCD using ffmpeg
- Manages Bluetooth speakers/headphones (scan, pair, connect, set as audio sink)
- Clean exit – no freezing

Controls:
  File browser:
    UP/DOWN   – navigate
    LEFT      – parent directory
    OK        – play video
    KEY2      – open Bluetooth menu
    KEY3      – exit

  Bluetooth menu:
    UP/DOWN   – select device/action
    OK        – pair/connect or perform action
    KEY2      – scan for devices (uses LE transport)
    KEY3      – back to file browser

Dependencies: ffmpeg, bluez, pulseaudio, pulseaudio-module-bluetooth
Install: sudo apt install ffmpeg bluez pulseaudio pulseaudio-module-bluetooth
"""

import os
import sys
import time
import subprocess
import threading
import re

# ----------------------------------------------------------------------
# Hardware
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

PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26,
        "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.webm'}
START_DIRS = ["/media", "/home", "/root", "/tmp"]

# ----------------------------------------------------------------------
# LCD
# ----------------------------------------------------------------------
LCD = None
image = None
draw = None
font_sm = None

def init_lcd():
    global LCD, image, draw, font_sm
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()
    image = Image.new("RGB", (128, 128), "black")
    draw = ImageDraw.Draw(image)
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except:
        font_sm = ImageFont.load_default()

def draw_screen(lines, title="VIDEO PLAYER", title_color="#8B0000"):
    draw.rectangle((0,0,128,128), fill="#0A0000")
    draw.rectangle((0,0,128,17), fill=title_color)
    draw.text((4,3), title[:20], font=font_sm, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        draw.text((4,y), line[:23], font=font_sm, fill="#FFBBBB")
        y += 12
    draw.rectangle((0,128-12,128,128), fill="#220000")
    draw.text((4,128-10), "UP/DN OK LEFT KEY2 KEY3", font=font_sm, fill="#FF7777")
    LCD.LCD_ShowImage(image, 0, 0)

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
# Bluetooth manager (fixed for Pi Zero 2W)
# ----------------------------------------------------------------------
def bluetooth_cmd(cmd):
    """Run a bluetoothctl command and return output."""
    try:
        result = subprocess.run(["bluetoothctl", cmd], capture_output=True, text=True, timeout=10)
        return result.stdout + result.stderr
    except:
        return ""

def get_paired_devices():
    """Return list of paired devices as (mac, name)."""
    out = bluetooth_cmd("devices")
    devices = []
    for line in out.splitlines():
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                mac = parts[1]
                name = parts[2]
                devices.append((mac, name))
    return devices

def scan_devices(duration=8):
    """Scan for Bluetooth devices using LE transport (works for most speakers)."""
    bluetooth_cmd("scan off")
    bluetooth_cmd("menu scan")
    bluetooth_cmd("transport le")
    bluetooth_cmd("back")
    bluetooth_cmd("scan on")
    time.sleep(duration)
    bluetooth_cmd("scan off")
    out = bluetooth_cmd("devices")
    devices = []
    for line in out.splitlines():
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                mac = parts[1]
                name = parts[2]
                devices.append((mac, name))
    # Remove duplicates by MAC
    seen = set()
    unique = []
    for mac, name in devices:
        if mac not in seen:
            seen.add(mac)
            unique.append((mac, name))
    return unique

def pair_device(mac):
    bluetooth_cmd(f"pair {mac}")
    time.sleep(2)
    bluetooth_cmd(f"trust {mac}")
    bluetooth_cmd(f"connect {mac}")
    return True

def connect_device(mac):
    bluetooth_cmd(f"connect {mac}")
    return True

def disconnect_device(mac):
    bluetooth_cmd(f"disconnect {mac}")

def set_audio_sink(device_mac):
    """Set PulseAudio default sink to the Bluetooth device."""
    # Find sink name that contains the device MAC (with underscores)
    mac_underscore = device_mac.replace(":", "_")
    sinks = subprocess.run(["pactl", "list", "sinks"], capture_output=True, text=True).stdout
    sink_name = None
    for line in sinks.splitlines():
        if "bluez" in line and mac_underscore in line:
            if "Name:" in line:
                sink_name = line.split("Name:")[1].strip()
                break
    if sink_name:
        subprocess.run(["pactl", "set-default-sink", sink_name])
        return True
    return False

def ensure_audio_module():
    """Make sure pulseaudio-module-bluetooth is loaded."""
    # Check if module-bluez5-discover is loaded
    modules = subprocess.run(["pactl", "list", "short", "modules"], capture_output=True, text=True).stdout
    if "module-bluez5-discover" not in modules:
        subprocess.run(["pactl", "load-module", "module-bluez5-discover"], capture_output=True)

def bluetooth_menu():
    """Full Bluetooth management UI."""
    # Ensure the Bluetooth audio module is loaded
    ensure_audio_module()
    
    # Check if Bluetooth hardware is present
    hci = subprocess.run("hciconfig -a", shell=True, capture_output=True, text=True)
    if "No such device" in hci.stdout or "not available" in hci.stderr:
        draw_screen(["Bluetooth Error:", "No adapter found", "Run: sudo hciconfig hci0 up"], title="ERROR")
        time.sleep(3)
        return

    while True:
        devices = get_paired_devices()
        lines = ["Bluetooth Menu", "", "Paired devices:"]
        for i, (mac, name) in enumerate(devices[:4]):
            lines.append(f"{i+1}. {name[:15]}")
        lines.append("")
        lines.append("KEY2=Scan  OK=Connect  K3=Back")
        draw_screen(lines, title="BLUETOOTH", title_color="#004466")
        btn = wait_btn(0.5)
        if btn == "KEY3":
            return
        elif btn == "KEY2":
            # Scan for devices
            draw_screen(["Scanning for devices...", "Please wait (~8 sec)"], title="BLUETOOTH")
            found = scan_devices(8)
            if not found:
                draw_screen(["No devices found", "Make sure your speaker", "is in pairing mode"], title="SCAN")
                time.sleep(2)
                continue
            # Show found devices and allow pairing
            for idx, (mac, name) in enumerate(found):
                draw_screen([f"Found: {name[:18]}", "", "OK to pair, K3 to skip"], title="BLUETOOTH")
                btn2 = wait_btn(3)
                if btn2 == "OK":
                    pair_device(mac)
                    draw_screen([f"Paired {name[:18]}", "Connecting..."], title="BLUETOOTH")
                    time.sleep(2)
                    set_audio_sink(mac)
                    draw_screen([f"Connected to {name[:18]}", "Audio set"], title="BLUETOOTH")
                    time.sleep(1.5)
                    break
                elif btn2 == "KEY3":
                    continue
        elif btn == "OK" and devices:
            # Select device to connect
            idx = 0
            while True:
                mac, name = devices[idx]
                lines = [f"Select device:", f"{name[:18]}", "", "UP/DOWN, OK to connect", "K3 to cancel"]
                draw_screen(lines, title="BLUETOOTH")
                btn2 = wait_btn(0.5)
                if btn2 == "UP":
                    idx = (idx - 1) % len(devices)
                elif btn2 == "DOWN":
                    idx = (idx + 1) % len(devices)
                elif btn2 == "OK":
                    connect_device(mac)
                    set_audio_sink(mac)
                    draw_screen([f"Connected to {name[:18]}", "Audio set"], title="BLUETOOTH")
                    time.sleep(1.5)
                    break
                elif btn2 == "KEY3":
                    break
                time.sleep(0.05)

# ----------------------------------------------------------------------
# File browser
# ----------------------------------------------------------------------
def list_media(path):
    try:
        items = []
        for f in sorted(os.scandir(path), key=lambda x: (not x.is_dir(), x.name.lower())):
            if f.is_dir():
                items.append(f)
            elif f.name.lower().endswith(tuple(VIDEO_EXTS)):
                items.append(f)
        return items
    except:
        return []

def draw_browser(path, entries, sel):
    lines = []
    short = os.path.basename(path) or "/"
    lines.append(f"Dir: {short[:18]}")
    lines.append("")
    start = max(0, sel - 5)
    for i in range(start, min(start+6, len(entries))):
        e = entries[i]
        marker = ">" if i == sel else " "
        name = e.name[:18] + ("/" if e.is_dir() else "")
        lines.append(f"{marker} {name}")
    if not entries:
        lines.append("(empty)")
    draw_screen(lines)

# ----------------------------------------------------------------------
# Video player (clean exit)
# ----------------------------------------------------------------------
playback_active = False
ffmpeg_proc = None

def stop_playback():
    global ffmpeg_proc, playback_active
    if ffmpeg_proc:
        ffmpeg_proc.terminate()
        try:
            ffmpeg_proc.wait(timeout=2)
        except:
            ffmpeg_proc.kill()
        ffmpeg_proc = None
    playback_active = False
    # Reinit LCD after playback
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()

def play_video(video_path):
    global ffmpeg_proc, playback_active
    playback_active = True
    draw.rectangle((0,0,128,128), fill="black")
    draw.text((4,60), "Loading...", font=font_sm, fill="#00FF00")
    LCD.LCD_ShowImage(image, 0, 0)

    # ffmpeg command: decode, scale, output raw RGB, audio goes through PulseAudio
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", "scale=128:128,fps=10",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "-"
    ]
    try:
        ffmpeg_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as e:
        draw_screen([f"FFmpeg error", str(e)[:20]], title="ERROR")
        time.sleep(2)
        playback_active = False
        return

    frame_size = 128 * 128 * 3
    draw.rectangle((0,0,128,128), fill="black")
    LCD.LCD_ShowImage(image, 0, 0)

    while playback_active:
        btn = wait_btn(0.01)
        if btn in ("KEY1", "KEY3"):
            stop_playback()
            break

        raw = ffmpeg_proc.stdout.read(frame_size)
        if len(raw) < frame_size:
            break

        try:
            img = Image.frombytes("RGB", (128, 128), raw)
            LCD.LCD_ShowImage(img, 0, 0)
        except:
            pass

    stop_playback()

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if not HAS_HW:
        return
    init_lcd()

    # Check dependencies
    if os.system("which ffmpeg > /dev/null 2>&1") != 0:
        draw_screen(["ffmpeg not installed", "sudo apt install ffmpeg", "KEY3 to exit"], title="ERROR")
        while wait_btn(0.5) != "KEY3":
            pass
        GPIO.cleanup()
        return

    if os.system("which bluetoothctl > /dev/null 2>&1") != 0:
        draw_screen(["bluetoothctl missing", "sudo apt install bluez", "KEY3 to exit"], title="ERROR")
        while wait_btn(0.5) != "KEY3":
            pass
        GPIO.cleanup()
        return

    # Start directory
    path = "/"
    for d in START_DIRS:
        if os.path.isdir(d):
            path = d
            break
    entries = list_media(path)
    sel = 0

    running = True
    while running:
        draw_browser(path, entries, sel)
        btn = wait_btn(0.5)
        if btn == "KEY3":
            running = False
        elif btn == "UP":
            sel = max(0, sel-1)
        elif btn == "DOWN":
            sel = min(len(entries)-1, sel+1) if entries else 0
        elif btn == "LEFT":
            parent = os.path.dirname(path)
            if parent and parent != path:
                path = parent
                entries = list_media(path)
                sel = 0
        elif btn == "KEY2":
            bluetooth_menu()
            entries = list_media(path)  # refresh after menu
        elif btn == "OK" and entries:
            selected = entries[sel]
            if selected.is_dir():
                path = selected.path
                entries = list_media(path)
                sel = 0
            else:
                play_video(selected.path)
                entries = list_media(path)
        time.sleep(0.05)

    if ffmpeg_proc:
        stop_playback()
    LCD.LCD_Clear()
    GPIO.cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
