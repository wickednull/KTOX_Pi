#!/usr/bin/env python3
import json
"""
KTOx *payload* – **WiFi Rogue AP**
=====================================
This payload sets up a rogue Wi-Fi access point (AP) with a customizable SSID
and channel. A rogue AP can be used for various purposes, including phishing,
man-in-the-middle attacks, or simply to attract clients for further exploitation.

Features:
- Interactive UI for selecting the wireless interface.
- Allows configuration of the rogue AP's SSID and channel.
- Uses `hostapd` to create the rogue access point.
- Displays status messages on the LCD.
- Graceful exit via KEY3 or Ctrl-C, cleaning up `hostapd` and restoring
  network settings.

Controls:
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate available wireless interfaces.
    - OK: Select interface.
    - KEY3: Cancel selection and exit.
- MAIN CONFIGURATION SCREEN:
    - UP/DOWN: Navigate configuration parameters (SSID, Channel).
    - OK: Edit selected parameter.
    - KEY2: Start Rogue AP.
    - KEY3: Exit Payload.
- SSID INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm SSID.
    - KEY3: Cancel input.
- CHANNEL INPUT SCREEN:
    - UP/DOWN: Increment/decrement channel.
    - OK: Confirm channel.
    - KEY3: Cancel input.
"""
import sys
import os
import time
import signal
import subprocess
import threading # Added threading import as it was missing

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

WIFI_INTERFACE = None
ORIGINAL_WIFI_INTERFACE = None
ROGUE_SSID = "Free_WiFi"
ROGUE_CHANNEL = 6
TEMP_CONF_DIR = "/tmp/ktox_rogue_ap" # Defined globally

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
rogue_ap_proc = None
status_msg = "Press OK to start"

# Loot directory and session log
BASE_DIR = os.path.dirname(__file__)
LOOT_DIR = os.path.join(os.path.abspath(os.path.join(BASE_DIR, '..', '..')), 'loot', 'WiFi_Rogue_AP')
os.makedirs(LOOT_DIR, exist_ok=True)

# --- Local Monitor Mode Functions ---
# These functions will be removed and replaced by monitor_mode_helper
# def _run_command(...): ...
# def _interface_exists(...): ...
# def _is_in_monitor_mode(...): ...
# def _activate_monitor_mode(...): ...
# def _deactivate_monitor_mode(...): ...

def cleanup(*_):
    global running
    running = False
    if rogue_ap_proc:
        try:
            os.killpg(rogue_ap_proc.pid, signal.SIGTERM)
        except Exception:
            try:
                rogue_ap_proc.terminate()
            except Exception:
                pass
    
    # Restore NetworkManager management for the interface
    try:
        if WIFI_INTERFACE:
            subprocess.run(["nmcli", "device", "set", WIFI_INTERFACE, "managed", "yes"], check=False)
            subprocess.run(["nmcli", "device", "connect", WIFI_INTERFACE], check=False)
    except Exception:
        pass

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(message: str, color: str = "yellow"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), message, font=FONT_TITLE)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (WIDTH - w) // 2
    y = (HEIGHT - h) // 2
    d.text((x, y), message, font=FONT_TITLE, fill=color)
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui_main(params, selected_index):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "WiFi Rogue AP", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    y_pos = 25
    param_keys = list(params.keys())
    for i, key in enumerate(param_keys):
        color = "yellow" if i == selected_index else "white"
        d.text((5, y_pos), f"{key}: {params[key]}", font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 80), status_msg, font=FONT, fill="yellow")
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
    
    # Prioritize wlan1 for evil twin attacks
    if 'wlan1' in available_interfaces:
        available_interfaces.remove('wlan1')
        available_interfaces.insert(0, 'wlan1')

    if not available_interfaces:
        draw_message("No WiFi interfaces found!", "red")
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
            WIFI_INTERFACE = selected_iface
            ORIGINAL_WIFI_INTERFACE = selected_iface
            draw_message(f"Selected interface\n{WIFI_INTERFACE}", "lime")
            time.sleep(1)
            return True
        elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return False
        
        time.sleep(0.05)

