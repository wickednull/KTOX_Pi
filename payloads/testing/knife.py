#!/usr/bin/env python3
"""USB Army Knife Controller payload (device-only build).
Designed for KTOx Pi hardware + 1.44" LCD + buttons.
"""
import os
import time
import glob
import subprocess
import serial
import serial.tools.list_ports
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

SERIAL_BAUD_CANDIDATES = (115200, 57600, 230400, 9600)
PROMPT_PATTERNS = ("uak>", "UAK>", "marauder>", "Marauder>")

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

COMMAND_CATEGORIES = {
    "Scan / Sniff": ["ESP32M help", "ESP32M scanap", "ESP32M scansta", "ESP32M sniffbeacon", "ESP32M sniffdeauth", "ESP32M packetcount"],
    "Attacks": ["ESP32M attack -t deauth -a", "ESP32M attack -t deauth -s", "ESP32M attack -t beacon -r", "ESP32M attack -t probe"],
    "Targets": ["ESP32M list -a", "ESP32M list -s", "ESP32M select -a 0", "ESP32M select -s 0", "ESP32M clearlist -a", "ESP32M clearlist -s"],
    "System": ["HELP", "SERIAL 115200", "SERIAL 57600", "ESP32M channel -s 6", "ESP32M stopscan", "LOGS", "REBOOT"],
}


def font(size=10):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


FONT = font(10)
FONT_SM = font(9)


