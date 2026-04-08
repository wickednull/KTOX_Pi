#!/usr/bin/env python3
"""
KTOx *payload* – **ARP Scanner**
====================================
This payload performs an ARP scan on the local network to discover active hosts
(IP and MAC addresses) and displays them on the 1.44-inch LCD.
Discovered hosts are also saved to a loot file.

Features:
- Scans the local network for active devices using ARP requests.
- Displays a scrollable list of discovered IP and MAC addresses.
- Saves scan results to a timestamped loot file.
- Automatically detects the best network interface for scanning.

Controls:
- OK: Start a new ARP scan.
- UP/DOWN: Scroll through the list of discovered hosts.
- KEY3: Exit Payload.
"""
import sys
import os
import time
import signal
import subprocess
import threading
import json

# Ensure KTOx root is on sys.path (exec_payload sets cwd=/root/KTOx)
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))

# ----------------------------
# KTOx PATH and ROOT check
# ----------------------------
def is_root():
    return os.geteuid() == 0

# Prefer installed KTOx path; fallback to repo-relative
PREFERRED_KTOX = '/root/KTOx'
if os.path.isdir(PREFERRED_KTOX):
    if PREFERRED_KTOX not in sys.path:
        sys.path.insert(0, PREFERRED_KTOX)
else:
    KTOX_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'KTOx'))
    if os.path.isdir(KTOX_PATH) and KTOX_PATH not in sys.path:
        sys.path.insert(0, KTOX_PATH)

# ----------------------------
# Third-party library imports 
# ----------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_Config
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Hardware libraries (RPi.GPIO, LCD, PIL) not found.", file=sys.stderr)
    print("Please run 'sudo pip3 install RPi.GPIO spidev Pillow'.", file=sys.stderr)
    sys.exit(1)

try:
    from scapy.all import *
    from scapy.error import Scapy_Exception
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

# Load PINS from KTOx gui_conf.json
PINS: dict[str, int] = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
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
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

KTOX_DIR = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
LOOT_DIR = os.path.join(KTOX_DIR, "loot", "ARP_Scan")
# Dynamically get the best interface
NETWORK_INTERFACE = get_best_interface()
running = True
scan_thread = None
discovered_hosts = []
selected_index = 0
ui_lock = threading.Lock()

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def get_network_range(interface):
    """Gets the network range (e.g., 192.168.1.0/24) for the given interface."""
    try:
        output = subprocess.check_output(f"ip -o -4 addr show {interface} | awk '{{print $4}}'", shell=True).decode().strip()
        if not output:
            return None
        return output
    except Exception:
        return None

def run_arp_scan(network_range, interface):
    """Uses Scapy to perform an ARP scan and update the discovered_hosts list."""
    global discovered_hosts
    try:
        ans, unans = srp(Ether(dst="ff:ff:ff:ff:ff:ff")/ARP(pdst=network_range), timeout=5, iface=interface, verbose=0)
        
        temp_hosts = []
        for sent, received in ans:
            temp_hosts.append({'ip': received.psrc, 'mac': received.hwsrc})
        
        with ui_lock:
            discovered_hosts = sorted(temp_hosts, key=lambda x: [int(y) for y in x['ip'].split('.')])
            save_loot()
            
    except Scapy_Exception as e:
        print(f"Scapy ARP Scan failed: {e}", file=sys.stderr)
        with ui_lock:
            discovered_hosts = []
            draw_ui(f"Scapy Error:\n{str(e)[:20]}", interface)
            time.sleep(3)
    except Exception as e:
        print(f"ARP Scan failed: {e}", file=sys.stderr)
        with ui_lock:
            discovered_hosts = []
            draw_ui(f"Scan Error:\n{str(e)[:20]}", interface)
            time.sleep(3)

def save_loot():
    os.makedirs(LOOT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    loot_file = os.path.join(LOOT_DIR, f"arp_scan_{timestamp}.txt")
    with open(loot_file, "w") as f:
        for host in discovered_hosts:
            f.write(f"{host['ip']:<15} {host['mac']}\n")

def draw_ui(status_msg="", interface=""):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)

    d.text((5, 5), f"ARP Scanner ({interface})", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if status_msg:
        lines = status_msg.split('\n')
        y_start = (HEIGHT - len(lines) * 12) // 2
        for line in lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (WIDTH - w) // 2
            d.text((x, y_start), line, font=FONT, fill="yellow")
            y_start += 12
    else:
        with ui_lock:
            if not discovered_hosts:
                d.text((10, 60), "No hosts found.", font=FONT, fill="white")
            else:
                start_display_index = max(0, selected_index - 3)
                end_display_index = min(len(discovered_hosts), start_display_index + 7)
                
                y_pos = 25
                for i in range(start_display_index, end_display_index):
                    host = discovered_hosts[i]
                    line = f"{host['ip']} {host['mac']}"
                    color = "yellow" if i == selected_index else "white"
                    d.text((5, y_pos), line, font=FONT, fill=color)
                    y_pos += 12

    d.text((5, 110), "OK=Scan | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

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

    try:
        current_interface = NETWORK_INTERFACE
        network_range = get_network_range(current_interface)
        if not network_range:
            draw_ui(f"Error:\n{current_interface} not connected\nor no IP address.", current_interface)
            time.sleep(5)
            raise SystemExit(f"{current_interface} has no IP address or is not connected.")

        while running:
            draw_ui(interface=current_interface)
            
            while running:
                if GPIO.input(PINS["KEY3"]) == 0:
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0:
                    draw_ui("Scanning...", current_interface)
                    run_arp_scan(network_range, current_interface)
                    selected_index = 0
                    break
                
                if GPIO.input(PINS["UP"]) == 0:
                    with ui_lock:
                        if discovered_hosts:
                            selected_index = (selected_index - 1) % len(discovered_hosts)
                    break
                elif GPIO.input(PINS["DOWN"]) == 0:
                    with ui_lock:
                        if discovered_hosts:
                            selected_index = (selected_index + 1) % len(discovered_hosts)
                    break
                
                time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw_ui(f"CRITICAL ERROR:\n{str(e)[:20]}", current_interface)
        time.sleep(3)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("ARP Scanner payload finished.")