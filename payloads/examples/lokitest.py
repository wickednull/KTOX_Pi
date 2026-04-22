#!/usr/bin/env python3
# NAME: Loki Autonomous Engine

import os, sys, time, subprocess, socket, signal, shutil, threading
from pathlib import Path
from datetime import datetime

# ----------------------------------------------------------------------
# Environment & paths
# ----------------------------------------------------------------------
LOOT_DIR   = os.environ.get("KTOX_LOOT_DIR", "/root/KTOx/loot")
KTOX_ROOT  = str(Path(LOOT_DIR).parent)

VENDOR_DIR = Path(KTOX_ROOT) / "vendor" / "loki"
LOKI_DIR   = VENDOR_DIR / "payloads" / "user" / "reconnaissance" / "loki"
LOKI_DATA  = Path(LOOT_DIR) / "loki"
LOKI_PID   = Path(LOOT_DIR) / "loki.pid"
LAUNCHER   = LOKI_DIR / "ktox_headless_loki.py"
LOKI_REPO  = "https://github.com/pineapple-pager-projects/pineapple_pager_loki"
LOKI_PORT  = 8000

# ----------------------------------------------------------------------
# GPIO pin map (Waveshare 1.44" HAT)
# ----------------------------------------------------------------------
PINS = {
    "KEY_UP_PIN":    6, "KEY_DOWN_PIN":  19, "KEY_LEFT_PIN":  5,
    "KEY_RIGHT_PIN": 26, "KEY_PRESS_PIN": 13,
    "KEY1_PIN":      21, "KEY2_PIN":      20, "KEY3_PIN":      16,
}

# ----------------------------------------------------------------------
# Display helpers (same as before, safe)
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
        print(f"[loki] HW init failed: {e}")

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
    _center(15, "LOKI", font, RED)
    draw.line([(4,27),(124,27)], fill=DIM)
    _center(33, "Not installed", small, ORANGE)
    draw.line([(4,58),(124,58)], fill=DIM)
    _center(64,  "KEY3: install", small, GREEN)
    _center(76,  "KEY1: exit",    small, DIM)
    _flush()

def screen_installing(step, total, msg):
    if not _HW: return
    _screen_clear()
    _center(15, "LOKI", font, RED)
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
    _center(15, "LOKI", font, RED)
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
    _center(15, "LOKI", font, RED)
    draw.line([(4,27),(124,27)], fill=DIM)
    _center(50, "Starting...", small, ORANGE)
    _center(112, "please wait", small, DIM)
    _flush()

def screen_running(url: str, web_ready: bool, since: str):
    if not _HW: return
    _screen_clear()
    _center(15, "LOKI", font, RED)
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
    _center(100, "KEY1: stop loki",   small, DIM)
    _center(112, "KEY3: exit (keep)", small, DIM)
    _flush()

def screen_stopped(msg=""):
    if not _HW: return
    _screen_clear()
    _center(15, "LOKI", font, RED)
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
# Loki process management
# ----------------------------------------------------------------------
_loki_proc = None

def _loki_installed() -> bool:
    return LAUNCHER.exists()

def _loki_running() -> bool:
    global _loki_proc
    if _loki_proc is not None and _loki_proc.poll() is None:
        return True
    if LOKI_PID.exists():
        try:
            pid = int(LOKI_PID.read_text().strip())
            os.kill(pid, 0)
            return True
        except:
            LOKI_PID.unlink(missing_ok=True)
    return False

def _run_with_cancel(cmd, timeout=300, step_msg=None):
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
            screen_installing(0, 1, step_msg)
            last_update = time.time()
        time.sleep(0.5)
        if timeout and (time.time() - start) > timeout:
            proc.terminate()
            raise Exception("timeout")
    return proc.returncode