def handle_text_input_logic(initial_text, prompt, char_set):
    global current_ssid_input, ssid_input_cursor_pos
    
    current_input_ref = initial_text
    ssid_input_cursor_pos = len(initial_text) - 1
    
    while running:
        img = Image.new("RGB", (WIDTH, HEIGHT), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {prompt}:", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)

        display_text = list(current_input_ref)
        if ssid_input_cursor_pos < len(display_text):
            display_text[ssid_input_cursor_pos] = '_'
        d.text((5, 40), "".join(display_text[:16]), font=FONT_TITLE, fill="yellow")
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
            if current_input_ref:
                return current_input_ref
            else:
                draw_message(["Input cannot", "be empty!"], "red")
                time.sleep(2)
                current_input_ref = initial_text
                ssid_input_cursor_pos = len(initial_text) - 1
        
        if btn == "LEFT":
            ssid_input_cursor_pos = max(0, ssid_input_cursor_pos - 1)
        elif btn == "RIGHT":
            ssid_input_cursor_pos = min(len(current_input_ref), ssid_input_cursor_pos + 1)
        elif btn == "UP" or btn == "DOWN":
            if ssid_input_cursor_pos < len(current_input_ref):
                char_list = list(current_input_ref)
                current_char = char_list[ssid_input_cursor_pos]
                
                try:
                    char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+"
                    char_index = char_set.index(current_char)
                    if btn == "UP":
                        char_index = (char_index + 1) % len(char_set)
                    else:
                        char_index = (char_index - 1 + len(char_set)) % len(char_set)
                    char_list[ssid_input_cursor_pos] = char_set[char_index]
                    current_input_ref = "".join(char_list)
                except ValueError:
                    char_list[ssid_input_cursor_pos] = char_set[0]
                    current_input_ref = "".join(char_list)
        
        time.sleep(0.05)
    return None

def get_user_number(prompt, initial_value, min_val=1, max_val=165):
    value = initial_value
    last_button_press_time = 0
    BUTTON_DEBOUNCE_TIME = 0.2 # seconds

    while running:
        current_time = time.time()
        draw_message([f"{prompt}:", f"{value}", "UP/DOWN | OK=Save"])
        
        if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            value = min(max_val, value + 1)
            time.sleep(BUTTON_DEBOUNCE_TIME)
        elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            value = max(min_val, value - 1)
            time.sleep(BUTTON_DEBOUNCE_TIME)
        elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return value
        elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return initial_value
        time.sleep(0.05)

def start_attack():
    global rogue_ap_proc, ORIGINAL_WIFI_INTERFACE, status_msg
    
    print(f"Attempting to activate {WIFI_INTERFACE} as primary interface...", file=sys.stderr)
    # if not set_ktox_interface(WIFI_INTERFACE): # set_ktox_interface is not imported
    #     print(f"ERROR: Failed to activate {WIFI_INTERFACE}", file=sys.stderr)
    #     status_msg = "Failed to set interface!"
    #     return False
    
    # Use direct commands as set_ktox_interface is not available here
    subprocess.run(f"nmcli device disconnect {WIFI_INTERFACE} 2>/dev/null || true", shell=True)
    subprocess.run(f"nmcli device set {WIFI_INTERFACE} managed off 2>/dev/null || true", shell=True)
    time.sleep(1)
    
    subprocess.run("pkill hostapd", shell=True)
    
    os.makedirs(TEMP_CONF_DIR, exist_ok=True)
    hostapd_conf_path = os.path.join(TEMP_CONF_DIR, "hostapd.conf")
    with open(hostapd_conf_path, "w") as f: f.write(f"interface={WIFI_INTERFACE}\ndriver=nl80211\nssid={ROGUE_SSID}\nhw_mode=g\nchannel={ROGUE_CHANNEL}\n")
    
    print(f"Starting hostapd on {WIFI_INTERFACE} with SSID {ROGUE_SSID}...", file=sys.stderr)
    rogue_ap_proc = subprocess.Popen(f"hostapd {hostapd_conf_path}", shell=True, preexec_fn=os.setsid)
    # Session log
    try:
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        with open(os.path.join(LOOT_DIR, f"session_{ts}.log"), 'w') as f:
            f.write(f"START {ts} iface={WIFI_INTERFACE} ssid={ROGUE_SSID} channel={ROGUE_CHANNEL}\n")
    except Exception:
        pass
    status_msg = "Rogue AP Running!"
    return True

def check_dependencies():
    """Check for required command-line tools."""
    for dep in ["hostapd"]:
        if subprocess.run(["which", dep], capture_output=True).returncode != 0:
            return dep
    return None

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

    dep_missing = check_dependencies()
    if dep_missing:
        draw_message(f"ERROR: {dep_missing} not found.", "red")
        time.sleep(5)
        sys.exit(1)

    if not WIFI_INTEGRATION_AVAILABLE:
        draw_message(["ERROR:", "WiFi integration not found."], "red")
        time.sleep(5)
        sys.exit(1)

    current_screen = "interface_select"
    selected_param_index = 0
    params = {
        "SSID": ROGUE_SSID,
        "Channel": ROGUE_CHANNEL
    }
    param_keys = list(params.keys())
    
    try:
        if not select_interface_menu():
            draw_message(["No interface selected", "or monitor mode failed."], "red")
            time.sleep(3)
            raise SystemExit("No interface selected or activation failed.")
        
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
                    if key == "SSID":
                        char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+"
                        new_ssid = handle_text_input_logic(params[key], "SSID", char_set)
                        if new_ssid:
                            params[key] = new_ssid
                            ROGUE_SSID = new_ssid
                    elif key == "Channel":
                        new_channel = get_user_number("Channel", int(params[key]), 1, 165)
                        params[key] = str(new_channel)
                        ROGUE_CHANNEL = str(new_channel)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    if start_attack():
                        status_msg = "Rogue AP Running!"
                    else:
                        status_msg = "Failed to start AP!"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # Write END to last session log if possible
        try:
            ts = time.strftime('%Y-%m-%d_%H%M%S')
            with open(os.path.join(LOOT_DIR, f"session_{ts}.log"), 'a') as f:
                f.write(f"END {ts}\n")
        except Exception:
            pass
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Rogue AP payload finished.")
