#!/usr/bin/env python3
"""
KTOx *payload* – **WiFi Channel Analyzer**
=============================================
This payload scans Wi-Fi channels to identify the number of access points
(APs) broadcasting on each channel. This information can be useful for
identifying less congested channels for your own network or for reconnaissance
during Wi-Fi penetration testing.

Features:
- Interactive UI for selecting the wireless interface.
- Activates monitor mode on the selected interface.
- Scans 2.4GHz and 5GHz channels for beacon frames.
- Displays the count of unique APs per channel on the LCD.
- Allows scrolling through scan results.
- Graceful exit via KEY3 or Ctrl-C, deactivating monitor mode.

Controls:
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate available wireless interfaces.
    - OK: Select interface and activate monitor mode.
    - KEY3: Cancel selection and exit.
- MAIN SCREEN:
    - OK: Start/Restart channel scan.
    - UP/DOWN: Scroll through channel results (after scan is complete).
    - KEY3: Exit Payload (stops scan and deactivates monitor mode).
"""
import sys
import os
import time
import json
import signal
import subprocess
import threading

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
CHANNELS_2_4GHZ = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
CHANNELS_5GHZ = [36, 40, 44, 48, 149, 153, 157, 161]
SCAN_TIME_PER_CHANNEL = 1

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
scan_thread = None
channel_data = {}
ui_lock = threading.Lock()
status_msg = "Press OK to scan"
selected_index = 0
current_menu_selection = 0

# Loot directory for scan snapshots (prefer installed KTOx)
BASE_DIR = os.path.dirname(__file__)
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'WiFi_Channel_Analyzer')
os.makedirs(LOOT_DIR, exist_ok=True)

def cleanup(*_):
    global running
    running = False
    if scan_thread and scan_thread.is_alive():
        scan_thread.join(timeout=1)
    
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
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "WiFi Channel Analyzer", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    with ui_lock:
        if not channel_data:
            d.text((10, 60), status_msg, font=FONT, fill="yellow")
        else:
            sorted_channels = sorted(channel_data.items())
            start_index = max(0, selected_index - 4)
            end_index = min(len(sorted_channels), start_index + 8)
            y_pos = 25
            for i in range(start_index, end_index):
                color = "yellow" if i == selected_index else "white"
                channel, ap_count = sorted_channels[i]
                d.text((5, y_pos), f"Ch {channel}: {ap_count} APs", font=FONT, fill=color)
                y_pos += 11

    d.text((5, 115), "OK=Scan | KEY3=Exit", font=FONT, fill="cyan")
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

def set_channel(channel):
    """Sets the Wi-Fi interface to the specified channel."""
    try:
        # Prefer modern iw command
        subprocess.run(['sudo', 'iw', 'dev', WIFI_INTERFACE, 'set', 'channel', str(channel)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        try:
            subprocess.run(['sudo', 'iwconfig', WIFI_INTERFACE, 'channel', str(channel)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            print(f"Error setting channel {channel} on {WIFI_INTERFACE}: {e}", file=sys.stderr)

def sniffer_worker():
    global channel_data, status_msg
    
    while running:
        with ui_lock:
            channel_data.clear()
            status_msg = "Scanning 2.4GHz..."
        
        for channel in CHANNELS_2_4GHZ:
            if not running: break
            set_channel(channel)
            ap_count = 0
            unique_aps = set()
            
            def packet_handler(pkt):
                nonlocal ap_count, unique_aps
                if pkt.haslayer(Dot11Beacon):
                    ap_mac = pkt.addr2
                    if ap_mac not in unique_aps:
                        unique_aps.add(ap_mac)
                        ap_count += 1
            
            sniff(iface=WIFI_INTERFACE, prn=packet_handler, timeout=SCAN_TIME_PER_CHANNEL, store=0)
            with ui_lock:
                channel_data[channel] = ap_count
        
        with ui_lock:
            status_msg = "Scanning 5GHz..."
        
        for channel in CHANNELS_5GHZ:
            if not running: break
            set_channel(channel)
            ap_count = 0
            unique_aps = set()
            
            def packet_handler(pkt):
                nonlocal ap_count, unique_aps
                if pkt.haslayer(Dot11Beacon):
                    ap_mac = pkt.addr2
                    if ap_mac not in unique_aps:
                        unique_aps.add(ap_mac)
                        ap_count += 1
            
            sniff(iface=WIFI_INTERFACE, prn=packet_handler, timeout=SCAN_TIME_PER_CHANNEL, store=0)
            with ui_lock:
                channel_data[channel] = ap_count
        
        with ui_lock:
            status_msg = "Scan Complete!"
        # Save snapshot to loot
        try:
            ts = time.strftime('%Y-%m-%d_%H%M%S')
            out = os.path.join(LOOT_DIR, f'channels_{ts}.txt')
            with open(out, 'w') as f:
                for ch, cnt in sorted(channel_data.items()):
                    f.write(f'{ch},{cnt}\n')
        except Exception:
            pass
        # Wait for a bit before restarting scan or exiting
        time.sleep(5)

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
                if not (scan_thread and scan_thread.is_alive()):
                    scan_thread = threading.Thread(target=sniffer_worker, daemon=True)
                    scan_thread.start()
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("WiFi Channel Analyzer payload finished.")