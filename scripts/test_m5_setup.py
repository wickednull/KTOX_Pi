#!/usr/bin/env python3
"""
test_m5_setup.py
Verifies M5Cardputer frame capture and streaming setup
"""

import sys
import os
import time
import socket
import subprocess
from pathlib import Path

# Colors for output
class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def test(name, condition, details=""):
    """Print test result"""
    status = f"{Color.GREEN}✓{Color.RESET}" if condition else f"{Color.RED}✗{Color.RESET}"
    print(f"  {status} {name}")
    if details:
        print(f"      {details}")
    return condition

def section(title):
    """Print section header"""
    print(f"\n{Color.BLUE}{title}{Color.RESET}")

def main():
    all_pass = True

    section("M5Cardputer Setup Verification")

    # 1. Environment variables
    section("1. Environment Configuration")

    frame_mirror = os.environ.get("RJ_FRAME_MIRROR", "1")
    frame_path = os.environ.get("RJ_FRAME_PATH", "/dev/shm/ktox_last.jpg")
    frame_fps = os.environ.get("RJ_FRAME_FPS", "10")
    ws_host = os.environ.get("RJ_WS_HOST", "0.0.0.0")
    ws_port = os.environ.get("RJ_WS_PORT", "8765")

    all_pass &= test(f"Frame mirror enabled", frame_mirror in ["1", "true", "True"],
                     f"RJ_FRAME_MIRROR={frame_mirror}")
    all_pass &= test(f"Frame path set", bool(frame_path),
                     f"RJ_FRAME_PATH={frame_path}")
    all_pass &= test(f"Frame FPS configured", bool(frame_fps),
                     f"RJ_FRAME_FPS={frame_fps} FPS")
    all_pass &= test(f"WebSocket host configured", bool(ws_host),
                     f"RJ_WS_HOST={ws_host}")
    all_pass &= test(f"WebSocket port configured", bool(ws_port),
                     f"RJ_WS_PORT={ws_port}")

    # 2. System resources
    section("2. System Resources")

    shm_path = Path("/dev/shm")
    all_pass &= test("Shared memory available", shm_path.exists(),
                     f"{shm_path} exists")

    try:
        shm_stat = shm_path.stat()
        all_pass &= test("Can write to /dev/shm", os.access(shm_path, os.W_OK),
                         f"Permissions: {oct(shm_stat.st_mode)}")
    except Exception as e:
        all_pass &= test("Can write to /dev/shm", False, str(e))

    # 3. Frame file
    section("3. Frame Capture Status")

    frame_file = Path(frame_path)
    frame_exists = frame_file.exists()
    all_pass &= test("Frame file exists", frame_exists,
                     f"{frame_path}")

    if frame_exists:
        try:
            stat = frame_file.stat()
            size_kb = stat.st_size / 1024
            all_pass &= test("Frame file has content", stat.st_size > 0,
                             f"Size: {size_kb:.1f} KB")

            # Check if frame is recent (updated in last 5 seconds)
            mtime = stat.st_mtime
            age_s = time.time() - mtime
            is_recent = age_s < 5.0
            all_pass &= test("Frame is being updated", is_recent,
                             f"Age: {age_s:.1f}s")

            # Check if JPEG is valid
            try:
                from PIL import Image
                img = Image.open(frame_file)
                all_pass &= test("JPEG is valid", True,
                                 f"Size: {img.size}, Format: {img.format}")
            except Exception as e:
                all_pass &= test("JPEG is valid", False, str(e))
        except Exception as e:
            all_pass &= test("Frame file readable", False, str(e))

    # 4. Network ports
    section("4. Network Connectivity")

    try:
        port_int = int(ws_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', port_int))
        sock.close()

        listening = result == 0
        all_pass &= test(f"WebSocket port {ws_port} listening", listening,
                         "device_server.py should be running")
    except Exception as e:
        all_pass &= test(f"WebSocket port {ws_port} accessible", False, str(e))

    # 5. Processes
    section("5. Required Processes")

    try:
        ps_output = subprocess.check_output(["ps", "aux"], text=True)

        device_server_running = "device_server.py" in ps_output
        all_pass &= test("device_server.py running", device_server_running,
                         "Serves frames to WebSocket clients")

        ktox_running = "ktox_device_root.py" in ps_output or "ktox_" in ps_output.lower()
        all_pass &= test("KTOX_Pi process running", ktox_running,
                         "Main KTOX application")
    except Exception as e:
        all_pass &= test("Process check", False, str(e))

    # 6. Dependencies
    section("6. Python Dependencies")

    dependencies = ["PIL", "websockets"]
    for dep in dependencies:
        try:
            __import__(dep if dep != "PIL" else "PIL.Image")
            all_pass &= test(f"{dep} installed", True)
        except ImportError:
            all_pass &= test(f"{dep} installed", False,
                             f"Install: pip3 install {dep}")

    # Summary
    section("Summary")

    if all_pass:
        print(f"{Color.GREEN}✓ All checks passed!{Color.RESET}")
        print("\nYour KTOX_Pi is ready for M5Cardputer remote control.")
        print(f"Connect M5 to WebSocket at: ws://YOUR_IP:{ws_port}")
        return 0
    else:
        print(f"{Color.RED}✗ Some checks failed.{Color.RESET}")
        print("\nRun with: sudo python3 test_m5_setup.py")
        print("Or check: cat M5_CARDPUTER_SETUP.md (Troubleshooting section)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
