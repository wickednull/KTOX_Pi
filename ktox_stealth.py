#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_stealth.py — KTOx IoT Fingerprinter + Stealth Mode Engine

"""
KTOx Stealth & Fingerprint Engine
  · IoT Fingerprinter  — device type ID from OUI + ports + banners + HTTP
  · Stealth Mode       — rate limiting, jitter, MAC rotation, IDS evasion
"""

import os, sys, re, time, json, socket, threading, subprocess, random, struct
import logging
from datetime import datetime
from contextlib import contextmanager

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

try:
    from scapy.all import *
    from scapy.config import conf as sconf
    sconf.ipv6_enabled = False
except ImportError as e:
    print(f"ERROR: scapy — {e}"); sys.exit(1)

try:
    from rich.console  import Console
    from rich.panel    import Panel
    from rich.table    import Table
    from rich.rule     import Rule
    from rich.prompt   import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich          import box
    from rich.text     import Text
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

console  = Console(highlight=False)
loot_dir = "ktox_loot"

C_BLOOD  = "#C0392B"
C_RUST   = "#922B21"
C_EMBER  = "#E74C3C"
C_STEEL  = "#717D7E"
C_ASH    = "#ABB2B9"
C_WHITE  = "#F2F3F4"
C_DIM    = "#566573"
C_ORANGE = "#CA6F1E"
C_YELLOW = "#D4AC0D"
C_GOOD   = "#1E8449"

def tag(t, c=C_BLOOD): return f"[{c}]{t}[/{c}]"
def section(t):
    console.print()
    console.print(Rule(f"[bold {C_BLOOD}] {t} [/bold {C_BLOOD}]", style=C_RUST))
    console.print()

def _loot(event, data):
    os.makedirs(loot_dir, exist_ok=True)
    path  = os.path.join(loot_dir, "stealth.log")
    entry = {"ts": datetime.now().isoformat(), "event": event, "data": data}
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass


