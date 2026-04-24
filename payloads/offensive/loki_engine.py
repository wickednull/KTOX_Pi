#!/usr/bin/env python3
"""
KTOx Loki Engine Integration
=============================
Comprehensive Loki payload launcher for KTOX_Pi

Provides:
- Automatic installation management
- Process lifecycle control
- LCD status display
- WebUI integration
- Headless operation support

Author: KTOx Development
"""

import os
import sys
import time
import subprocess
import socket
import signal
import shutil
import threading
import logging
from pathlib import Path
from datetime import datetime

# Environment & Paths
KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
LOOT_DIR = os.path.join(KTOX_DIR, "loot")
VENDOR_DIR = Path(KTOX_DIR) / "vendor" / "loki"
LOKI_DATA = Path(LOOT_DIR) / "loki"
LOKI_PID = Path(LOOT_DIR) / "loki.pid"
LOKI_PORT = 8000

LOKI_REPO = "https://github.com/pineapple-pager-projects/pineapple_pager_loki"
LAUNCHER = VENDOR_DIR / "ktox_headless_loki.py"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[Loki] %(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# GPIO Pins (Waveshare 1.44" HAT)
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

# Colors (RGB hex)
COLORS = {
    "BLACK": "#0a0a0a",
    "WHITE": "#c8c8c8",
    "RED": "#8B0000",
    "GREEN": "#2ecc40",
    "ORANGE": "#ff8800",
    "BLUE": "#3399ff",
    "DIM": "#444444",
}

# Hardware detection
try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    import LCD_Config
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False
    GPIO = None
    LCD_1in44 = None

_lcd = None
_image = None
_draw = None


class LokiDisplay:
    """LCD display handler for Loki status."""

    @staticmethod
    def init():
        global _lcd, _image, _draw
        if not HAS_GPIO:
            return False
        try:
            _lcd = LCD_1in44.LCD()
            _lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            LCD_Config.Driver_Delay_ms(50)
            _image = Image.new("RGB", (_lcd.width, _lcd.height))
            _draw = ImageDraw.Draw(_image)
            return True
        except Exception as e:
            logger.error(f"LCD init failed: {e}")
            return False

    @staticmethod
    def clear():
        if _draw:
            _draw.rectangle((0, 0, 128, 128), fill=(10, 10, 10))

    @staticmethod
    def show():
        if _lcd and _image:
            _lcd.LCD_ShowImage(_image, 0, 0)

    @staticmethod
    def text(x, y, text, color="#c8c8c8", size=9):
        if not _draw:
            return
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size
            )
        except:
            font = ImageFont.load_default()

        # Convert hex color to RGB
        c = color.lstrip("#")
        rgb = tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))
        _draw.text((x, y), text, font=font, fill=rgb)

    @staticmethod
    def centered(y, text, color="#c8c8c8", size=9):
        if not _draw:
            return
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", size
            )
        except:
            font = ImageFont.load_default()

        c = color.lstrip("#")
        rgb = tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))
        bbox = _draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        _draw.text(((128 - w) // 2, y), text, font=font, fill=rgb)

    @staticmethod
    def hbar(y, percent):
        if not _draw:
            return
        width = 116
        _draw.rectangle([6, y, 6 + width, y + 4], fill=(18, 24, 60))
        _draw.rectangle(
            [6, y, 6 + max(1, int(width * percent / 100)), y + 4],
            fill=(100, 180, 255),
        )

    @staticmethod
    def border():
        if not _draw:
            return
        red = (139, 0, 0)
        _draw.line([(127, 12), (127, 127)], fill=red, width=5)
        _draw.line([(127, 127), (0, 127)], fill=red, width=5)
        _draw.line([(0, 127), (0, 12)], fill=red, width=5)
        _draw.line([(0, 12), (128, 12)], fill=red, width=5)


class LokiEngine:
    """Main Loki management engine."""

    def __init__(self):
        self.proc = None
        self.log_file = None
        self.port = LOKI_PORT

    def is_installed(self) -> bool:
        """Check if Loki is installed."""
        return LAUNCHER.exists()

    def is_running(self) -> bool:
        """Check if Loki process is running."""
        if self.proc is not None and self.proc.poll() is None:
            return True

        if LOKI_PID.exists():
            try:
                pid = int(LOKI_PID.read_text().strip())
                os.kill(pid, 0)  # Check if process exists
                return True
            except (ProcessLookupError, ValueError):
                LOKI_PID.unlink(missing_ok=True)

        return False

    def get_local_ip(self) -> str:
        """Get local IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"

    def is_port_open(self, port: int = None) -> bool:
        """Check if port is open."""
        if port is None:
            port = self.port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def install(self, progress_callback=None):
        """Install Loki from GitHub."""
        steps = [
            ("Updating apt cache", self._update_apt),
            ("Cloning Loki repo", self._clone_repo),
            ("Creating data dirs", self._create_dirs),
            ("Writing pagerctl shim", self._write_shim),
            ("Writing headless launcher", self._write_launcher),
            ("Verifying installation", self._verify_install),
        ]

        for i, (label, step_func) in enumerate(steps):
            if progress_callback:
                progress_callback(i + 1, len(steps), label)

            try:
                step_func()
            except Exception as e:
                logger.error(f"Installation step failed: {e}")
                return False

        logger.info("Loki installation complete")
        return True

    def _update_apt(self):
        subprocess.run(
            ["apt-get", "update", "-qq"],
            capture_output=True,
            timeout=120,
            check=True,
        )
        subprocess.run(
            [
                "apt-get",
                "install",
                "-y",
                "-qq",
                "nmap",
                "python3-pil",
                "git",
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )

    def _clone_repo(self):
        VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)

        if VENDOR_DIR.exists() and (VENDOR_DIR / ".git").exists():
            subprocess.run(
                ["git", "-C", str(VENDOR_DIR), "pull"],
                capture_output=True,
                timeout=120,
                check=True,
            )
        else:
            if VENDOR_DIR.exists():
                shutil.rmtree(VENDOR_DIR)

            subprocess.run(
                ["git", "clone", "--depth=1", LOKI_REPO, str(VENDOR_DIR)],
                capture_output=True,
                timeout=300,
                check=True,
            )

    def _create_dirs(self):
        for sub in [
            "logs",
            "output/crackedpwd",
            "output/datastolen",
            "output/zombies",
            "output/vulnerabilities",
            "input",
        ]:
            (LOKI_DATA / sub).mkdir(parents=True, exist_ok=True)

    def _write_shim(self):
        """Write pagerctl.py shim for KTOx LCD integration."""
        shim_path = VENDOR_DIR / "lib" / "pagerctl.py"
        shim_path.parent.mkdir(parents=True, exist_ok=True)

        # Simplified pagerctl shim
        shim_code = '''# pagerctl.py - KTOx LCD shim for Loki
import os, time, threading, queue
from PIL import Image, ImageDraw, ImageFont

HAS_LCD = False
try:
    import LCD_1in44, LCD_Config
    HAS_LCD = True
except ImportError:
    pass

BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT = 0x01, 0x02, 0x04, 0x08
BTN_A, BTN_B = 0x10, 0x20

class Pager:
    BLACK, WHITE, RED = 0x0000, 0xFFFF, 0xF800
    GREEN, BLUE, YELLOW = 0x07E0, 0x001F, 0xFFE0

    def __init__(self):
        self.lcd = None
        self.image = None
        self.draw = None
        self.width = 128
        self.height = 128
        self._initialized = False
        self._input_thread = None
        self._input_queue = queue.Queue()
        self._running = False

    def init(self):
        if self._initialized: return 0
        if not HAS_LCD: return 0
        try:
            self.lcd = LCD_1in44.LCD()
            self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            LCD_Config.Driver_Delay_ms(50)
            self.width, self.height = self.lcd.width, self.lcd.height
            self.image = Image.new("RGB", (self.width, self.height))
            self.draw = ImageDraw.Draw(self.image)
            self._initialized = True
            return 0
        except Exception as e:
            return -1

    def cleanup(self):
        self._running = False
        if self._input_thread and self._input_thread.is_alive():
            self._input_thread.join(timeout=1)

    def clear(self, color=0):
        if self.draw:
            r, g, b = self._rgb565_to_rgb(color)
            self.draw.rectangle((0, 0, self.width, self.height), fill=(r, g, b))

    def flip(self):
        if self.lcd and self.image:
            self.lcd.LCD_ShowImage(self.image, 0, 0)

    def set_rotation(self, rotation): pass

    def pixel(self, x, y, color):
        if self.draw:
            r, g, b = self._rgb565_to_rgb(color)
            self.draw.point((x, y), fill=(r, g, b))

    def fill_rect(self, x, y, w, h, color):
        if self.draw:
            r, g, b = self._rgb565_to_rgb(color)
            self.draw.rectangle((x, y, x + w - 1, y + h - 1), fill=(r, g, b))

    def rect(self, x, y, w, h, color):
        if self.draw:
            r, g, b = self._rgb565_to_rgb(color)
            self.draw.rectangle((x, y, x + w - 1, y + h - 1), outline=(r, g, b))

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)

    def line(self, x1, y1, x2, y2, color):
        if self.draw:
            r, g, b = self._rgb565_to_rgb(color)
            self.draw.line((x1, y1, x2, y2), fill=(r, g, b))

    def fill_circle(self, x, y, r, color):
        if self.draw:
            r_c, g_c, b_c = self._rgb565_to_rgb(color)
            self.draw.ellipse((x - r, y - r, x + r, y + r), fill=(r_c, g_c, b_c))

    def circle(self, x, y, r, color):
        if self.draw:
            r_c, g_c, b_c = self._rgb565_to_rgb(color)
            self.draw.ellipse((x - r, y - r, x + r, y + r), outline=(r_c, g_c, b_c))

    def draw_text(self, x, y, text, color, size=1):
        self.draw_ttf(x, y, text, color, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)

    def draw_ttf(self, x, y, text, color, font_path, font_size):
        if not self.draw: return
        r, g, b = self._rgb565_to_rgb(color)
        try:
            font = ImageFont.truetype(font_path, font_size)
        except:
            font = ImageFont.load_default()
        self.draw.text((x, y), text, font=font, fill=(r, g, b))

    def draw_text_centered(self, x, y, text, color, size=1):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size * 8)
            bbox = self.draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            self.draw_ttf(x - w // 2, y, text, color, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size * 8)
        except:
            self.draw_text(x, y, text, color, size)

    def draw_ttf_centered(self, x, y, text, color, font_path, font_size):
        try:
            font = ImageFont.truetype(font_path, font_size)
            bbox = self.draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            self.draw_ttf(x - w // 2, y, text, color, font_path, font_size)
        except:
            self.draw_text(x, y, text, color)

    @staticmethod
    def rgb(r, g, b):
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    def _rgb565_to_rgb(self, color):
        r = (color >> 11) & 0x1F
        g = (color >> 5) & 0x3F
        b = color & 0x1F
        return (r << 3, g << 2, b << 3)

class PagerInput:
    def __init__(self): self.pager = None
    def attach(self, pager): self.pager = pager
    def get_input_event(self): return None

class PagerInputEvent:
    def __init__(self, event_type, button):
        self.type = event_type
        self.button = button
'''
        shim_path.write_text(shim_code)
        shim_path.chmod(0o644)

    def _write_launcher(self):
        """Write headless Loki launcher."""
        launcher_code = f'''#!/usr/bin/env python3
# ktox_headless_loki.py
import sys, os, threading, signal, logging, time, subprocess

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.join(_dir, 'lib')
if os.path.exists(_lib) and _lib not in sys.path:
    sys.path.insert(0, _lib)
if _dir not in sys.path:
    sys.path.insert(0, _dir)

os.environ['CRYPTOGRAPHY_OPENSSL_NO_LEGACY'] = '1'
_DATA = os.environ.get('LOKI_DATA_DIR', '{LOKI_DATA}')

# Patch SharedData
try:
    from shared import SharedData as _SD
    _orig = _SD.__init__
    def _patch(self, *a, **kw):
        _orig(self, *a, **kw)
        self.datadir = _DATA
        self.logsdir = os.path.join(_DATA, 'logs')
        self.output_dir = os.path.join(_DATA, 'output')
        self.input_dir = os.path.join(_DATA, 'input')
        self.crackedpwddir = os.path.join(_DATA, 'output', 'crackedpwd')
        self.datastolendir = os.path.join(_DATA, 'output', 'datastolen')
        self.zombiesdir = os.path.join(_DATA, 'output', 'zombies')
        self.vulnerabilities_dir = os.path.join(_DATA, 'output', 'vulnerabilities')
        self.netkbfile = os.path.join(_DATA, 'netkb.csv')
        for d in [self.datadir, self.logsdir, self.output_dir, self.input_dir,
                  self.crackedpwddir, self.datastolendir, self.zombiesdir,
                  self.vulnerabilities_dir]:
            os.makedirs(d, exist_ok=True)
    _SD.__init__ = _patch
except: pass

try:
    from init_shared import shared_data
    from Loki import Loki, handle_exit
    from webapp import web_thread, handle_exit_web
    from logger import Logger

    logger = Logger(name='ktox_headless_loki', level=logging.INFO)

    shared_data.load_config()
    bjorn_ip = os.environ.get('BJORN_IP', '')
    if bjorn_ip:
        os.environ['BJORN_IP'] = bjorn_ip

    pid_file = os.environ.get('LOKI_PID_FILE', '')
    if pid_file:
        with open(pid_file, 'w') as _f:
            _f.write(str(os.getpid()))

    shared_data.webapp_should_exit = False
    shared_data.display_should_exit = True
    web_thread.start()

    loki = Loki(shared_data)
    shared_data.loki_instance = loki
    lt = threading.Thread(target=loki.run, daemon=True)
    lt.start()

    signal.signal(signal.SIGINT, lambda s, f: handle_exit(s, f, lt, web_thread))
    signal.signal(signal.SIGTERM, lambda s, f: handle_exit(s, f, lt, web_thread))

    while not shared_data.should_exit:
        time.sleep(2)
except Exception as e:
    print(f"Error: {{e}}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
'''
        LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
        LAUNCHER.write_text(launcher_code)
        LAUNCHER.chmod(0o755)

    def _verify_install(self):
        if not LAUNCHER.exists():
            raise Exception("Launcher not found")
        if not (VENDOR_DIR / "lib" / "pagerctl.py").exists():
            raise Exception("pagerctl shim not found")

    def start(self) -> tuple[bool, str]:
        """Start Loki process."""
        if self.is_running():
            return True, f"http://{self.get_local_ip()}:{self.port}"

        if self.is_port_open():
            return False, f"Port {self.port} already in use"

        ip = self.get_local_ip()
        env = os.environ.copy()
        env["LOKI_DATA_DIR"] = str(LOKI_DATA)
        env["BJORN_IP"] = ip
        env["LOKI_PID_FILE"] = str(LOKI_PID)

        log_path = LOKI_DATA / "logs" / "loki.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self.log_file = open(log_path, "a")
            self.proc = subprocess.Popen(
                [sys.executable, str(LAUNCHER)],
                env=env,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
                cwd=str(VENDOR_DIR),
            )

            # Wait for port to open
            for _ in range(300):  # 30 seconds
                if self.proc.poll() is not None:
                    return False, "Process crashed"
                if self.is_port_open():
                    logger.info(f"Loki started at http://{ip}:{self.port}")
                    return True, f"http://{ip}:{self.port}"
                time.sleep(0.1)

            return False, "Startup timeout"

        except Exception as e:
            logger.error(f"Failed to start Loki: {e}")
            return False, str(e)

    def stop(self):
        """Stop Loki process."""
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

        if self.log_file:
            try:
                self.log_file.close()
            except:
                pass

        # Kill via PID file
        if LOKI_PID.exists():
            try:
                pid = int(LOKI_PID.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
                try:
                    os.kill(pid, signal.SIGKILL)
                except:
                    pass
            except:
                pass
            LOKI_PID.unlink(missing_ok=True)

        # Cleanup subprocess
        subprocess.run(["pkill", "-f", "ktox_headless_loki"], capture_output=True)
        logger.info("Loki stopped")


# Global instance
_engine = None


def get_loki_engine():
    global _engine
    if _engine is None:
        _engine = LokiEngine()
    return _engine


if __name__ == "__main__":
    engine = get_loki_engine()
    print(f"Installed: {engine.is_installed()}")
    print(f"Running: {engine.is_running()}")
    print(f"Port open: {engine.is_port_open()}")
