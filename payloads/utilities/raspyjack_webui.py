#!/usr/bin/env python3
# NAME: RaspyJack WebUI
# DESC: Remote control KTOx via RaspyJack Cardputer app
"""
RaspyJack WebUI Setup
=====================
Automatically launches and manages the WebSocket server and KTOx device
for seamless RaspyJack Cardputer remote control.

Features:
- Auto-start WebSocket server and KTOx device
- Display connection info and QR code on LCD
- Real-time status monitoring
- One-touch enable/disable
- Network interface detection
"""

import os
import sys
import json
import time
import socket
import subprocess
import signal
import threading
from pathlib import Path
from datetime import datetime

# Add KTOX to path
KTOX_DIR = "/root/KTOx"
if KTOX_DIR not in sys.path:
    sys.path.insert(0, KTOX_DIR)
    sys.path.insert(0, f"{KTOX_DIR}/ktox_pi")

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False

# Configuration
WS_PORT = int(os.environ.get("RJ_WS_PORT", "8765"))
WS_FPS = int(os.environ.get("RJ_FPS", "10"))
FRAME_PATH = Path(os.environ.get("RJ_FRAME_PATH", "/dev/shm/ktox_last.jpg"))
INPUT_SOCK = os.environ.get("RJ_INPUT_SOCK", "/dev/shm/ktox_input.sock")
LOG_DIR = Path("/root/KTOx/loot")

# Paths
DEVICE_SERVER = Path(KTOX_DIR) / "device_server.py"
KTOX_DEVICE = Path(KTOX_DIR) / "ktox_device.py"
PID_FILE = Path("/dev/shm/raspyjack_pids.json")

# GPIO Pins
PINS = {
    "UP": 6,
    "DOWN": 19,
    "LEFT": 5,
    "RIGHT": 26,
    "OK": 13,
    "KEY1": 21,
    "KEY2": 20,
    "KEY3": 16,
}

# State
ws_process = None
device_process = None
running = True
lcd = None
font_large = None
font_small = None

def setup_hardware():
    """Initialize GPIO and LCD."""
    global lcd, font_large, font_small
    if not HAS_HW:
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        lcd = LCD_1in44.LCD()
        lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        return True
    except Exception as e:
        print(f"Hardware init failed: {e}")
        return False

def draw_screen(title, lines):
    """Draw text on LCD."""
    if not HAS_HW or not lcd:
        return

    try:
        img = Image.new("RGB", (128, 128), "#000000")
        draw = ImageDraw.Draw(img)

        # Title bar
        draw.rectangle([0, 0, 128, 16], fill="#8B0000")
        draw.text((4, 3), title[:16], font=font_small, fill="#FFFFFF")

        # Content
        y = 20
        for line in lines[:7]:
            draw.text((4, y), str(line)[:22], font=font_small, fill="#CCCCCC")
            y += 12

        # Footer
        draw.rectangle([0, 116, 128, 128], fill="#220000")
        draw.text((4, 118), "UP/DN K3=exit", font=font_small, fill="#FF7777")

        lcd.LCD_ShowImage(img, 0, 0)
    except Exception as e:
        print(f"Draw error: {e}")

def get_local_ip():
    """Get local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_active_interface():
    """Detect active network interface."""
    interfaces = ["eth0", "wlan0", "tailscale0"]
    for iface in interfaces:
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", iface],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and "inet " in result.stdout:
                return iface
        except:
            pass
    return "eth0"

def is_process_running(pid):
    """Check if process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except:
        return False

def start_websocket_server():
    """Start device_server.py."""
    global ws_process

    if ws_process and is_process_running(ws_process.pid):
        return True

    draw_screen("WebSocket", ["Starting server...", "", "Please wait..."])

    try:
        env = os.environ.copy()
        env.update({
            "RJ_WS_PORT": str(WS_PORT),
            "RJ_FPS": str(WS_FPS),
            "RJ_FRAME_PATH": str(FRAME_PATH),
            "RJ_INPUT_SOCK": INPUT_SOCK,
            "PYTHONUNBUFFERED": "1",
        })

        ws_process = subprocess.Popen(
            ["python3", str(DEVICE_SERVER)],
            cwd=KTOX_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=os.setsid,
        )

        # Wait for server to start
        for i in range(10):
            time.sleep(0.5)
            if is_process_running(ws_process.pid):
                return True

        return False
    except Exception as e:
        print(f"Failed to start WebSocket server: {e}")
        return False

