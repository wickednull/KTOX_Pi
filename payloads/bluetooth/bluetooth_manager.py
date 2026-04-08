#!/usr/bin/env python3
# KTOx Bluetooth Manager Payload

import sys
import os
import time
import signal
import subprocess
import re

# Add KTOx root to the Python path
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import LCD_Config
    import LCD_1in44
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Required libraries not found. Please run install_ktox.sh")
    sys.exit(1)

# --- Configuration ---
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "KEY_PRESS": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16
}
SCAN_TIME = 12  # seconds

# --- Global State ---
RUNNING = True
LCD = None
image = Image.new("RGB", (128, 128), "BLACK")
draw = ImageDraw.Draw(image)
font = ImageFont.load_default()

# --- Helper Functions ---
def cleanup(*_):
    global RUNNING
    if not RUNNING: return
    RUNNING = False
    # Ensure bluetoothctl scan is off
    subprocess.run(["bluetoothctl", "scan", "off"], timeout=5, capture_output=True)
    print("Bluetooth Manager: Cleaning up GPIO...")
    if LCD: LCD.LCD_Clear()
    GPIO.cleanup()
    print("Bluetooth Manager: Exiting.")
    sys.exit(0)

def draw_message(message, fill="WHITE"):
    """Draws a multi-line message centered on the screen."""
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    y = 10
    for i, line in enumerate(message.split('\n')):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text(((128 - text_width) // 2, y + i * 15), line, fill=fill)
    LCD.LCD_ShowImage(image, 0, 0)

def run_bt_command(command, timeout=10):
    """Runs a bluetoothctl command and returns its output."""
    try:
        # Using a heredoc to pass commands non-interactively
        full_command = f"printf '{command}\nexit' | bluetoothctl"
        proc = subprocess.run(full_command, shell=True, capture_output=True, text=True, timeout=timeout)
        return proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return "", "Command timed out"
    except Exception as e:
        return "", str(e)

# --- Main Execution Block ---
if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

        # --- 1. Initial Power On ---
        draw_message("Powering on\nBluetooth...")
        run_bt_command("power on")
        time.sleep(1)

        # --- 2. Scanning Phase ---
        draw_message(f"Scanning for\ndevices for\n{SCAN_TIME} seconds...")
        # Start scan in background
        scan_proc = subprocess.Popen(["bluetoothctl", "scan", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(SCAN_TIME)
        scan_proc.terminate()
        run_bt_command("scan off", timeout=2) # Ensure scan is off

        # --- 3. Parse Devices ---
        draw_message("Processing list...")
        devices_raw, _ = run_bt_command("devices")
        
        found_devices = []
        # Regex to capture MAC and Name
        device_regex = re.compile(r"Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) (.+)")
        for line in devices_raw.split('\n'):
            match = device_regex.match(line)
            if match:
                mac, name = match.groups()
                found_devices.append({"mac": mac, "name": name})

        if not found_devices:
            draw_message("No devices found.\n\nExiting.", fill="YELLOW")
            time.sleep(5)
            cleanup()

        # --- 4. Menu Phase ---
        selected_index = 0
        last_press_time = 0
        DEBOUNCE_DELAY = 0.25

        while RUNNING:
            # Input
            now = time.time()
            if (now - last_press_time) > DEBOUNCE_DELAY:
                if GPIO.input(PINS["KEY3"]) == 0: break
                if GPIO.input(PINS["UP"]) == 0:
                    last_press_time = now
                    selected_index = (selected_index - 1) % len(found_devices)
                if GPIO.input(PINS["DOWN"]) == 0:
                    last_press_time = now
                    selected_index = (selected_index + 1) % len(found_devices)
                
                if GPIO.input(PINS["KEY_PRESS"]) == 0:
                    last_press_time = now
                    device = found_devices[selected_index]
                    mac = device["mac"]
                    name = device["name"]

                    # --- 5. Connection Phase ---
                    draw_message(f"Connecting to\n{name[:18]}...")
                    
                    # Chain commands for pairing, trusting, and connecting
                    out, err = run_bt_command(f"pair {mac}\ntrust {mac}\nconnect {mac}", timeout=25)
                    
                    if "Connection successful" in out:
                        draw_message(f"Connected to\n{name[:18]}!", fill="LIME")
                    elif "Failed to connect" in out or err:
                        draw_message(f"Failed to\nconnect.", fill="RED")
                    else: # Sometimes it connects without the "successful" message
                        draw_message(f"Connected to\n{name[:18]}!", fill="YELLOW")

                    time.sleep(4)
                    cleanup() # Exit after attempting connection

            # Drawing
            draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
            display_start = max(0, selected_index - 4)
            display_end = display_start + 8
            
            y = 5
            for i, device in enumerate(found_devices[display_start:display_end]):
                idx = i + display_start
                prefix = ">" if idx == selected_index else " "
                display_item = device['name']
                if len(display_item) > 18: display_item = display_item[:17] + "…"
                draw.text((5, y), f"{prefix} {display_item}", fill="YELLOW" if idx == selected_index else "WHITE", font=font)
                y += 15

            LCD.LCD_ShowImage(image, 0, 0)
            time.sleep(0.05)

    finally:
        cleanup()
