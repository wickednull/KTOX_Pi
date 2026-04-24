#!/usr/bin/env python3
"""
KTOx Payload – Bluetooth Audio Manager
=======================================
Scan, pair, connect, and automatically set up A2DP audio sink.
No manual terminal commands needed.

Controls:
  UP/DOWN – navigate
  OK      – select / pair+connect
  KEY2    – scan for devices
  KEY3    – exit
"""

import os
import sys
import time
import subprocess
import re
import select

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
    print("Hardware not found")
    sys.exit(1)

PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26,
        "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

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

def draw_screen(lines, title="BT AUDIO", title_color="#8B0000"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill=title_color)
    d.text((4,3), title[:20], font=f9, fill=(231, 76, 60))
    y = 20
    for line in lines[:7]:
        d.text((4,y), line[:23], font=f9, fill=(171, 178, 185))
        y += 12
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "UP/DN OK K2=scan K3=exit", font=f9, fill="#FF7777")
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
# Bluetooth helpers
# ----------------------------------------------------------------------
def bt_cmd(cmd):
    try:
        proc = subprocess.run(["bluetoothctl", cmd], capture_output=True, text=True, timeout=10)
        return proc.stdout + proc.stderr
    except:
        return ""

def scan_devices(duration=8):
    draw_screen(["Scanning...", f"{duration} seconds"], title="BT SCAN")
    bt_cmd("scan off")
    bt_cmd("menu scan")
    bt_cmd("transport le")
    bt_cmd("back")
    bt_cmd("scan on")
    time.sleep(duration)
    bt_cmd("scan off")
    out = bt_cmd("devices")
    devices = []
    for line in out.splitlines():
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                devices.append((parts[1], parts[2]))
    # deduplicate by MAC
    seen = set()
    unique = []
    for mac, name in devices:
        if mac not in seen:
            seen.add(mac)
            unique.append((mac, name))
    return unique

def pair_and_connect(mac):
    draw_screen([f"Pairing {mac[:17]}", "Please wait..."])
    # Use bluetoothctl in interactive mode for reliable pairing
    proc = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    proc.stdin.write("power on\n")
    time.sleep(0.5)
    proc.stdin.write("agent on\n")
    proc.stdin.write("default-agent\n")
    proc.stdin.write(f"pair {mac}\n")
    time.sleep(5)
    proc.stdin.write(f"trust {mac}\n")
    time.sleep(1)
    proc.stdin.write(f"connect {mac}\n")
    time.sleep(5)
    proc.stdin.write("quit\n")
    proc.wait(timeout=10)
    return True

def setup_audio_sink():
    """Ensure PulseAudio is configured for A2DP and set default sink."""
    # Install missing module if needed
    subprocess.run("pactl load-module module-bluez5-discover 2>/dev/null", shell=True)
    # Find Bluetooth sink
    sinks = subprocess.run("pactl list sinks short", shell=True, capture_output=True, text=True).stdout
    sink_name = None
    for line in sinks.splitlines():
        if "bluez" in line:
            sink_name = line.split()[1]
            break
    if sink_name:
        subprocess.run(f"pactl set-default-sink {sink_name}", shell=True)
        # Set profile to a2dp-sink for the card
        cards = subprocess.run("pactl list cards short", shell=True, capture_output=True, text=True).stdout
        for line in cards.splitlines():
            if "bluez" in line:
                card_id = line.split()[0]
                subprocess.run(f"pactl set-card-profile {card_id} a2dp-sink", shell=True)
        return True
    return False

def test_audio():
    """Play a short test tone."""
    subprocess.run("speaker-test -t sine -f 1000 -c 2 -l 1 -D default", shell=True, stderr=subprocess.DEVNULL)

def get_paired_devices():
    out = bt_cmd("devices")
    devices = []
    for line in out.splitlines():
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                devices.append((parts[1], parts[2]))
    return devices

# ----------------------------------------------------------------------
# Main UI
# ----------------------------------------------------------------------
def main():
    # Ensure PulseAudio is running
    subprocess.run("pulseaudio --start", shell=True)
    # Load Bluetooth module
    subprocess.run("pactl load-module module-bluez5-discover", shell=True)

    while True:
        # Show paired devices
        paired = get_paired_devices()
        lines = ["Paired devices:"]
        if paired:
            for i, (mac, name) in enumerate(paired[:4]):
                lines.append(f"{i+1}. {name[:15]}")
        else:
            lines.append("(none)")
        lines.append("")
        lines.append("KEY2=Scan  OK=Connect")
        draw_screen(lines, title="BT AUDIO")
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "KEY2":
            devices = scan_devices(8)
            if not devices:
                draw_screen(["No devices found", "KEY3 to continue"])
                while wait_btn(0.5) != "KEY3":
                    pass
                continue
            # Select device
            idx = 0
            while True:
                mac, name = devices[idx]
                draw_screen([f"Select:", name[:18], "", f"{idx+1}/{len(devices)}", "UP/DOWN OK"])
                btn2 = wait_btn(0.5)
                if btn2 == "UP":
                    idx = (idx - 1) % len(devices)
                elif btn2 == "DOWN":
                    idx = (idx + 1) % len(devices)
                elif btn2 == "OK":
                    pair_and_connect(mac)
                    draw_screen(["Connected", name, "Setting up audio..."])
                    time.sleep(2)
                    if setup_audio_sink():
                        draw_screen(["Audio sink ready", "Testing...", name])
                        test_audio()
                        draw_screen(["Connected & working!", name, "Press KEY3 to exit"])
                    else:
                        draw_screen(["Audio setup failed", "Check pulseaudio"])
                    while wait_btn(0.5) not in ("KEY3", "KEY1"):
                        pass
                    break
                elif btn2 == "KEY3":
                    break
                time.sleep(0.05)
        elif btn == "OK" and paired:
            # Choose from paired devices
            idx = 0
            while True:
                mac, name = paired[idx]
                draw_screen([f"Connect to:", name[:18], "", f"{idx+1}/{len(paired)}", "UP/DOWN OK"])
                btn2 = wait_btn(0.5)
                if btn2 == "UP":
                    idx = (idx - 1) % len(paired)
                elif btn2 == "DOWN":
                    idx = (idx + 1) % len(paired)
                elif btn2 == "OK":
                    draw_screen([f"Connecting to {name[:15]}..."])
                    bt_cmd(f"connect {mac}")
                    time.sleep(3)
                    setup_audio_sink()
                    draw_screen(["Connected", name, "Audio ready", "Testing..."])
                    test_audio()
                    draw_screen(["Success!", name, "KEY3 to exit"])
                    while wait_btn(0.5) != "KEY3":
                        pass
                    break
                elif btn2 == "KEY3":
                    break
                time.sleep(0.05)

    LCD.LCD_Clear()
    GPIO.cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
EOF