def start_ktox_device():
    """Start ktox_device.py."""
    global device_process

    if device_process and is_process_running(device_process.pid):
        return True

    draw_screen("KTOx Device", ["Starting device...", "", "Please wait..."])

    try:
        device_process = subprocess.Popen(
            ["python3", str(KTOX_DEVICE)],
            cwd=KTOX_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

        # Wait for device to start
        for i in range(10):
            time.sleep(0.5)
            if is_process_running(device_process.pid):
                return True

        return False
    except Exception as e:
        print(f"Failed to start KTOx device: {e}")
        return False

def show_connection_info():
    """Display connection info on LCD."""
    ip = get_local_ip()
    iface = get_active_interface()
    url = f"ws://{ip}:{WS_PORT}"

    lines = [
        "RaspyJack WebUI",
        "",
        f"Interface: {iface}",
        f"IP: {ip}",
        f"Port: {WS_PORT}",
        "",
        "Use RaspyJack app",
    ]

    draw_screen("Connected!", lines)

    # Also print to console
    print("\n" + "="*40)
    print("RaspyJack WebUI Ready!")
    print("="*40)
    print(f"WebSocket URL: {url}")
    print(f"Configure RaspyJack Cardputer:")
    print(f"  Server: {url}")
    print(f"  Interface: {iface}")
    print("="*40 + "\n")

    return url

def save_pids():
    """Save process IDs for reference."""
    try:
        pids = {
            "ws_pid": ws_process.pid if ws_process else None,
            "device_pid": device_process.pid if device_process else None,
            "timestamp": datetime.now().isoformat(),
        }
        with open(PID_FILE, "w") as f:
            json.dump(pids, f, indent=2)
    except:
        pass

def stop_processes():
    """Stop all running processes."""
    global ws_process, device_process

    for proc in [ws_process, device_process]:
        if proc and is_process_running(proc.pid):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            except:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except:
                    pass

    ws_process = None
    device_process = None

    # Clean up socket
    try:
        if Path(INPUT_SOCK).exists():
            os.unlink(INPUT_SOCK)
    except:
        pass

def get_button():
    """Get button press from GPIO."""
    if not HAS_HW:
        time.sleep(0.1)
        return None

    for name, pin in PINS.items():
        try:
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                if GPIO.input(pin) == 0:
                    return name
        except:
            pass
    return None

def monitor_loop():
    """Main monitoring loop."""
    global running

    draw_screen("Setup", ["Initializing...", "", "Please wait..."])

    # Start processes
    if not start_websocket_server():
        draw_screen("Error", ["WebSocket failed", "Check logs:"])
        time.sleep(3)
        return

    time.sleep(1)

    if not start_ktox_device():
        draw_screen("Error", ["KTOx Device failed", "Check logs"])
        time.sleep(3)
        return

    # Show connection info
    save_pids()
    show_connection_info()

    # Monitor loop
    last_status_check = 0
    while running:
        # Check buttons
        btn = get_button()
        if btn == "KEY3":
            break

        # Periodically check process status
        now = time.time()
        if now - last_status_check > 5:
            ws_ok = ws_process and is_process_running(ws_process.pid)
            device_ok = device_process and is_process_running(device_process.pid)

            if not ws_ok or not device_ok:
                draw_screen("Alert!", [
                    "Process down!",
                    f"WS: {'OK' if ws_ok else 'FAIL'}",
                    f"Device: {'OK' if device_ok else 'FAIL'}",
                ])
                time.sleep(3)

            last_status_check = now

        time.sleep(0.1)

def cleanup():
    """Cleanup on exit."""
    global running
    running = False

    try:
        if HAS_HW:
            draw_screen("Shutdown", ["Stopping processes...", "", "Please wait..."])
    except:
        pass

    print("Stopping RaspyJack WebUI...")
    stop_processes()

    try:
        if HAS_HW:
            GPIO.cleanup()
    except:
        pass

    print("Done!")

def main():
    """Main entry point."""
    if not setup_hardware():
        print("Hardware not available, running in headless mode")

    try:
        monitor_loop()
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

if __name__ == "__main__":
    main()
