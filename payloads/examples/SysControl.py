#!/usr/bin/env python3
"""
KTOx Payload: System Core
Real System Utilities for Pi Operations
"""

import os
import time
import subprocess

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except:
    HAS_HW = False
    print("No hardware detected")

# ── CONFIG ─────────────────────────────────────────
W, H = 128, 128

PINS = {
    "UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,
    "OK":13,"KEY1":21,"KEY2":20,"KEY3":16
}

MENU = [
    "CPU / RAM",
    "Disk Usage",
    "Temperature",
    "Uptime",
    "IP Info",
    "Interfaces",
    "Restart Net",
    "Processes",
    "Kill Process",
    "List Files",
    "Reboot",
    "Shutdown",
    "Exit"
]

# ── GLOBALS ────────────────────────────────────────
LCD = None
_draw = None
_image = None
_font = None

menu_idx = 0

# ── INIT ───────────────────────────────────────────
def init():
    global LCD, _draw, _image, _font

    if HAS_HW:
        GPIO.setmode(GPIO.BCM)
        for p in PINS.values():
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        _image = Image.new("RGB",(W,H),"black")
        _draw = ImageDraw.Draw(_image)
        _font = ImageFont.load_default()

# ── UI ─────────────────────────────────────────────
def draw_menu():
    _draw.rectangle((0,0,W,H), fill="black")
    _draw.rectangle((0,0,W,16), fill=(80,0,0))
    _draw.text((3,2),"System Core", font=_font, fill="#FF4444")

    y = 18
    for i in range(6):
        idx = (menu_idx + i) % len(MENU)
        color = "#FF6666" if i == 0 else "#CCCCCC"
        _draw.text((3,y), MENU[idx][:18], font=_font, fill=color)
        y += 11

    _draw.text((3,116),"K1 Select K3 Exit", font=_font, fill="#FF8888")
    LCD.LCD_ShowImage(_image,0,0)

def draw_result(lines, title):
    _draw.rectangle((0,0,W,H), fill="black")
    _draw.rectangle((0,0,W,16), fill=(80,0,0))
    _draw.text((3,2), title[:18], font=_font, fill="#FF4444")

    y = 18
    for l in lines[:9]:
        _draw.text((3,y), l[:20], font=_font, fill="#FFCCCC")
        y += 11

    _draw.text((3,116),"K3 Back", font=_font, fill="#FF8888")
    LCD.LCD_ShowImage(_image,0,0)

# ── INPUT ──────────────────────────────────────────
def get_input(prompt="Input:"):
    return subprocess.getoutput(f"read -p '{prompt}' var; echo $var")

# ── UTILITIES ──────────────────────────────────────
def cpu_ram():
    cpu = subprocess.getoutput("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
    ram = subprocess.getoutput("free -h | grep Mem | awk '{print $3\"/\"$2}'")
    return [f"CPU:{cpu}%", f"RAM:{ram}"]

def disk_usage():
    out = subprocess.getoutput("df -h / | tail -1")
    return [out]

def temperature():
    temp = subprocess.getoutput("vcgencmd measure_temp")
    return [temp]

def uptime():
    return [subprocess.getoutput("uptime -p")]

def ip_info():
    return subprocess.getoutput("hostname -I").split()

def interfaces():
    return subprocess.getoutput("ip -brief addr").splitlines()[:8]

def restart_net():
    os.system("sudo systemctl restart NetworkManager")
    return ["Restarted"]

def processes():
    return subprocess.getoutput("ps aux --sort=-%mem | head -6").splitlines()[1:]

def kill_process():
    pid = input("PID: ")
    try:
        os.kill(int(pid), 9)
        return ["Killed"]
    except:
        return ["Fail"]

def list_files():
    return os.listdir(".")[:8]

def reboot():
    os.system("sudo reboot")

def shutdown():
    os.system("sudo shutdown now")

# ── MAIN ───────────────────────────────────────────
def main():
    global menu_idx

    init()

    while True:
        draw_menu()

        if HAS_HW:
            if GPIO.input(PINS["UP"]) == 0:
                menu_idx = (menu_idx - 1) % len(MENU)
                time.sleep(0.2)

            if GPIO.input(PINS["DOWN"]) == 0:
                menu_idx = (menu_idx + 1) % len(MENU)
                time.sleep(0.2)

            if GPIO.input(PINS["KEY1"]) == 0:
                item = MENU[menu_idx]

                if item == "CPU / RAM": lines = cpu_ram()
                elif item == "Disk Usage": lines = disk_usage()
                elif item == "Temperature": lines = temperature()
                elif item == "Uptime": lines = uptime()
                elif item == "IP Info": lines = ip_info()
                elif item == "Interfaces": lines = interfaces()
                elif item == "Restart Net": lines = restart_net()
                elif item == "Processes": lines = processes()
                elif item == "Kill Process": lines = kill_process()
                elif item == "List Files": lines = list_files()
                elif item == "Reboot": reboot()
                elif item == "Shutdown": shutdown()
                elif item == "Exit": break

                draw_result(lines, item)
                time.sleep(3)

            if GPIO.input(PINS["KEY3"]) == 0:
                break

        time.sleep(0.05)

    if HAS_HW:
        GPIO.cleanup()
        LCD.LCD_Clear()

if __name__ == "__main__":
    main()
