#!/usr/bin/env python3
"""
KTOx *payload* – **Dependency Updater**
==========================================
This payload provides a UI to install all necessary dependencies for the
advanced payloads from the ktox-payloads repository.

Features:
- Displays a list of required APT and PIP packages.
- Requires user confirmation before starting the installation.
- Runs the installation in a background thread to keep the UI responsive.
- Streams the output of the `apt-get` and `pip` commands to the LCD in real-time.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- CONFIRMATION SCREEN:
    - OK: Start the installation.
    - KEY3: Cancel and exit the payload.
- INSTALLATION SCREEN:
    - KEY3: Abort and exit (installation will continue in the background).
"""

import sys
import os
import time
import signal
import subprocess
import threading

# Add KTOx root to path for imports
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_Config
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Hardware libraries not found.", file=sys.stderr)
    sys.exit(1)

# --- Global State ---
PINS = {"OK": 13, "KEY3": 16}
RUNNING = True
INSTALL_THREAD = None
UI_LOCK = threading.Lock()
INSTALL_OUTPUT_LINES = ["Press OK to start..."]

# --- Dependencies ---
APT_PACKAGES = [
    # Bluetooth & Hardware
    "bluez", "bluez-tools",
    # WiFi & Network Core
    "aircrack-ng", "hcxtools", "hcxdumptool", "mdk4",
    "wireless-tools", "wpasupplicant", "iw", "arp-scan",
    "nmap", "tcpdump", "net-tools",
    # MITM & Interception
    "mitmproxy", "responder", "dnsmasq", "hostapd",
    # Credential & Exploitation
    "hashcat", "john", "hydra", "sshpass",
    "enum4linux", "impacket-scripts", "smbclient",
    # Reconnaissance (snmp provides snmpwalk binary)
    "snmp", "snmpd",
    # Utilities
    "wifite", "w3m"
]
PIP_PACKAGES = [
    "impacket"
]

# --- Cleanup Handler ---
def cleanup(*_):
    global RUNNING
    if not RUNNING:
        return
    RUNNING = False
    print("Updater: Cleaning up GPIO...")
    GPIO.cleanup()
    print("Updater: Exiting.")

# --- UI Drawing ---
def draw_ui(screen_state="confirm"):
    with UI_LOCK:
        image = Image.new("RGB", (128, 128), (10, 0, 0))
        draw = ImageDraw.Draw(image)
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except IOError:
            font_title = ImageFont.load_default()
            font_small = ImageFont.load_default()

        draw.text((5, 5), "Dependency Updater", font=font_title, fill=(171, 178, 185))
        draw.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)

        if screen_state == "confirm":
            draw.text((5, 25), "Will install:", font=font_small, fill=(242, 243, 244))
            draw.text((10, 40), f"APT: {', '.join(APT_PACKAGES)}", font=font_small, fill=(212, 172, 13))
            draw.text((10, 65), f"PIP: {', '.join(PIP_PACKAGES)}", font=font_small, fill=(212, 172, 13))
            draw.text((5, 100), "OK=Start | KEY3=Cancel", font=font_small, fill=(231, 76, 60))
        
        elif screen_state == "installing":
            draw.text((5, 25), "Installing...", font=font_small, fill=(242, 243, 244))
            y = 40
            for line in INSTALL_OUTPUT_LINES[-8:]:
                draw.text((5, y), line, font=font_small, fill=(212, 172, 13))
                y += 10
            draw.text((5, 115), "KEY3 to Exit", font=font_small, fill="ORANGE")

        LCD.LCD_ShowImage(image, 0, 0)

# --- Installation Logic ---
def installation_worker():
    global INSTALL_OUTPUT_LINES

    def run_command(command):
        global INSTALL_OUTPUT_LINES
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in iter(process.stdout.readline, ''):
                if not RUNNING:
                    process.terminate()
                    break
                with UI_LOCK:
                    INSTALL_OUTPUT_LINES.append(line.strip())
                time.sleep(0.05) 
            process.wait()
            return process.returncode == 0
        except Exception as e:
            with UI_LOCK:
                INSTALL_OUTPUT_LINES.append(f"Error: {e}")
            return False

    with UI_LOCK:
        INSTALL_OUTPUT_LINES = ["Updating package list..."]
    
    if not run_command(["sudo", "apt-get", "update", "-qq"]):
        with UI_LOCK:
            INSTALL_OUTPUT_LINES.append("APT update failed!")
            INSTALL_OUTPUT_LINES.append("Finished.")
        return

    with UI_LOCK:
        INSTALL_OUTPUT_LINES.append("Installing APT packages...")
    if not run_command(["sudo", "apt-get", "install", "-y", "--no-install-recommends"] + APT_PACKAGES):
        with UI_LOCK:
            INSTALL_OUTPUT_LINES.append("APT install failed!")
            INSTALL_OUTPUT_LINES.append("Finished.")
        return
    
    with UI_LOCK:
        INSTALL_OUTPUT_LINES.append("Installing PIP packages...")
    if not run_command(["sudo", "pip3", "install"] + PIP_PACKAGES):
        with UI_LOCK:
            INSTALL_OUTPUT_LINES.append("PIP install failed!")
            INSTALL_OUTPUT_LINES.append("Finished.")
        return

    with UI_LOCK:
        INSTALL_OUTPUT_LINES.append("--------------------")
        INSTALL_OUTPUT_LINES.append("Installation complete!")
        INSTALL_OUTPUT_LINES.append("Finished.")


# --- Main Execution Block ---
if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # --- Hardware Initialization ---
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        current_screen = "confirm"

        # --- Main Loop ---
        while RUNNING:
            draw_ui(current_screen)

            if current_screen == "confirm":
                if GPIO.input(PINS["OK"]) == 0:
                    current_screen = "installing"
                    INSTALL_THREAD = threading.Thread(target=installation_worker, daemon=True)
                    INSTALL_THREAD.start()
                    time.sleep(0.3) 

                if GPIO.input(PINS["KEY3"]) == 0:
                    break 

            elif current_screen == "installing":
                if GPIO.input(PINS["KEY3"]) == 0:
                    break 
            
            time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        # Log any fatal error
        with open("/tmp/updater_payload_error.log", "w") as f:
            f.write(f"FATAL ERROR: {e}\n")
            import traceback
            traceback.print_exc(file=f)
    finally:
        LCD.LCD_Clear()
        cleanup()
