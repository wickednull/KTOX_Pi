#!/usr/bin/env python3
"""
KTOx *payload* – **BLE Characteristic Scanner**
==================================================
This payload scans for Bluetooth Low Energy (BLE) devices and allows the user
to select a device to retrieve and display its GATT (Generic Attribute Profile)
table. The GATT table, including services and characteristics, is shown on the
LCD and saved to a loot file.

Features:
- Scans for nearby BLE devices.
- Interactive list UI to select a target device.
- Connects to the selected device and retrieves its GATT table.
- Displays GATT services and characteristics on the LCD.
- Saves the GATT table to a loot file for later analysis.
- Graceful exit via KEY3 or Ctrl-C, ensuring Bluetooth is powered off.

Controls:
- DEVICE SELECTION SCREEN:
    - UP/DOWN: Navigate through discovered BLE devices.
    - OK: Select a device to scan its GATT table.
    - KEY3: Rescan for devices.
- GATT TABLE DISPLAY SCREEN:
    - UP/DOWN: Scroll through GATT services and characteristics.
    - KEY3: Go back to device selection.
"""

import sys
import os
import time
import signal
import subprocess
import re
from select import select
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

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

KTOX_DIR = os.path.abspath(os.path.join(__file__, '..', '..'))
LOOT_DIR = os.path.join(KTOX_DIR, "loot", "BLE_GATT")
running = True

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
        draw_message("Cleaning up BLE...")
        run_bt_command(["bluetoothctl", "power", "off"], "Failed to power off Bluetooth", display_error=False)
        run_bt_command(["bluetoothctl", "disconnect"], "Failed to disconnect Bluetooth", display_error=False)
        run_bt_command(["bluetoothctl", "scan", "off"], "Failed to stop Bluetooth scan", display_error=False)
        run_bt_command(["pkill", "-f", "bluetoothctl"], "Failed to kill bluetoothctl processes", display_error=False)
        print("Bluetooth cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(message, color="yellow"):
    """Clear the screen and draw text lines, centering each line."""
    if isinstance(message, str):
        message = [message]
    
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    y_offset = (HEIGHT - len(message) * 15) // 2 # Center vertically
    
    for line in message:
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2 # Center horizontally
        d.text((x, y_offset), line, font=FONT_TITLE, fill=color)
        y_offset += 15 # Line spacing
    
    LCD.LCD_ShowImage(img, 0, 0)

def draw_list_ui(title, items, selected_index):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), title, font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    if not items:
        d.text((10, 60), "Nothing found.", font=FONT, fill="white")
    else:
        start_index = max(0, selected_index - 3) # Show 4 items above, 4 below
        end_index = min(len(items), start_index + 7) # Max 7 lines for items
        
        y_pos = 25
        for i in range(start_index, end_index):
            color = "yellow" if i == selected_index else "white"
            line = items[i]
            if len(line) > 20:
                line = line[:19] + "..."
            d.text((5, y_pos), line, font=FONT, fill=color)
            y_pos += 11
            
    d.text((5, 115), "OK=Select | KEY3=Back", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def bluetoothctl_command(commands):
    output = ""
    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8'
        )
        
        for command in commands:
            proc.stdin.write(command + "\n")
            proc.stdin.flush()
            time.sleep(0.5)

        proc.stdin.write("exit\n")
        proc.stdin.flush()
        
        out, _ = proc.communicate(timeout=15)
        output = out
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        output = out + "\n[Timeout]"
        draw_message(["Bluetoothctl Timeout!", "Check connection."], "red")
        time.sleep(3)
    except Exception as e:
        output = f"Error: {e}"
        draw_message(["Bluetoothctl Error!", f"{str(e)[:20]}"], "red")
        time.sleep(3)
        
    return output

def scan_ble_devices():
    draw_message("Scanning BLE...")
    # Ensure Bluetooth is ready before scanning
    if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"): return {}
    if not run_bt_command(["hciconfig", "hci0", "up"], "Failed to bring up HCI interface"): return {}

    output = bluetoothctl_command(["scan on", "scan off"])
    
    devices = {}
    for line in output.split('\n'):
        match = re.search(r"Device ([0-9A-F:]{17}) (.+)", line)
        if match:
            mac, name = match.group(1), match.group(2).strip()
            if name != "n/a":
                devices[mac] = name
    return devices

