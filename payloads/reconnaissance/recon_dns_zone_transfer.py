#!/usr/bin/env python3
"""
KTOx *payload* – **DNS Zone Transfer Recon**
==============================================
This payload attempts to perform a DNS zone transfer (AXFR) against a target
domain's name servers. A successful zone transfer can reveal a wealth of
information about a domain's infrastructure, including hostnames, IP addresses,
and other sensitive records, which can be valuable for reconnaissance.

Features:
- Interactive UI for entering the target domain.
- Automatically discovers name servers for the target domain.
- Attempts zone transfer from each discovered name server.
- Displays scan status and success/failure on the LCD.
- Saves successful zone transfer results to a loot file.
- Allows selection of the network interface to use for the scan.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start DNS zone transfer scan.
    - KEY1: Edit target domain.
    - KEY3: Exit Payload.
- DOMAIN INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm domain.
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
# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
# Also add wifi subdir if present
wifi_subdir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(wifi_subdir) and wifi_subdir not in sys.path:
    sys.path.insert(0, wifi_subdir)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from wifi.ktox_integration import get_available_interfaces, set_ktox_interface
from wifi.wifi_manager import WiFiManager

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "UP": 6, "DOWN": 19 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

TARGET_DOMAIN = "example.com"
# Loot under /root/KTOx when available
LOOT_DIR = os.path.join(KTOX_ROOT, "loot", "DNS_Zone_Transfer")
running = True
scan_thread = None
results = []
ui_lock = threading.Lock()
status_msg = "Press OK to start"
current_domain_input = TARGET_DOMAIN
domain_input_cursor_pos = 0
wifi_manager = WiFiManager()

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
    
    d.text((5, 115), "UP/DOWN=Select | OK=Confirm", font=FONT, fill=(171, 178, 185))
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

def draw_ui(screen_state="main"):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "DNS Zone Transfer", font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

    if screen_state == "main":
        with ui_lock:
            d.text((5, 25), f"Domain: {TARGET_DOMAIN[:16]}...", font=FONT, fill=(242, 243, 244))
            if "Press" in status_msg or "Finding" in status_msg or "Testing" in status_msg:
                d.text((5, 45), status_msg, font=FONT, fill=(212, 172, 13))
            elif "SUCCESS" in status_msg:
                d.text((5, 45), status_msg, font=FONT_TITLE, fill=(231, 76, 60))
                d.text((5, 60), f"Saved {len(results)} records", font=FONT, fill=(242, 243, 244))
            else:
                d.text((5, 45), status_msg, font=FONT_TITLE, fill="red")

        d.text((5, 115), "OK=Start | KEY1=Edit Domain | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    elif screen_state == "domain_input":
        d.text((5, 30), "Enter Domain:", font=FONT, fill=(242, 243, 244))
        display_domain = list(current_domain_input)
        if domain_input_cursor_pos < len(display_domain):
            display_domain[domain_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_domain[:16]), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
    elif screen_state == "scanning":
        d.text((5, 25), f"Domain: {TARGET_DOMAIN[:16]}...", font=FONT, fill=(242, 243, 244))
        d.text((5, 45), status_msg, font=FONT, fill=(212, 172, 13))
        d.text((5, 115), "KEY3=Stop", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_text_input_logic(initial_text, screen_state_name, char_set):
    global current_domain_input, domain_input_cursor_pos
    
    current_input_ref = current_domain_input
    cursor_pos_ref = domain_input_cursor_pos

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
    global results, status_msg, TARGET_DOMAIN
    with ui_lock:
        status_msg = f"Finding NS for\n{TARGET_DOMAIN}..."
        results = []

    try:
        if set_ktox_interface(interface):
            show_message([f"Interface {interface}", "activated."], "lime")
            time.sleep(1)
        else:
            show_message([f"Failed to activate", f"{interface}."], "red")
            return

        ns_proc = subprocess.run(f"host -t ns {TARGET_DOMAIN}", shell=True, capture_output=True, text=True)
        if ns_proc.returncode != 0:
            with ui_lock: status_msg = "Domain not found"
            return
            
        name_servers = [line.split()[-1] for line in ns_proc.stdout.strip().split('\n') if "name server" in line]
        
        if not name_servers:
            with ui_lock: status_msg = "No NS found!"
            return

        for ns in name_servers:
            if not running: break
            with ui_lock: status_msg = f"Testing {ns[:-1][:16]}..."
            
            axfr_proc = subprocess.run(f"host -l {TARGET_DOMAIN} {ns}", shell=True, capture_output=True, text=True)
            
            if "Transfer failed" not in axfr_proc.stdout and "has address" in axfr_proc.stdout:
                with ui_lock:
                    results = axfr_proc.stdout.strip().split('\n')
                    status_msg = "SUCCESS!"
                
                os.makedirs(LOOT_DIR, exist_ok=True)
                loot_file = os.path.join(LOOT_DIR, f"{TARGET_DOMAIN}.txt")
                with open(loot_file, "w") as f:
                    f.write(f"Zone transfer results for {TARGET_DOMAIN} from {ns}\n\n")
                    f.write(axfr_proc.stdout)
                return

        if running:
             with ui_lock: status_msg = "Transfer FAILED"

    except Exception as e:
        with ui_lock: status_msg = "Scan Error!"
        print(f"AXFR Scan failed: {e}", file=sys.stderr)

if __name__ == "__main__":
    current_screen = "main"
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds
    
        if subprocess.run("which host", shell=True, capture_output=True).returncode != 0:
            show_message(["ERROR:", "host tool", "not found!"], "red")
            time.sleep(3)
            sys.exit(1)
    
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
                    current_screen = "scanning"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_domain_input = TARGET_DOMAIN
                    current_screen = "domain_input"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "domain_input":
                char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
                new_domain = handle_text_input_logic(current_domain_input, "domain_input", char_set)
                if new_domain:
                    TARGET_DOMAIN = new_domain
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "scanning":
                draw_ui("scanning")
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                if not (scan_thread and scan_thread.is_alive()):
                    current_screen = "main"
                time.sleep(0.1)
    
            time.sleep(0.1)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        show_message(["CRITICAL ERROR:", str(e)[:20]], "red")
        time.sleep(3)
    finally:
        cleanup()
        if scan_thread and scan_thread.is_alive():
            scan_thread.join(timeout=1)
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("DNS Zone Transfer payload finished.")