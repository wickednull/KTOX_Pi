#!/usr/bin/env python3
"""
KTOx *payload* – **Full System Cleanup**
===========================================
This payload performs a comprehensive cleanup of the KTOx's network
configuration and running processes. It is designed to stop any active
attack tools, reset network interfaces to their default managed mode,
and flush iptables rules, ensuring the system returns to a clean state.

Features:
- Kills common attack-related processes (e.g., hostapd, dnsmasq, mitmdump).
- Flushes all iptables rules.
- Disables IP forwarding.
- Resets Wi-Fi interfaces (wlan0, wlan1) to managed mode.
- Restarts the DHCP client service.
- Displays status messages on the LCD during cleanup.

Usage:
- This payload is designed to be executed directly.
- No interactive controls after launch, it performs its function and exits.
"""
import sys
import os
import time
import signal
import subprocess
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

PROCESSES_TO_KILL = [
    "hostapd", "dnsmasq", "php", "reaver", "wash", "hcxdumptool",
    "arpspoof", "mitmdump", "ettercap", "aireplay-ng", "airodump-ng",
    "hydra", "nmap"
]

PINS = { "OK": 13, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True

def cleanup_handler(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup_handler)
signal.signal(signal.SIGTERM, cleanup_handler)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    y = 30
    for line in lines:
        d.text((5, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def run_cleanup():
    show_message(["Cleaning up...", "Please wait..."])
    
    for proc in PROCESSES_TO_KILL:
        subprocess.run(f"pkill -f {proc}", shell=True, capture_output=True)
        time.sleep(0.1)
        
    subprocess.run("iptables -F && iptables -t nat -F", shell=True)
    
    subprocess.run("echo 0 > /proc/sys/net/ipv4/ip_forward", shell=True)
    
    subprocess.run("ifconfig wlan0 down && iwconfig wlan0 mode managed && ifconfig wlan0 up", shell=True, capture_output=True)
    subprocess.run("ifconfig wlan1 down && iwconfig wlan1 mode managed && ifconfig wlan1 up", shell=True, capture_output=True)
    
    subprocess.run("systemctl restart dhcpcd", shell=True)
    
    show_message(["Cleanup complete!", "System should be", "back to normal."], "lime")

if __name__ == '__main__':
    try:
        run_cleanup()
        time.sleep(5)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Full Cleanup payload finished.")