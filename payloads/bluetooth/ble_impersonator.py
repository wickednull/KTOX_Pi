#!/usr/bin/env python3
"""
KTOx *payload* – **BLE Impersonator**
========================================
This payload impersonates a Bluetooth Low Energy (BLE) device by continuously
broadcasting a specific device name (e.g., "My Smart Lock"). This can be used
for social engineering, tricking users into connecting to a fake device, or
to test how devices react to spoofed advertisements.

Features:
- Broadcasts a configurable BLE device name.
- Displays current status (ACTIVE/STOPPED) on the LCD.
- Graceful exit via KEY3 or Ctrl-C, ensuring Bluetooth is cleaned up.

Controls:
- OK: Start impersonation (currently not used, starts automatically)
- KEY3: Exit Payload
"""

import sys
import os
import time
import signal
import subprocess
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

TARGET_NAME = "My Smart Lock"

PINS = { "OK": 13, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()
WIDTH, HEIGHT = 128, 128

running = True
advertisement_id = 0 # To track the registered advertisement

def run_bt_command(command_parts, error_message, display_error=True):
    try:
        result = subprocess.run(command_parts, shell=False, check=True, capture_output=True, text=True)
        if result.stderr:
            print(f"WARNING: {error_message} - STDERR: {result.stderr.strip()}", file=sys.stderr)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {error_message} - Command: {' '.join(command_parts)} - STDERR: {e.stderr.strip()}", file=sys.stderr)
        if display_error:
            draw_ui(status="ERROR", message_lines=[f"ERROR: {error_message}", f"{e.stderr.strip()[:20]}"])
            time.sleep(3)
        return False
    except FileNotFoundError:
        print(f"ERROR: {error_message} - Command not found: {command_parts[0]}", file=sys.stderr)
        if display_error:
            draw_ui(status="ERROR", message_lines=[f"ERROR: Command not found", f"{command_parts[0]}"])
            time.sleep(3)
        return False

def cleanup(*_):
    global running
    if running:
        running = False
        print("Cleaning up Bluetooth devices...", file=sys.stderr)
        draw_ui(status="CLEANING UP", message_lines=["Cleaning up BLE..."])
        stop_impersonation() # Ensure impersonation is stopped gracefully
        run_bt_command(["bluetoothctl", "power", "off"], "Failed to power off Bluetooth", display_error=False)
        run_bt_command(["pkill", "-f", "bluetoothctl"], "Failed to kill bluetoothctl processes", display_error=False)
        print("Bluetooth cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(status: str, message_lines=None):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "BLE Impersonator", font=FONT_TITLE, fill="#FF0000")
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
    else:
        status_color = "lime" if status == "ACTIVE" else "red"
        d.text((30, 40), status, font=FONT_TITLE, fill=status_color)
        d.text((5, 60), f"Spoofing:", font=FONT)
        d.text((10, 75), TARGET_NAME[:20], font=FONT, fill="yellow")
    
    d.text((5, 110), "Press KEY3 to Stop", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def start_impersonation():
    global advertisement_id
    
    draw_ui(status="STARTING", message_lines=["Starting BLE Impersonation..."])
    # Explicitly ensure Bluetooth adapter is ready
    if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"): return False
    if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"): return False
    if not run_bt_command(["hciconfig", "hci0", "up"], "Failed to bring up HCI interface"): return False

    # Remove any existing advertisement with our ID
    run_bt_command(["bluetoothctl", "remove-advertisement", str(advertisement_id)], "Failed to remove previous advertisement", display_error=False)

    # Register a new advertisement with the target name as local name
    advertisement_id = 1 # Use a fixed ID for this script
    register_cmd_parts = [
        "bluetoothctl", "advertise", str(advertisement_id),
        "type", "broadcast",
        "local-name", f"'{TARGET_NAME}'"
    ]
    
    if run_bt_command(register_cmd_parts, "Failed to register advertisement"):
        if run_bt_command(["bluetoothctl", "advertise", "on"], "Failed to enable advertising"):
            return True
    return False

def stop_impersonation():
    draw_ui(status="STOPPING", message_lines=["Stopping BLE Impersonation..."])
    run_bt_command(["bluetoothctl", "advertise", "off"], "Failed to stop advertising", display_error=False)
    run_bt_command(["bluetoothctl", "remove-advertisement", str(advertisement_id)], "Failed to remove current advertisement", display_error=False)
    run_bt_command(["bluetoothctl", "remove-advertisement", "0"], "Failed to remove default advertisement 0", display_error=False)

class Payload:
    def run(self):
        try:
            if not run_bt_command(["which", "bluetoothctl"], "bluetoothctl not found"):
                draw_ui(status="ERROR", message_lines=["bluetoothctl not found!"])
                time.sleep(3)
                raise SystemExit("bluetoothctl not found.")
            
            if not run_bt_command(["which", "hciconfig"], "hciconfig not found"):
                draw_ui(status="ERROR", message_lines=["hciconfig not found!"])
                time.sleep(3)
                raise SystemExit("hciconfig not found.")

            if start_impersonation():
                while running:
                    draw_ui("ACTIVE")
                    if GPIO.input(PINS["KEY3"]) == 0:
                        cleanup()
                    time.sleep(1)
            else:
                draw_ui(status="FAILED", message_lines=["Failed to start", "impersonation!"])
                time.sleep(3)
        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            draw_ui(status="ERROR", message_lines=["An error occurred.", str(e)[:20]])
            time.sleep(3)
        finally:
            cleanup()
            LCD.LCD_Clear()
            GPIO.cleanup()
            print("BLE Impersonator payload finished.")

if __name__ == "__main__":
    payload = Payload()
    payload.run()