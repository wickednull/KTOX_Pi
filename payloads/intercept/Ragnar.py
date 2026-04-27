#!/usr/bin/env python3
# NAME: Ragnar Autonomous Engine

"""
Ragnar Headless Installer for KTOx_Pi (using venv)

- Clones original Ragnar from PierreGode/Ragnar
- Replaces main script with headless version (no e‑paper)
- Creates Python virtual environment (required for Kali)
- Installs dependencies inside venv
- Starts Ragnar web UI on port 8000
- Shows status on LCD
- Controls: KEY1 = stop + exit, KEY3 = exit (Ragnar keeps running)
"""

import os, sys, time, subprocess, socket, signal, shutil, threading
from pathlib import Path
from datetime import datetime

# ----------------------------------------------------------------------
# Environment & paths
# ----------------------------------------------------------------------
LOOT_DIR   = os.environ.get("KTOX_LOOT_DIR", "/root/KTOx/loot")
KTOX_ROOT  = str(Path(LOOT_DIR).parent)

VENDOR_DIR = Path(KTOX_ROOT) / "vendor" / "ragnar"
RAGNAR_DIR = VENDOR_DIR / "Ragnar"                # original repo cloned here
VENV_DIR   = VENDOR_DIR / "venv"                  # virtual environment
PYTHON_VENV = VENV_DIR / "bin" / "python3"
PIP_VENV    = VENV_DIR / "bin" / "pip"
DATA_DIR   = Path(LOOT_DIR) / "ragnar"
PID_FILE   = Path(LOOT_DIR) / "ragnar.pid"
LAUNCHER   = VENDOR_DIR / "ktox_headless_ragnar.py"
RAGNAR_REPO = "https://github.com/PierreGode/Ragnar.git"
RAGNAR_PORT = 8000

# ----------------------------------------------------------------------
# GPIO pin map (Waveshare 1.44" HAT)
# ----------------------------------------------------------------------
PINS = {
    "KEY_UP_PIN":    6, "KEY_DOWN_PIN":  19, "KEY_LEFT_PIN":  5,
    "KEY_RIGHT_PIN": 26, "KEY_PRESS_PIN": 13,
    "KEY1_PIN":      21, "KEY2_PIN":      20, "KEY3_PIN":      16,
}

# ----------------------------------------------------------------------
# Display helpers (safe, no flashing)
# ----------------------------------------------------------------------
BG     = "#0a0a0a"
FG     = "#c8c8c8"
RED    = "#8B0000"
GREEN  = "#2ecc40"
ORANGE = "#ff8800"
BLUE   = "#3399ff"
DIM    = "#444444"

FONT_BOLD  = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_MONO  = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

_HW = False
LCD = None
image = None
draw = None
font = None
small = None

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    import LCD_Config
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False

def _init_hw():
    global _HW, LCD, image, draw, font, small
    if not _HAS_GPIO:
        return
    try:
        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD_Config.Driver_Delay_ms(50)
        image = Image.new("RGB", (LCD.width, LCD.height), BG)
        draw  = ImageDraw.Draw(image)
        font  = ImageFont.truetype(FONT_BOLD, 9)
        small = ImageFont.truetype(FONT_MONO, 8)
        _HW = True
    except Exception as e:
        print(f"[ragnar] HW init failed: {e}")

def _flush():
    if _HW and LCD:
        LCD.LCD_ShowImage(image, 0, 0)

def _key(pin_name):
    if not _HAS_GPIO:
        return False
    try:
        return GPIO.input(PINS[pin_name]) == 0
    except:
        return False

def _wait_key_release(pin_name, timeout=0.5):
    t = time.time()
    while time.time() - t < timeout:
        if not _key(pin_name):
            break
        time.sleep(0.02)

def should_exit():
    return _key("KEY3_PIN")

def _border():
    if not _HW: return
    draw.line([(127,12),(127,127)], fill=RED, width=5)
    draw.line([(127,127),(0,127)],  fill=RED, width=5)
    draw.line([(0,127),(0,12)],     fill=RED, width=5)
    draw.line([(0,12),(128,12)],    fill=RED, width=5)

