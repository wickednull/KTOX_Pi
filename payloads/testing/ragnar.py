#!/usr/bin/env python3
"""
KTOx Payload – Ragnar Web Controller
=====================================
- Auto‑installs Ragnar (if missing) using /root/KTOx/scripts/install_ragnar.sh
- Starts/stops the Ragnar headless web server
- Displays the local IP and port (default 8000) on the LCD
- Shows live status (running / stopped)

Controls:
  OK      – Start Ragnar (if not running)
  KEY1    – Stop Ragnar
  KEY2    – Refresh status / show IP
  KEY3    – Exit payload
"""

import os
import sys
import time
import subprocess
import socket
import signal
import threading
import json

# KTOx hardware
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Paths & configuration
# ----------------------------------------------------------------------
RAGNAR_DIR = "/root/Ragnar"
RAGNAR_PY = os.path.join(RAGNAR_DIR, "Ragnar.py")
RAGNAR_VENV_PYTHON = os.path.join(RAGNAR_DIR, "venv", "bin", "python3")
RAGNAR_INSTALL_SCRIPT = "/root/KTOx/scripts/install_ragnar_kali_pi.sh"
RAGNAR_PID_FILE = "/dev/shm/ragnar.pid"
RAGNAR_PORT = 8000    # as shown in install script output

# Use either system python or venv python
if os.path.exists(RAGNAR_VENV_PYTHON):
    RAGNAR_CMD = f"cd {RAGNAR_DIR} && sudo {RAGNAR_VENV_PYTHON} {RAGNAR_PY}"
else:
    RAGNAR_CMD = f"cd {RAGNAR_DIR} && sudo python3 {RAGNAR_PY}"

LOOT_DIR = "/root/KTOx/loot/Ragnar"
os.makedirs(LOOT_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# Hardware
# ----------------------------------------------------------------------
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
FONT = font(9)
FONT_BOLD = font(10)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def show_message(msg, sub=""):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((64, 50), msg, font=FONT_BOLD, fill=(30, 132, 73), anchor="mm")
    if sub:
        d.text((64, 65), sub[:22], font=FONT, fill=(113, 125, 126), anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1.5)

def get_local_ip():
    """Return the primary IPv4 address (e.g., 192.168.x.x)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        # Fallback: read from interface
        for iface in ["wlan0", "eth0"]:
            try:
                rc, out = subprocess.run(["ip", "-4", "addr", "show", iface],
                                         capture_output=True, text=True)
                for line in out.splitlines():
                    if "inet " in line:
                        return line.split()[1].split("/")[0]
            except:
                pass
        return "0.0.0.0"

def is_ragnar_running():
    """Check if Ragnar process is running."""
    # First try PID file
    if os.path.exists(RAGNAR_PID_FILE):
        try:
            with open(RAGNAR_PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except:
            pass
    # Fallback to pgrep
    try:
        subprocess.run(["pgrep", "-f", "Ragnar.py"], check=True, capture_output=True)
        return True
    except:
        return False

def start_ragnar():
    """Launch Ragnar in background, record PID."""
    if is_ragnar_running():
        show_message("Already running")
        return False
    if not os.path.exists(RAGNAR_PY):
        show_message("Ragnar not installed", "Use KEY2 to install")
        return False
    try:
        proc = subprocess.Popen(RAGNAR_CMD, shell=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        with open(RAGNAR_PID_FILE, "w") as f:
            f.write(str(proc.pid))
        show_message("Ragnar started", f"Port {RAGNAR_PORT}")
        return True
    except Exception as e:
        show_message("Start failed", str(e))
        return False

def stop_ragnar():
    """Terminate Ragnar process."""
    if not is_ragnar_running():
        show_message("Not running")
        return False
    try:
        # Kill by PID file first
        if os.path.exists(RAGNAR_PID_FILE):
            with open(RAGNAR_PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
            except:
                pass
            os.remove(RAGNAR_PID_FILE)
        else:
            subprocess.run(["pkill", "-f", "Ragnar.py"], check=False)
        show_message("Ragnar stopped")
        return True
    except Exception as e:
        show_message("Stop failed", str(e))
        return False

def install_ragnar():
    """Run the install script if it exists, else show instructions."""
    if not os.path.exists(RAGNAR_INSTALL_SCRIPT):
        show_message("Install script missing", "Run manually: /root/KTOx/scripts/install_ragnar_kali_pi.sh")
        return False
    show_message("Installing Ragnar...", "This may take a while")
    try:
        subprocess.run(["bash", RAGNAR_INSTALL_SCRIPT], check=True, timeout=600)
        show_message("Installation complete", "Ragnar ready")
        return True
    except subprocess.TimeoutExpired:
        show_message("Install timed out")
        return False
    except Exception as e:
        show_message("Install failed", str(e)[:22])
        return False

def draw_status():
    """Draw the main status screen."""
    running = is_ragnar_running()
    ip = get_local_ip()
    url = f"http://{ip}:{RAGNAR_PORT}"
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((4, 2), "RAGNAR CONTROL", font=FONT_BOLD, fill=(231, 76, 60))
    # Status
    status_str = "RUNNING" if running else "STOPPED"
    status_col = (30, 132, 73) if running else (231, 76, 60)
    d.text((W-4, 2), status_str, font=FONT, fill=status_col, anchor="rt")
    # URL
    d.text((4, 20), "Web UI:", font=FONT_BOLD, fill=(171, 178, 185))
    d.text((4, 32), url[:22], font=FONT, fill=(30, 132, 73))
    if len(url) > 22:
        d.text((4, 44), url[22:], font=FONT, fill=(30, 132, 73))
    # Buttons help
    d.text((4, 70), "OK=Start  K1=Stop", font=FONT, fill=(113, 125, 126))
    d.text((4, 82), "K2=Refresh  K3=Exit", font=FONT, fill=(113, 125, 126))
    # Footer
    d.rectangle((0, H-12, W, H), fill=(34, 0, 0))
    d.text((4, H-10), "Use your browser to open URL", font=FONT, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def main():
    # If Ragnar is not installed, offer to install
    if not os.path.exists(RAGNAR_PY) and not os.path.exists(RAGNAR_DIR):
        show_message("Ragnar not found", "Press KEY2 to install")
        while True:
            btn = wait_btn(0.5)
            if btn == "KEY2":
                install_ragnar()
                break
            elif btn == "KEY3":
                GPIO.cleanup()
                return
            draw_status()   # show missing status
    draw_status()
    while True:
        btn = wait_btn(0.2)
        if btn == "KEY3":
            break
        elif btn == "OK":
            start_ragnar()
        elif btn == "KEY1":
            stop_ragnar()
        elif btn == "KEY2":
            draw_status()
        # else redraw periodically to show status changes
        draw_status()
        time.sleep(0.2)
    GPIO.cleanup()
    LCD.LCD_Clear()

if __name__ == "__main__":
    main()
