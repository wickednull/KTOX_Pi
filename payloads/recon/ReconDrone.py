#!/usr/bin/env python3
"""
KTOX Recon Drone 
======================================
Portable recon dashboard 
Dark red cyberpunk style
"""

import os
import sys
import time
import subprocess
import requests
import urllib.parse
from urllib.request import urlopen, Request

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not detected")

# ── Constants ────────────────────────────────────────────────────────────────
W, H = 128, 128
CHAR_SET = "abcdefghijklmnopqrstuvwxyz0123456789.-_@/"
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

VISIBLE_LINES = 7

MENU = [
    "1. Live Network Scan",
    "2. Target Profiler",
    "3. Nmap Quick Scan",
    "4. Sherlock Username",
    "5. theHarvester",
    "6. WiFi Nearby",
    "7. My Public IP",
    "8. DNS Lookup",
    "9. Reverse IP",
    "10. Mission Status",
    "11. Exit"
]

# ── Globals ──────────────────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font_sm = None
_font_md = None

RUNNING = True
_menu_idx = 0
_scroll_offset = 0
_current_target = "none"

# ── Hardware Init ────────────────────────────────────────────────────────────
def init_hw():
    global LCD, _image, _draw, _font_sm, _font_md
    if not HAS_HW:
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        for p in PINS.values():
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        _image = Image.new("RGB", (W, H), (10, 0, 0))
        _draw = ImageDraw.Draw(_image)

        for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/freefont/FreeMono.ttf"]:
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
    except Exception as e:
        print(f"HW error: {e}")
        return False

def push():
    if LCD and _image:
        LCD.LCD_ShowImage(_image, 0, 0)

# ── Dark Red Cyberpunk UI ────────────────────────────────────────────────────
def draw_menu():
    _draw.rectangle((0,0,W,H), fill="#0A0000")
    _draw.rectangle((0,0,W,17), fill="#8B0000")
    _draw.text((4,3), "KTOX RECON DRONE", font=_font_sm, fill=(231, 76, 60))

    start = _scroll_offset
    for i in range(VISIBLE_LINES):
        idx = start + i
        if idx >= len(MENU):
            break
        color = "#FF5555" if idx == _menu_idx else "#FFAAAA"
        _draw.text((5, 20 + i*11), MENU[idx][:22], font=_font_sm, fill=color)

    _draw.rectangle((0, H-12, W, H), fill="#220000")
    _draw.text((4, H-11), "UP/DN scroll  K1 launch", font=_font_sm, fill="#FF7777")
    push()

def draw_status(lines, title="STATUS"):
    _draw.rectangle((0,0,W,H), fill="#0A0000")
    _draw.rectangle((0,0,W,17), fill="#8B0000")
    _draw.text((4,3), title, font=_font_sm, fill=(231, 76, 60))

    y = 20
    for line in lines[:8]:
        _draw.text((4, y), line[:20], font=_font_sm, fill=(171, 178, 185))
        y += 12

    _draw.rectangle((0, H-12, W, H), fill="#220000")
    _draw.text((4, H-11), "K3=Back", font=_font_sm, fill="#FF7777")
    push()

# ── On-Screen Keyboard ───────────────────────────────────────────────────────
def on_screen_keyboard(prompt="Enter:"):
    input_text = ""
    char_idx = 0
    while RUNNING:
        _draw.rectangle((0,0,W,H), fill="#0A0000")
        _draw.rectangle((0,0,W,17), fill="#8B0000")
        _draw.text((4,3), prompt[:20], font=_font_sm, fill=(231, 76, 60))

        shown = input_text[-17:] if len(input_text) > 17 else input_text
        _draw.rectangle((0,19,W,36), fill="#220000")
        _draw.text((4,21), "> " + shown, font=_font_sm, fill="#FFCCCC")

        cs = CHAR_SET
        prev = cs[(char_idx-1)%len(cs)]
        curr = cs[char_idx]
        nxt = cs[(char_idx+1)%len(cs)]
        _draw.text((8,48), f"< {prev}  ", font=_font_md, fill="#884444")
        _draw.rectangle((52,45,78,63), fill="#AA0000")
        _draw.text((58,47), curr, font=_font_md, fill="#FF6666")
        _draw.text((82,48), f"  {nxt} >", font=_font_md, fill="#884444")

        hints = ["U/D=char OK=add", "L=del R=. K1=/", "K2=GO K3=Cancel"]
        y = 72
        for h in hints:
            _draw.text((4,y), h, font=_font_sm, fill="#FF9999")
            y += 11
        push()

        btn = None
        t0 = time.time()
        while not btn and RUNNING and time.time()-t0 < 60:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    btn = name
                    break
            time.sleep(0.04)

        if not btn or not RUNNING: return ""
        if btn == "KEY3": return ""
        if btn == "KEY2": return input_text.strip()
        if btn == "OK": input_text += CHAR_SET[char_idx]
        elif btn == "LEFT": input_text = input_text[:-1]
        elif btn == "RIGHT": input_text += "."
        elif btn == "KEY1": input_text += "/"
        elif btn == "UP": char_idx = (char_idx - 1 + len(CHAR_SET)) % len(CHAR_SET)
        elif btn == "DOWN": char_idx = (char_idx + 1) % len(CHAR_SET)
        time.sleep(0.1)
    return ""

