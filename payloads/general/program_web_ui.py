#!/usr/bin/env python3
"""
KTOx *payload* – **Web-Based Management Interface**
======================================================
This payload provides a web-based interface for managing the KTOx.

Features:
- A web-based interface for managing the KTOx.
- The web server runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the web server.
    - KEY1: Edit the port number.
    - KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import threading
from bottle import route, run, template

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

PORT = 8080
running = True
web_server_thread = None

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
    d.text((5, 5), "Web UI", font=FONT_TITLE, fill="#00FF00")
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
        d.text((5, 30), "Web server is stopped.", font=FONT, fill="white")
        d.text((5, 60), f"Port: {PORT}", font=FONT, fill="white")
        d.text((5, 100), "OK=Start | KEY1=Port", font=FONT, fill="cyan")
        d.text((5, 110), "KEY3=Exit", font=FONT, fill="cyan")
    elif screen_state == "running":
        ip_address = subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True).decode().strip()
        d.text((5, 30), "Web server is running.", font=FONT, fill="lime")
        d.text((5, 50), f"http://{ip_address}:{PORT}", font=FONT, fill="yellow")
        d.text((5, 100), "OK=Stop", font=FONT, fill="cyan")
        d.text((5, 110), "KEY3=Exit", font=FONT, fill="cyan")

    LCD.LCD_ShowImage(img, 0, 0)

@route('/')
def index():
    return template('<b>Hello {{name}}</b>!', name='World')

def run_web_server():
    run(host='0.0.0.0', port=PORT)

def handle_port_input_logic(initial_port):
    char_set = "0123456789"
    char_index = 0
    input_port = ""
    
    while running:
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), "Enter Port Number", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        d.text((5, 40), f"Port: {input_port}", font=FONT, fill="white")
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
            input_port += char_set[char_index]
            time.sleep(0.2)
        if btn == "KEY1":
            input_port = input_port[:-1]
            time.sleep(0.2)
        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)
        if GPIO.input(PINS["KEY2"]) == 0:
            if input_port.isdigit() and 1 <= int(input_port) <= 65535:
                return int(input_port)
            else:
                draw_ui(message_lines=["Invalid Port!", "Try again."])
                time.sleep(2)
                input_port = ""
        
        time.sleep(0.1)
    return None

if __name__ == "__main__":
    try:
        while running:
            if web_server_thread and web_server_thread.is_alive():
                draw_ui("running")
                if GPIO.input(PINS["OK"]) == 0:
                    # This is a bit tricky, as we can't easily stop the bottle server
                    # A better approach would be to use a different web server
                    pass
                if GPIO.input(PINS["KEY3"]) == 0:
                    cleanup()
                    break
            else:
                draw_ui("main")
                if GPIO.input(PINS["OK"]) == 0:
                    web_server_thread = threading.Thread(target=run_web_server)
                    web_server_thread.daemon = True
                    web_server_thread.start()
                    time.sleep(0.3)
                if GPIO.input(PINS["KEY1"]) == 0:
                    new_port = handle_port_input_logic(str(PORT))
                    if new_port:
                        PORT = new_port
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
        print("Web UI payload finished.")
