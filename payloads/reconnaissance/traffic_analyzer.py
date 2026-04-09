#!/usr/bin/env python3
"""
KTOx *payload* – **Traffic Analyzer**
========================================
This payload acts as a passive network traffic analyzer, capturing packets
on a specified network interface and providing real-time statistics on
packet counts, protocol distribution (TCP, UDP, ICMP, ARP), and top talkers
(source IP addresses).

Features:
- Interactive UI for selecting the network interface to monitor.
- Captures and analyzes live network traffic.
- Displays total packet count, protocol breakdown, and top source IPs on the LCD.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - KEY1: Select network interface.
    - KEY3: Exit Payload.
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
from collections import Counter
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

PINS: dict[str, int] = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

ETH_INTERFACE = "eth0"
running = True
sniff_thread = None
ui_lock = threading.Lock()

packet_count = 0
protocol_counts = Counter()
ip_counts = Counter()
current_interface_input = ETH_INTERFACE
interface_input_cursor_pos = 0
wifi_manager = WiFiManager()

# Loot directory under KTOx
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'Traffic_Analyzer')

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
    global ETH_INTERFACE
    
    available_interfaces = get_available_interfaces()
    if not available_interfaces:
        show_message(["No network", "interfaces found!"], "red")
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
            show_message([f"Selected:", f"{selected_iface}"], "lime")
            time.sleep(1)
            return selected_iface
        
        time.sleep(0.1)

def cleanup(*_):
    global running
    running = False
    # Save a final snapshot to loot
    try:
        os.makedirs(LOOT_DIR, exist_ok=True)
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f'summary_{ETH_INTERFACE}_{ts}.txt')
        with open(loot_file, 'w') as f:
            f.write(f'Interface: {ETH_INTERFACE}\n')
            f.write(f'Total packets: {packet_count}\n')
            f.write('Protocol counts:\n')
            for k in ['TCP','UDP','ICMP','ARP']:
                f.write(f'  {k}: {protocol_counts[k]}\n')
            f.write('Top talkers:\n')
            for ip, cnt in ip_counts.most_common(10):
                f.write(f'  {ip}: {cnt}\n')
    except Exception as e:
        print(f'[WARN] Failed to write loot: {e}', file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2
        d.text((x, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui(screen_state="main"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)

    d.text((5, 5), f"Traffic Analyzer ({ETH_INTERFACE})", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if screen_state == "main":
        with ui_lock:
            d.text((5, 25), f"Total Packets: {packet_count}", font=FONT, fill="white")
            
            proto_str_1 = f"T:{protocol_counts['TCP']} U:{protocol_counts['UDP']}"
            proto_str_2 = f"I:{protocol_counts['ICMP']} A:{protocol_counts['ARP']}"
            d.text((5, 40), proto_str_1, font=FONT, fill="cyan")
            d.text((5, 50), proto_str_2, font=FONT, fill="cyan")

            d.text((5, 65), "Top Talkers:", font=FONT, fill="yellow")
            y_pos = 75
            top_5 = ip_counts.most_common(4)
            for ip, count in top_5:
                d.text((8, y_pos), f"{ip}", font=FONT, fill="white")
                y_pos += 10

        d.text((5, 115), "KEY1=Edit Iface | KEY3=Exit", font=FONT, fill="orange")
    elif screen_state == "iface_input":
        d.text((5, 30), "Enter Interface:", font=FONT, fill="white")
        display_iface = list(current_interface_input)
        if interface_input_cursor_pos < len(display_iface):
            display_iface[interface_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_iface[:16]), font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill="cyan")
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_text_input_logic(initial_text, screen_state_name, char_set):
    global current_interface_input, interface_input_cursor_pos
    
    current_input_ref = current_interface_input
    cursor_pos_ref = interface_input_cursor_pos

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
                show_message(["Input cannot", "be empty!"], "red")
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

# Packet processing and sniffer

def _process_packet(pkt):
    global packet_count, protocol_counts, ip_counts
    try:
        packet_count += 1
        if pkt.haslayer(TCP):
            protocol_counts['TCP'] += 1
        elif pkt.haslayer(UDP):
            protocol_counts['UDP'] += 1
        elif pkt.haslayer(ICMP):
            protocol_counts['ICMP'] += 1
        elif pkt.haslayer(ARP):
            protocol_counts['ARP'] += 1
        if pkt.haslayer(IP):
            ip_counts[pkt[IP].src] += 1
    except Exception:
        pass

def sniffer_worker():
    try:
        sniff(prn=_process_packet, store=False, iface=ETH_INTERFACE, stop_filter=lambda x: not running)
    except Exception as e:
        print(f'[WARN] Sniffer error: {e}', file=sys.stderr)

if __name__ == "__main__":
    current_screen = "main"
    try:
        selected_interface = select_interface_menu()
        if not selected_interface:
            show_message(["No interface", "selected!", "Exiting..."], "red")
            time.sleep(3)
            sys.exit(1)
        ETH_INTERFACE = selected_interface

        if "NO-CARRIER" in subprocess.check_output(f"ip link show {ETH_INTERFACE}", shell=True).decode():
            draw_ui("main")
            time.sleep(1)
            d = ImageDraw.Draw(Image.new("RGB", (WIDTH, HEIGHT), "black"))
            d.text((10, 60), f"{ETH_INTERFACE} Disconnected", font=FONT_TITLE, fill="red")
            LCD.LCD_ShowImage(d.im, 0, 0)
            time.sleep(3)
            raise SystemExit("Ethernet cable not connected.")

        sniff_thread = threading.Thread(target=sniffer_worker, daemon=True)
        sniff_thread.start()

        while running:
            if current_screen == "main":
                draw_ui("main")
                
                start_wait = time.time()
                while time.time() - start_wait < 2.0:
                    if GPIO.input(PINS["KEY3"]) == 0:
                        cleanup()
                        break
                    if GPIO.input(PINS["KEY1"]) == 0:
                        current_interface_input = ETH_INTERFACE
                        current_screen = "iface_input"
                        time.sleep(0.3)
                        break
                    time.sleep(0.1)
                
                if not running:
                    break
            
            elif current_screen == "iface_input":
                char_set = "abcdefghijklmnopqrstuvwxyz0123456789"
                new_iface = handle_text_input_logic(current_interface_input, "iface_input", char_set)
                if new_iface:
                    ETH_INTERFACE = new_iface
                    # Restart sniffer with new interface
                    if sniff_thread and sniff_thread.is_alive():
                        running_temp = running
                        running = False
                        sniff_thread.join(timeout=1)
                        running = running_temp
                        
                    packet_count = 0
                    protocol_counts.clear()
                    ip_counts.clear()
                    
                    sniff_thread = threading.Thread(target=sniffer_worker, daemon=True)
                    sniff_thread.start()
                current_screen = "main"
                time.sleep(0.3)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
    finally:
        cleanup()
        if sniff_thread:
            sniff_thread.join(timeout=1)
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Traffic Analyzer payload finished.")