# ── Awesome Recon Tools ──────────────────────────────────────────────────────
def live_network_scan():
    draw_status(["Scanning local net..."], "NETWORK DRONE")
    try:
        out = subprocess.getoutput("arp -a | head -8")
        lines = [line.strip()[:20] for line in out.splitlines() if line.strip()]
        return lines or ["No devices found"]
    except:
        return ["Scan failed"]

def target_profiler():
    global _current_target
    target = on_screen_keyboard("Target IP/Domain:")
    if not target:
        return ["Cancelled"]
    _current_target = target
    return [f"Target set:", target[:20], "Ready for tools"]

def nmap_quick_scan():
    target = on_screen_keyboard("Target:")
    if not target:
        return ["Cancelled"]
    draw_status(["Running nmap..."], "NMAP")
    try:
        out = subprocess.getoutput(f"nmap -F -T4 {target} 2>/dev/null | grep -E 'open|PORT' | head -6")
        lines = [line.strip()[:20] for line in out.splitlines() if line.strip()]
        return lines or ["No open ports"]
    except:
        return ["Nmap failed"]

def sherlock_hunt():
    username = on_screen_keyboard("Username:")
    if not username:
        return ["Cancelled"]
    draw_status(["Launching Sherlock..."], "SHERLOCK")
    try:
        cmd = ["sherlock", username, "--timeout", "15", "--print-found"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout.strip()
        if output:
            lines = [line[:20] for line in output.splitlines() if "http" in line]
            return lines[:7] or ["Found (check terminal)"]
        return ["No profiles found"]
    except:
        return ["Sherlock error"]

def theharvester_scan():
    domain = on_screen_keyboard("Domain:")
    if not domain:
        return ["Cancelled"]
    draw_status(["Harvesting..."], "theHarvester")
    try:
        out = subprocess.getoutput(f"theHarvester -d {domain} -b google -l 10 2>/dev/null | tail -15")
        lines = [line.strip()[:20] for line in out.splitlines() if line.strip() and "@" in line or "." in line]
        return lines[:7] or ["No results"]
    except:
        return ["theHarvester failed"]

def wifi_nearby():
    draw_status(["Scanning WiFi..."], "WIFI DRONE")
    try:
        out = subprocess.getoutput("iwlist wlan0 scan | grep ESSID | head -6")
        lines = [line.strip().replace('"','')[:20] for line in out.splitlines() if line.strip()]
        return lines or ["No networks found"]
    except:
        return ["WiFi scan failed (check wlan0)"]

def my_public_ip():
    try:
        ip = requests.get("https://api.ipify.org", timeout=8).text.strip()
        return [f"Public IP:", ip]
    except:
        return ["IP fetch failed"]

def google_dorks():
    return [
        "site:target.com inurl:admin",
        "intitle:index.of",
        "filetype:pdf password",
        "intext:confidential",
        "Use responsibly"
    ]

# ── Main Loop ────────────────────────────────────────────────────────────────
def main():
    global RUNNING, _menu_idx, _scroll_offset
    hw_ok = init_hw()
    draw_menu()

    held = {}
    while RUNNING:
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
            item = MENU[_menu_idx]
            draw_status(["Launching..."], item)

            if "Live Network" in item:     lines = live_network_scan()
            elif "Target Profiler" in item: lines = target_profiler()
            elif "Nmap" in item:           lines = nmap_quick_scan()
            elif "Sherlock" in item:       lines = sherlock_hunt()
            elif "theHarvester" in item:   lines = theharvester_scan()
            elif "WiFi Nearby" in item:    lines = wifi_nearby()
            elif "My Public IP" in item:   lines = my_public_ip()
            elif "Google Dorks" in item:   lines = google_dorks()
            elif "Reverse IP" in item:     lines = ["Not implemented yet"]
            elif "Geo IP" in item:         lines = ["Not implemented yet"]
            else:                          lines = ["Mission complete"]

            draw_status(lines, item)
            time.sleep(6)
            draw_menu()

        elif just_pressed("UP"):
            _menu_idx = (_menu_idx - 1) % len(MENU)
            if _menu_idx < _scroll_offset:
                _scroll_offset = _menu_idx
            elif _menu_idx >= _scroll_offset + VISIBLE_LINES:
                _scroll_offset = _menu_idx - VISIBLE_LINES + 1
            draw_menu()
            time.sleep(0.12)

        elif just_pressed("DOWN"):
            _menu_idx = (_menu_idx + 1) % len(MENU)
            if _menu_idx >= _scroll_offset + VISIBLE_LINES:
                _scroll_offset = _menu_idx - VISIBLE_LINES + 1
            draw_menu()
            time.sleep(0.12)

        time.sleep(0.05)

    RUNNING = False
    if HAS_HW:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    print("KTOX Recon Drone exited.")

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