def get_gatt_table(mac):
    draw_message(f"Connecting to\n{mac[:10]}...")
    
    commands = [
        f"connect {mac}",
        "menu gatt",
        "list-attributes",
        f"disconnect {mac}"
    ]
    
    output = ""
    try:
        proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8'
        )
        
        proc.stdin.write(f"connect {mac}\n"); proc.stdin.flush()
        time.sleep(5) # Give time to connect
        
        proc.stdin.write("menu gatt\n"); proc.stdin.flush()
        time.sleep(1)
        
        proc.stdin.write("list-attributes\n"); proc.stdin.flush()
        time.sleep(5) # Give time to list attributes
        
        proc.stdin.write(f"disconnect {mac}\n"); proc.stdin.flush()
        time.sleep(1)
        
        proc.stdin.write("exit\n"); proc.stdin.flush()
        
        out, _ = proc.communicate(timeout=20)
        output = out
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        output = out + "\n[Timeout]"
        draw_message(["GATT Timeout!", "Check connection."], "red")
        time.sleep(3)
    except Exception as e:
        output = f"Error: {e}"
        draw_message(["GATT Error!", f"{str(e)[:20]}"], "red")
        time.sleep(3)

    attributes = []
    for line in output.split('\n'):
        if "Attribute" in line or "Primary Service" in line or "Characteristic" in line:
            cleaned_line = line.replace("Attribute", "").strip()
            attributes.append(cleaned_line)
            
    return attributes

class Payload:
    def run(self):
        try:
            # Centralized Bluetooth initialization
            draw_message("Initializing BLE...")
            if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"):
                raise SystemExit("Bluetooth initialization failed.")
            if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"):
                raise SystemExit("Bluetooth initialization failed.")
            if not run_bt_command(["hciconfig", "hci0", "up"], "Failed to bring up HCI interface"):
                raise SystemExit("Bluetooth initialization failed.")

            if not run_bt_command(["which", "bluetoothctl"], "bluetoothctl not found"):
                draw_message("bluetoothctl not found!", "red")
                time.sleep(5)
                raise SystemExit("bluetoothctl not found.")
            if not run_bt_command(["which", "hciconfig"], "hciconfig not found"):
                draw_message("hciconfig not found!", "red")
                time.sleep(5)
                raise SystemExit("hciconfig not found.")

            while running:
                devices = scan_ble_devices()
                if not devices:
                    draw_message("No BLE devices\nfound. Retrying...")
                    time.sleep(3)
                    continue
                    
                device_list = [f"{name} {mac[-5:]}" for mac, name in devices.items()]
                mac_list = list(devices.keys())
                selected_index = 0

                while running:
                    draw_list_ui("Select BLE Target", device_list, selected_index)
                    
                    btn = None
                    for name, pin in PINS.items():
                        if GPIO.input(pin) == 0:
                            btn = name
                            while GPIO.input(pin) == 0:
                                time.sleep(0.05)
                            break

                    if btn == "KEY3": # Back to rescan
                        break
                    
                    if btn == "UP":
                        selected_index = (selected_index - 1) % len(device_list)
                    elif btn == "DOWN":
                        selected_index = (selected_index + 1) % len(device_list)
                    elif btn == "OK":
                        target_mac = mac_list[selected_index]
                        target_name = devices[target_mac]
                        
                        attributes = get_gatt_table(target_mac)
                        
                        if attributes:
                            os.makedirs(LOOT_DIR, exist_ok=True)
                            loot_file = os.path.join(LOOT_DIR, f"{target_mac.replace(':', '')}.txt")
                            with open(loot_file, "w") as f:
                                f.write(f"GATT Table for {target_name} ({target_mac})\n\n")
                                f.writelines([f"{attr}\n" for attr in attributes])
                            
                            attr_selected_index = 0
                            while running:
                                draw_list_ui(f"GATT: {target_name[:10]}", attributes, attr_selected_index)
                                
                                btn_attr = None
                                for name, pin in PINS.items():
                                    if GPIO.input(pin) == 0:
                                        btn_attr = name
                                        while GPIO.input(pin) == 0:
                                            time.sleep(0.05)
                                        break

                                if btn_attr == "KEY3":
                                    break # Back to device selection
                                if btn_attr == "UP":
                                    attr_selected_index = (attr_selected_index - 1) % len(attributes)
                                elif btn_attr == "DOWN":
                                    attr_selected_index = (attr_selected_index + 1) % len(attributes)
                        else:
                            draw_message("Failed to get\nattributes.")
                            time.sleep(3)
                        
                        # After viewing GATT, go back to device selection
                        break
                    
                    time.sleep(0.05)
                
                if not running: # Check if cleanup was called
                    break

        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            draw_message(["An error occurred.", str(e)[:20]], "red")
            time.sleep(3)
        finally:
            LCD.LCD_Clear()
            GPIO.cleanup()
            print("BLE Char Scanner payload finished.")

if __name__ == "__main__":
    payload = Payload()
    payload.run()
