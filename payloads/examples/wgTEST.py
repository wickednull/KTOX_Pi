#!/usr/bin/env python3
"""
KTOX Simple VPN Payload - WireGuard
===================================
Auto-connect on start • Shows VPN IP • One-tap toggle
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
    print("Hardware not detected")

# ── Config ───────────────────────────────────────────────────────────────────
CONFIG_NAME = "ktox"          # Must match /etc/wireguard/ktox.conf
INTERFACE = f"wg-{CONFIG_NAME}"

# ── Hardware ─────────────────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font_sm = None
_font_md = None

def init_hw():
    global LCD, _image, _draw, _font_sm, _font_md
    if not HAS_HW:
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        pins = [6,19,5,26,13,21,20,16]
        for p in pins:
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        _image = Image.new("RGB", (128, 128), "black")
        _draw = ImageDraw.Draw(_image)

        for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/freefont/FreeMono.ttf"]:
            try:
                _font_sm = ImageFont.truetype(path, 9)
                _font_md = ImageFont.truetype(path, 11)
                break
            except:
                pass
        if not _font_sm:
            _font_sm = ImageFont.load_default()
            _font_md = _font_sm
        return True
    except:
        return False

def push():
    if LCD and _image:
        LCD.LCD_ShowImage(_image, 0, 0)

# ── Dark Red UI ──────────────────────────────────────────────────────────────
def draw_screen(lines, header="KTOX VPN"):
    _draw.rectangle((0,0,128,128), fill="#0A0000")
    _draw.rectangle((0,0,128,17), fill="#8B0000")
    _draw.text((4,3), header, font=_font_sm, fill="#FF3333")

    y = 22
    for line in lines[:8]:
        color = "#FF6666" if "VPN IP" in line or "Connected" in line else "#FFBBBB"
        _draw.text((4, y), line[:20], font=_font_sm, fill=color)
        y += 12

    _draw.rectangle((0, 116, 128, 128), fill="#220000")
    _draw.text((4, 118), "K1=Toggle  K3=Exit", font=_font_sm, fill="#FF7777")
    push()

# ── VPN Functions ────────────────────────────────────────────────────────────
def get_vpn_ip():
    try:
        out = subprocess.getoutput(f"ip -4 addr show {INTERFACE} 2>/dev/null")
        for line in out.splitlines():
            if "inet " in line:
                return line.split()[1].split('/')[0]
        return None
    except:
        return None

def is_connected():
    return get_vpn_ip() is not None

def connect_vpn():
    draw_screen(["Connecting..."])
    try:
        subprocess.run(["sudo", "wg-quick", "up", CONFIG_NAME], capture_output=True, timeout=15)
        time.sleep(2)
        ip = get_vpn_ip()
        if ip:
            draw_screen([f"Connected", f"VPN IP:", ip], "KTOX VPN")
            return True
        else:
            draw_screen(["Connect failed", "Check config"], "ERROR")
            return False
    except:
        draw_screen(["Failed to connect"], "ERROR")
        return False

def disconnect_vpn():
    draw_screen(["Disconnecting..."])
    try:
        subprocess.run(["sudo", "wg-quick", "down", CONFIG_NAME], capture_output=True, timeout=10)
        time.sleep(1)
        draw_screen(["Disconnected"], "KTOX VPN")
        return True
    except:
        draw_screen(["Disconnect failed"], "ERROR")
        return False

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    hw_ok = init_hw()
    if not hw_ok and HAS_HW:
        print("Hardware init failed")

    # Auto-connect on start
    if not is_connected():
        connect_vpn()
    else:
        ip = get_vpn_ip()
        draw_screen([f"Already Connected", f"VPN IP: {ip}"], "KTOX VPN")

    held = {}
    while True:
        pressed = {name: GPIO.input(pin) == 0 for name, pin in PINS.items()}
        now = time.time()
        for n, down in pressed.items():
            if down and n not in held:
                held[n] = now
            elif not down:
                held.pop(n, None)

        def just_pressed(n):
            return pressed.get(n) and (now - held.get(n, 0)) < 0.2

        if just_pressed("KEY3"):
            break

        if just_pressed("KEY1"):
            if is_connected():
                disconnect_vpn()
            else:
                connect_vpn()
            time.sleep(0.4)

        time.sleep(0.08)

    # Cleanup
    if HAS_HW:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    print("KTOX VPN payload closed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        if HAS_HW:
            try:
                GPIO.cleanup()
            except:
                pass