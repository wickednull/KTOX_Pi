#!/usr/bin/env python3
"""
KTOx *payload* – **Ethernet Link Manipulator**
=================================================
This payload allows you to actively manipulate the physical layer (Layer 1/2)
of an Ethernet connection. By forcing specific link speeds, duplex settings,
or rapidly toggling the link state, you can cause network instability,
force devices to renegotiate, or potentially trigger vulnerabilities in
network hardware.

Features:
- Interactive UI for selecting an Ethernet interface.
- Options to force link speed (10/100/1000 Mbps).
- Options to force duplex mode (Half/Full).
- Option to perform a rapid link flap attack (repeatedly toggle link up/down).
- Displays current link status and manipulation effects on the LCD.
- Graceful exit via KEY3 or Ctrl-C, attempting to restore original link settings.

Controls:
- INTERFACE SELECTION SCREEN:
    - UP/DOWN: Navigate available Ethernet interfaces.
    - OK: Select interface.
    - KEY3: Exit Payload.
- MAIN CONFIGURATION SCREEN:
    - UP/DOWN: Navigate manipulation options (Speed, Duplex, Flap).
    - LEFT/RIGHT: Adjust selected option's value.
    - OK: Apply setting / Start attack.
    - KEY3: Exit Payload.
"""
import sys
import os
import time
import signal
import subprocess
import threading
from collections import deque

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

# --- Constants and Globals ---
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
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
current_interface = None
original_link_settings = {} # To store settings for restoration
manipulation_type = "Speed" # "Speed", "Duplex", "Flap"
speed_options = ["Auto", "10", "100", "1000"]
duplex_options = ["Auto", "Half", "Full"]
current_speed_index = 0
current_duplex_index = 0
link_flap_active = False
ui_lock = threading.Lock()
status_msg = "Ready"

LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'attack_ethernet_link_manipulator')
os.makedirs(LOOT_DIR, exist_ok=True)

# --- Signal Handling and Cleanup ---
def cleanup(*_):
    global running
    running = False
    # Attempt to restore original link settings
    if current_interface and original_link_settings:
        draw_message(["Restoring link", "settings..."], "yellow")
        print(f"Restoring original link settings for {current_interface}...", file=sys.stderr)
        try:
            if original_link_settings.get('speed'):
                subprocess.run(["sudo", "ethtool", "-s", current_interface, "speed", original_link_settings['speed']], check=False, capture_output=True)
            if original_link_settings.get('duplex'):
                subprocess.run(["sudo", "ethtool", "-s", current_interface, "duplex", original_link_settings['duplex']], check=False, capture_output=True)
            subprocess.run(["sudo", "ethtool", "-s", current_interface, "autoneg", "on"], check=False, capture_output=True)
            print(f"Restored autonegotiation for {current_interface}.", file=sys.stderr)
        except Exception as e:
            print(f"Error restoring link settings: {e}", file=sys.stderr)
    save_loot_snapshot()

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def save_loot_snapshot():
    try:
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f"eth_link_manipulator_{ts}.txt")
        with open(loot_file, 'w') as f:
            f.write("Ethernet Link Manipulator Session\n")
            f.write(f"Interface: {current_interface or 'N/A'}\n")
            f.write(f"Speed option: {speed_options[current_speed_index]}\n")
            f.write(f"Duplex option: {duplex_options[current_duplex_index]}\n")
            f.write(f"Link flap active: {link_flap_active}\n")
            f.write(f"Last status: {status_msg}\n")
            f.write(f"Timestamp: {ts}\n")
        print(f"Loot saved to {loot_file}")
    except Exception as e:
        print(f"Loot save failed: {e}", file=sys.stderr)

# --- UI Drawing Functions ---
def draw_message(lines, color="yellow"):
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

def draw_interface_selection_ui(interfaces, current_selection):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Select Interface", font=FONT_TITLE, fill="cyan")
    d.line([(0, 22), (128, 22)], fill="cyan", width=1)

    y_pos = 25
    for i, iface in enumerate(interfaces):
        color = "yellow" if i == current_selection else "white"
        d.text((5, y_pos), iface, font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 115), "UP/DOWN=Select | OK=Confirm | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_main_config_ui(selected_option_index):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    d.text((5, 5), f"Eth Manipulator ({current_interface})", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    options = ["Speed", "Duplex", "Link Flap"]
    y_pos = 25
    for i, option in enumerate(options):
        color = "yellow" if i == selected_option_index else "white"
        
        display_value = ""
        if option == "Speed":
            display_value = speed_options[current_speed_index]
        elif option == "Duplex":
            display_value = duplex_options[current_duplex_index]
        elif option == "Link Flap":
            display_value = "ACTIVE" if link_flap_active else "OFF"
        
        d.text((5, y_pos), f"{option}: {display_value}", font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 80), f"Status: {status_msg}", font=FONT, fill="yellow")
    d.text((5, 115), "L/R=Adjust | OK=Apply | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

# --- Ethernet Manipulation Functions ---
def get_ethernet_interfaces():
    interfaces = []
    try:
        # Use 'ip link show' to find interfaces that are typically Ethernet
        proc = subprocess.run(["ip", "-br", "link", "show"], capture_output=True, text=True, check=True)
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) > 0 and parts[0].startswith("eth"): # Simple check for eth interfaces
                interfaces.append(parts[0])
    except Exception as e:
        print(f"Error getting interfaces: {e}", file=sys.stderr)
    return interfaces