# ══════════════════════════════════════════════════════════════════════════════
# ── IoT FINGERPRINTER ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class IoTFingerprinter:
    """
    Multi-layer device fingerprinting:
    Layer 1: MAC OUI  → manufacturer + device family
    Layer 2: Port profile → service fingerprint
    Layer 3: Banner grab → firmware / software strings
    Layer 4: HTTP probe → embedded web UI detection
    Layer 5: MDNS/SSDP → service announcements

    Produces a confidence score + device classification for each host.
    """

    # ── OUI database ──────────────────────────────────────────────────────────
    OUI_DB = {
        # Raspberry Pi
        "B8:27:EB": ("Raspberry Pi Foundation", ["Single-board Computer", "IoT Hub"], 90),
        "DC:A6:32": ("Raspberry Pi Foundation", ["Single-board Computer", "IoT Hub"], 90),
        "E4:5F:01": ("Raspberry Pi Foundation", ["Single-board Computer"],            90),
        "28:CD:C1": ("Raspberry Pi Foundation", ["Single-board Computer"],            90),
        # Espressif ESP8266/ESP32
        "E8:DB:84": ("Espressif Systems",  ["ESP IoT Device"],  85),
        "A4:CF:12": ("Espressif Systems",  ["ESP IoT Device"],  85),
        "8C:AA:B5": ("Espressif Systems",  ["ESP IoT Device"],  85),
        "24:62:AB": ("Espressif Systems",  ["ESP IoT Device"],  85),
        "2C:F4:32": ("Espressif Systems",  ["ESP IoT Device"],  85),
        "84:CC:A8": ("Espressif Systems",  ["ESP IoT Device"],  85),
        "FC:F5:C4": ("Espressif Systems",  ["ESP IoT Device"],  85),
        "5C:CF:7F": ("Espressif Systems",  ["ESP8266 Module"],  85),
        # Smart Home
        "18:B4:30": ("Nest Labs",          ["Smart Thermostat", "IoT Sensor"], 95),
        "64:16:66": ("Nest Labs",          ["Smart Thermostat", "Camera"],     95),
        "00:17:88": ("Philips Hue",        ["Smart Lighting", "IoT Hub"],      95),
        "EC:B5:FA": ("Philips Hue",        ["Smart Lighting"],                 95),
        "AC:84:C6": ("Shelly",             ["Smart Plug", "IoT Switch"],       90),
        "60:01:94": ("TP-Link Kasa",       ["Smart Plug", "Smart Switch"],     90),
        # Google
        "00:1A:11": ("Google",             ["Chromecast", "Google Home"],      80),
        "54:60:09": ("Google",             ["Chromecast", "Nest Hub"],         80),
        "F4:F5:D8": ("Google",             ["Google Home", "Nest"],            80),
        "1C:F2:9A": ("Google",             ["Chromecast"],                     85),
        # Amazon
        "74:44:01": ("Amazon",             ["Echo", "Fire TV", "Ring"],        80),
        "FC:A6:67": ("Amazon",             ["Echo", "Fire Stick"],             80),
        "40:B4:CD": ("Amazon",             ["Echo"],                           85),
        "68:37:E9": ("Amazon",             ["Ring Doorbell"],                  90),
        "0C:47:C9": ("Amazon",             ["Ring Camera"],                    90),
        # Apple
        "B8:27:EB": ("Apple",              ["iPhone", "iPad"],                 70),
        "F0:18:98": ("Apple",              ["MacBook", "iMac"],                70),
        "A4:B1:97": ("Apple",              ["Apple TV", "HomePod"],            80),
        "3C:07:54": ("Apple",              ["iPhone", "Mac"],                  70),
        # Network gear
        "00:23:AE": ("Cisco",              ["Router", "Switch", "AP"],         80),
        "44:D9:E7": ("Ubiquiti",           ["Access Point", "Router"],         85),
        "68:72:51": ("Ubiquiti",           ["UniFi AP"],                       90),
        "80:2A:A8": ("Ubiquiti",           ["UniFi Device"],                   85),
        "C0:3F:0E": ("Netgear",            ["Router", "Switch"],               80),
        "20:4E:7F": ("Netgear",            ["Router"],                         80),
        "F4:F2:6D": ("TP-Link",            ["Router", "AP"],                   80),
        "50:C7:BF": ("TP-Link",            ["Router", "Smart Hub"],            75),
        "00:1A:2B": ("Asus",               ["Router", "Laptop"],               70),
        "90:E6:BA": ("Asus",               ["Router"],                         75),
        # Cameras / NVR
        "74:DA:EA": ("Edimax",             ["IP Camera", "WiFi Module"],       85),
        "B4:E6:2D": ("Liteon",             ["IP Camera", "DVR"],               80),
        "00:40:8C": ("Axis",               ["IP Camera"],                      90),
        "AC:CC:8E": ("Hikvision",          ["IP Camera", "NVR"],               90),
        "8C:E7:48": ("Hikvision",          ["IP Camera"],                      90),
        "28:57:BE": ("Dahua",              ["IP Camera", "DVR"],               90),
        "E0:50:8B": ("Dahua",              ["IP Camera"],                      90),
        # Printers
        "00:00:48": ("Epson",              ["Printer"],                        90),
        "00:26:AB": ("HP",                 ["Printer", "Workstation"],         80),
        "00:21:5A": ("HP",                 ["Printer"],                        85),
        "08:00:37": ("Xerox",              ["Printer"],                        90),
        # Medical / Industrial
        "00:E0:86": ("Bard Medical",       ["Medical Device"],                 95),
        "00:1C:C0": ("Welch Allyn",        ["Medical Device"],                 95),
        "00:D0:E0": ("Siemens",            ["Industrial Device", "PLC"],       90),
        # Virtual
        "00:0C:29": ("VMware",             ["Virtual Machine"],                99),
        "00:50:56": ("VMware",             ["Virtual Machine"],                99),
        "08:00:27": ("VirtualBox",         ["Virtual Machine"],                99),
        "00:15:5D": ("Microsoft Hyper-V",  ["Virtual Machine"],                99),
        "52:54:00": ("QEMU/KVM",           ["Virtual Machine"],                99),
        # Samsung (IoT)
        "F4:7B:5E": ("Samsung SmartThings",["IoT Hub", "Smart TV"],           85),
        "00:1F:C6": ("Samsung",            ["Smart TV", "Mobile"],             70),
        "8C:77:12": ("Samsung",            ["Smart TV", "Mobile"],             70),
        # Wemo / Belkin
        "94:10:3E": ("Belkin/Wemo",        ["Smart Plug", "Smart Switch"],     90),
        "EC:1A:59": ("Belkin/Wemo",        ["Smart Plug"],                     90),
    }

    # ── Port profiles ─────────────────────────────────────────────────────────
    PORT_PROFILES = {
        frozenset([80, 443]):               ("Web Server",          ["Server", "NAS", "Router"],   60),
        frozenset([22]):                    ("SSH Only",            ["Linux Server", "Raspberry Pi"], 50),
        frozenset([22, 80]):                ("SSH+Web",             ["Linux Server", "Router", "NAS"], 55),
        frozenset([22, 80, 443]):           ("SSH+HTTPS",           ["NAS", "Linux Server"],       55),
        frozenset([80, 8080]):              ("Dual HTTP",           ["IP Camera", "Router", "IoT Hub"], 65),
        frozenset([80, 554]):               ("HTTP+RTSP",           ["IP Camera", "DVR"],          80),
        frozenset([80, 554, 8554]):         ("RTSP Camera",         ["IP Camera"],                 90),
        frozenset([21]):                    ("FTP Server",          ["NAS", "Printer", "Camera"],  60),
        frozenset([21, 80]):                ("FTP+Web",             ["NAS", "Camera"],             65),
        frozenset([25, 587]):               ("Mail Server",         ["Email Server"],              85),
        frozenset([53]):                    ("DNS Server",          ["Router", "DNS Server"],      80),
        frozenset([53, 80]):                ("DNS+Web",             ["Router", "Pi-hole"],         75),
        frozenset([445, 139]):              ("SMB/Samba",           ["Windows PC", "NAS"],         80),
        frozenset([445, 139, 80]):          ("SMB+Web",             ["Windows Server", "NAS"],     75),
        frozenset([3389]):                  ("RDP",                 ["Windows PC", "Server"],      90),
        frozenset([5900]):                  ("VNC",                 ["Desktop", "Raspberry Pi"],   75),
        frozenset([1883]):                  ("MQTT Broker",         ["IoT Hub", "Smart Home"],     90),
        frozenset([1883, 8883]):            ("MQTT+TLS",            ["IoT Hub"],                   90),
        frozenset([5353]):                  ("mDNS",                ["Apple Device", "IoT"],       60),
        frozenset([9100]):                  ("RAW Print",           ["Printer"],                   95),
        frozenset([515, 9100]):             ("LPD+RAW",             ["Printer"],                   95),
        frozenset([8883, 443]):             ("IoT Cloud",           ["IoT Device"],                75),
        frozenset([4840]):                  ("OPC-UA",              ["Industrial PLC", "SCADA"],   95),
        frozenset([102]):                   ("S7comm",              ["Siemens PLC"],               99),
        frozenset([502]):                   ("Modbus",              ["PLC", "Industrial Device"],  95),
        frozenset([20000]):                 ("DNP3",                ["SCADA", "Industrial"],       95),
        frozenset([6881, 6882, 6883]):      ("BitTorrent",          ["Desktop PC"],                80),
        frozenset([32400]):                 ("Plex Media",          ["Media Server", "NAS"],       95),
        frozenset([8123]):                  ("Home Assistant",      ["IoT Hub", "Smart Home"],     98),
        frozenset([1880]):                  ("Node-RED",            ["IoT Hub", "Raspberry Pi"],   95),
        frozenset([3000]):                  ("Grafana/Dev",         ["IoT Hub", "Server"],         80),
        frozenset([5000]):                  ("Synology DSM",        ["NAS"],                       90),
        frozenset([5001]):                  ("Synology HTTPS",      ["NAS"],                       90),
        frozenset([6052]):                  ("ESPHome",             ["ESP IoT Device"],            98),
        frozenset([6789]):                  ("UniFi Inform",        ["Ubiquiti Device"],           95),
        frozenset([8088, 8089]):            ("Unifi Controller",    ["Ubiquiti Controller"],       90),
    }

    # ── Banner signatures ─────────────────────────────────────────────────────
    BANNER_SIGS = [
        (re.compile(r"raspberry\s?pi|raspbian|libreelec",         re.I), "Raspberry Pi",         90),
        (re.compile(r"esp8266|esp32|espressif|esphome",           re.I), "ESP IoT Device",        90),
        (re.compile(r"hikvision|dvr|nvr|ipc",                     re.I), "Hikvision Camera",      85),
        (re.compile(r"dahua\s?technology",                        re.I), "Dahua Camera",          85),
        (re.compile(r"axis\s?communications",                     re.I), "Axis Camera",           90),
        (re.compile(r"synology",                                  re.I), "Synology NAS",          95),
        (re.compile(r"qnap",                                      re.I), "QNAP NAS",              95),
        (re.compile(r"home.?assistant|hass\.io|hassio",           re.I), "Home Assistant Hub",    98),
        (re.compile(r"node.?red",                                 re.I), "Node-RED IoT",          95),
        (re.compile(r"openwrt|dd-wrt|tomato|merlin",              re.I), "Custom Router",         85),
        (re.compile(r"mikrotik|routeros",                         re.I), "MikroTik Router",       90),
        (re.compile(r"ubnt|ubiquiti|unifi|airmax",                re.I), "Ubiquiti Device",       90),
        (re.compile(r"hp.*jetdirect|hp.*laserjet|hp.*inkjet",     re.I), "HP Printer",            90),
        (re.compile(r"epson.*printer|epson.*tm",                  re.I), "Epson Printer",         90),
        (re.compile(r"cisco\s?ios|cisco\s?adaptive",              re.I), "Cisco Device",          85),
        (re.compile(r"plex\s?media\s?server",                     re.I), "Plex Media Server",     95),
        (re.compile(r"kodi|xbmc",                                 re.I), "Kodi Media Center",     90),
        (re.compile(r"pi-?hole",                                  re.I), "Pi-hole DNS",           98),
        (re.compile(r"openelec|libreelec|osmc",                   re.I), "Media Center OS",       90),
        (re.compile(r"Arduino|teensy",                            re.I), "Arduino/Microcontroller",85),
        (re.compile(r"modbus|simatic|step\s?7",                   re.I), "Industrial PLC",        95),
        (re.compile(r"mqtt|mosquitto|emqx",                       re.I), "MQTT Broker",           85),
        (re.compile(r"isc\s?dhcp|dnsmasq",                       re.I), "Network Server",        70),
        (re.compile(r"nginx|apache|lighttpd|caddy",               re.I), "Web Server",            60),
        (re.compile(r"IIS|Microsoft-IIS",                         re.I), "Windows IIS Server",    85),
        (re.compile(r"OpenSSH.*ubuntu|OpenSSH.*debian|OpenSSH.*kali", re.I), "Linux Server",     70),
        (re.compile(r"Samsung\s?Smart|Tizen",                     re.I), "Samsung Smart TV",      90),
        (re.compile(r"Roku",                                      re.I), "Roku Streaming",        95),
        (re.compile(r"ring\s?(doorbell|camera)|ring\.com",        re.I), "Ring Device",           95),
        (re.compile(r"nest\s?(cam|hello|thermostat)",             re.I), "Nest Device",           95),
        (re.compile(r"tp-?link|tplink|archer|deco",               re.I), "TP-Link Device",        80),
    ]

    # ── HTTP path probes ──────────────────────────────────────────────────────
    HTTP_PROBES = [
        ("/",                "General web UI"),
        ("/admin",           "Admin panel"),
        ("/cgi-bin/main.cgi","Hikvision Camera"),
        ("/doc/page/login.asp","Hikvision DVR"),
        ("/ISAPI/",          "Hikvision ISAPI"),
        ("/web/",            "Dahua Camera"),
        ("/setup.cgi",       "Netgear Router"),
        ("/webadmin/",       "Router Admin"),
        ("/luci/",           "OpenWRT"),
        ("/cgi-bin/luci",    "OpenWRT/LEDE"),
        ("/syno/",           "Synology DSM"),
        ("/webapi/",         "Synology API"),
        ("/lovelace",        "Home Assistant"),
        ("/api/states",      "Home Assistant API"),
        ("/red/",            "Node-RED"),
        ("/printer/",        "Printer Admin"),
        ("/hp/device/",      "HP Printer"),
        ("/ipp/",            "IPP Printer"),
        ("/canon/",          "Canon Printer"),
        ("/epson/",          "Epson Printer"),
        ("/plex/",           "Plex Server"),
        ("/web/index.html",  "Plex Web"),
        ("/metrics",         "Prometheus/Grafana"),
        ("/api",             "Generic API"),
    ]

    def __init__(self, timeout=2):
        self.timeout  = timeout
        self._results = {}

    def _oui_lookup(self, mac):
        if not mac or mac == "N/A":
            return None, [], 0
        prefix = mac.upper()[:8]
        row = self.OUI_DB.get(prefix)
        if row:
            return row[0], row[1], row[2]
        # Try 6-char
        prefix6 = mac.upper()[:5] + "0"
        row = self.OUI_DB.get(prefix6)
        if row:
            return row[0], row[1], row[2] - 10
        return "Unknown", [], 0

    def _port_scan(self, ip, ports=None):
        """Fast TCP connect scan on common ports."""
        if ports is None:
            ports = [
                21, 22, 23, 25, 53, 80, 110, 139, 143, 443,
                445, 502, 515, 554, 587, 1883, 1880, 3000,
                3389, 4840, 5000, 5001, 5353, 5900, 6052,
                6789, 8080, 8088, 8089, 8123, 8554, 8883,
                9100, 32400
            ]
        open_ports = []
        for port in ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self.timeout * 0.3)
                if s.connect_ex((ip, port)) == 0:
                    open_ports.append(port)
                s.close()
            except: pass
        return open_ports

    def _grab_banner(self, ip, port):
        """Grab service banner from a port."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((ip, port))

            # Send probes for common services
            if port in (80, 8080, 8081, 8088, 8123, 1880, 3000, 5000):
                s.sendall(
                    f"GET / HTTP/1.0\r\nHost: {ip}\r\nUser-Agent: Mozilla/5.0\r\n\r\n"
                    .encode()
                )
            elif port == 21:
                pass  # FTP sends banner on connect
            elif port == 22:
                pass  # SSH sends banner on connect
            elif port == 25:
                s.sendall(b"EHLO ktox\r\n")
            elif port == 554:
                s.sendall(b"OPTIONS * RTSP/1.0\r\nCSeq: 1\r\n\r\n")
            else:
                s.sendall(b"\r\n")

            banner = s.recv(2048).decode("utf-8", errors="ignore")
            s.close()
            return banner.strip()
        except:
            return ""

    def _http_probe(self, ip, port=80):
        """Probe HTTP paths and collect signatures from responses."""
        signatures = []
        try:
            for path, label in self.HTTP_PROBES[:8]:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(self.timeout * 0.5)
                    s.connect((ip, port))
                    s.sendall(
                        f"GET {path} HTTP/1.0\r\nHost: {ip}\r\n\r\n".encode()
                    )
                    resp = s.recv(4096).decode("utf-8", errors="ignore")
                    s.close()
                    if resp and ("200" in resp[:20] or "301" in resp[:20]):
                        signatures.append((path, label, resp[:500]))
                except: pass
        except: pass
        return signatures

    def _match_banners(self, text):
        """Match banner text against signature database."""
        matches = []
        for pattern, device_type, confidence in self.BANNER_SIGS:
            if pattern.search(text):
                matches.append((device_type, confidence))
        return matches

    def _port_profile_match(self, open_ports):
        """Match open port set against known device profiles."""
        port_set = frozenset(open_ports)
        best_match = None
        best_score = 0
        best_size  = 0

        for profile_ports, (service, device_types, confidence) in self.PORT_PROFILES.items():
            overlap = len(profile_ports & port_set)
            if overlap > 0:
                score = (overlap / max(len(profile_ports), 1)) * confidence
                if score > best_score or (score == best_score and overlap > best_size):
                    best_score  = score
                    best_match  = (service, device_types, int(confidence))
                    best_size   = overlap

        return best_match

    def fingerprint(self, ip, mac=""):
        """
        Full fingerprint of a single host.
        Returns a dict with device type, confidence, evidence.
        """
        result = {
            "ip":           ip,
            "mac":          mac,
            "manufacturer": "Unknown",
            "device_types": [],
            "confidence":   0,
            "open_ports":   [],
            "banners":      {},
            "http_paths":   [],
            "evidence":     [],
        }

        # Layer 1: OUI
        manufacturer, oui_types, oui_conf = self._oui_lookup(mac)
        result["manufacturer"] = manufacturer
        if oui_types:
            result["device_types"] = oui_types
            result["confidence"]   = oui_conf
            result["evidence"].append(f"OUI {mac[:8]} → {manufacturer} ({oui_conf}%)")

        # Layer 2: Port scan
        open_ports = self._port_scan(ip)
        result["open_ports"] = open_ports

        if open_ports:
            result["evidence"].append(f"Open ports: {open_ports}")
            port_match = self._port_profile_match(open_ports)
            if port_match:
                service, port_types, port_conf = port_match
                result["evidence"].append(
                    f"Port profile '{service}' → {port_types} ({port_conf}%)"
                )
                # Merge with OUI result
                if port_conf > result["confidence"]:
                    result["device_types"] = port_types
                    result["confidence"]   = port_conf
                elif port_conf == result["confidence"] and port_types:
                    result["device_types"] = list(
                        dict.fromkeys(result["device_types"] + port_types)
                    )[:3]

        # Layer 3: Banner grabbing
        probe_ports = [p for p in open_ports if p in
                       (21, 22, 23, 25, 80, 443, 554, 1883, 8080, 8123, 1880)]
        all_banners = ""
        for port in probe_ports[:4]:
            banner = self._grab_banner(ip, port)
            if banner:
                result["banners"][port] = banner[:200]
                all_banners += banner + " "

        if all_banners:
            banner_matches = self._match_banners(all_banners)
            for device_type, confidence in banner_matches:
                result["evidence"].append(
                    f"Banner match: {device_type} ({confidence}%)"
                )
                if confidence > result["confidence"]:
                    result["device_types"] = [device_type]
                    result["confidence"]   = confidence

        # Layer 4: HTTP probe (if port 80 or 8080 open)
        for http_port in [p for p in open_ports if p in (80, 8080, 8123, 1880, 5000)]:
            http_sigs = self._http_probe(ip, http_port)
            for path, label, resp in http_sigs:
                result["http_paths"].append(path)
                banner_matches = self._match_banners(resp)
                for device_type, confidence in banner_matches:
                    result["evidence"].append(
                        f"HTTP {path} → {device_type} ({confidence}%)"
                    )
                    if confidence > result["confidence"]:
                        result["device_types"] = [device_type]
                        result["confidence"]   = confidence
            if http_sigs:
                break

        # Clamp confidence
        result["confidence"] = min(result["confidence"], 99)
        return result

    def _confidence_color(self, conf):
        if conf >= 90: return C_EMBER
        if conf >= 70: return C_YELLOW
        if conf >= 50: return C_STEEL
        return C_DIM

    def _device_icon(self, types):
        t = " ".join(types).lower()
        if "camera" in t or "dvr" in t or "nvr" in t: return "📷"
        if "printer" in t:                              return "🖨"
        if "router" in t or "ap" in t:                 return "📡"
        if "nas" in t:                                  return "💾"
        if "raspberry" in t or "esp" in t:             return "🍓"
        if "smart" in t or "iot" in t or "hub" in t:   return "🏠"
        if "plc" in t or "scada" in t or "industrial" in t: return "⚙"
        if "virtual" in t:                             return "📦"
        if "server" in t:                              return "🖥"
        if "phone" in t or "iphone" in t or "android" in t: return "📱"
        if "tv" in t or "media" in t or "plex" in t:   return "📺"
        if "windows" in t or "pc" in t or "desktop" in t:   return "🪟"
        if "medical" in t:                             return "🏥"
        if "printer" in t:                             return "🖨"
        return "❓"

    def scan_network(self, hosts):
        """
        Fingerprint a list of hosts. Shows live progress.
        hosts: list of (ip, mac) tuples
        """
        section("IoT FINGERPRINTER")
        results = []

        with Progress(
            SpinnerColumn(style=C_BLOOD),
            TextColumn("[{task.description}]", style=C_STEEL),
            BarColumn(bar_width=30, style=C_RUST, complete_style=C_BLOOD),
            TaskProgressColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(
                f"Fingerprinting {len(hosts)} host(s)...",
                total=len(hosts)
            )

            for ip, mac in hosts:
                progress.update(task, description=f"Probing {ip}")
                result = self.fingerprint(ip, mac)
                results.append(result)
                progress.advance(task)

        # Render results table
        table = Table(
            box=box.SIMPLE_HEAD,
            border_style=C_RUST,
            header_style=f"bold {C_BLOOD}",
            show_lines=True,
            padding=(0, 1),
        )
        table.add_column("IP",           style=C_WHITE,  no_wrap=True, width=15)
        table.add_column("MAC",          style=C_STEEL,  no_wrap=True, width=17)
        table.add_column("MANUFACTURER", style=C_ASH,    no_wrap=True, width=18)
        table.add_column("DEVICE TYPE",  style=C_WHITE,  no_wrap=True, width=24)
        table.add_column("PORTS",        style=C_DIM,    no_wrap=True, width=20)
        table.add_column("CONF",         style=C_YELLOW, no_wrap=True, width=6)

        for r in results:
            conf  = r["confidence"]
            color = self._confidence_color(conf)
            icon  = self._device_icon(r["device_types"])
            dtype = f"{icon} " + ", ".join(r["device_types"][:2]) if r["device_types"] else "—"
            ports = ", ".join(str(p) for p in r["open_ports"][:6])
            if len(r["open_ports"]) > 6:
                ports += f" +{len(r['open_ports'])-6}"

            table.add_row(
                r["ip"],
                r["mac"] or "—",
                r["manufacturer"][:17],
                dtype[:23],
                ports or "—",
                f"[{color}]{conf}%[/{color}]",
            )

        console.print(table)

        # Detailed evidence panels for high-confidence finds
        interesting = [r for r in results if r["confidence"] >= 75]
        if interesting:
            console.print(
                f"\n  [{C_STEEL}]High-confidence findings ({len(interesting)}):[/{C_STEEL}]"
            )
            for r in interesting[:5]:
                icon  = self._device_icon(r["device_types"])
                dtype = ", ".join(r["device_types"][:2])
                ev    = "\n".join(f"    [{C_DIM}]· {e}[/{C_DIM}]"
                                  for e in r["evidence"][:4])
                console.print(Panel(
                    f"  {tag('Device:', C_BLOOD)}  [{C_WHITE}]{icon} {dtype}[/{C_WHITE}]\n"
                    f"  {tag('Maker:',  C_STEEL)}  [{C_ASH}]{r['manufacturer']}[/{C_ASH}]\n"
                    f"  {tag('Ports:',  C_STEEL)}  [{C_DIM}]{r['open_ports']}[/{C_DIM}]\n\n"
                    f"{ev}",
                    border_style=C_RUST,
                    title=f"[bold {C_BLOOD}]◈ {r['ip']}  {r['confidence']}% confidence[/bold {C_BLOOD}]",
                    padding=(1, 2),
                ))

        # Save
        os.makedirs(loot_dir, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(loot_dir, f"fingerprint_{ts}.json")
        with open(path, "w") as f:
            json.dump(results, f, indent=2)
        console.print(f"\n  [{C_GOOD}]✔ Results saved → {path}[/{C_GOOD}]")
        _loot("FINGERPRINT_COMPLETE", {"count": len(results), "file": path})

        return results


# ══════════════════════════════════════════════════════════════════════════════
# ── STEALTH MODE ENGINE ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class StealthMode:
    """
    IDS/IPS evasion engine for KTOx attack modules.

    Features:
    · Rate limiting        — cap packets per second globally
    · Jitter               — randomised inter-packet delays
    · MAC rotation         — cycle through random MACs during attacks
    · Fragmentation        — split packets to evade signature detection
    · Timing profiles      — preset evasion levels (ghost/ninja/normal)
    · Idle insertion       — inject benign traffic between attack packets
    · Interface cycling    — rotate interface MAC at configurable intervals
    """

    PROFILES = {
        "ghost": {
            "description": "Maximum stealth — very slow, high jitter, MAC rotation every 5 min",
            "ppm_cap":     6,        # packets per minute max
            "jitter_min":  3.0,      # min extra delay seconds
            "jitter_max":  12.0,     # max extra delay seconds
            "mac_rotate":  300,      # rotate MAC every N seconds
            "idle_inject": True,     # inject benign packets
            "idle_rate":   0.3,      # benign packets per second
        },
        "ninja": {
            "description": "Balanced — moderate rate, jitter, occasional MAC rotation",
            "ppm_cap":     30,
            "jitter_min":  0.5,
            "jitter_max":  3.0,
            "mac_rotate":  600,
            "idle_inject": False,
            "idle_rate":   0,
        },
        "normal": {
            "description": "Minimal evasion — slight jitter only",
            "ppm_cap":     120,
            "jitter_min":  0.05,
            "jitter_max":  0.3,
            "mac_rotate":  0,        # no rotation
            "idle_inject": False,
            "idle_rate":   0,
        },
        "custom": {
            "description": "User-configured",
            "ppm_cap":     60,
            "jitter_min":  0.1,
            "jitter_max":  1.0,
            "mac_rotate":  0,
            "idle_inject": False,
            "idle_rate":   0,
        },
    }

    def __init__(self, iface, profile="ninja"):
        self.iface    = iface
        self.profile  = self.PROFILES.get(profile, self.PROFILES["ninja"]).copy()
        self._mac_lock       = threading.Lock()
        self._current_mac    = self._get_current_mac()
        self._original_mac   = self._current_mac
        self._packet_count   = 0
        self._window_start   = time.time()
        self._rotate_thread  = None
        self._idle_thread    = None
        self._active         = False
        self._stop           = threading.Event()

    def _get_current_mac(self):
        try:
            return get_if_hwaddr(self.iface)
        except:
            return "00:00:00:00:00:00"

    def _random_mac(self):
        """Generate a locally administered random MAC."""
        return "02:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}".format(
            *[random.randint(0, 255) for _ in range(5)]
        )

    def _set_mac(self, mac):
        """Change interface MAC address."""
        try:
            subprocess.run(
                ["ip", "link", "set", self.iface, "down"],
                capture_output=True, check=True
            )
            subprocess.run(
                ["ip", "link", "set", self.iface, "address", mac],
                capture_output=True, check=True
            )
            subprocess.run(
                ["ip", "link", "set", self.iface, "up"],
                capture_output=True, check=True
            )
            with self._mac_lock:
                self._current_mac = mac
            return True
        except:
            return False

    def _mac_rotation_loop(self):
        """Periodically rotate MAC address."""
        interval = self.profile["mac_rotate"]
        while not self._stop.is_set():
            self._stop.wait(interval)
            if self._stop.is_set(): break
            new_mac = self._random_mac()
            if self._set_mac(new_mac):
                console.print(
                    f"  [{C_YELLOW}]⟳ MAC rotated → {new_mac}[/{C_YELLOW}]  "
                    f"[{C_DIM}]{datetime.now().strftime('%H:%M:%S')}[/{C_DIM}]"
                )
                _loot("MAC_ROTATED", {"new_mac": new_mac, "iface": self.iface})

    def _idle_injection_loop(self, gateway_ip):
        """Inject benign ARP request traffic to mask attack packets."""
        interval = 1.0 / max(self.profile["idle_rate"], 0.01)
        while not self._stop.is_set():
            try:
                # Send benign ARP WHO-HAS for a random subnet IP
                fake_ip = ".".join(
                    gateway_ip.split(".")[:3] +
                    [str(random.randint(1, 254))]
                )
                sendp(
                    Ether(dst="ff:ff:ff:ff:ff:ff") /
                    ARP(op=1, pdst=fake_ip),
                    verbose=False, iface=self.iface
                )
            except: pass
            self._stop.wait(interval)

    def jitter(self):
        """Sleep for a random jitter delay."""
        delay = random.uniform(
            self.profile["jitter_min"],
            self.profile["jitter_max"]
        )
        time.sleep(delay)

    def rate_check(self):
        """
        Enforce packets-per-minute cap.
        Blocks if cap is reached until window resets.
        """
        now      = time.time()
        elapsed  = now - self._window_start
        cap      = self.profile["ppm_cap"]

        if elapsed >= 60.0:
            self._packet_count = 0
            self._window_start = now

        if self._packet_count >= cap:
            wait = 60.0 - elapsed
            if wait > 0:
                console.print(
                    f"  [{C_DIM}]⏸ Rate cap reached ({cap} ppm) — "
                    f"waiting {wait:.1f}s[/{C_DIM}]",
                    end="\r"
                )
                time.sleep(wait)
                self._packet_count = 0
                self._window_start = time.time()

        self._packet_count += 1

    @contextmanager
    def stealth_send(self, gateway_ip=None):
        """
        Context manager for a stealth-wrapped send operation.
        Applies rate check + jitter before each packet.

        Usage:
            with stealth.stealth_send():
                spoof.sendPacket(...)
        """
        self.rate_check()
        self.jitter()
        yield
        # optional: post-send delay
        if random.random() < 0.1:  # 10% chance of extra pause
            time.sleep(random.uniform(0.1, 0.5))

    def start(self, gateway_ip=None):
        """Start stealth engine background threads."""
        self._active = True
        self._stop.clear()

        if self.profile["mac_rotate"] > 0:
            self._rotate_thread = threading.Thread(
                target=self._mac_rotation_loop, daemon=True
            )
            self._rotate_thread.start()

        if self.profile["idle_inject"] and gateway_ip:
            self._idle_thread = threading.Thread(
                target=self._idle_injection_loop,
                args=(gateway_ip,), daemon=True
            )
            self._idle_thread.start()

        console.print(Panel(
            f"  {tag('Profile:',    C_BLOOD)}    [{C_WHITE}]{self.profile.get('description','')}[/{C_WHITE}]\n"
            f"  {tag('Rate cap:',   C_STEEL)}    [{C_ASH}]{self.profile['ppm_cap']} pkt/min[/{C_ASH}]\n"
            f"  {tag('Jitter:',     C_STEEL)}    [{C_ASH}]{self.profile['jitter_min']}s – "
            f"{self.profile['jitter_max']}s[/{C_ASH}]\n"
            f"  {tag('MAC rotate:', C_STEEL)}    [{C_ASH}]"
            f"{'every ' + str(self.profile['mac_rotate']) + 's' if self.profile['mac_rotate'] else 'disabled'}"
            f"[/{C_ASH}]\n"
            f"  {tag('Idle inject:',C_STEEL)}    [{C_ASH}]"
            f"{'enabled' if self.profile['idle_inject'] else 'disabled'}[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ STEALTH MODE ACTIVE[/bold {C_BLOOD}]",
            padding=(1, 2),
        ))

    def stop(self):
        """Stop stealth engine and restore original MAC."""
        self._stop.set()
        self._active = False

        if self._original_mac and self._original_mac != self._current_mac:
            console.print(
                f"  [{C_STEEL}]Restoring original MAC → {self._original_mac}[/{C_STEEL}]"
            )
            self._set_mac(self._original_mac)
            console.print(f"  [{C_GOOD}]✔ MAC restored.[/{C_GOOD}]")

    def configure_custom(self):
        """Interactive configuration for custom profile."""
        section("STEALTH MODE — CUSTOM CONFIGURATION")

        console.print(f"  [{C_STEEL}]Configure each parameter:[/{C_STEEL}]\n")

        try:
            ppm = int(Prompt.ask(
                f"  [{C_BLOOD}]Max packets/min [{C_DIM}]1–999[/{C_DIM}][/{C_BLOOD}]",
                default="30"
            ))
            jmin = float(Prompt.ask(
                f"  [{C_BLOOD}]Min jitter seconds[/{C_BLOOD}]", default="0.2"
            ))
            jmax = float(Prompt.ask(
                f"  [{C_BLOOD}]Max jitter seconds[/{C_BLOOD}]", default="2.0"
            ))
            rotate = int(Prompt.ask(
                f"  [{C_BLOOD}]MAC rotation interval seconds [{C_DIM}]0=disabled[/{C_DIM}][/{C_BLOOD}]",
                default="0"
            ))
            idle = Confirm.ask(
                f"  [{C_BLOOD}]Inject idle benign traffic?[/{C_BLOOD}]",
                default=False
            )
        except KeyboardInterrupt:
            return

        self.profile.update({
            "description": "Custom",
            "ppm_cap":     ppm,
            "jitter_min":  jmin,
            "jitter_max":  jmax,
            "mac_rotate":  rotate,
            "idle_inject": idle,
            "idle_rate":   0.2 if idle else 0,
        })
        console.print(f"  [{C_GOOD}]✔ Custom profile configured.[/{C_GOOD}]")

    def show_status(self):
        """Print current stealth status."""
        console.print(Panel(
            f"  {tag('Active:',    C_BLOOD)}     [{C_GOOD if self._active else C_DIM}]"
            f"{'YES' if self._active else 'NO'}[/{C_GOOD if self._active else C_DIM}]\n"
            f"  {tag('Current MAC:', C_STEEL)}  [{C_WHITE}]{self._current_mac}[/{C_WHITE}]\n"
            f"  {tag('Packets sent:',C_STEEL)}  [{C_ASH}]{self._packet_count}[/{C_ASH}]\n"
            f"  {tag('Rate cap:',    C_STEEL)}  [{C_ASH}]{self.profile['ppm_cap']} ppm[/{C_ASH}]\n"
            f"  {tag('Jitter:',      C_STEEL)}  [{C_ASH}]{self.profile['jitter_min']}–"
            f"{self.profile['jitter_max']}s[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ STEALTH STATUS[/bold {C_BLOOD}]",
            padding=(1, 2),
        ))


# ══════════════════════════════════════════════════════════════════════════════
# ── MENU ─────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# Global stealth instance (shared across modules)
_stealth_instance = None

def get_stealth(iface="wlan0", profile="ninja"):
    global _stealth_instance
    if _stealth_instance is None:
        _stealth_instance = StealthMode(iface, profile)
    return _stealth_instance


def fingerprint_menu(iface, hosts):
    """
    hosts: list of (ip, mac) tuples
    """
    section("IoT FINGERPRINTER")

    if not hosts:
        console.print(
            f"  [{C_ORANGE}]No hosts to fingerprint. Run a network scan first.[/{C_ORANGE}]"
        )
        return

    console.print(
        f"  [{C_STEEL}]{len(hosts)} host(s) to fingerprint.[/{C_STEEL}]\n"
        f"  [{C_DIM}]This performs active probing — port scan + banner grab + HTTP.[/{C_DIM}]\n"
    )

    if not Confirm.ask(f"  [{C_BLOOD}]Proceed?[/{C_BLOOD}]", default=True):
        return

    timeout = float(Prompt.ask(
        f"  [{C_STEEL}]Probe timeout seconds [{C_DIM}]default=2[/{C_DIM}][/{C_STEEL}]",
        default="2"
    ))

    fp = IoTFingerprinter(timeout=timeout)
    fp.scan_network(hosts)


def stealth_menu(iface):
    """Interactive stealth mode menu."""
    section("STEALTH MODE ENGINE")

    console.print(f"""
  [{C_BLOOD}][1][/{C_BLOOD}]  [{C_ASH}]Ghost    — Maximum stealth (6 ppm, high jitter, MAC rotation)[/{C_ASH}]
  [{C_BLOOD}][2][/{C_BLOOD}]  [{C_ASH}]Ninja    — Balanced evasion (30 ppm, moderate jitter)[/{C_ASH}]
  [{C_BLOOD}][3][/{C_BLOOD}]  [{C_ASH}]Normal   — Light evasion (120 ppm, minimal jitter)[/{C_ASH}]
  [{C_BLOOD}][4][/{C_BLOOD}]  [{C_ASH}]Custom   — Configure manually[/{C_ASH}]
  [{C_BLOOD}][5][/{C_BLOOD}]  [{C_ASH}]Status   — Show current stealth state[/{C_ASH}]
  [{C_BLOOD}][6][/{C_BLOOD}]  [{C_ASH}]MAC Rotate Now — Change interface MAC immediately[/{C_ASH}]
  [{C_BLOOD}][E][/{C_BLOOD}]  [{C_ASH}]Back[/{C_ASH}]