class USBArmyKnife:
    def __init__(self):
        self.ser = None
        self.port = None
        self.baud = None
        self.last_error = None

    def _try_load_usb_serial_modules(self):
        for mod in ("cdc_acm", "cp210x", "ch341", "ftdi_sio", "usbserial"):
            subprocess.run(["modprobe", mod], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def list_ports(self):
        self._try_load_usb_serial_modules()
        out = []

        # 1) pyserial-discovered ports with descriptions
        for p in serial.tools.list_ports.comports():
            label = f"{p.device} | {(p.description or 'Unknown')[:32]}"
            if label not in out:
                out.append(label)

        # 2) stable by-id symlinks are best if present
        for dev in sorted(glob.glob("/dev/serial/by-id/*")):
            if os.path.exists(dev):
                label = f"{dev} | by-id"
                if label not in out:
                    out.append(label)

        # 3) fallback patterns commonly used by ESP32 bridges on Linux
        for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*", "/dev/ttyAMA*", "/dev/ttyS*", "/dev/ttyGS0"):
            for dev in sorted(glob.glob(pattern)):
                if os.path.exists(dev):
                    label = f"{dev} | detected"
                    if label not in out:
                        out.append(label)
        return out

    def _open(self, baud):
        self.ser = serial.Serial(
            self.port,
            baud,
            timeout=0.1,
            write_timeout=1,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        # Kick CDC ACM endpoints that need DTR/RTS asserted.
        try:
            self.ser.setDTR(False)
            self.ser.setRTS(False)
            time.sleep(0.05)
            self.ser.setDTR(True)
            self.ser.setRTS(True)
        except Exception:
            pass
        time.sleep(1.2)
        self.ser.write(b"\r\n")
        self.ser.write(b"\n")
        self.ser.write(b"HELP\r\n")
        self.ser.flush()
        time.sleep(0.25)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def _probe_cli(self):
        # UAK shell + Marauder wrapper probes from the wiki command model.
        self.ser.write(b"HELP\n")
        self.ser.write(b"ESP32M help\n")
        self.ser.flush()
        raw = ""
        start = time.time()
        while time.time() - start < 2.5:
            waiting = self.ser.in_waiting
            if waiting > 0:
                raw += self.ser.read(waiting).decode(errors="ignore")
            else:
                time.sleep(0.03)
        return raw

    def connect(self, port):
        # strip menu label suffix if present
        self.port = port.split(" | ")[0].strip()
        last_exc = None
        for baud in SERIAL_BAUD_CANDIDATES:
            keep_open = False
            try:
                self._open(baud)
                probe = self._probe_cli().lower()
                if "esp32m" in probe or "duckyscript" in probe or "usb army knife" in probe or "marauder" in probe or "command" in probe:
                    self.baud = baud
                    keep_open = True
                    return True
                # Some builds are quiet until first real command; keep candidate if port is open.
                if self.ser and self.ser.is_open:
                    self.baud = baud
                    keep_open = True
                    return True
            except Exception as e:
                last_exc = e
            finally:
                if self.ser and not keep_open:
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None
        self.last_error = f"No working baud on {self.port}. Last error: {last_exc}"
        return False

    def send(self, cmd, timeout=20):
        if not self.ser or not self.ser.is_open:
            return ["[ERROR] serial not open"]
        raw = ""
        # Try multiple line-endings because different builds parse differently.
        for payload in (cmd + "\r\n", cmd + "\n", cmd + "\r"):
            self.ser.write(payload.encode())
            self.ser.flush()
            start = time.time()
            last = 0
            while time.time() - start < timeout:
                chunk = self.ser.read(512).decode(errors="ignore")
                if chunk:
                    raw += chunk
                    last = time.time()
                else:
                    if raw and last and time.time() - last > 2.5:
                        break
                    time.sleep(0.03)
            if raw.strip():
                break
        lines = [ln.strip() for ln in raw.replace("\r", "\n").split("\n") if ln.strip()]
        if lines:
            return lines
        return [f"[TIMEOUT] no data from {self.port}@{self.baud}"]

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()


class UI:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.lcd = LCD_1in44.LCD()
        self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

    def button(self, timeout=0.15):
        end = time.time() + timeout
        while time.time() < end:
            for k, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    time.sleep(0.07)
                    return k
            time.sleep(0.01)
        return None

    def draw_lines(self, title, lines, sel=None, footer="OK=Select  K3=Back"):
        img = Image.new("RGB", (128, 128), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, 128, 14), fill=(139, 0, 0))
        d.text((4, 2), title[:20], font=FONT_SM, fill=(255, 255, 255))
        y = 18
        for i, line in enumerate(lines[:8]):
            text = ("> " if sel == i else "  ") + line
            d.text((2, y), text[:24], font=FONT_SM, fill=(200, 200, 200))
            y += 13
        d.rectangle((0, 116, 128, 128), fill=(34, 0, 0))
        d.text((2, 118), footer[:24], font=FONT_SM, fill=(140, 140, 140))
        self.lcd.LCD_ShowImage(img, 0, 0)

    def menu(self, title, items):
        idx = 0
        while True:
            start = max(0, min(idx, len(items) - 8))
            view = items[start:start+8]
            self.draw_lines(title, view, sel=idx-start)
            b = self.button()
            if b == "UP":
                idx = (idx - 1) % len(items)
            elif b == "DOWN":
                idx = (idx + 1) % len(items)
            elif b in ("OK", "RIGHT", "KEY1"):
                return items[idx]
            elif b in ("LEFT", "KEY3"):
                return None

    def message(self, title, body, seconds=1.5):
        self.draw_lines(title, [body])
        time.sleep(seconds)


def run():
    ui = UI()
    knife = USBArmyKnife()

    ports = knife.list_ports()
    if not ports:
        ui.message("USB Army Knife", "No serial ports found", 2)
        GPIO.cleanup()
        return

    port = ui.menu("Select Serial", ports + ["Refresh ports", "Exit"])
    if not port:
        GPIO.cleanup()
        return
    if port == "Exit":
        GPIO.cleanup()
        return
    if port == "Refresh ports":
        return run()

    if not knife.connect(port):
        ui.message("Connect failed", knife.last_error or "unknown", 2)
        GPIO.cleanup()
        return

    ui.message("Connected", f"{knife.port}@{knife.baud}", 1)

    selected_ap = None
    selected_sta = None

    while True:
        cat = ui.menu("USB Army Knife", list(COMMAND_CATEGORIES.keys()) + ["Exit"])
        if not cat or cat == "Exit":
            break
        cmd = ui.menu(cat, COMMAND_CATEGORIES[cat])
        if not cmd:
            continue
        if cmd == "ESP32M select -a 0" and selected_ap is not None:
            cmd = f"ESP32M select -a {selected_ap}"
        elif cmd == "ESP32M select -s 0" and selected_sta is not None:
            cmd = f"ESP32M select -s {selected_sta}"
        ui.message("Sending", cmd[:20], 0.7)
        out = knife.send(cmd)
        # Parse discovered indexes to make target selection easier later.
        if cmd == "ESP32M list -a":
            ap_indices = [ln.split()[0] for ln in out if ln and ln[0].isdigit()]
            if ap_indices:
                choice = ui.menu("Select AP idx", ap_indices + ["Skip"])
                if choice and choice != "Skip":
                    selected_ap = choice
                    knife.send(f"ESP32M select -a {choice}")
        elif cmd == "ESP32M list -s":
            sta_indices = [ln.split()[0] for ln in out if ln and ln[0].isdigit()]
            if sta_indices:
                choice = ui.menu("Select STA idx", sta_indices + ["Skip"])
                if choice and choice != "Skip":
                    selected_sta = choice
                    knife.send(f"ESP32M select -s {choice}")
        # output viewer
        idx = 0
        while True:
            page = out[idx:idx+8] if out else ["(no output)"]
            ui.draw_lines(cmd[:20], page, footer="UP/DN scroll K3 back")
            b = ui.button()
            if b == "UP":
                idx = max(0, idx-1)
            elif b == "DOWN":
                idx = min(max(0, len(out)-1), idx+1)
            elif b in ("LEFT", "KEY3", "OK", "RIGHT"):
                break

    knife.close()
    GPIO.cleanup()


if __name__ == "__main__":
    run()
