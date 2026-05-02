#!/usr/bin/env python3
"""USB Army Knife Controller payload (device-only build).
Designed for KTOx Pi hardware + 1.44" LCD + buttons.
"""
import os
import time
import serial
import serial.tools.list_ports
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

SERIAL_BAUD = 115200
PROMPT_PATTERNS = ("marauder>", "Marauder>", ">")

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

COMMAND_CATEGORIES = {
    "Scan / Sniff": ["scanap", "scansta", "scanall", "sniffbeacon", "sniffdeauth", "packetcount"],
    "Attacks": ["attack -t deauth -a", "attack -t deauth -s", "attack -t beacon -r", "attack -t probe"],
    "Targets": ["list -a", "list -s", "list -c", "select -a 0", "clearlist -a", "clearlist -s"],
    "System": ["help", "channel -s 6", "stopscan", "clear", "reboot"],
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
        self.last_error = None

    def list_ports(self):
        ports = list(serial.tools.list_ports.comports())
        out = [p.device for p in ports]
        for dev in ["/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyUSB1"]:
            if os.path.exists(dev) and dev not in out:
                out.append(dev)
        return out

    def connect(self, port):
        self.port = port
        try:
            self.ser = serial.Serial(port, SERIAL_BAUD, timeout=1)
            time.sleep(1.2)
            self.ser.write(b"\r\n")
            self.ser.reset_input_buffer()
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def send(self, cmd, timeout=12):
        if not self.ser or not self.ser.is_open:
            return ["[ERROR] serial not open"]
        self.ser.write((cmd + "\r\n").encode())
        out, buf = [], ""
        start = time.time()
        last = time.time()
        while time.time() - start < timeout:
            chunk = self.ser.read(256).decode(errors="ignore")
            if chunk:
                last = time.time()
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        out.append(line)
                        if any(p in line for p in PROMPT_PATTERNS):
                            return out
            else:
                if out and time.time() - last > 0.8:
                    return out
                time.sleep(0.03)
        if buf.strip():
            out.append(buf.strip())
        return out if out else ["[TIMEOUT]"]

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

    port = ui.menu("Select Serial", ports)
    if not port:
        GPIO.cleanup()
        return

    if not knife.connect(port):
        ui.message("Connect failed", knife.last_error or "unknown", 2)
        GPIO.cleanup()
        return

    ui.message("Connected", port, 1)

    while True:
        cat = ui.menu("USB Army Knife", list(COMMAND_CATEGORIES.keys()) + ["Exit"])
        if not cat or cat == "Exit":
            break
        cmd = ui.menu(cat, COMMAND_CATEGORIES[cat])
        if not cmd:
            continue
        ui.message("Sending", cmd[:20], 0.7)
        out = knife.send(cmd)
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
