#!/usr/bin/env python3
"""
KTOx *payload* – **Dependency Updater**
==========================================
This payload checks for missing dependencies and installs them.

Features:
- Scans and displays missing APT and PIP packages.
- Requires user confirmation before starting the installation.
- Runs the installation in a background thread to keep the UI responsive.
- Streams the output of the `apt-get` and `pip` commands to the LCD in real-time.
- Graceful exit via KEY3 or Ctrl-C.

EXCLUDED PACKAGES (install separately if needed):
- customtkinter  → Too resource-intensive for RPi Zero 2 W
  Install with: pip3 install customtkinter

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
INSTALL_OUTPUT_LINES = ["Scanning dependencies..."]

# --- Complete Dependency List ---
APT_PACKAGES = [
    "bluez", "bluez-tools",
    "aircrack-ng", "hcxtools", "hcxdumptool", "mdk4",
    "wireless-tools", "wpasupplicant", "iw", "arp-scan",
    "nmap", "tcpdump", "net-tools",
    "mitmproxy", "responder", "dnsmasq", "hostapd",
    "hashcat", "john", "hydra", "sshpass",
    "enum4linux", "impacket-scripts", "smbclient",
    "snmp", "snmpd",
    "wifite", "w3m",
    "openssh-server", "openssh-client", "autossh",
    "python3-dev", "python3-pip",
]

PIP_PACKAGES = [
    "rich",
    "scapy",
    "python-nmap",
    "netifaces",
    "flask",
    "evdev",
    "Pillow",
    "impacket",
    "requests",
    "paramiko",
    "cryptography",
]
# NOTE: customtkinter removed — too resource-intensive for RPi Zero 2 W
# Install separately if needed: pip3 install customtkinter

# --- Dependency Checker ---
def get_missing_packages():
    """Scan and return lists of missing APT and PIP packages."""
    missing_apt = []
    missing_pip = []

    try:
        result = subprocess.run(["dpkg", "-l"], capture_output=True, text=True, timeout=10)
        installed = set()
        for line in result.stdout.split('\n'):
            if line.startswith('ii'):
                parts = line.split()
                if len(parts) >= 2:
                    installed.add(parts[1].split(':')[0])

        for pkg in APT_PACKAGES:
            if pkg not in installed:
                missing_apt.append(pkg)
    except:
        pass

    try:
        result = subprocess.run(["pip3", "list"], capture_output=True, text=True, timeout=10)
        installed_lower = {line.split()[0].lower() for line in result.stdout.split('\n')[2:] if line.strip()}

        for pkg in PIP_PACKAGES:
            pkg_name = pkg.split('>')[0].split('=')[0].split('<')[0].lower()
            if pkg_name not in installed_lower:
                missing_pip.append(pkg)
    except:
        pass

    return missing_apt, missing_pip

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
def draw_ui(screen_state="confirm", missing_apt=None, missing_pip=None):
    with UI_LOCK:
        image = Image.new("RGB", (128, 128), (10, 0, 0))
        draw = ImageDraw.Draw(image)
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        except IOError:
            font_title = ImageFont.load_default()
            font_small = ImageFont.load_default()

        draw.text((5, 5), "Dependency Updater", font=font_title, fill=(171, 178, 185))
        draw.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)

        if screen_state == "confirm":
            if missing_apt or missing_pip:
                apt_count = len(missing_apt) if missing_apt else 0
                pip_count = len(missing_pip) if missing_pip else 0
                draw.text((5, 25), f"Missing packages:", font=font_small, fill=(242, 243, 244))
                draw.text((10, 40), f"APT: {apt_count}", font=font_small, fill=(212, 172, 13))
                draw.text((10, 55), f"PIP: {pip_count}", font=font_small, fill=(212, 172, 13))
                draw.text((5, 70), "Note: customtkinter", font=font_small, fill=(212, 172, 13))
                draw.text((5, 80), "excluded (RPi Zero)", font=font_small, fill=(212, 172, 13))
                draw.text((5, 95), "OK=Install", font=font_small, fill=(52, 152, 219))
                draw.text((5, 110), "KEY3=Cancel", font=font_small, fill=(231, 76, 60))
            else:
                draw.text((5, 40), "All dependencies", font=font_small, fill=(46, 204, 113))
                draw.text((5, 55), "are installed!", font=font_small, fill=(46, 204, 113))
                draw.text((5, 100), "KEY3=Exit", font=font_small, fill=(231, 76, 60))

        elif screen_state == "installing":
            draw.text((5, 25), "Installing...", font=font_small, fill=(242, 243, 244))
            y = 40
            for line in INSTALL_OUTPUT_LINES[-7:]:
                if len(line) > 20:
                    line = line[:17] + "..."
                draw.text((5, y), line, font=font_small, fill=(212, 172, 13))
                y += 11
            draw.text((5, 115), "KEY3 to Exit", font=font_small, fill="ORANGE")

        LCD.LCD_ShowImage(image, 0, 0)

# --- Installation Logic ---
def installation_worker(to_install_apt, to_install_pip):
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

    if not run_command(["apt-get", "update", "-qq"]):
        with UI_LOCK:
            INSTALL_OUTPUT_LINES.append("APT update failed!")
            INSTALL_OUTPUT_LINES.append("Finished.")
        return

    if to_install_apt:
        with UI_LOCK:
            INSTALL_OUTPUT_LINES.append("Installing APT packages...")
        if not run_command(["apt-get", "install", "-y", "--no-install-recommends"] + to_install_apt):
            with UI_LOCK:
                INSTALL_OUTPUT_LINES.append("APT install failed!")
                INSTALL_OUTPUT_LINES.append("Finished.")
            return

    if to_install_pip:
        with UI_LOCK:
            INSTALL_OUTPUT_LINES.append("Installing PIP packages...")
        if not run_command(["pip3", "install", "-q"] + to_install_pip):
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

        # --- Check for missing packages ---
        missing_apt, missing_pip = get_missing_packages()

        current_screen = "confirm"

        # --- Main Loop ---
        while RUNNING:
            draw_ui(current_screen, missing_apt, missing_pip)

            if current_screen == "confirm":
                if not missing_apt and not missing_pip:
                    # All installed, wait for KEY3 to exit
                    if GPIO.input(PINS["KEY3"]) == 0:
                        break
                else:
                    # Has missing packages
                    if GPIO.input(PINS["OK"]) == 0:
                        current_screen = "installing"
                        INSTALL_THREAD = threading.Thread(target=installation_worker, args=(missing_apt, missing_pip), daemon=True)
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
