#!/usr/bin/env python3
"""
KTOx *payload* – **Nmap Vulnerability Scan**
================================================
This payload performs an Nmap vulnerability scan against a target IP address.
It allows the user to input the target IP and select a network interface
for the scan. The scan runs in a background thread to keep the UI responsive.

Features:
- Interactive UI for entering target IP address.
- Allows selection of network interface for the scan.
- Uses `nmap` with `--script vuln` for vulnerability detection.
- Displays scan status on the LCD.
- Runs Nmap scan in a background thread.
- Graceful exit via KEY3 or Ctrl-C, ensuring `nmap` is terminated.
- Dynamically determines the active network interface.

Controls:
- MAIN SCREEN:
    - OK: Start/Enter Target IP
    - KEY3: Exit Payload
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position
    - LEFT/RIGHT: Move cursor
    - OK: Confirm IP and start scan
    - KEY3: Cancel IP input and return to main screen
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate interfaces
    - OK: Select interface
    - KEY3: Cancel selection and return to main screen
"""

import sys
import os
import time
import signal
import subprocess
import threading
import re # For IP validation

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
# Also add wifi subdir if present (some environments rely on it directly)
wifi_subdir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(wifi_subdir) and wifi_subdir not in sys.path:
    sys.path.insert(0, wifi_subdir)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

# WiFi Integration - Import dynamic interface support
try:
    from wifi.ktox_integration import get_best_interface, get_available_interfaces
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def get_best_interface():
        return "eth0" # Fallback
    def get_available_interfaces():
        # Fallback for when wifi integration is not available
        try:
            output = subprocess.check_output("ls /sys/class/net | grep -E 'eth|wlan'", shell=True).decode().strip()
            return output.split('\n') if output else ["eth0"]
        except:
            return ["eth0"]

TARGET_IP = "192.168.1.1"
LOOT_DIR = os.path.join(KTOX_ROOT, "loot", "Nmap_Vuln")

PINS = { "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
scan_thread = None
nmap_process = None # To keep track of the nmap subprocess
status_msg = "Press OK to scan"
current_ip_input = "192.168.1.1"
ip_input_cursor_pos = 0
ip_input_segment = 0
NETWORK_INTERFACE = get_best_interface() # Dynamically get the best interface

def cleanup(*_):
    global running
    running = False
    stop_scan_process() # Ensure nmap is terminated

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def stop_scan_process():
    """Terminate the nmap process if it's running."""
    global nmap_process
    if nmap_process and nmap_process.poll() is None:
        try:
            nmap_process.terminate()
            nmap_process.wait(timeout=5)
            print("Nmap process terminated.")
        except (subprocess.TimeoutExpired, ProcessLookupError):
            nmap_process.kill()
            print("Nmap process killed.")
        nmap_process = None

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    
    # Header
    d.text((5, 5), "Nmap Vuln Scan", font=FONT_TITLE, fill=(231, 76, 60))
    d.line([(0, 22), (128, 22)], fill=(231, 76, 60), width=1)
    d.text((5, 115), f"IF: {NETWORK_INTERFACE}", font=FONT, fill=(86, 101, 115)) # Display interface

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
    elif screen_state == "main":
        d.text((10, 60), status_msg, font=FONT, fill=(212, 172, 13))
        d.text((5, 100), "OK=Scan | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui_interface_selection(interfaces, current_selection):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Select Interface", font=FONT_TITLE, fill=(171, 178, 185))
    d.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)

    y_pos = 25
    for i, iface in enumerate(interfaces):
        color = "yellow" if i == current_selection else "white"
        d.text((5, y_pos), iface, font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 100), "UP/DOWN=Select | OK=Confirm", font=FONT, fill=(171, 178, 185))
    d.text((5, 110), "KEY3=Cancel", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

def select_interface_menu():
    global NETWORK_INTERFACE, status_msg
    
    available_interfaces = get_available_interfaces()
    if not available_interfaces:
        draw_ui(message_lines=["No network", "interfaces found!"])
        time.sleep(3)
        return None

    current_menu_selection = 0
    while running:
        draw_ui_interface_selection(available_interfaces, current_menu_selection)
        
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                while GPIO.input(pin) == 0:
                    time.sleep(0.05)
                break

        if btn == "KEY3":
            return None
        
        if btn == "UP":
            current_menu_selection = (current_menu_selection - 1 + len(available_interfaces)) % len(available_interfaces)
        elif btn == "DOWN":
            current_menu_selection = (current_menu_selection + 1) % len(available_interfaces)
        elif btn == "OK":
            selected_iface = available_interfaces[current_menu_selection]
            draw_ui(message_lines=[f"Selected:", f"{selected_iface}"])
            time.sleep(1)
            return selected_iface
        
        time.sleep(0.1)

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
                draw_ui(message_lines=["Invalid IP!", "Try again."])
                time.sleep(2)
                input_ip = "" # Reset on invalid
        
        time.sleep(0.1)
    return None

def run_scan(target_ip, interface):
    global status_msg, nmap_process
    
    os.makedirs(LOOT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    output_file = os.path.join(LOOT_DIR, f"vuln_scan_{target_ip}_{timestamp}.txt")
    
    status_msg = f"Scanning {target_ip} on {interface}..."
    draw_ui("main") # Update UI with status
    
    try:
        command = ["nmap", "-e", interface, "--script", "vuln", "-oN", output_file, target_ip]
        # Use Popen to allow termination
        nmap_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = nmap_process.communicate(timeout=600) # Wait for process to complete or timeout
        
        if nmap_process.returncode == 0:
            status_msg = "Scan complete!"
        else:
            status_msg = f"Nmap exited with error: {nmap_process.returncode}"
            print(f"Nmap stderr: {stderr}", file=sys.stderr)

    except subprocess.TimeoutExpired:
        stop_scan_process() # Ensure nmap is killed if it times out
        status_msg = "Scan timed out!"
    except Exception as e:
        status_msg = "Scan failed!"
        print(f"Nmap scan failed: {e}", file=sys.stderr)
    finally:
        nmap_process = None # Clear process reference
    draw_ui("main") # Update UI with final status

if __name__ == "__main__":
    try:
        if subprocess.run("which nmap", shell=True, capture_output=True).returncode != 0:
            draw_ui(message_lines=["ERROR:", "`nmap` not found!", "Install with:", "`sudo apt install nmap`"])
            time.sleep(5)
            raise SystemExit("`nmap` command not found.")

        # Use the dynamically determined NETWORK_INTERFACE as default
        selected_interface = NETWORK_INTERFACE
        
        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["KEY3"]) == 0:
                cleanup()
                break
            
            if GPIO.input(PINS["OK"]) == 0:
                # Allow user to select interface before IP input
                temp_interface = select_interface_menu()
                if temp_interface:
                    selected_interface = temp_interface
                
                new_ip = handle_ip_input_logic(TARGET_IP)
                if new_ip:
                    TARGET_IP = new_ip
                    if not (scan_thread and scan_thread.is_alive()):
                        scan_thread = threading.Thread(target=run_scan, args=(TARGET_IP, selected_interface,), daemon=True)
                        scan_thread.start()
                time.sleep(0.3)

            time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw_ui(message_lines=[f"CRITICAL ERROR:", f"{str(e)[:20]}"], color="red")
        time.sleep(3)
    finally:
        stop_scan_process() # Ensure nmap is terminated on final exit
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Nmap Vuln Scan payload finished.")