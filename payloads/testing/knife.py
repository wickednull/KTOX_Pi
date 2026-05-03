#!/usr/bin/env python3
"""USB Army Knife controller for KTOX Pi LCD/button hardware.

Controls an iamshodan USBArmyKnife over USB serial from the KTOX payload menu.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
except Exception as exc:
    serial = None
    SERIAL_IMPORT_ERROR = exc
else:
    SERIAL_IMPORT_ERROR = None

try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None

try:
    import LCD_1in44
except Exception:
    LCD_1in44 = None

from PIL import Image, ImageDraw, ImageFont

KTOX_ROOT = Path(os.environ.get("KTOX_DIR", "/root/KTOx"))
if str(KTOX_ROOT) not in sys.path:
    sys.path.insert(0, str(KTOX_ROOT))

try:
    from _input_helper import flush_input, get_button
except Exception:
    flush_input = lambda: None

    def get_button(pins, gpio):
        if gpio is None:
            return None
        for btn, pin in pins.items():
            if gpio.input(pin) == 0:
                return btn
        return None

try:
    from _display_helper import LCD_SCALE, ScaledDraw, scaled_font
except Exception:
    LCD_SCALE = 1.0
    ScaledDraw = ImageDraw.Draw

    def scaled_font(size=10):
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()


SERIAL_BAUD_CANDIDATES = (115200, 57600, 230400, 9600)
PROBE_COMMANDS = ("HELP", "ESP32M help")
PROBE_MARKERS = (
    "usb army knife",
    "ducky",
    "duckyscript",
    "esp32m",
    "marauder",
    "run_payload",
    "display_text",
    "serial",
)

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

COMMAND_CATEGORIES = {
    "Marauder Scan": [
        "ESP32M scanap",
        "ESP32M scansta",
        "ESP32M stopscan",
        "ESP32M list -a",
        "ESP32M list -s",
        "ESP32M packetcount",
    ],
    "Marauder Attack": [
        "ESP32M select -a 0",
        "ESP32M select -s 0",
        "ESP32M sniffpmkid -l -d",
        "ESP32M sniffbeacon",
        "ESP32M sniffdeauth",
        "ESP32M attack -t deauth -a",
        "ESP32M attack -t deauth -s",
    ],
    "USB Device": [
        "USB_RESET",
        "USB_NCM_PCAP_ON",
        "USB_NCM_PCAP_OFF",
        "USB_MOUNT_DISK_READ_ONLY benign.img",
        "USB_MOUNT_CDROM_READ_ONLY cdrom.iso",
    ],
    "Display / WiFi": [
        "DISPLAY_CLEAR",
        "DISPLAY_TEXT 0 0 KTOX READY",
        "TFT_ON",
        "TFT_OFF",
        "WIFI_ON",
        "WIFI_OFF",
        "WEB_OFF",
    ],
    "Payload / Agent": [
        "RUN_PAYLOAD autorun.ds",
        "RUN_PAYLOAD menu.ds",
        "LOAD_DS_FILES_FROM_SD()",
        "AGENT_CONNECTED()",
        "AGENT_RUN whoami",
        "WAIT_FOR_AGENT_RUN_RESULT",
    ],
    "System": [
        "HELP",
        "SERIAL 115200",
        "SERIAL 57600",
        "SET_SETTING_BOOL StartWebService 1",
        "RESET_SETTINGS",
        "LOG KTOX USBArmyKnife control",
    ],
}

TEXT_CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-/.:"


def _lcd_size():
    if LCD_SCALE != 1.0:
        return int(128 * LCD_SCALE), int(128 * LCD_SCALE)
    return 128, 128


def _wrap(text, width=24):
    words = str(text).replace("\r", "\n").split()
    lines = []
    current = ""
    for word in words:
        if len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.extend(word[i : i + width] for i in range(0, len(word), width))
            continue
        candidate = f"{current} {word}".strip()
        if len(candidate) > width:
            if current:
                lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


class USBArmyKnife:
    def __init__(self, serial_factory=None):
        self.serial_factory = serial_factory
        self.ser = None
        self.port = None
        self.baud = None
        self.last_error = None
        self.probe_text = ""

    def _try_load_usb_serial_modules(self):
        for mod in ("cdc_acm", "cp210x", "ch341", "ftdi_sio", "usbserial"):
            try:
                subprocess.run([_command("modprobe"), mod], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

    def list_ports(self):
        if serial is None:
            self.last_error = f"pyserial unavailable: {SERIAL_IMPORT_ERROR}"
            return []

        self._try_load_usb_serial_modules()
        out = []

        for port in serial.tools.list_ports.comports():
            device = getattr(port, "device", "")
            desc = (getattr(port, "description", "") or "Unknown")[:32]
            hwid = (getattr(port, "hwid", "") or "").lower()
            priority = 0
            joined = f"{device} {desc} {hwid}".lower()
            if any(token in joined for token in ("esp", "cp210", "ch340", "ch341", "cdc", "acm", "usb serial")):
                priority = 1
            if device:
                out.append((priority, f"{device} | {desc}"))

        for dev in sorted(glob.glob("/dev/serial/by-id/*")):
            if os.path.exists(dev):
                out.append((2, f"{dev} | by-id"))

        for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
            for dev in sorted(glob.glob(pattern)):
                if os.path.exists(dev):
                    out.append((1, f"{dev} | detected"))

        seen = set()
        labels = []
        for _priority, label in sorted(out, key=lambda item: (-item[0], item[1])):
            if label not in seen:
                seen.add(label)
                labels.append(label)
        return labels

    def _open(self, baud):
        factory = self.serial_factory or serial.Serial
        self.ser = factory(
            self.port,
            baud,
            timeout=0.1,
            write_timeout=1,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        try:
            self.ser.setDTR(False)
            self.ser.setRTS(False)
            time.sleep(0.05)
            self.ser.setDTR(True)
            self.ser.setRTS(True)
        except Exception:
            pass
        time.sleep(0.8)
        self._drain(0.25)

    def _drain(self, seconds=0.25):
        end = time.time() + seconds
        while time.time() < end and self.ser:
            try:
                waiting = getattr(self.ser, "in_waiting", 0)
                if waiting:
                    self.ser.read(waiting)
                else:
                    time.sleep(0.02)
            except Exception:
                break

    def _read_until_idle(self, timeout=2.5, idle=0.35):
        raw = ""
        start = time.time()
        last_data = None
        while time.time() - start < timeout:
            try:
                chunk = self.ser.read(512).decode(errors="ignore")
            except Exception:
                break
            if chunk:
                raw += chunk
                last_data = time.time()
                continue
            if raw and last_data and time.time() - last_data >= idle:
                break
            time.sleep(0.03)
        return raw

    def _probe_cli(self):
        raw = ""
        for cmd in PROBE_COMMANDS:
            try:
                self.ser.write((cmd + "\r\n").encode())
                self.ser.flush()
            except Exception:
                break
            raw += self._read_until_idle(timeout=2.0, idle=0.35)
        self.probe_text = raw
        return raw

    def connect(self, port):
        if serial is None and self.serial_factory is None:
            self.last_error = f"pyserial unavailable: {SERIAL_IMPORT_ERROR}"
            return False

        self.port = port.split(" | ")[0].strip()
        last_exc = None
        for baud in SERIAL_BAUD_CANDIDATES:
            keep_open = False
            try:
                self._open(baud)
                probe = self._probe_cli().lower()
                if any(marker in probe for marker in PROBE_MARKERS):
                    self.baud = baud
                    keep_open = True
                    return True
            except Exception as exc:
                last_exc = exc
            finally:
                if self.ser and not keep_open:
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None
        self.last_error = f"{self.port} did not look like USB Army Knife. Last error: {last_exc}"
        return False

    def send(self, cmd, timeout=12):
        if not self.ser or not getattr(self.ser, "is_open", False):
            return ["[ERROR] serial not open"]
        clean = cmd.strip()
        if not clean:
            return ["[ERROR] empty command"]
        try:
            self._drain(0.05)
            self.ser.write((clean + "\r\n").encode())
            self.ser.flush()
        except Exception as exc:
            return [f"[ERROR] write failed: {exc}"]
        raw = self._read_until_idle(timeout=timeout, idle=0.8)
        lines = [ln.strip() for ln in raw.replace("\r", "\n").split("\n") if ln.strip()]
        return lines or [f"[TIMEOUT] no data from {self.port}@{self.baud}"]

    def close(self):
        if self.ser and getattr(self.ser, "is_open", False):
            self.ser.close()


class UI:
    def __init__(self):
        self.gpio = GPIO
        if self.gpio is not None:
            try:
                self.gpio.setmode(self.gpio.BCM)
                self.gpio.setwarnings(False)
                for pin in PINS.values():
                    self.gpio.setup(pin, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)
            except Exception:
                self.gpio = None
        self.lcd = None
        if LCD_1in44 is not None:
            try:
                self.lcd = LCD_1in44.LCD()
                self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            except Exception:
                self.lcd = None
        self.width, self.height = _lcd_size()
        if self.lcd is not None:
            self.width = getattr(self.lcd, "width", self.width)
            self.height = getattr(self.lcd, "height", self.height)
        self.font = scaled_font(10)
        self.font_sm = scaled_font(9)

    def button(self, timeout=0.15):
        end = time.time() + timeout
        while time.time() < end:
            button = get_button(PINS, self.gpio)
            if button:
                time.sleep(0.07)
                return button
            time.sleep(0.01)
        return None

    def draw_lines(self, title, lines, sel=None, footer="OK Select K3 Back"):
        img = Image.new("RGB", (self.width, self.height), (10, 0, 0))
        draw = ScaledDraw(img)
        draw.rectangle((0, 0, 128, 14), fill=(139, 0, 0))
        draw.text((4, 2), title[:20], font=self.font_sm, fill=(255, 255, 255))
        y = 18
        for i, line in enumerate(lines[:8]):
            text = ("> " if sel == i else "  ") + str(line)
            draw.text((2, y), text[:24], font=self.font_sm, fill=(220, 220, 220))
            y += 13
        draw.rectangle((0, 116, 128, 128), fill=(34, 0, 0))
        draw.text((2, 118), footer[:24], font=self.font_sm, fill=(155, 155, 155))
        if self.lcd is not None:
            self.lcd.LCD_ShowImage(img, 0, 0)
        else:
            print(f"\n[{title}]")
            for line in lines[:8]:
                print(line)

    def menu(self, title, items):
        if not items:
            return None
        idx = 0
        flush_input()
        while True:
            start = max(0, min(idx, max(0, len(items) - 8)))
            view = items[start : start + 8]
            self.draw_lines(title, view, sel=idx - start)
            button = self.button()
            if button == "UP":
                idx = (idx - 1) % len(items)
            elif button == "DOWN":
                idx = (idx + 1) % len(items)
            elif button in ("OK", "RIGHT", "KEY1"):
                flush_input()
                return items[idx]
            elif button in ("LEFT", "KEY3"):
                flush_input()
                return None

    def message(self, title, body, seconds=1.5):
        lines = []
        for part in str(body).splitlines() or [""]:
            lines.extend(_wrap(part))
        self.draw_lines(title, lines)
        time.sleep(seconds)

    def text_input(self, title, default=""):
        value = default
        pos = 0
        flush_input()
        while True:
            char = TEXT_CHARS[pos]
            visible = value[-18:] or "(empty)"
            self.draw_lines(
                title,
                [visible, "", f"Char: {char}", "UP/DN change", "OK add", "K1 send", "K2 del", "K3 cancel"],
                footer="K1 Send K3 Back",
            )
            button = self.button()
            if button == "UP":
                pos = (pos + 1) % len(TEXT_CHARS)
            elif button == "DOWN":
                pos = (pos - 1) % len(TEXT_CHARS)
            elif button in ("OK", "RIGHT"):
                value += char
            elif button in ("KEY2", "LEFT"):
                value = value[:-1]
            elif button == "KEY1":
                flush_input()
                return value.strip()
            elif button == "KEY3":
                flush_input()
                return None

    def close(self):
        if self.gpio is not None:
            try:
                self.gpio.cleanup()
            except Exception:
                pass


def _command(name):
    return name


def _parse_indices(lines):
    out = []
    for line in lines:
        parts = line.replace(")", " ").replace(":", " ").split()
        if parts and parts[0].isdigit():
            out.append(parts[0])
    return out


def _show_output(ui, title, lines):
    idx = 0
    lines = lines or ["(no output)"]
    while True:
        page = lines[idx : idx + 8]
        ui.draw_lines(title[:20], page, footer="UP/DN scroll K3 back")
        button = ui.button()
        if button == "UP":
            idx = max(0, idx - 1)
        elif button == "DOWN":
            idx = min(max(0, len(lines) - 1), idx + 1)
        elif button in ("LEFT", "KEY3", "OK", "RIGHT"):
            return


def _choose_port(ui, knife):
    while True:
        ports = knife.list_ports()
        choices = ports + ["Refresh ports", "Manual path", "Exit"]
        choice = ui.menu("Select Serial", choices)
        if not choice or choice == "Exit":
            return None
        if choice == "Refresh ports":
            continue
        if choice == "Manual path":
            return ui.text_input("Serial path", "/dev/ttyACM0")
        return choice


def run():
    ui = UI()
    knife = USBArmyKnife()
    selected_ap = None
    selected_sta = None

    try:
        port = _choose_port(ui, knife)
        if not port:
            return
        ui.message("Connecting", port[:24], 0.8)
        if not knife.connect(port):
            ui.message("Connect failed", knife.last_error or "unknown", 3)
            return

        ui.message("Connected", f"{knife.port}@{knife.baud}", 1)

        while True:
            top = list(COMMAND_CATEGORIES.keys()) + ["Raw Command", "Reconnect", "Exit"]
            category = ui.menu("USB Army Knife", top)
            if not category or category == "Exit":
                break
            if category == "Reconnect":
                knife.close()
                port = _choose_port(ui, knife)
                if not port or not knife.connect(port):
                    ui.message("Connect failed", knife.last_error or "unknown", 3)
                    break
                ui.message("Connected", f"{knife.port}@{knife.baud}", 1)
                continue
            if category == "Raw Command":
                command = ui.text_input("Raw Command", "")
            else:
                command = ui.menu(category, COMMAND_CATEGORIES[category])
            if not command:
                continue

            if command == "ESP32M select -a 0" and selected_ap is not None:
                command = f"ESP32M select -a {selected_ap}"
            elif command == "ESP32M select -s 0" and selected_sta is not None:
                command = f"ESP32M select -s {selected_sta}"

            ui.message("Sending", command[:24], 0.5)
            output = knife.send(command)

            if command == "ESP32M list -a":
                indices = _parse_indices(output)
                if indices:
                    choice = ui.menu("Select AP idx", indices + ["Skip"])
                    if choice and choice != "Skip":
                        selected_ap = choice
                        output += knife.send(f"ESP32M select -a {choice}")
            elif command == "ESP32M list -s":
                indices = _parse_indices(output)
                if indices:
                    choice = ui.menu("Select STA idx", indices + ["Skip"])
                    if choice and choice != "Skip":
                        selected_sta = choice
                        output += knife.send(f"ESP32M select -s {choice}")

            _show_output(ui, command, output)
    finally:
        knife.close()
        ui.close()


if __name__ == "__main__":
    run()
