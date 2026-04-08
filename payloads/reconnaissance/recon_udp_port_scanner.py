#!/usr/bin/env python3
"""
KTOx *payload* – **UDP Port Scanner**
========================================
This payload performs a basic UDP port scan on a target IP address to identify
open or filtered UDP ports. It sends UDP packets to a list of specified ports
and analyzes the responses (or lack thereof) to determine port status.

Features:
- Interactive UI for entering the target IP address.
- Interactive UI for entering a comma-separated list of ports to scan.
- Scans specified UDP ports and displays open/filtered ports on the LCD.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start UDP port scan.
    - KEY1: Edit target IP.
    - KEY2: Edit ports to scan.
    - KEY3: Exit Payload.
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm IP.
    - KEY3: Cancel input.
- PORTS INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm ports.
    - KEY3: Cancel input.
"""
import sys
import os
import time
import signal
import subprocess
import threading
import socket
# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from scapy.all import *
conf.verb = 0

TARGET_IP = "192.168.1.1"
PORTS_TO_SCAN = [53, 67, 68, 123, 161, 162, 500]
running = True
scan_thread = None
open_ports = []
ui_lock = threading.Lock()
status_msg = "Press OK to scan"
current_ip_input = TARGET_IP
ip_input_cursor_pos = 0
current_ports_input = ",".join(map(str, PORTS_TO_SCAN))
ports_input_cursor_pos = 0

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

# Loot directory under KTOx
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'UDP_Port_Scanner')

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (128, 128), "black")
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

def draw_ui(screen_state="main"):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "UDP Port Scanner", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if screen_state == "main":
        d.text((5, 25), "Target IP:", font=FONT, fill="white")
        d.text((5, 40), TARGET_IP, font=FONT_TITLE, fill="yellow")
        d.text((5, 60), "Ports:", font=FONT, fill="white")
        d.text((5, 75), ",".join(map(str, PORTS_TO_SCAN))[:16] + "...", font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "OK=Scan | KEY1=Edit IP | KEY2=Edit Ports | KEY3=Exit", font=FONT, fill="cyan")
    elif screen_state == "scanning":
        d.text((5, 50), "Scanning...", font=FONT_TITLE, fill="yellow")
        d.text((5, 70), f"Target: {TARGET_IP}", font=FONT, fill="white")
        d.text((5, 115), "KEY3=Stop", font=FONT, fill="cyan")
    elif screen_state == "results":
        d.text((5, 25), f"Open/Filtered: {len(open_ports)}", font=FONT, fill="yellow")
        y_pos = 40
        for port in open_ports[-7:]:
            d.text((10, y_pos), f"Port {port} is open", font=FONT, fill="white")
            y_pos += 11
        d.text((5, 115), "OK=Scan | KEY3=Exit", font=FONT, fill="cyan")
    
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
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), "Enter Target IP", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        
        # Display the current input
        d.text((5, 40), f"IP: {input_ip}", font=FONT, fill="white")
        
        # Display the character selection
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

def handle_ports_input_logic(initial_ports_str):
    # The character set for port numbers input
    char_set = "0123456789,"
    char_index = 0
    
    input_ports = ""
    
    while running:
        # Draw the UI for port input
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), "Enter Target Ports", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        
        # Display the current input
        d.text((5, 40), f"Ports: {input_ports}", font=FONT, fill="white")
        
        # Display the character selection
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
            input_ports += char_set[char_index]
            time.sleep(0.2)

        if btn == "KEY1": # Backspace
            input_ports = input_ports[:-1]
            time.sleep(0.2)

        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)

        # Let's use KEY2 to confirm the ports
        if GPIO.input(PINS["KEY2"]) == 0:
            if input_ports:
                try:
                    ports = [int(p.strip()) for p in input_ports.split(',') if p.strip().isdigit()]
                    if all(1 <= p <= 65535 for p in ports):
                        return input_ports
                    else:
                        show_message(["Invalid Port Range!", "1-65535 only."], "red")
                        time.sleep(2)
                except ValueError:
                    show_message(["Invalid Format!", "Use comma-sep", "numbers."], "red")
                    time.sleep(2)
            else:
                show_message(["Input cannot", "be empty!"], "red")
                time.sleep(2)
        
        time.sleep(0.1)
    return None

def run_scan():
    global open_ports, status_msg
    with ui_lock:
        status_msg = f"Scanning {TARGET_IP}..."
        open_ports = []

    for port in PORTS_TO_SCAN:
        if not running: break
        with ui_lock:
            status_msg = f"Scanning Port: {port}"
        
        try:
            p = IP(dst=TARGET_IP)/UDP(dport=port)
            resp = sr1(p, timeout=2, verbose=0)
            
            if resp is None:
                with ui_lock:
                    if port not in open_ports:
                        open_ports.append(port)
            elif resp.haslayer(ICMP) and resp[ICMP].type == 3 and resp[ICMP].code == 3:
                pass
            else:
                with ui_lock:
                    if port not in open_ports:
                        open_ports.append(port)

        except Exception as e:
            print(f"Scapy error on port {port}: {e}", file=sys.stderr)
            
    with ui_lock:

        status_msg = "Scan Finished"
    # Save results to loot
    try:
        os.makedirs(LOOT_DIR, exist_ok=True)
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f'scan_{TARGET_IP}_{ts}.txt')
        with open(loot_file, 'w') as f:
            for p in open_ports:
                f.write(f'{p}\n')
    except Exception as e:
        print(f'[WARN] Failed to write loot: {e}', file=sys.stderr)

if __name__ == '__main__':
    last_scan_results = []
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds
        while running:
            current_time = time.time()
            
            if scan_thread and scan_thread.is_alive():
                draw_ui("scanning")
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                time.sleep(0.1)
            elif open_ports:
                draw_ui("results")
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    open_ports = []
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    scan_thread = threading.Thread(target=run_scan, daemon=True)
                    scan_thread.start()
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
                    scan_thread = threading.Thread(target=run_scan, daemon=True)
                    scan_thread.start()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_ip = handle_ip_input_logic(TARGET_IP)
                    if new_ip:
                        TARGET_IP = new_ip
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_ports_str = handle_ports_input_logic(",".join(map(str, PORTS_TO_SCAN)))
                    if new_ports_str:
                        try:
                            parsed_ports = [int(p.strip()) for p in new_ports_str.split(',') if p.strip().isdigit()]
                            if all(1 <= p <= 65535 for p in parsed_ports):
                                PORTS_TO_SCAN = parsed_ports
                            else:
                                show_message(["Invalid Port Range!", "1-65535 only."], "red")
                                time.sleep(2)
                        except ValueError:
                            show_message(["Invalid Format!", "Use comma-sep", "numbers."], "red")
                            time.sleep(2)
                    time.sleep(BUTTON_DEBOUNCE_TIME)

            time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("UDP Port Scanner payload finished.")