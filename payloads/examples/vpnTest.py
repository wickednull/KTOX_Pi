#!/usr/bin/env python3
"""
KTOX Simple VPN Payload - Auto Connect + Show VPN IP
===================================================
One tap toggle. Dark red style.
"""

import os
import time
import subprocess

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

CONFIG_NAME = "ktox"   # filename without .conf → /etc/wireguard/ktox.conf

def init_hw():
    global LCD, _image, _draw, _font_sm
    if not HAS_HW:
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        for pin in [6,19,5,26,13,21,20,16]:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        _image = Image.new("RGB", (128, 128), "black")
        _draw = ImageDraw.Draw(_image)
        _font_sm = ImageFont.load_default()  # safe fallback
        try:
            _font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        except:
            pass
        return True
    except:
        return False

def push():
    if LCD and _image:
        LCD.LCD_ShowImage(_image, 0, 0)

def draw(lines, header="KTOX VPN"):
    _draw.rectangle((0,0,128,128), fill="#0A0000")
    _draw.rectangle((0,0,128,18), fill="#8B0000")
    _draw.text((5,3), header, fill="#FF3333")
    y = 25
    for line in lines:
        _draw.text((5, y), line[:20], fill="#FFBBBB")
        y += 12
    _draw.rectangle((0,117,128,128), fill="#220000")
    _draw.text((5,118), "K1=Toggle  K3=Exit", fill="#FF7777")
    push()

def get_vpn_ip():
    try:
        out = subprocess.getoutput(f"ip -4 addr show wg-{CONFIG_NAME} 2>/dev/null")
        for line in out.splitlines():
            if "inet " in line:
                return line.split()[1].split("/")[0]
        return None
    except:
        return None

def toggle_vpn():
    if get_vpn_ip():
        draw(["Disconnecting..."])
        subprocess.run(["sudo", "wg-quick", "down", CONFIG_NAME], capture_output=True)
        draw(["Disconnected"])
    else:
        draw(["Connecting..."])
        result = subprocess.run(["sudo", "wg-quick", "up", CONFIG_NAME], capture_output=True)
        ip = get_vpn_ip()
        if ip:
            draw([f"Connected ✓", f"VPN IP:", ip])
        else:
            draw(["Failed to connect", "Check config"])

# Main
if __name__ == "__main__":
    hw_ok = init_hw()

    # Auto connect on start
    if not get_vpn_ip():
        toggle_vpn()
    else:
        ip = get_vpn_ip()
        draw([f"Already Connected", f"VPN IP: {ip or 'Unknown'}"])

    held = {}
    while True:
        pressed = {name: GPIO.input(pin) == 0 for name, pin in {"KEY1":21, "KEY3":16}.items()}  # only need these two
        now = time.time()
        for n, down in pressed.items():
            if down and n not in held:
                held[n] = now
            elif not down:
                held.pop(n, None)

        if pressed.get("KEY3") and (now - held.get("KEY3", 0)) < 0.3:
            break

        if pressed.get("KEY1") and (now - held.get("KEY1", 0)) < 0.3:
            toggle_vpn()
            time.sleep(0.5)

        time.sleep(0.08)

    if HAS_HW:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    print("VPN payload closed.")