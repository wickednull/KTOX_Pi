#!/usr/bin/env python3
"""
KTOx *payload* – **BLE Service Explorer**
============================================
This payload scans for Bluetooth Low Energy (BLE) devices, connects to them,
and then lists their primary services. It provides an interactive way to
discover what services are offered by nearby BLE devices.

Features:
- Scans for nearby BLE devices.
- Connects to discovered devices to retrieve service information.
- Displays a scrollable list of devices and their identified services on the LCD.
- Graceful exit via KEY3 or Ctrl-C, ensuring Bluetooth is cleaned up.

Controls:
- MAIN SCREEN:
    - OK: Start a new scan.
    - KEY3: Exit Payload.
- SCAN RESULTS SCREEN:
    - UP/DOWN: Scroll through the list of devices and services.
    - KEY3: Go back to the main screen (to rescan or exit).
"""

import sys
import os
import time
import signal
import subprocess
import re

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)

import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

PINS = { "OK": 13, "KEY3": 16, "UP": 6, "DOWN": 19}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default() 
WIDTH, HEIGHT = 128, 128

running = True
selected_index = 0
results = []

LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'ble_service_explorer')
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
            draw_ui(message_lines=[f"ERROR: {error_message}", f"{e.stderr.strip()[:20]}"])
            time.sleep(3)
        return False
    except FileNotFoundError:
        print(f"ERROR: {error_message} - Command not found: {command_parts[0]}", file=sys.stderr)
        if display_error:
            draw_ui(message_lines=[f"ERROR: Command not found", f"{command_parts[0]}"])
            time.sleep(3)
        return False

def cleanup(*_):
    global running
    if running:
        running = False
        print("Cleaning up Bluetooth devices...", file=sys.stderr)
        draw_ui(message_lines=["Cleaning up BLE..."])
        run_bt_command(["bluetoothctl", "power", "off"], "Failed to power off Bluetooth", display_error=False)
        run_bt_command(["bluetoothctl", "disconnect"], "Failed to disconnect Bluetooth", display_error=False)
        run_bt_command(["bluetoothctl", "scan", "off"], "Failed to stop Bluetooth scan", display_error=False)
        run_bt_command(["pkill", "-f", "bluetoothctl"], "Failed to kill bluetoothctl processes", display_error=False)
        print("Bluetooth cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(status_msg=None, message_lines=None):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "BLE Service Explorer", font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

    if message_lines:
        if isinstance(message_lines, str):
            message_lines = [message_lines]
        y_offset = (HEIGHT - len(message_lines) * 12) // 2
        for line in message_lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (WIDTH - w) // 2
            d.text((x, y_offset), line, font=FONT, fill=(212, 172, 13))
            y_offset += 12
    elif status_msg:
        d.text((10, 60), status_msg, font=FONT, fill=(212, 172, 13))
    else: # Display scan results
        start_index = max(0, selected_index - 4)
        end_index = min(len(results), start_index + 8)
        y_pos = 25
        for i in range(start_index, end_index):
            color = "yellow" if i == selected_index else "white"
            line = results[i]
            if len(line) > 20: line = line[:19] + "..."
            d.text((5, y_pos), line, font=FONT, fill=color)
            y_pos += 11

    d.text((5, 110), "OK=Scan | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

def run_scan():
    global results, selected_index
    draw_ui(status_msg="Scanning BLE...")
    results = []
    selected_index = 0
    
    try:
        # Explicit Bluetooth adapter initialization (already done in main)
        # if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"): return
        # if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"): return
        # if not run_bt_command(["hciconfig", "hci0", "up"], "Failed to bring up HCI interface"): return

        scan_proc = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8'
        )
        assert scan_proc.stdin and scan_proc.stdout
        scan_proc.stdin.write("scan on\n"); scan_proc.stdin.flush()
        time.sleep(8) # Scan for 8 seconds
        scan_proc.stdin.write("scan off\n"); scan_proc.stdin.flush()
        scan_proc.stdin.write("exit\n"); scan_proc.stdin.flush()
        out, _ = scan_proc.communicate(timeout=5)
        
        devices = {}
        for line in out.split('\n'):
            match = re.search(r"Device ([0-9A-F:]{17}) (.+)", line)
            if match:
                mac, name = match.group(1), match.group(2).strip()
                if name != "n/a": devices[mac] = name
        
        if not devices:
            results.append("No devices found.")
            return

        for mac, name in devices.items():
            if not running: break
            draw_ui(status_msg=f"Checking {name[:10]}...")
            
            conn_proc = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                encoding='utf-8'
            )
            assert conn_proc.stdin
            conn_proc.stdin.write(f"connect {mac}\n"); conn_proc.stdin.flush()
            time.sleep(4) # Give time to connect
            
            conn_proc.stdin.write("info\n"); conn_proc.stdin.flush()
            time.sleep(1) # Give time to get info
            
            conn_proc.stdin.write("exit\n"); conn_proc.stdin.flush()
            out, _ = conn_proc.communicate(timeout=10)
            
            if "Connected: yes" in out:
                results.append(f"DEV: {name[:12]}")
                for line in out.split('\n'):
                    if "Primary" in line:
                        uuid_match = re.search(r"([0-9a-f-]{36})", line)
                        if uuid_match:
                            uuid = uuid_match.group(1)
                            if "1800" in uuid: results.append("  Generic Access")
                            elif "1801" in uuid: results.append("  Generic Attribute")
                            elif "180f" in uuid: results.append("  Battery Service")
                            elif "180d" in uuid: results.append("  Heart Rate")
                            else: results.append(f"  {uuid[:8]}...")
            
    except subprocess.TimeoutExpired as e:
        results.append("Scan timed out!")
        print(f"BLE scan timed out: {e}", file=sys.stderr)
        draw_ui(message_lines=["Scan timed out!", f"{str(e)[:20]}"])
        time.sleep(3)
    except Exception as e:
        results.append("Scan error!")
        print(f"BLE scan failed: {e}", file=sys.stderr)
        draw_ui(message_lines=["Scan error!", f"{str(e)[:20]}"])
        time.sleep(3)
    finally:
        # Save loot snapshot of results
        try:
            ts = time.strftime('%Y-%m-%d_%H%M%S')
            loot_file = os.path.join(LOOT_DIR, f"ble_services_{ts}.txt")
            with open(loot_file, 'w') as f:
                f.write(f"BLE Service Explorer results ({ts})\n")
                for line in results:
                    f.write(line + "\n")
            print(f"Loot saved to {loot_file}")
        except Exception as e:
            print(f"Failed to save BLE loot: {e}", file=sys.stderr)

