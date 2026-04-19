#!/usr/bin/env python3
"""
KTOx Diagnostic – Bettercap API Test
"""

import os, sys, time, subprocess, socket, requests
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
except:
    font = ImageFont.load_default()

def draw(lines):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "DIAGNOSTIC", font=font, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        d.text((4,y), line[:23], font=font, fill="#FFBBBB")
        y += 12
    d.rectangle((0,H-12,W,H), fill="#220000")
    d.text((4,H-10), "K3=Exit", font=font, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def wait_btn():
    for _ in range(50):
        for n,p in PINS.items():
            if GPIO.input(p) == 0:
                time.sleep(0.05)
                return n
        time.sleep(0.01)
    return None

def main():
    draw(["Testing bettercap API...", "Starting bettercap"])
    # Start bettercap with API on port 8081
    proc = subprocess.Popen(["bettercap", "-eval", "set api.rest true; set api.rest.port 8081; events.stream off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    # Check if port is open
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8081))
    sock.close()
    if result == 0:
        draw(["Port 8081 OPEN", "Testing session endpoint..."])
        try:
            r = requests.get("http://127.0.0.1:8081/api/session", timeout=2)
            draw([f"Session OK (HTTP {r.status_code})", "Bettercap API works!"])
            time.sleep(3)
        except Exception as e:
            draw([f"Session error: {str(e)[:20]}", "API may need auth"])
    else:
        draw([f"Port 8081 CLOSED", "Bettercap API not started", "Check bettercap install", "Try: sudo bettercap"])
    proc.terminate()
    while wait_btn() != "KEY3":
        time.sleep(0.1)
    GPIO.cleanup()

if __name__ == "__main__":
    main()
