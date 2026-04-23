#!/usr/bin/env python3
"""
KTOx *payload* – **Bluetooth Device Scanner**
================================================
This payload scans for classic Bluetooth devices (not BLE) and displays
their MAC addresses and names on the LCD. It provides a simple way to
discover nearby Bluetooth devices.

Features:
- Scans for classic Bluetooth devices using `bluetoothctl`.
- Displays a scrollable list of discovered devices on the LCD.
- Graceful exit via KEY3 or Ctrl-C, ensuring Bluetooth is cleaned up.

Controls:
- UP/DOWN: Scroll through the list of discovered devices.
- OK: Rescan for devices.
- KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import re
from select import select
from typing import List, Tuple

# ----------------------------
# KTOx PATH and ROOT check
# ----------------------------
def is_root():
    return os.geteuid() == 0

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)

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

running = True

LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'bluetooth_scanner')
os.makedirs(LOOT_DIR, exist_ok=True)

def run_bt_command(command_parts, error_message, display_error=True):
    try:
        result = subprocess.run(command_parts, shell=False, check=True, capture_output=True, text=True)
        if result.stderr:
            print(f"WARNING: {error_message} - STDERR: {result.stderr.strip()}", file=sys.stderr)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {error_message} - Command: {' '.join(command_parts)} - STDERR: {e.stderr.strip()}", file=sys.stderr)
        if display_error:
            draw_message([f"ERROR: {error_message}", f"{e.stderr.strip()[:20]}"], "red")
            time.sleep(3)
        return False
    except FileNotFoundError:
        print(f"ERROR: {error_message} - Command not found: {command_parts[0]}", file=sys.stderr)
        if display_error:
            draw_message([f"ERROR: Command not found", f"{command_parts[0]}"], "red")
            time.sleep(3)
        return False

def cleanup(*_):
    global running
    if running:
        running = False
        print("Cleaning up Bluetooth devices...", file=sys.stderr)
        draw_message(["Cleaning up Bluetooth..."])
        run_bt_command(["bluetoothctl", "power", "off"], "Failed to power off Bluetooth", display_error=False)
        run_bt_command(["bluetoothctl", "scan", "off"], "Failed to stop Bluetooth scan", display_error=False)
        run_bt_command(["pkill", "-f", "bluetoothctl"], "Failed to kill bluetoothctl processes", display_error=False)
        print("Bluetooth cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(lines: List[str], color="yellow") -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    
    y_offset = (HEIGHT - len(lines) * 15) // 2 # Center vertically
    
    for ln in lines:
        bbox = d.textbbox((0, 0), ln, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2
        d.text((x, y_offset), ln, font=FONT_TITLE, fill=color)
        y_offset += 15
    LCD.LCD_ShowImage(img, 0, 0)

def draw_device_list(devices: List[Tuple[str, str]], selected_index: int):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    
    title = f"BT Scan ({len(devices)})"
    d.text((5, 5), title, font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

    if not devices:
        d.text((10, 50), "No devices found", font=FONT, fill=(242, 243, 244))
    else:
        start_index = max(0, selected_index - 2)
        end_index = min(len(devices), start_index + 6)
        
        y_pos = 30
        for i in range(start_index, end_index):
            mac, name = devices[i]
            display_name = name if name else "N/A"
            line = f"{mac} {display_name[:10]}"
            
            fill = (212, 172, 13) if i == selected_index else "white"
            d.text((5, y_pos), line, font=FONT, fill=fill)
            y_pos += 15

    d.text((5, 110), "UP/DOWN | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

SCAN_SECONDS = 10

def discover_devices() -> List[Tuple[str, str]]:
    draw_message(["Scanning for", "Bluetooth devices...", f"({SCAN_SECONDS}s)"])

    # Centralized Bluetooth initialization (already done in main)
    # run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth")

    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write("scan on\n"); proc.stdin.flush()

    seen: dict[str, str] = {}
    start_time = time.time()
    try:
        while running and (time.time() - start_time) < SCAN_SECONDS:
            if GPIO.input(PINS["KEY3"]) == 0:
                cleanup()
                break
            
            ready, _, _ = select([proc.stdout], [], [], 0.2)
            if ready:
                line = proc.stdout.readline()
                m = re.search(r"Device ([0-9A-F:]{17}) (.+)", line)
                if m:
                    mac, name = m.group(1), m.group(2).strip()
                    if name != "n/a":
                        seen[mac] = name
                draw_message([f"Scanning ({int(SCAN_SECONDS - (time.time() - start_time))}s)", f"Found: {len(seen)} devices"])
    finally:
        proc.stdin.write("scan off\n"); proc.stdin.flush()
        time.sleep(1)
        proc.terminate()

    devices = sorted(seen.items(), key=lambda t: (t[1].lower(), t[0]))
    try:
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f"scan_{ts}.txt")
        with open(loot_file, 'w') as f:
            f.write(f"Bluetooth scan results ({ts})\n")
            for mac, name in devices:
                f.write(f"{mac} {name}\n")
        print(f"Loot saved to {loot_file}")
    except Exception as e:
        print(f"Failed to save scan loot: {e}", file=sys.stderr)
    return devices

class Payload:
    def run(self):
        try:
            # Centralized Bluetooth initialization
            draw_message(["Initializing Bluetooth..."])
            if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"):
                raise SystemExit("Bluetooth initialization failed.")
            if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"):
                raise SystemExit("Bluetooth initialization failed.")
            if not run_bt_command(["hciconfig", "hci0", "up"], "Failed to bring up HCI interface"):
                raise SystemExit("Bluetooth initialization failed.")

            if not run_bt_command(["which", "bluetoothctl"], "bluetoothctl not found"):
                draw_message(["bluetoothctl not found!", "Exiting..."], "red")
                time.sleep(3)
                sys.exit(1)

            devices = []
            selected_index = 0
            
            last_button_press_time = 0
            BUTTON_DEBOUNCE_TIME = 0.3 # seconds

            draw_message(["Press OK to scan"])

            while running:
                current_time = time.time()

                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    devices = discover_devices()
                    selected_index = 0
                    if not running: break # Check if cleanup was called during scan
                    draw_device_list(devices, selected_index)
                    time.sleep(BUTTON_DEBOUNCE_TIME) # Debounce after OK press

                if devices: # Only allow scrolling if devices are found
                    if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                        last_button_press_time = current_time
                        selected_index = (selected_index - 1) % len(devices)
                        draw_device_list(devices, selected_index)
                        time.sleep(BUTTON_DEBOUNCE_TIME)
                    elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                        last_button_press_time = current_time
                        selected_index = (selected_index + 1) % len(devices)
                        draw_device_list(devices, selected_index)
                        time.sleep(BUTTON_DEBOUNCE_TIME)
                
                time.sleep(0.05)

        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            draw_message(["An error occurred.", str(e)[:20]], "red")
            time.sleep(3)
        finally:
            LCD.LCD_Clear()
            GPIO.cleanup()
            print("Bluetooth Scanner payload finished.")

def check_dependencies():
    """Check for required command-line tools."""
    for dep in ["bluetoothctl", "hciconfig", "rfkill"]:
        if subprocess.run(["which", dep], capture_output=True).returncode != 0:
            return dep
    return None

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

    dep_missing = check_dependencies()
    if dep_missing:
        draw_message([f"ERROR:", f"{dep_missing} not found."], "red")
        time.sleep(5)
        sys.exit(1)
        
    payload = Payload()
    payload.run()