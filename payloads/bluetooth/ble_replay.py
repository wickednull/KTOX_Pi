#!/usr/bin/env python3
"""
KTOx *payload* – **BLE Replay Attack (Conceptual)**
======================================================
This payload is a conceptual demonstration of a Bluetooth Low Energy (BLE)
replay attack. It simulates sending a pre-defined BLE advertisement packet.
**Note: This payload currently only simulates the replay process and does
not perform an actual BLE packet replay.** A full implementation would require
capturing and re-transmitting actual BLE packets, which is more complex.

Features:
- Simulates sending a pre-defined BLE advertisement packet.
- Provides UI feedback on the simulated replay status.
- Graceful exit via KEY3 or Ctrl-C, ensuring Bluetooth is cleaned up.

Controls:
- OK: "Send" the simulated replay packet.
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

FAKE_REPLAY_PACKET_DATA = "0x08 0x0008 1e 02 01 06 1a ff 4c 00 07 19 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"

PINS = { "OK": 13, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()
WIDTH, HEIGHT = 128, 128

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
        run_bt_command(["pkill", "-f", "bluetoothctl"], "Failed to kill bluetoothctl processes", display_error=False)
        print("Bluetooth cleanup complete.", file=sys.stderr)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_ui(status_msg=None, message_lines=None):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    d.text((5, 5), "BLE Replay Attack", font=FONT_TITLE, fill="#FF0000")
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
    elif status_msg:
        y_pos = 30
        for line in status_msg.split('\n'):
            d.text((5, y_pos), line, font=FONT, fill="yellow")
            y_pos += 12
    
    d.text((5, 110), "OK=Replay | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def run_attack():
    draw_ui(message_lines=["Simulating replay...", "Sending packet..."])
    
    try:
        time.sleep(2) # Simulate packet sending time
        
        draw_ui(message_lines=["Simulated packet sent.", "Check if action", "occurred on the", "target device."])
        
    except Exception as e:
        draw_ui(message_lines=[f"Attack FAILED!", f"{str(e)[:20]}"])
        print(f"BLE Replay failed: {e}", file=sys.stderr)

class Payload:
    def run(self):
        try:
            # Explicitly ensure Bluetooth adapter is ready
            if not run_bt_command(["rfkill", "unblock", "bluetooth"], "Failed to unblock Bluetooth"):
                raise SystemExit("Bluetooth initialization failed.")
            if not run_bt_command(["bluetoothctl", "power", "on"], "Failed to power on Bluetooth"):
                raise SystemExit("Bluetooth initialization failed.")
            if not run_bt_command(["hciconfig", "hci0", "up"], "Failed to bring up HCI interface"):
                raise SystemExit("Bluetooth initialization failed.")

            draw_ui(message_lines=["BLE Replay Concept", "Press OK to 'send'", "a fake packet."])
            while running:
                if GPIO.input(PINS["KEY3"]) == 0:
                    cleanup()
                    break
                if GPIO.input(PINS["OK"]) == 0:
                    run_attack()
                    time.sleep(4)
                    draw_ui(message_lines=["Ready to replay", "again."])
                time.sleep(0.1)
                
        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            draw_ui(message_lines=["An error occurred.", str(e)[:20]], color="red")
            time.sleep(3)
        finally:
            cleanup()
            LCD.LCD_Clear()
            GPIO.cleanup()
            print("BLE Replay payload finished.")

if __name__ == "__main__":
    payload = Payload()
    payload.run()