""")

    choice = Prompt.ask(f"  [{C_BLOOD}]select[/{C_BLOOD}]").strip()

    profile_map = {"1": "ghost", "2": "ninja", "3": "normal"}

    if choice in profile_map:
        profile = profile_map[choice]
        stealth = get_stealth(iface, profile)
        gw_ip   = Prompt.ask(
            f"  [{C_STEEL}]Gateway IP for idle injection [{C_DIM}]leave blank to skip[/{C_DIM}][/{C_STEEL}]",
            default=""
        )
        stealth.start(gateway_ip=gw_ip or None)
        console.print(
            f"  [{C_DIM}]Stealth mode active. All attack modules will use "
            f"rate/jitter controls automatically.[/{C_DIM}]"
        )

    elif choice == "4":
        stealth = get_stealth(iface, "custom")
        stealth.configure_custom()
        stealth.start()

    elif choice == "5":
        stealth = get_stealth(iface)
        stealth.show_status()

    elif choice == "6":
        stealth = get_stealth(iface)
        new_mac = stealth._random_mac()
        if stealth._set_mac(new_mac):
            console.print(f"  [{C_GOOD}]✔ MAC changed → {new_mac}[/{C_GOOD}]")
        else:
            console.print(f"  [{C_ORANGE}]MAC change failed.[/{C_ORANGE}]")

    elif choice.upper() == "E":
        return

    else:
        console.print(f"  [{C_ORANGE}]Invalid option.[/{C_ORANGE}]")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Must run as root"); sys.exit(1)
    iface = Prompt.ask("Interface", default="wlan0")
    stealth_menu(iface)