if __name__ == "__main__":
    try:
        # Centralized Bluetooth initialization
        draw_ui(message_lines=["Initializing BLE..."])
        if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"):
            raise SystemExit("Bluetooth initialization failed.")
        if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"):
            raise SystemExit("Bluetooth initialization failed.")
        if not run_bt_command(["hciconfig", "hci0", "up"], "Failed to bring up HCI interface"):
            raise SystemExit("Bluetooth initialization failed.")

        if subprocess.run("which bluetoothctl", shell=True, capture_output=True).returncode != 0:
            draw_ui(message_lines=["bluetoothctl not found!"])
            time.sleep(5)
            raise SystemExit("bluetoothctl not found.")
        if subprocess.run("which hciconfig", shell=True, capture_output=True).returncode != 0:
            draw_ui(message_lines=["hciconfig not found!"])
            time.sleep(5)
            raise SystemExit("hciconfig not found.")

        draw_ui(status_msg="Press OK to scan")
        while running:
            if GPIO.input(PINS["KEY3"]) == 0:
                cleanup()
                break
            
            if GPIO.input(PINS["OK"]) == 0:
                run_scan()
                draw_ui() # Display results
                time.sleep(0.5)
                while running: # Loop for scrolling results
                    btn = None
                    for name, pin in PINS.items():
                        if GPIO.input(pin) == 0:
                            btn = name
                            while GPIO.input(pin) == 0:
                                time.sleep(0.05)
                            break
                    
                    if btn == "KEY3":
                        break # Exit results view
                    if btn == "UP":
                        selected_index = (selected_index - 1) % len(results) if results else 0
                        draw_ui()
                    elif btn == "DOWN":
                        selected_index = (selected_index + 1) % len(results) if results else 0
                        draw_ui()
                    time.sleep(0.05)
                draw_ui(status_msg="Press OK to scan") # Return to main prompt
            
            time.sleep(0.1)

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
        print("BLE Service Explorer payload finished.")