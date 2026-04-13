#!/usr/bin/env python3
"""
KTOx Payload – WPA/WPA2 Cracker
"""

import sys
import os
import time
import signal
import subprocess

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

HANDSHAKE_FILE = ""
WORDLIST_FILE = ""
running = True

PINS = { "OK": 13, "KEY3": 16, "KEY1": 21, "KEY2": 20, "UP": 6, "DOWN": 19 }

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)

# ---------------- UI ----------------
def draw(lines):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)

    d.text((2, 2), "HASHCAT LIVE", font=FONT_TITLE, fill="#00FFAA")
    d.line((0, 16, 128, 16), fill="#00FFAA")

    y = 20
    for line in lines[:8]:
        d.text((2, y), line[:21], font=FONT, fill="white")
        y += 12

    LCD.LCD_ShowImage(img, 0, 0)

# ---------------- BUTTON ----------------
def get_button():
    for name, pin in PINS.items():
        if GPIO.input(pin) == 0:
            while GPIO.input(pin) == 0:
                time.sleep(0.05)
            return name
    return None

# ---------------- FILE SEARCH ----------------
def get_files(ftype):
    files = []

    if ftype == "Handshake":
        dirs = [os.path.join(KTOX_ROOT, "loot")]
        exts = (".pcap", ".cap", ".22000")
    else:
        dirs = [
            os.path.join(KTOX_ROOT, "wordlists"),
            "/usr/share/wordlists",
            "/usr/share/seclists"
        ]
        exts = (".txt", ".lst")

    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _, names in os.walk(d):
            for n in names:
                if n.endswith(exts):
                    files.append(os.path.join(root, n))

    return sorted(set(files))

# ---------------- SELECTOR ----------------
def select_file(ftype):
    files = get_files(ftype)
    if not files:
        draw(["No files found"])
        time.sleep(2)
        return None

    idx, offset = 0, 0
    visible = 6

    while running:
        view = files[offset:offset+visible]
        lines = [f"{ftype}:"]

        for i, f in enumerate(view):
            mark = ">" if offset+i == idx else " "
            lines.append(f"{mark} {os.path.basename(f)[:18]}")

        lines.append("OK=Select")
        draw(lines)

        btn = get_button()
        if btn == "KEY3":
            return None
        elif btn == "OK":
            return files[idx]
        elif btn == "UP":
            idx = (idx - 1) % len(files)
        elif btn == "DOWN":
            idx = (idx + 1) % len(files)

        if idx < offset:
            offset = idx
        elif idx >= offset + visible:
            offset = idx - visible + 1

# ---------------- HASHCAT LIVE ----------------
def run_attack():
    cmd = [
        "hashcat",
        "-m", "22000",
        HANDSHAKE_FILE,
        WORDLIST_FILE,
        "--status",
        "--status-timer", "2",
        "--force"
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    speed = "0 H/s"
    progress = "0%"
    eta = "--"
    found = None

    for line in process.stdout:
        line = line.strip()

        # Parse speed
        if "Speed." in line:
            speed = line.split(":")[-1].strip()

        # Parse progress
        elif "Progress." in line:
            try:
                pct = line.split("(")[-1].split(")")[0]
                progress = pct
            except:
                pass

        # Parse ETA
        elif "Time.Estimated." in line:
            eta = line.split(":")[-1].strip()

        # PASSWORD FOUND
        elif ":" in line and len(line.split(":")) > 1:
            found = line.split(":")[-1]

        draw([
            "Cracking...",
            f"SPD {speed[:14]}",
            f"PRG {progress}",
            f"ETA {eta[:14]}",
            f"PWD {found[:14] if found else '--'}",
            "",
            "KEY3=STOP"
        ])

        if get_button() == "KEY3":
            process.terminate()
            draw(["Stopped"])
            time.sleep(2)
            return

    draw(["Done", f"PWD: {found if found else 'Not found'}"])
    time.sleep(4)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    try:
        while running:
            draw([
                f"H:{os.path.basename(HANDSHAKE_FILE)[:16]}",
                f"W:{os.path.basename(WORDLIST_FILE)[:16]}",
                "",
                "OK=Start",
                "K1=Handshake",
                "K2=Wordlist",
                "K3=Exit"
            ])

            btn = get_button()

            if btn == "OK":
                if HANDSHAKE_FILE and WORDLIST_FILE:
                    run_attack()
                else:
                    draw(["Select files first"])
                    time.sleep(2)

            elif btn == "KEY1":
                f = select_file("Handshake")
                if f: HANDSHAKE_FILE = f

            elif btn == "KEY2":
                f = select_file("Wordlist")
                if f: WORDLIST_FILE = f

            elif btn == "KEY3":
                break

    finally:
        subprocess.run("killall hashcat", shell=True)
        LCD.LCD_Clear()
        GPIO.cleanup()