def get_current_link_settings(iface):
    settings = {}
    try:
        proc = subprocess.run(["sudo", "ethtool", iface], capture_output=True, text=True, check=True)
        for line in proc.stdout.splitlines():
            if "Speed:" in line:
                settings['speed'] = line.split(":")[1].strip().replace("Mb/s", "")
            elif "Duplex:" in line:
                settings['duplex'] = line.split(":")[1].strip()
            elif "Autonegotiation:" in line:
                settings['autoneg'] = line.split(":")[1].strip()
    except Exception as e:
        print(f"Error getting current link settings for {iface}: {e}", file=sys.stderr)
    return settings

def apply_link_setting(iface, speed=None, duplex=None, autoneg=None):
    global status_msg
    cmd = ["sudo", "ethtool", "-s", iface]
    if speed:
        cmd.extend(["speed", speed])
    if duplex:
        cmd.extend(["duplex", duplex])
    if autoneg is not None:
        cmd.extend(["autoneg", "on" if autoneg else "off"])
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        status_msg = "Settings applied!"
    except subprocess.CalledProcessError as e:
        status_msg = f"Failed: {e.stderr.strip()[:15]}"
        print(f"Error applying link settings: {e.stderr}", file=sys.stderr)
    except Exception as e:
        status_msg = f"Error: {str(e)[:15]}"
        print(f"Error applying link settings: {e}", file=sys.stderr)

def link_flap_worker(iface):
    global status_msg
    while running and link_flap_active:
        try:
            subprocess.run(["sudo", "ifconfig", iface, "down"], check=True, capture_output=True)
            status_msg = f"{iface} DOWN"
            time.sleep(0.5)
            subprocess.run(["sudo", "ifconfig", iface, "up"], check=True, capture_output=True)
            status_msg = f"{iface} UP"
            time.sleep(0.5)
        except Exception as e:
            status_msg = f"Flap Error: {str(e)[:15]}"
            print(f"Link flap error: {e}", file=sys.stderr)
            break # Stop flapping on error
    status_msg = "Link Flap Stopped"

# --- Main Logic ---
if __name__ == "__main__":
    last_button_press_time = 0
    BUTTON_DEBOUNCE_TIME = 0.3 # seconds
    
    # Calculate character width and height for font
    _img = Image.new("RGB", (10, 10))
    _d = ImageDraw.Draw(_img)
    _bbox = _d.textbbox((0, 0), "M", font=FONT)
    CHAR_W, CHAR_H = _bbox[2] - _bbox[0], _bbox[3] - _bbox[1]
    COLS = WIDTH // CHAR_W
    LINES_PER_SCREEN = HEIGHT // 11 - 3 # Approx lines that fit, minus header/footer

    try:
        # Check for ethtool
        if subprocess.run(["which", "ethtool"], capture_output=True).returncode != 0:
            draw_message(["ethtool not found!", "Please install it."], "red")
            time.sleep(3)
            raise SystemExit("ethtool not found.")

        # --- Interface Selection Screen ---
        ethernet_interfaces = get_ethernet_interfaces()
        if not ethernet_interfaces:
            draw_message(["No Ethernet", "interfaces found!"], "red")
            time.sleep(3)
            raise SystemExit("No Ethernet interfaces found.")
        
        selected_iface_index = 0
        
        while running and not current_interface:
            current_time = time.time()
            draw_interface_selection_ui(ethernet_interfaces, selected_iface_index)
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_iface_index = (selected_iface_index - 1 + len(ethernet_interfaces)) % len(ethernet_interfaces)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_iface_index = (selected_iface_index + 1) % len(ethernet_interfaces)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                current_interface = ethernet_interfaces[selected_iface_index]
                draw_message([f"Selected: {current_interface}"], "lime")
                original_link_settings = get_current_link_settings(current_interface)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

        # --- Main Configuration Screen ---
        if current_interface:
            selected_option_index = 0 # 0: Speed, 1: Duplex, 2: Link Flap
            
            while running:
                current_time = time.time()
                draw_main_config_ui(selected_option_index)
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    selected_option_index = (selected_option_index - 1 + 3) % 3
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    selected_option_index = (selected_option_index + 1) % 3
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["LEFT"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    if selected_option_index == 0: # Speed
                        current_speed_index = (current_speed_index - 1 + len(speed_options)) % len(speed_options)
                    elif selected_option_index == 1: # Duplex
                        current_duplex_index = (current_duplex_index - 1 + len(duplex_options)) % len(duplex_options)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["RIGHT"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    if selected_option_index == 0: # Speed
                        current_speed_index = (current_speed_index + 1) % len(speed_options)
                    elif selected_option_index == 1: # Duplex
                        current_duplex_index = (current_duplex_index + 1) % len(duplex_options)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    if selected_option_index == 0: # Speed
                        speed_val = speed_options[current_speed_index]
                        if speed_val == "Auto":
                            apply_link_setting(current_interface, autoneg=True)
                        else:
                            apply_link_setting(current_interface, speed=speed_val, autoneg=False)
                    elif selected_option_index == 1: # Duplex
                        duplex_val = duplex_options[current_duplex_index]
                        if duplex_val == "Auto":
                            apply_link_setting(current_interface, autoneg=True)
                        else:
                            apply_link_setting(current_interface, duplex=duplex_val, autoneg=False)
                    elif selected_option_index == 2: # Link Flap
                        link_flap_active = not link_flap_active
                        if link_flap_active:
                            threading.Thread(target=link_flap_worker, args=(current_interface,), daemon=True).start()
                            status_msg = "Link Flap Started"
                        else:
                            status_msg = "Link Flap Stopped"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        draw_message([f"CRITICAL ERROR:", str(e)[:20]], "red")
        print(f"Critical error in Ethernet Link Manipulator: {e}", file=sys.stderr)
        time.sleep(5)
    finally:
        cleanup()
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Ethernet Link Manipulator payload finished.")