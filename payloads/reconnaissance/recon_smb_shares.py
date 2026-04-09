#!/usr/bin/env python3
"""
KTOx *payload* – **SMB Share Scanner**
=========================================
This payload scans a target IP address for accessible Server Message Block (SMB)
shares. It uses the `smbclient` utility to list shares, which can reveal
valuable information about network resources and potential data exfiltration
points.

Features:
- Interactive UI for selecting the network interface.
- Interactive UI for entering the target IP address.
- Uses `smbclient` to enumerate SMB shares.
- Displays found shares on the LCD with scrolling capabilities.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start scanning for SMB shares.
    - KEY1: Edit target IP.
    - KEY3: Exit Payload.
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm IP.
    - KEY3: Cancel input.
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate interfaces.
    - OK: Select interface.
    - KEY3: Cancel selection.
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
# Also add wifi subdir if present
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
def get_available_interfaces():
    try:
        import re as _re, subprocess as _sub
        out = _sub.run(['iw', 'dev'], capture_output=True, text=True, timeout=5).stdout
        return _re.findall(r'Interface (\S+)', out)
    except Exception:
        return []

def set_ktox_interface(iface):
    pass

try:
    from wifi.wifi_manager import WiFiManager
except Exception:
    class WiFiManager:
        def __init__(self): pass
        def get_interface(self): return 'wlan0'
        def get_available_interfaces(self): return get_available_interfaces()
        def connect(self, *a, **kw): return False
        def disconnect(self, *a, **kw): return False

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

TARGET_IP = "192.168.1.10"
running = True
selected_index = 0
shares = []
current_ip_input = TARGET_IP
ip_input_cursor_pos = 0
wifi_manager = WiFiManager()

# Loot directory under KTOx
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'SMB_Shares')

def draw_ui_interface_selection(interfaces, current_selection):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Select Interface", font=FONT_TITLE, fill="cyan")
    d.line([(0, 22), (128, 22)], fill="cyan", width=1)

    y_pos = 25
    for i, iface in enumerate(interfaces):
        color = "yellow" if i == current_selection else "white"
        d.text((5, y_pos), iface, font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 115), "UP/DOWN=Select | OK=Confirm", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def select_interface_menu():
    global status_msg
    
    available_interfaces = get_available_interfaces()
    if not available_interfaces:
        show_message(["No network", "interfaces found!"], "red")
        time.sleep(3)
        return None

    current_menu_selection = 0
    while running:
        draw_ui_interface_selection(available_interfaces, current_menu_selection)
        
        if GPIO.input(PINS["KEY3"]) == 0:
            return None
        
        if GPIO.input(PINS["UP"]) == 0:
            current_menu_selection = (current_menu_selection - 1 + len(available_interfaces)) % len(available_interfaces)
            time.sleep(0.2)
        elif GPIO.input(PINS["DOWN"]) == 0:
            current_menu_selection = (current_menu_selection + 1) % len(available_interfaces)
            time.sleep(0.2)
        elif GPIO.input(PINS["OK"]) == 0:
            selected_iface = available_interfaces[current_menu_selection]
            show_message([f"Selected:", f"{selected_iface}"], "lime")
            time.sleep(1)
            return selected_iface
        
        time.sleep(0.1)

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
    d.text((5, 5), "SMB Share Scanner", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if screen_state == "main":
        d.text((5, 25), "Target IP:", font=FONT, fill="white")
        d.text((5, 40), TARGET_IP, font=FONT_TITLE, fill="yellow")
        
        if not shares:
            d.text((10, 60), "No shares found.", font=FONT, fill="white")
        else:
            d.text((5, 55), f"Shares Found: {len(shares)}", font=FONT, fill="yellow")
            start_index = max(0, selected_index - 2)
            end_index = min(len(shares), start_index + 4)
            y_pos = 70
            for i in range(start_index, end_index):
                color = "yellow" if i == selected_index else "white"
                d.text((10, y_pos), shares[i], font=FONT, fill=color)
                y_pos += 11

        d.text((5, 115), "OK=Scan | KEY1=Edit IP | KEY3=Exit", font=FONT, fill="cyan")
    elif screen_state == "scanning":
        d.text((5, 50), "Scanning...", font=FONT_TITLE, fill="yellow")
        d.text((5, 70), f"Target: {TARGET_IP}", font=FONT, fill="white")
        d.text((5, 115), "KEY3=Stop", font=FONT, fill="cyan")
    
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

def run_scan(interface):
    global shares, selected_index, TARGET_IP
    draw_ui("scanning")
    shares = []
    selected_index = 0
    
    try:
        if set_ktox_interface(interface):
            show_message([f"Interface {interface}", "activated."], "lime")
            time.sleep(1)
        else:
            show_message([f"Failed to activate", f"{interface}."], "red")
            return

        command = f"smbclient -L //{TARGET_IP} -N"
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        
        if proc.returncode == 0:
            for line in proc.stdout.split('\n'):
                if "Disk" in line:
                    share_name = line.split('|')[0].strip()
                    if share_name:
                        shares.append(share_name)
            if not shares:
                shares.append("No shares found")
            # Save to loot
            try:
                os.makedirs(LOOT_DIR, exist_ok=True)
                ts = time.strftime('%Y-%m-%d_%H%M%S')
                loot_file = os.path.join(LOOT_DIR, f"shares_{TARGET_IP}_{ts}.txt")
                with open(loot_file, 'w') as f:
                    for s in shares:
                        f.write(s + "\n")
            except Exception as e:
                print(f"[WARN] Failed to write loot: {e}", file=sys.stderr)
        else:
            if "Connection refused" in proc.stderr:
                shares.append("Connection refused")
            elif "NT_STATUS_HOST_UNREACH" in proc.stderr:
                shares.append("Host unreachable")
            else:
                shares.append("Scan failed")
                print(proc.stderr, file=sys.stderr)

    except Exception as e:
        shares.append("Scan error!")
        print(f"smbclient scan failed: {e}", file=sys.stderr)

if __name__ == '__main__':
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds
    
        if subprocess.run("which smbclient", shell=True, capture_output=True).returncode != 0:
            show_message(["ERROR:", "smbclient", "not found!"], "red")
            time.sleep(3)
            sys.exit(1)
    
        selected_interface = select_interface_menu()
        if not selected_interface:
            show_message(["No interface", "selected!", "Exiting..."], "red")
            time.sleep(3)
            sys.exit(1)
    
        while running:
            current_time = time.time()
            
            draw_ui("main")
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                run_scan(selected_interface)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if shares:
                    selected_index = (selected_index - 1) % len(shares)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if shares:
                    selected_index = (selected_index + 1) % len(shares)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                new_ip = handle_ip_input_logic(TARGET_IP)
                if new_ip:
                    TARGET_IP = new_ip
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.1)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        show_message(["CRITICAL ERROR:", str(e)[:20]], "red")
        time.sleep(3)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("SMB Share payload finished.")