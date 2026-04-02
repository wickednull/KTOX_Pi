#!/usr/bin/env python3
"""
KTOx *payload* – **Stop Monitor Mode (wlan1)**
=================================================
This payload attempts to deactivate monitor mode on the specified Wi-Fi interface
(defaulting to `wlan1`) and restore it to managed mode. This is useful after
completing Wi-Fi reconnaissance or attacks that require monitor mode.

Features:
- Automatically attempts to put `wlan1` into managed mode.
- Displays status messages on the LCD regarding the deactivation process.
- Uses `WiFiManager` for robust interface management.
- Graceful exit via Ctrl-C or SIGTERM.

Controls:
- This payload is designed to be executed directly.
- No interactive controls after launch, it performs its function and exits.
"""
import sys
import os
import time
import signal
import subprocess
import threading

# ----------------------------
# KTOx PATH and ROOT check
# ----------------------------
def is_root():
    return os.geteuid() == 0

# Dynamically add KTOx path
KTOX_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'KTOx'))
if KTOX_PATH not in sys.path:
    sys.path.append(KTOX_PATH)

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

# ----------------------------
# KTOx WiFi Integration
# ----------------------------
try:
    import monitor_mode_helper
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def deactivate_monitor_mode(interface):
        return False

def _detect_monitor_target():
    """Prefer wlan1 (USB external adapter) for monitor mode; fall back to wlan0."""
    for iface in ['wlan1', 'wlan0']:
        if os.path.exists(f'/sys/class/net/{iface}'):
            return iface
    return 'wlan1'

TARGET_INTERFACE_BASE = _detect_monitor_target()

PINS: dict[str, int] = {
    "OK": 13, "KEY3": 16,
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

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def draw_message(lines, color="lime"):
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

def main():
    draw_message(["Deactivating monitor", f"mode on {TARGET_INTERFACE_BASE}...", "Please wait."], "yellow")

    print(f"Attempting to deactivate monitor mode on {TARGET_INTERFACE_BASE}...", file=sys.stderr)
    try:
        success = monitor_mode_helper.deactivate_monitor_mode(TARGET_INTERFACE_BASE)
        if success:
            draw_message(["Monitor mode", "DEACTIVATED!", f"Interface: {TARGET_INTERFACE_BASE}"], "lime")
            print(f"Successfully deactivated monitor mode on {TARGET_INTERFACE_BASE}", file=sys.stderr)
        else:
            draw_message(["ERROR:", "Failed to deactivate", "monitor mode!"], "red")
            print(f"ERROR: monitor_mode_helper.deactivate_monitor_mode failed for {TARGET_INTERFACE_BASE}", file=sys.stderr)
    except Exception as e:
        draw_message(["CRITICAL ERROR:", str(e)[:20]], "red")
        print(f"Critical error during monitor mode deactivation: {e}", file=sys.stderr)
    
    time.sleep(5)

if __name__ == "__main__":
    if not is_root():
        print("ERROR: This script requires root privileges.", file=sys.stderr)
        # Attempt to display on LCD if possible
        try:
            LCD = LCD_1in44.LCD()
            LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            img = Image.new("RGB", (128, 128), "black")
            d = ImageDraw.Draw(img)
            FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            d.text((10, 40), "ERROR:\nRoot privileges\nrequired.", font=FONT_TITLE, fill="red")
            LCD.LCD_ShowImage(img, 0, 0)
        except Exception as e:
            print(f"Could not display error on LCD: {e}", file=sys.stderr)
        sys.exit(1)

    if not WIFI_INTEGRATION_AVAILABLE:
        draw_message(["ERROR:", "WiFi integration not found."], "red")
        time.sleep(5)
        sys.exit(1)
        
    try:
        main()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        draw_message(["Payload", "interrupted."], "yellow")
        time.sleep(2)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Stop Monitor Mode payload finished.")