def _center(y, text, fnt, color=FG):
    if not _HW: return
    bbox = draw.textbbox((0,0), text, font=fnt)
    w = bbox[2] - bbox[0]
    draw.text(((128-w)//2, y), text, font=fnt, fill=color)

def _hbar(y, pct, clr=(100,180,255)):
    if not _HW: return
    W = 116
    draw.rectangle([6, y, 6+W, y+4], fill=(18,24,60))
    draw.rectangle([6, y, 6+max(1,int(W*pct/100)), y+4], fill=clr)

def _screen_clear():
    if not _HW: return
    draw.rectangle((0,0,128,128), fill=BG)
    _border()

def screen_not_installed():
    if not _HW: return
    _screen_clear()
    _center(15, "RAGNAR", font, RED)
    draw.line([(4,27),(124,27)], fill=DIM)
    _center(33, "Not installed", small, ORANGE)
    draw.line([(4,58),(124,58)], fill=DIM)
    _center(64,  "KEY3: install", small, GREEN)
    _center(76,  "KEY1: exit",    small, DIM)
    _flush()

def screen_installing(step, total, msg):
    if not _HW: return
    _screen_clear()
    _center(15, "RAGNAR", font, RED)
    _center(27, "INSTALLING", small, ORANGE)
    draw.line([(4,38),(124,38)], fill=DIM)
    _hbar(43, step/max(total,1)*100)
    draw.text((6,51), msg[:20], font=small, fill=FG)
    draw.text((6,62), f"step {step}/{total}", font=small, fill=DIM)
    _center(112, "KEY3: cancel", small, DIM)
    _flush()

def screen_error(msg1, msg2=""):
    if not _HW: return
    _screen_clear()
    _center(15, "RAGNAR", font, RED)
    draw.line([(4,27),(124,27)], fill=DIM)
    _center(38, "ERROR", small, RED)
    draw.text((4,52), msg1[:20], font=small, fill=ORANGE)
    if msg2:
        draw.text((4,63), msg2[:20], font=small, fill=DIM)
    _center(112, "KEY3/KEY1: exit", small, DIM)
    _flush()

def screen_starting():
    if not _HW: return
    _screen_clear()
    _center(15, "RAGNAR", font, RED)
    draw.line([(4,27),(124,27)], fill=DIM)
    _center(50, "Starting...", small, ORANGE)
    _center(112, "please wait", small, DIM)
    _flush()

def screen_running(url: str, web_ready: bool, since: str):
    if not _HW: return
    _screen_clear()
    _center(15, "RAGNAR", font, RED)
    draw.line([(4,26),(124,26)], fill=DIM)
    dot_color = GREEN if web_ready else ORANGE
    draw.ellipse([5,29,12,36], fill=dot_color)
    status_label = "WEB READY" if web_ready else "STARTING"
    draw.text((15,29), status_label, font=small, fill=dot_color)
    draw.line([(4,40),(124,40)], fill=DIM)
    host_port = url.replace("http://","")
    parts = host_port.split(":")
    draw.text((4,44), "http://", font=small, fill=DIM)
    draw.text((4,54), parts[0],  font=small, fill=BLUE)
    draw.text((4,64), f":{parts[1]}" if len(parts)>1 else "", font=small, fill=BLUE)
    draw.line([(4,76),(124,76)], fill=DIM)
    draw.text((4,80), since[:20], font=small, fill=DIM)
    _center(100, "KEY1: stop ragnar",   small, DIM)
    _center(112, "KEY3: exit (keep)", small, DIM)
    _flush()

def screen_stopped(msg=""):
    if not _HW: return
    _screen_clear()
    _center(15, "RAGNAR", font, RED)
    draw.line([(4,26),(124,26)], fill=DIM)
    draw.ellipse([5,29,12,36], fill=DIM)
    draw.text((15,29), "STOPPED", font=small, fill=DIM)
    draw.line([(4,40),(124,40)], fill=DIM)
    if msg:
        draw.text((4,44), msg[:20], font=small, fill=ORANGE)
    _center(88,  "KEY3: start",     small, GREEN)
    _center(100, "KEY1: exit",      small, DIM)
    _center(112, "KEY2: reinstall", small, DIM)
    _flush()

# ----------------------------------------------------------------------
# Network helpers
# ----------------------------------------------------------------------
def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

def _port_open(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except:
        return False

# ----------------------------------------------------------------------
# Ragnar process management
# ----------------------------------------------------------------------
_ragnar_proc = None
_log_fh = None

def _ragnar_installed() -> bool:
    return LAUNCHER.exists() and PYTHON_VENV.exists()

def _ragnar_running() -> bool:
    global _ragnar_proc
    if _ragnar_proc is not None and _ragnar_proc.poll() is None:
        return True
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b'\x00', b' ').decode(errors="replace")
            if "ragnar" in cmdline.lower() or "ktox_headless_ragnar" in cmdline.lower():
                return True
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            PID_FILE.unlink(missing_ok=True)
    return False

def _run_with_cancel(cmd, timeout=300, step=0, total=1, step_msg=None):
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    start = time.time()
    last_update = 0
    while proc.poll() is None:
        if should_exit():
            proc.terminate()
            time.sleep(0.5)
            proc.kill()
            raise Exception("cancelled by user")
        if step_msg and _HW and (time.time() - last_update) > 1:
            screen_installing(step, total, step_msg)
            last_update = time.time()
        time.sleep(0.5)
        if timeout and (time.time() - start) > timeout:
            proc.terminate()
            raise Exception("timeout")
    return proc.returncode

def _start_ragnar() -> tuple[bool, str]:
    global _ragnar_proc, _log_fh
    if _ragnar_running():
        return True, "already running"
    if _port_open(RAGNAR_PORT):
        return False, f"port {RAGNAR_PORT} in use"
    ip = _local_ip()
    env = os.environ.copy()
    env["RAGNAR_DATA_DIR"] = str(DATA_DIR)
    env["BJORN_IP"] = ip
    env["RAGNAR_PID_FILE"] = str(PID_FILE)
    log = DATA_DIR / "logs" / "ktox_ragnar.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    _log_fh = open(log, "a")
    _ragnar_proc = subprocess.Popen(
        [str(PYTHON_VENV), str(LAUNCHER)],
        env=env,
        stdout=_log_fh,
        stderr=subprocess.STDOUT,
        cwd=str(RAGNAR_DIR),
    )
    for _ in range(300):  # 30 seconds
        if should_exit():
            _stop_ragnar()
            return False, "cancelled"
        if _ragnar_proc.poll() is not None:
            return False, "crashed - check logs"
        if _port_open(RAGNAR_PORT):
            return True, f"http://{ip}:{RAGNAR_PORT}"
        time.sleep(0.1)
    if not _ragnar_running():
        return False, "timed out - check logs"
    return True, f"http://{ip}:{RAGNAR_PORT}"

def _stop_ragnar():
    global _ragnar_proc, _log_fh
    if _ragnar_proc is not None:
        try:
            _ragnar_proc.terminate()
            _ragnar_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _ragnar_proc.kill()
        except Exception:
            pass
        _ragnar_proc = None
    if _log_fh is not None:
        try:
            _log_fh.close()
        except Exception:
            pass
        _log_fh = None
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except Exception:
            pass
        PID_FILE.unlink(missing_ok=True)
    subprocess.run(["pkill", "-f", "ktox_headless_ragnar"], capture_output=True)

# ----------------------------------------------------------------------
# Write the headless Ragnar.py (modified by DezusAZ, no LCD)
# ----------------------------------------------------------------------
def _write_headless_ragnar():
    dest = RAGNAR_DIR / "Ragnar.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    headless_code = '''#!/usr/bin/env python3
"""
Ragnar main entrypoint (Hackberry / no-EPD version)
This version removes all e-paper / Display dependencies.
"""

import os
import signal
import threading
import time
import sys
import subprocess
import logging

from init_shared import shared_data
from comment import Commentaireia
from webapp_modern import run_server
from orchestrator import Orchestrator
from logger import Logger
from wifi_manager import WiFiManager
from env_manager import load_env

logger = Logger(name="Ragnar.py", level=logging.DEBUG)

class Ragnar:
    def __init__(self, shared_data_obj):
        self.shared_data = shared_data_obj
        self.commentaire_ia = Commentaireia()
        self.orchestrator_thread = None
        self.orchestrator = None
        self.wifi_manager = WiFiManager(self.shared_data)
        self.shared_data.ragnar_instance = self

    def run(self):
        logger.info("RAGNAR MAIN THREAD STARTING (no EPD display)")
        self.wifi_manager.start()
        while not self.shared_data.should_exit:
            if not self.shared_data.manual_mode:
                self.check_and_start_orchestrator()
            time.sleep(10)

    def check_and_start_orchestrator(self):
        if self.wifi_manager.check_wifi_connection():
            self.shared_data.wifi_connected = True
            if self.orchestrator_thread is None or not self.orchestrator_thread.is_alive():
                self.start_orchestrator()
        else:
            self.shared_data.wifi_connected = False

    def start_orchestrator(self):
        if self.wifi_manager.check_wifi_connection():
            self.shared_data.wifi_connected = True
            if self.orchestrator_thread is None or not self.orchestrator_thread.is_alive():
                self.shared_data.orchestrator_should_exit = False
                self.shared_data.manual_mode = False
                self.orchestrator = Orchestrator()
                self.orchestrator_thread = threading.Thread(target=self.orchestrator.run)
                self.orchestrator_thread.start()

    def stop_orchestrator(self):
        self.shared_data.manual_mode = True
        if self.orchestrator_thread and self.orchestrator_thread.is_alive():
            self.shared_data.orchestrator_should_exit = True
            self.orchestrator_thread.join(timeout=10)

    def stop(self):
        self.stop_orchestrator()
        if hasattr(self, "wifi_manager"):
            self.wifi_manager.stop()
        self.shared_data.should_exit = True
        self.shared_data.webapp_should_exit = True

    def is_wifi_connected(self):
        if hasattr(self, "wifi_manager"):
            return self.wifi_manager.check_wifi_connection()
        try:
            result = subprocess.Popen(["nmcli","-t","-f","STATE","g"], stdout=subprocess.PIPE, text=True).communicate()[0]
            return "connected" in result
        except: return False

def handle_exit(sig, frame, ragnar_thread, web_thread):
    if hasattr(shared_data, "ragnar_instance") and shared_data.ragnar_instance:
        shared_data.ragnar_instance.stop()
    shared_data.should_exit = True
    sys.exit(0)

if __name__ == "__main__":
    load_env()
    shared_data.load_config()
    ragnar = Ragnar(shared_data)
    shared_data.ragnar_instance = ragnar
    ragnar_thread = threading.Thread(target=ragnar.run, daemon=True)
    ragnar_thread.start()
    if shared_data.config.get("websrv", True):
        web_thread = threading.Thread(target=run_server, daemon=True)
        web_thread.start()
    signal.signal(signal.SIGINT, lambda s,f: handle_exit(s,f,ragnar_thread,None))
    signal.signal(signal.SIGTERM, lambda s,f: handle_exit(s,f,ragnar_thread,None))
    while True:
        time.sleep(1)
'''
    dest.write_text(headless_code)
    dest.chmod(0o755)

# ----------------------------------------------------------------------
# Write the KTOx headless launcher (uses venv python)
# ----------------------------------------------------------------------
def _write_launcher():
    launcher_code = f'''#!/usr/bin/env python3
# ktox_headless_ragnar.py
import sys, os, signal
from pathlib import Path
os.environ["RAGNAR_DATA_DIR"] = os.environ.get("RAGNAR_DATA_DIR", "/root/KTOx/loot/ragnar")
os.environ["BJORN_IP"] = os.environ.get("BJORN_IP", "localhost")

def signal_handler(sig, frame):
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

venv_python = Path("{PYTHON_VENV}")
if not venv_python.exists():
    venv_python = Path(sys.executable)
os.execve(str(venv_python), [str(venv_python), "Ragnar.py"], os.environ)
'''
    LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHER.write_text(launcher_code)
    LAUNCHER.chmod(0o755)

# ----------------------------------------------------------------------
# Installation routine (with venv)
# ----------------------------------------------------------------------
def install_ragnar():
    try:
        # Step 1: system packages
        screen_installing(1, 8, "Installing system packages...")
        _run_with_cancel("apt-get update -qq && apt-get install -y git python3-venv python3-pip python3-pil nmap bluetooth libbluetooth-dev python3-bluez", timeout=300, step=1, total=8, step_msg="Installing packages")

        # Step 2: clone repo
        screen_installing(2, 8, "Cloning Ragnar repo...")
        VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
        if VENDOR_DIR.exists():
            shutil.rmtree(VENDOR_DIR)
        _run_with_cancel(f"git clone --depth=1 {RAGNAR_REPO} {VENDOR_DIR}/Ragnar", timeout=180, step=2, total=8, step_msg="Cloning repo")

        # Step 3: replace Ragnar.py with headless
        screen_installing(3, 8, "Patching headless...")
        _write_headless_ragnar()

        # Step 4: create venv
        screen_installing(4, 8, "Creating virtual environment...")
        _run_with_cancel(f"python3 -m venv {VENV_DIR}", timeout=60, step=4, total=8, step_msg="Creating venv")

        # Step 5: upgrade pip
        screen_installing(5, 8, "Upgrading pip...")
        _run_with_cancel(f"{PIP_VENV} install --upgrade pip", timeout=60, step=5, total=8, step_msg="Upgrading pip")

        # Step 6: install dependencies
        screen_installing(6, 8, "Installing pip packages...")
        req_file = RAGNAR_DIR / "requirements.txt"
        if req_file.exists():
            _run_with_cancel(f"{PIP_VENV} install -r {req_file}", timeout=180, step=6, total=8, step_msg="Installing from requirements")
        _run_with_cancel(f"{PIP_VENV} install requests", timeout=30, step=6, total=8, step_msg="Installing requests")

        # Step 7: create data directories
        screen_installing(7, 8, "Creating data directories...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
        os.chmod(DATA_DIR, 0o777)

        # Step 8: write launcher
        screen_installing(8, 8, "Writing launcher...")
        _write_launcher()

        screen_installing(8, 8, "Done!")
        time.sleep(1)
        return True, "ok"

    except Exception as e:
        return False, str(e)[:30]

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    _init_hw()
    ip = _local_ip()
    url = f"http://{ip}:{RAGNAR_PORT}"

    if not _ragnar_installed():
        print("[ragnar] Not installed.")
        if _HW:
            screen_not_installed()
            deadline = time.time() + 15
            chosen = None
            while time.time() < deadline and chosen is None:
                if _key("KEY3_PIN"):
                    _wait_key_release("KEY3_PIN")
                    chosen = "install"
                elif _key("KEY1_PIN"):
                    _wait_key_release("KEY1_PIN")
                    chosen = "exit"
                time.sleep(0.05)
            if chosen != "install":
                return
        else:
            print("[ragnar] Press Enter to install, Ctrl+C to cancel.")
            input()

        print("[ragnar] Installing...")
        ok, msg = install_ragnar()
        if not ok:
            print(f"[ragnar] Install failed: {msg}")
            if _HW:
                screen_error("Install failed", msg)
                time.sleep(4)
            return

    if not _ragnar_running():
        print(f"[ragnar] Starting Ragnar → {url}")
        if _HW:
            screen_starting()
        ok, result = _start_ragnar()
        if not ok:
            print(f"[ragnar] Start failed: {result}")
            if _HW:
                screen_error("Start failed", result)
                time.sleep(4)
            return
        print(f"[ragnar] Ragnar running at {result}")
    else:
        print(f"[ragnar] Already running at {url}")

    start_ts = datetime.now().strftime("%H:%M:%S")
    since_label = f"since {start_ts}"

    while True:
        running = _ragnar_running()
        if running:
            web_up = _port_open(RAGNAR_PORT)
            if _HW:
                screen_running(url, web_up, since_label)
            else:
                print(f"\r[ragnar] {'WEB READY' if web_up else 'STARTING':10s}  {url}", end="", flush=True)
        else:
            if _HW:
                screen_stopped()
            else:
                print("\r[ragnar] STOPPED                                    ", end="", flush=True)

        for _ in range(10):
            time.sleep(0.1)
            if running:
                if _key("KEY1_PIN"):
                    _wait_key_release("KEY1_PIN")
                    print("\n[ragnar] Stopping Ragnar...")
                    _stop_ragnar()
                    return
                if _key("KEY3_PIN"):
                    _wait_key_release("KEY3_PIN")
                    print(f"\n[ragnar] Exiting — Ragnar continues at {url}")
                    return
            else:
                if _key("KEY3_PIN"):
                    _wait_key_release("KEY3_PIN")
                    if _HW:
                        screen_starting()
                    ok, result = _start_ragnar()
                    if ok:
                        start_ts = datetime.now().strftime("%H:%M:%S")
                        since_label = f"since {start_ts}"
                    else:
                        if _HW:
                            screen_error("Start failed", result)
                            time.sleep(3)
                    break
                if _key("KEY1_PIN"):
                    _wait_key_release("KEY1_PIN")
                    return
                if _key("KEY2_PIN"):
                    _wait_key_release("KEY2_PIN")
                    ok, msg = install_ragnar()
                    if not ok and _HW:
                        screen_error("Install failed", msg)
                        time.sleep(3)
                    break

if __name__ == "__main__":
    main()
