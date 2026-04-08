#!/usr/bin/env python3
"""
KTOx *payload* – **WPA/WPA2 Handshake Cracker**
====================================================
This payload automates the process of cracking WPA/WPA2 handshakes using
hashcat. It allows the user to select a handshake file and a wordlist,
and then starts the cracking process.

Features:
- Interactive UI for selecting a handshake file and a wordlist.
- Uses hashcat to crack the handshake.
- The cracking process runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the cracking process.
    - KEY1: Select the handshake file.
    - KEY2: Select the wordlist.
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

HANDSHAKE_FILE = ""
WORDLIST_FILE = ""
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
    subprocess.run("killall hashcat", shell=True)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "WPA/WPA2 Cracker", font=FONT_TITLE, fill="#00FF00")
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
        d.text((5, 30), f"Handshake: {os.path.basename(HANDSHAKE_FILE)}", font=FONT, fill="white")
        d.text((5, 50), f"Wordlist: {os.path.basename(WORDLIST_FILE)}", font=FONT, fill="white")
        d.text((5, 100), "OK=Start", font=FONT, fill="cyan")
        d.text((5, 110), "KEY1=Handshake | KEY2=Wordlist", font=FONT, fill="cyan")
    elif screen_state == "cracking":
        d.text((5, 50), "Cracking...", font=FONT_TITLE, fill="yellow")
        d.text((5, 70), f"Handshake: {os.path.basename(HANDSHAKE_FILE)}", font=FONT, fill="white")
        d.text((5, 85), f"Wordlist: {os.path.basename(WORDLIST_FILE)}", font=FONT, fill="white")

    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    draw_ui("cracking")
    
    # Command to execute
    command = [
        "hashcat",
        "-m",
        "2500",
        HANDSHAKE_FILE,
        WORDLIST_FILE
    ]
    
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=3600) # 1 hour timeout
        
        if process.returncode == 0:
            draw_ui(message_lines=["Cracking finished!", "Check hashcat potfile."])
        else:
            draw_ui(message_lines=["Cracking failed!", "Check console."])
            print(stderr)
            
    except subprocess.TimeoutExpired:
        draw_ui(message_lines=["Cracking timed out!"])
    except Exception as e:
        draw_ui(message_lines=["Cracking failed!", str(e)])
        
    time.sleep(3)

def handle_file_input_logic(file_type):
    files = []
    if file_type == "Handshake":
        loot_dir = os.path.join(KTOX_ROOT, "loot")
        for root, dirs, filenames in os.walk(loot_dir):
            for filename in filenames:
                if filename.endswith(".pcap") or filename.endswith(".cap"):
                    files.append(os.path.join(root, filename))
    elif file_type == "Wordlist":
        wordlist_dir = os.path.join(KTOX_ROOT, "wordlists")
        for root, dirs, filenames in os.walk(wordlist_dir):
            for filename in filenames:
                if filename.endswith(".txt"):
                    files.append(os.path.join(root, filename))

    if not files:
        draw_ui(message_lines=[f"No {file_type} files found!"])
        time.sleep(2)
        return None

    selected_index = 0
    while running:
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Select {file_type}", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        
        for i, f in enumerate(files):
            color = "yellow" if i == selected_index else "white"
            d.text((5, 30 + i * 15), os.path.basename(f), font=FONT, fill=color)

        d.text((5, 115), "UP/DOWN=Select | OK=Confirm", font=FONT, fill="cyan")
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
            return files[selected_index]
        if btn == "UP":
            selected_index = (selected_index - 1) % len(files)
            time.sleep(0.2)
        if btn == "DOWN":
            selected_index = (selected_index + 1) % len(files)
            time.sleep(0.2)
        
        time.sleep(0.1)
    return None

if __name__ == "__main__":
    try:
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                if HANDSHAKE_FILE and WORDLIST_FILE:
                    attack_thread = threading.Thread(target=run_attack)
                    attack_thread.start()
                    time.sleep(0.3)
                else:
                    draw_ui(message_lines=["Select files first!"])
                    time.sleep(2)
            
            if GPIO.input(PINS["KEY1"]) == 0:
                new_handshake_file = handle_file_input_logic("Handshake")
                if new_handshake_file:
                    HANDSHAKE_FILE = new_handshake_file
                time.sleep(0.3)

            if GPIO.input(PINS["KEY2"]) == 0:
                new_wordlist_file = handle_file_input_logic("Wordlist")
                if new_wordlist_file:
                    WORDLIST_FILE = new_wordlist_file
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
        print("WPA/WPA2 Cracker payload finished.")
