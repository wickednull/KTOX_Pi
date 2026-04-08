#!/usr/bin/env python3
"""
KTOx *payload* – **Find FTP Servers**
========================================
This payload scans the local network for active FTP servers (port 21).
It performs a basic port scan on all hosts within the local subnet to
identify machines running an FTP service.

Features:
- Interactive UI for selecting the network interface to scan.
- Allows editing of the target FTP port (default 21).
- Scans all hosts in the local subnet for the specified port.
- Displays found FTP server IP addresses on the LCD.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start scanning for FTP servers.
    - KEY1: Select network interface.
    - KEY2: Edit target FTP port.
    - KEY3: Exit Payload.
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate interfaces.
    - OK: Select interface.
    - KEY3: Cancel selection.
- PORT INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm port.
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
# Also add wifi subdir if present
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from wifi.ktox_integration import get_available_interfaces
from wifi.wifi_manager import WiFiManager

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

FTP_PORT = 21
ETH_INTERFACE = "eth0"
running = True
scan_thread = None
ftp_servers = []
ui_lock = threading.Lock()
status_msg = "Press OK to scan"
selected_index = 0
current_interface_input = ETH_INTERFACE
interface_input_cursor_pos = 0
current_port_input = str(FTP_PORT)
port_input_cursor_pos = 0
wifi_manager = WiFiManager()

# Loot directory under KTOx
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'FTP_Servers')

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
    global ETH_INTERFACE, status_msg
    
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
    d.text((5, 5), "Find FTP Servers", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if screen_state == "main":
        with ui_lock:
            d.text((5, 25), f"Interface: {ETH_INTERFACE}", font=FONT, fill="white")
            d.text((5, 40), f"Port: {FTP_PORT}", font=FONT, fill="white")
            if "Scanning" in status_msg or "Press" in status_msg:
                d.text((5, 55), status_msg, font=FONT, fill="yellow")
            else:
                d.text((5, 55), f"Servers Found: {len(ftp_servers)}", font=FONT, fill="yellow")
                start_index = max(0, selected_index - 2)
                end_index = min(len(ftp_servers), start_index + 4)
                y_pos = 70
                for i in range(start_index, end_index):
                    color = "yellow" if i == selected_index else "white"
                    d.text((10, y_pos), ftp_servers[i], font=FONT, fill=color)
                    y_pos += 11

        d.text((5, 115), "OK=Scan | KEY1=Edit Iface | KEY2=Edit Port | KEY3=Exit", font=FONT, fill="cyan")
    elif screen_state == "iface_input":
        d.text((5, 30), "Enter Interface:", font=FONT, fill="white")
        display_iface = list(current_interface_input)
        if interface_input_cursor_pos < len(display_iface):
            display_iface[interface_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_iface[:16]), font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill="cyan")
    elif screen_state == "port_input":
        d.text((5, 30), "Enter Port:", font=FONT, fill="white")
        display_port = list(current_port_input)
        if port_input_cursor_pos < len(display_port):
            display_port[port_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_port), font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "UP/DOWN=Digit | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill="cyan")
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_text_input_logic(initial_text, screen_state_name, char_set):
    global current_interface_input, interface_input_cursor_pos, current_port_input, port_input_cursor_pos
    
    if screen_state_name == "iface_input":
        current_input_ref = current_interface_input
        cursor_pos_ref = interface_input_cursor_pos
    else:
        current_input_ref = current_port_input
        cursor_pos_ref = port_input_cursor_pos

    current_input_ref = initial_text
    cursor_pos_ref = len(initial_text) - 1
    
    draw_ui(screen_state_name)
    
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
            if current_input_ref:
                return current_input_ref
            else:
                show_message(["Input cannot", "be empty!"], "red")
                time.sleep(2)
                current_input_ref = initial_text
                cursor_pos_ref = len(initial_text) - 1
                draw_ui(screen_state_name)
        
        if btn == "LEFT":
            cursor_pos_ref = max(0, cursor_pos_ref - 1)
            draw_ui(screen_state_name)
        elif btn == "RIGHT":
            cursor_pos_ref = min(len(current_input_ref), cursor_pos_ref + 1)
            draw_ui(screen_state_name)
        elif btn == "UP" or btn == "DOWN":
            if cursor_pos_ref < len(current_input_ref):
                char_list = list(current_input_ref)
                current_char = char_list[cursor_pos_ref]
                
                try:
                    char_index = char_set.index(current_char)
                    if btn == "UP":
                        char_index = (char_index + 1) % len(char_set)
                    else:
                        char_index = (char_index - 1 + len(char_set)) % len(char_set)
                    char_list[cursor_pos_ref] = char_set[char_index]
                    current_input_ref = "".join(char_list)
                except ValueError:
                    char_list[cursor_pos_ref] = char_set[0]
                    current_input_ref = "".join(char_list)
                draw_ui(screen_state_name)
        
        time.sleep(0.1)
    return None

def run_scan(interface):
    global ftp_servers, status_msg, selected_index, ETH_INTERFACE, FTP_PORT
    with ui_lock:
        status_msg = "Scanning network..."
        ftp_servers = []
        selected_index = 0

    try:
        try:
            ip_output = subprocess.check_output(f"ip -o -4 addr show {interface}", shell=True).decode()
            if "inet " not in ip_output:
                with ui_lock: status_msg = f"{interface} No IP!"
                return
            network_range_str = ip_output.split("inet ")[1].split(" ")[0]
        except subprocess.CalledProcessError:
            with ui_lock: status_msg = f"{interface} not found!"
            return
        
        from ipaddress import ip_network
        network = ip_network(network_range_str, strict=False)
        
        socket.setdefaulttimeout(0.2)
        for ip in network.hosts():
            if not running: break
            ip_str = str(ip)
            with ui_lock: status_msg = f"Scanning: {ip_str}"
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if sock.connect_ex((ip_str, FTP_PORT)) == 0:
                    with ui_lock:
                        if ip_str not in ftp_servers:
                            ftp_servers.append(ip_str)
                sock.close()
            except socket.error:
                pass
            
    except Exception as e:
        with ui_lock: status_msg = "Scan Failed!"
        print(f"Scan failed: {e}", file=sys.stderr)
        
    if running:
        with ui_lock: status_msg = "Scan Finished"
    # Save results to loot
    try:
        os.makedirs(LOOT_DIR, exist_ok=True)
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f'servers_{interface}_{ts}.txt')
        with open(loot_file, 'w') as f:
            for ip in ftp_servers:
                f.write(ip + '\n')
    except Exception as e:
        print(f'[WARN] Failed to write loot: {e}', file=sys.stderr)

if __name__ == "__main__":
    current_screen = "main"
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds
    
        selected_interface = select_interface_menu()
        if not selected_interface:
            show_message(["No interface", "selected!", "Exiting..."], "red")
            time.sleep(3)
            sys.exit(1)
    
        while running:
            current_time = time.time()
            
            if current_screen == "main":
                draw_ui("main")
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    if not (scan_thread and scan_thread.is_alive()):
                        scan_thread = threading.Thread(target=run_scan, args=(selected_interface,), daemon=True)
                        scan_thread.start()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    with ui_lock:
                        if ftp_servers: selected_index = (selected_index - 1) % len(ftp_servers)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    with ui_lock:
                        if ftp_servers: selected_index = (selected_index + 1) % len(ftp_servers)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    show_message(["Interface selection", "is now menu-driven."], "yellow")
                    time.sleep(2)
                    current_screen = "main"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_port_input = str(FTP_PORT)
                    current_screen = "port_input"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "iface_input":
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "port_input":
                char_set = "0123456789"
                new_port = handle_text_input_logic(current_port_input, "port_input", char_set)
                if new_port:
                    FTP_PORT = int(new_port)
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.1)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        show_message(["CRITICAL ERROR:", str(e)[:20]], "red")
        time.sleep(3)
    finally:
        if scan_thread and scan_thread.is_alive():
            scan_thread.join(timeout=1)
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Find FTP Servers payload finished.")