def _start_loki() -> tuple[bool, str]:
    global _loki_proc
    if _loki_running():
        return True, "already running"
    if _port_open(LOKI_PORT):
        return False, f"port {LOKI_PORT} in use"
    ip = _local_ip()
    env = os.environ.copy()
    env["LOKI_DATA_DIR"] = str(LOKI_DATA)
    env["BJORN_IP"]      = ip
    env["LOKI_PID_FILE"] = str(LOKI_PID)
    log = LOKI_DATA / "logs" / "ktox_loki.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    _loki_proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER)],
        env=env,
        stdout=open(log, "a"),
        stderr=subprocess.STDOUT,
        cwd=str(LOKI_DIR),
    )
    for _ in range(100):
        if should_exit():
            _stop_loki()
            return False, "cancelled"
        if _port_open(LOKI_PORT):
            break
        time.sleep(0.1)
    if not _loki_running():
        return False, "check loot/loki/logs"
    return True, f"http://{ip}:{LOKI_PORT}"

def _stop_loki():
    global _loki_proc
    if _loki_proc is not None:
        try:
            _loki_proc.terminate()
            _loki_proc.wait(timeout=8)
        except:
            _loki_proc.kill()
        _loki_proc = None
    if LOKI_PID.exists():
        try:
            pid = int(LOKI_PID.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            os.kill(pid, signal.SIGKILL)
        except:
            pass
        LOKI_PID.unlink(missing_ok=True)
    subprocess.run(["pkill", "-f", "nmap"], capture_output=True)

# ----------------------------------------------------------------------
# Write the pagerctl.py shim (full emulation)
# ----------------------------------------------------------------------
def _write_pagerctl_shim():
    shim_path = LOKI_DIR / "lib" / "pagerctl.py"
    shim_path.parent.mkdir(parents=True, exist_ok=True)
    shim_code = '''\
# pagerctl.py – KTOx shim for Loki
import os, time, threading, queue
from PIL import Image, ImageDraw, ImageFont
import LCD_1in44
import LCD_Config

# Button masks (same as original)
BTN_UP    = 0x01
BTN_DOWN  = 0x02
BTN_LEFT  = 0x04
BTN_RIGHT = 0x08
BTN_A     = 0x10   # Green / OK
BTN_B     = 0x20   # Red / Back

# Map KTOx pins to button masks (adjust if your pins differ)
PIN_MAP = {
    6:  BTN_UP,
    19: BTN_DOWN,
    5:  BTN_LEFT,
    26: BTN_RIGHT,
    13: BTN_A,
    21: BTN_B,
}

class Pager:
    BLACK   = 0x0000
    WHITE   = 0xFFFF
    RED     = 0xF800
    GREEN   = 0x07E0
    BLUE    = 0x001F
    YELLOW  = 0xFFE0
    CYAN    = 0x07FF
    MAGENTA = 0xF81F
    ORANGE  = 0xFD20
    PURPLE  = 0x8010
    GRAY    = 0x8410

    def __init__(self):
        self.lcd = None
        self.image = None
        self.draw = None
        self.width = 128
        self.height = 128
        self.fonts = {}
        self._initialized = False
        self._input_thread = None
        self._input_queue = queue.Queue()
        self._running = False

    def init(self):
        if self._initialized:
            return 0
        try:
            self.lcd = LCD_1in44.LCD()
            self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            LCD_Config.Driver_Delay_ms(50)
            self.width = self.lcd.width
            self.height = self.lcd.height
            self.image = Image.new("RGB", (self.width, self.height))
            self.draw = ImageDraw.Draw(self.image)
            self._initialized = True
            self._start_input_thread()
            return 0
        except Exception as e:
            print(f"Pager init error: {e}")
            return -1

    def cleanup(self):
        self._running = False
        if self._input_thread and self._input_thread.is_alive():
            self._input_thread.join(timeout=1)
        self._initialized = False

    def clear(self, color=0):
        if not self.draw:
            return
        r,g,b = self._rgb565_to_rgb(color)
        self.draw.rectangle((0,0,self.width,self.height), fill=(r,g,b))

    def flip(self):
        if self.lcd and self.image:
            self.lcd.LCD_ShowImage(self.image, 0, 0)

    def set_rotation(self, rotation):
        pass

    # Primitives
    def pixel(self, x, y, color):
        if self.draw:
            r,g,b = self._rgb565_to_rgb(color)
            self.draw.point((x,y), fill=(r,g,b))

    def fill_rect(self, x, y, w, h, color):
        if self.draw:
            r,g,b = self._rgb565_to_rgb(color)
            self.draw.rectangle((x,y,x+w-1,y+h-1), fill=(r,g,b))

    def rect(self, x, y, w, h, color):
        if self.draw:
            r,g,b = self._rgb565_to_rgb(color)
            self.draw.rectangle((x,y,x+w-1,y+h-1), outline=(r,g,b))

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)

    def line(self, x1, y1, x2, y2, color):
        if self.draw:
            r,g,b = self._rgb565_to_rgb(color)
            self.draw.line((x1,y1,x2,y2), fill=(r,g,b))

    def fill_circle(self, x, y, r, color):
        if self.draw:
            r,g,b = self._rgb565_to_rgb(color)
            self.draw.ellipse((x-r, y-r, x+r, y+r), fill=(r,g,b))

    def circle(self, x, y, r, color):
        if self.draw:
            r,g,b = self._rgb565_to_rgb(color)
            self.draw.ellipse((x-r, y-r, x+r, y+r), outline=(r,g,b))

    # Text
    def draw_text(self, x, y, text, color, size=1):
        self.draw_ttf(x, y, text, color, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)

    def draw_ttf(self, x, y, text, color, font_path, font_size):
        if not self.draw:
            return
        r,g,b = self._rgb565_to_rgb(color)
        key = f"{font_path}:{font_size}"
        if key not in self.fonts:
            try:
                self.fonts[key] = ImageFont.truetype(font_path, font_size)
            except:
                self.fonts[key] = ImageFont.load_default()
        self.draw.text((x,y), text, font=self.fonts[key], fill=(r,g,b))

    def draw_text_centered(self, x, y, text, color, size=1):
        if not self.draw:
            return
        r,g,b = self._rgb565_to_rgb(color)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size*8)
            bbox = self.draw.textbbox((0,0), text, font=font)
            w = bbox[2]-bbox[0]
            self.draw.text((x - w//2, y), text, font=font, fill=(r,g,b))
        except:
            self.draw_text(x, y, text, color, size)

    def draw_ttf_centered(self, x, y, text, color, font_path, font_size):
        try:
            font = ImageFont.truetype(font_path, font_size)
            bbox = self.draw.textbbox((0,0), text, font=font)
            w = bbox[2]-bbox[0]
            self.draw_ttf(x - w//2, y, text, color, font_path, font_size)
        except:
            self.draw_text(x, y, text, color)

    # Color conversion
    @staticmethod
    def rgb(r, g, b):
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    def _rgb565_to_rgb(self, color):
        r = (color >> 11) & 0x1F
        g = (color >> 5) & 0x3F
        b = color & 0x1F
        return (r << 3, g << 2, b << 3)

    # Input handling
    def _start_input_thread(self):
        if not self._running:
            self._running = True
            self._input_thread = threading.Thread(target=self._input_loop, daemon=True)
            self._input_thread.start()

    def _input_loop(self):
        import RPi.GPIO as GPIO
        for pin in PIN_MAP:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        last_state = 0
        while self._running:
            current_state = 0
            for pin, mask in PIN_MAP.items():
                if GPIO.input(pin) == 0:
                    current_state |= mask
            changed = current_state ^ last_state
            if changed:
                # Queue press/release events
                for mask in PIN_MAP.values():
                    if changed & mask:
                        event_type = 1 if (current_state & mask) else 0  # 1=pressed, 0=released
                        self._input_queue.put((event_type, mask))
            last_state = current_state
            time.sleep(0.05)

    def get_input_event(self):
        try:
            return self._input_queue.get_nowait()
        except queue.Empty:
            return None

# Also provide PagerInput and PagerInputEvent for compatibility
class PagerInputEvent:
    def __init__(self, event_type, button):
        self.type = event_type  # 1 = pressed, 0 = released
        self.button = button

class PagerInput:
    def __init__(self):
        self.pager = None
    def attach(self, pager):
        self.pager = pager
    def get_input_event(self):
        if self.pager:
            ev = self.pager.get_input_event()
            if ev:
                return PagerInputEvent(ev[0], ev[1])
        return None
'''
    shim_path.write_text(shim_code)
    shim_path.chmod(0o644)

# ----------------------------------------------------------------------
# Write the headless launcher (uses real pagerctl, no mocks)
# ----------------------------------------------------------------------
def _write_launcher():
    launcher_code = f'''\
#!/usr/bin/env python3
# ktox_headless_loki.py - uses real pagerctl shim

import sys, os, threading, signal, logging, time, subprocess

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.join(_dir, 'lib')
if os.path.exists(_lib) and _lib not in sys.path:
    sys.path.insert(0, _lib)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

os.environ['CRYPTOGRAPHY_OPENSSL_NO_LEGACY'] = '1'
_DATA = os.environ.get('LOKI_DATA_DIR', '{LOKI_DATA}')

# Patch SharedData paths
from shared import SharedData as _SD
_orig = _SD.__init__
def _patch(self, *a, **kw):
    _orig(self, *a, **kw)
    self.datadir             = _DATA
    self.logsdir             = os.path.join(_DATA, 'logs')
    self.output_dir          = os.path.join(_DATA, 'output')
    self.input_dir           = os.path.join(_DATA, 'input')
    self.crackedpwddir       = os.path.join(_DATA, 'output', 'crackedpwd')
    self.datastolendir       = os.path.join(_DATA, 'output', 'datastolen')
    self.zombiesdir          = os.path.join(_DATA, 'output', 'zombies')
    self.vulnerabilities_dir = os.path.join(_DATA, 'output', 'vulnerabilities')
    self.scan_results_dir    = os.path.join(_DATA, 'output', 'vulnerabilities')
    self.netkbfile           = os.path.join(_DATA, 'netkb.csv')
    for d in [self.datadir, self.logsdir, self.output_dir, self.input_dir,
              self.crackedpwddir, self.datastolendir, self.zombiesdir,
              self.vulnerabilities_dir]:
        os.makedirs(d, exist_ok=True)
_SD.__init__ = _patch

# Fix WiFi check
import Loki as _lm
def _wifi(self):
    try:
        r = subprocess.run(['ip', 'route', 'show', 'default'],
                           capture_output=True, text=True, timeout=5)
        self.wifi_connected = bool(r.stdout.strip())
    except:
        self.wifi_connected = True
    return self.wifi_connected
_lm.Loki.is_wifi_connected = _wifi

from init_shared import shared_data
from Loki import Loki, handle_exit
from webapp import web_thread, handle_exit_web
from logger import Logger

logger = Logger(name='ktox_headless_loki', level=logging.INFO)

if __name__ == '__main__':
    shared_data.load_config()
    bjorn_ip = os.environ.get('BJORN_IP', '')
    if bjorn_ip:
        os.environ['BJORN_IP'] = bjorn_ip
    pid_file = os.environ.get('LOKI_PID_FILE', '')
    if pid_file:
        with open(pid_file, 'w') as _f:
            _f.write(str(os.getpid()))

    shared_data.webapp_should_exit  = False
    shared_data.display_should_exit = True   # we handle display via pagerctl
    web_thread.start()
    logger.info('Loki web interface started on port 8000')

    loki = Loki(shared_data)
    shared_data.loki_instance = loki
    lt = threading.Thread(target=loki.run, daemon=True)
    lt.start()

    signal.signal(signal.SIGINT,  lambda s, f: handle_exit(s, f, lt, lt, web_thread))
    signal.signal(signal.SIGTERM, lambda s, f: handle_exit(s, f, lt, lt, web_thread))
    logger.info('Loki running — open http://0.0.0.0:8000 in your browser')

    while not shared_data.should_exit:
        time.sleep(2)
'''
    LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHER.write_text(launcher_code)
    LAUNCHER.chmod(0o755)

# ----------------------------------------------------------------------
# Installation routine
# ----------------------------------------------------------------------
def install_loki():
    try:
        # Step 1: system packages
        screen_installing(1, 7, "Installing system packages...")
        _run_with_cancel("apt-get update -qq && apt-get install -y nmap python3-pil python3-pil.imagetk git", timeout=300, step_msg="Installing packages")

        # Step 2: clone/pull repo
        screen_installing(2, 7, "Cloning Loki repo...")
        VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
        if VENDOR_DIR.exists() and (VENDOR_DIR / ".git").exists():
            _run_with_cancel(f"git -C {VENDOR_DIR} pull", timeout=120, step_msg="Updating repo")
        else:
            if VENDOR_DIR.exists():
                shutil.rmtree(VENDOR_DIR)
            _run_with_cancel(f"git clone --depth=1 {LOKI_REPO} {VENDOR_DIR}", timeout=300, step_msg="Cloning repo")

        # Step 3: create data dirs
        screen_installing(3, 7, "Creating data directories...")
        for sub in ["logs", "output/crackedpwd", "output/datastolen",
                    "output/zombies", "output/vulnerabilities", "input"]:
            (LOKI_DATA / sub).mkdir(parents=True, exist_ok=True)

        # Step 4: write pagerctl shim
        screen_installing(4, 7, "Installing pagerctl shim...")
        _write_pagerctl_shim()

        # Step 5: write headless launcher
        screen_installing(5, 7, "Writing launcher...")
        _write_launcher()

        # Step 6: verify
        screen_installing(6, 7, "Verifying installation...")
        if not LAUNCHER.exists() or not (LOKI_DIR / "lib" / "pagerctl.py").exists():
            return False, "missing files"

        # Step 7: done
        screen_installing(7, 7, "Done!")
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
    url = f"http://{ip}:{LOKI_PORT}"

    # First run: prompt to install
    if not _loki_installed():
        print("[loki] Not installed.")
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
            print("[loki] Press Enter to install, Ctrl+C to cancel.")
            input()

        print("[loki] Installing...")
        ok, msg = install_loki()
        if not ok:
            print(f"[loki] Install failed: {msg}")
            if _HW:
                screen_error("Install failed", msg)
                time.sleep(4)
            return

    # Start Loki if not running
    if not _loki_running():
        print(f"[loki] Starting Loki → {url}")
        if _HW:
            screen_starting()
        ok, result = _start_loki()
        if not ok:
            print(f"[loki] Start failed: {result}")
            if _HW:
                screen_error("Start failed", result)
                time.sleep(4)
            return
        print(f"[loki] Loki running at {result}")
    else:
        print(f"[loki] Already running at {url}")

    start_ts = datetime.now().strftime("%H:%M:%S")
    since_label = f"since {start_ts}"

    # Main control loop
    while True:
        running = _loki_running()
        if running:
            web_up = _port_open(LOKI_PORT)
            if _HW:
                screen_running(url, web_up, since_label)
            else:
                print(f"\r[loki] {'WEB READY' if web_up else 'STARTING':10s}  {url}", end="", flush=True)
        else:
            if _HW:
                screen_stopped()
            else:
                print("\r[loki] STOPPED                                    ", end="", flush=True)

        for _ in range(10):
            time.sleep(0.1)
            if running:
                if _key("KEY1_PIN"):
                    _wait_key_release("KEY1_PIN")
                    print("\n[loki] Stopping Loki...")
                    _stop_loki()
                    return
                if _key("KEY3_PIN"):
                    _wait_key_release("KEY3_PIN")
                    print(f"\n[loki] Exiting — Loki continues at {url}")
                    return
            else:
                if _key("KEY3_PIN"):
                    _wait_key_release("KEY3_PIN")
                    if _HW:
                        screen_starting()
                    ok, result = _start_loki()
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
                    ok, msg = install_loki()
                    if not ok and _HW:
                        screen_error("Install failed", msg)
                        time.sleep(3)
                    break

if __name__ == "__main__":
    main()
