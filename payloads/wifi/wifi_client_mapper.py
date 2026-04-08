#!/usr/bin/env python3
"""
KTOx payload – WiFi Client Mapper (passive)
===============================================
Map nearby Wi‑Fi clients and access points passively on the 1.44" LCD.

Features
- Interface selection (prefers wlan1) and monitor-mode enable via KTOx helper
- Live passive sniff of 802.11 (beacons, probe req/resp, assoc) using scapy
- Two views: AP-centric (AP -> ESSID, channel, client count) and Client-centric (Client -> last AP/probes)
- Toggle logging to loot/WiFiClientMapper (KEY1)
- Toggle view (APs/Clients) (KEY2)
- Pause/Resume sniff (LEFT)
- Exit cleanly (KEY3), restoring interface

Notes
- Requires root and scapy (sudo pip3 install scapy)
"""
import os
import sys
import time
import signal
import json
import threading
from collections import defaultdict, deque

# KTOx pathing
BASE_DIR = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(BASE_DIR, '..', '..')))
# Prefer installed KTOx first
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')

# Hardware/UI imports (strict order)
try:
    import RPi.GPIO as GPIO
    import LCD_Config
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:
    print(f"[ERROR] LCD/GPIO deps missing: {e}", file=sys.stderr)
    sys.exit(1)

# WiFi integration helpers from KTOx
try:
    from wifi.ktox_integration import get_available_interfaces
    import monitor_mode_helper
    WIFI_OK = True
except Exception:
    WIFI_OK = False

# Scapy (required)
try:
    from scapy.all import sniff, Dot11, Dot11Beacon, Dot11ProbeReq, Dot11ProbeResp, Dot11AssoReq
    from scapy.layers.dot11 import RadioTap
    SCAPY_OK = True
except Exception:
    SCAPY_OK = False

# ---------------------------
# GPIO / LCD / Fonts
# ---------------------------
WIDTH, HEIGHT = 128, 128
LCD = None

# Load PINS from gui_conf.json with robust lookup
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

def _find_gui_conf() -> str | None:
    candidates = [
        os.path.join(os.getcwd(), 'gui_conf.json'),
        os.path.join('/root/KTOx', 'gui_conf.json'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'KTOx', 'gui_conf.json'),
    ]
    for sp in list(sys.path):
        try:
            if sp and os.path.basename(sp) == 'KTOx':
                candidates.append(os.path.join(sp, 'gui_conf.json'))
        except Exception:
            pass
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

try:
    cfg = _find_gui_conf()
    if cfg:
        with open(cfg, 'r') as f:
            data = json.load(f)
        mp = data.get('PINS', {})
        PINS = {
            "UP": mp.get("KEY_UP_PIN", PINS["UP"]),
            "DOWN": mp.get("KEY_DOWN_PIN", PINS["DOWN"]),
            "LEFT": mp.get("KEY_LEFT_PIN", PINS["LEFT"]),
            "RIGHT": mp.get("KEY_RIGHT_PIN", PINS["RIGHT"]),
            "OK": mp.get("KEY_PRESS_PIN", PINS["OK"]),
            "KEY1": mp.get("KEY1_PIN", PINS["KEY1"]),
            "KEY2": mp.get("KEY2_PIN", PINS["KEY2"]),
            "KEY3": mp.get("KEY3_PIN", PINS["KEY3"]),
        }
except Exception:
    pass

GPIO.setmode(GPIO.BCM)
for p in PINS.values():
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
IMG = Image.new("RGB", (WIDTH, HEIGHT), "black")
DRAW = ImageDraw.Draw(IMG)
try:
    FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
except Exception:
    FONT_TITLE = ImageFont.load_default()
FONT = ImageFont.load_default()

# ---------------------------
# Global state
# ---------------------------
RUNNING = True
PAUSED = False
VIEW = 'aps'  # 'aps' or 'clients'
SELECTION = 0
SCROLL = 0

WIFI_INTERFACE = None
MONITOR_IFACE = None

# AP info map: bssid -> {essid, channel, clients:set, last_seen, power}
APS = {}
# Client info: client_mac -> {last_ap, probes:deque(maxlen=5), last_seen, power}
CLIENTS = {}

# Loot/logging
LOGGING = False
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'WiFiClientMapper')
CURRENT_LOG = None

# ---------------------------
# Helpers
# ---------------------------

def is_root():
    return os.geteuid() == 0

def draw_message(lines, color="yellow"):
    IMG.paste((0, 0, 0), [0, 0, WIDTH, HEIGHT])
    y = 40
    for line in (lines if isinstance(lines, list) else [lines]):
        DRAW.text((6, y), line, font=FONT_TITLE, fill=color)
        y += 14
    LCD.LCD_ShowImage(IMG, 0, 0)

def open_log():
    global CURRENT_LOG
    os.makedirs(LOG_DIR(), exist_ok=True)
    ts = time.strftime('%Y-%m-%d_%H%M%S')
    CURRENT_LOG = os.path.join(LOG_DIR(), f'mapper_{ts}.log')
    try:
        with open(CURRENT_LOG, 'a') as f:
            f.write('# WiFi Client Mapper log\n')
    except Exception:
        pass

def LOG_DIR():
    return LOOT_DIR

def log_line(s: str):
    if LOGGING and CURRENT_LOG:
        try:
            with open(CURRENT_LOG, 'a') as f:
                f.write(s.rstrip() + '\n')
        except Exception:
            pass

# ---------------------------
# Sniffer
# ---------------------------

def _oui(mac: str) -> str:
    try:
        return mac.upper()[0:8]
    except Exception:
        return mac

def handle_packet(pkt):
    if PAUSED:
        return
    ts = time.time()
    rssi = None
    try:
        if pkt.haslayer(RadioTap) and hasattr(pkt[RadioTap], 'dBm_AntSignal'):
            rssi = pkt[RadioTap].dBm_AntSignal
    except Exception:
        pass

    if pkt.haslayer(Dot11):
        dot11 = pkt[Dot11]
        sa = dot11.addr2  # transmitter
        da = dot11.addr1  # receiver
        bssid = dot11.addr3

        # Beacons/Probe Responses define APs
        if pkt.haslayer(Dot11Beacon) or pkt.haslayer(Dot11ProbeResp):
            essid = None
            try:
                essid = pkt[Dot11].info.decode(errors='ignore') if hasattr(pkt[Dot11], 'info') else None
            except Exception:
                essid = None
            # Some stacks store ESSID in Dot11Elt at index 0
            if not essid:
                try:
                    essid = pkt[Dot11Elt].info.decode(errors='ignore')
                except Exception:
                    essid = None
            ch = None
            # Try extracting channel from DS params (Dot11Elt ID 3)
            try:
                for elt in pkt.iterpayloads():
                    if getattr(elt, 'ID', None) == 3:  # DS Parameter set
                        ch = int(elt.info[0])
                        break
            except Exception:
                pass
            if bssid:
                ap = APS.get(bssid) or {"essid": essid or "Hidden", "channel": ch, "clients": set(), "last_seen": ts, "power": rssi}
                if essid:
                    ap["essid"] = essid or ap["essid"]
                if ch:
                    ap["channel"] = ch
                ap["last_seen"] = ts
                ap["power"] = rssi if rssi is not None else ap.get("power")
                APS[bssid] = ap
                if LOGGING:
                    log_line(f"AP {bssid} ({ap['essid']}) ch:{ap['channel']} rssi:{ap['power']}")
            return

        # Probe requests from clients
        if pkt.haslayer(Dot11ProbeReq):
            client = sa or da
            if client:
                entry = CLIENTS.get(client) or {"last_ap": None, "probes": deque(maxlen=5), "last_seen": ts, "power": rssi}
                # SSID in Dot11Elt
                ssid = None
                try:
                    ssid = pkt.info.decode(errors='ignore') if hasattr(pkt, 'info') else None
                except Exception:
                    ssid = None
                if ssid:
                    if ssid not in entry["probes"]:
                        entry["probes"].appendleft(ssid)
                entry["last_seen"] = ts
                entry["power"] = rssi if rssi is not None else entry.get("power")
                CLIENTS[client] = entry
                if LOGGING:
                    log_line(f"PROBE {client} -> '{ssid or ''}' rssi:{entry['power']}")
            return

        # Association Requests: link client to AP
        if pkt.haslayer(Dot11AssoReq) and bssid and sa:
            entry = CLIENTS.get(sa) or {"last_ap": None, "probes": deque(maxlen=5), "last_seen": ts, "power": rssi}
            entry["last_ap"] = bssid
            entry["last_seen"] = ts
            entry["power"] = rssi if rssi is not None else entry.get("power")
            CLIENTS[sa] = entry
            ap = APS.get(bssid) or {"essid": "", "channel": None, "clients": set(), "last_seen": ts, "power": None}
            ap["clients"].add(sa)
            ap["last_seen"] = ts
            APS[bssid] = ap
            if LOGGING:
                log_line(f"ASSOC {sa} -> {bssid}")
            return

# ---------------------------
# UI
# ---------------------------

def draw_interface_select(options, sel):
    IMG.paste((0, 0, 0), [0, 0, WIDTH, HEIGHT])
    DRAW.text((5, 5), "Select Interface", font=FONT_TITLE, fill="#00FFFF")
    DRAW.line([(0, 20), (WIDTH, 20)], fill="#004444", width=1)
    y = 28
    for i, iface in enumerate(options):
        if i == sel:
            DRAW.rectangle([(2, y-1), (WIDTH-2, y+12)], fill="#002244")
        DRAW.text((8, y), iface, font=FONT, fill="#FFFF00" if i == sel else "#FFFFFF")
        y += 13
    DRAW.text((4, 113), "OK=Confirm  LEFT=Back", font=FONT, fill="#888888")
    LCD.LCD_ShowImage(IMG, 0, 0)


def draw_main():
    IMG.paste((0, 0, 0), [0, 0, WIDTH, HEIGHT])
    title = "WiFi Client Mapper"
    DRAW.text((5, 3), title, font=FONT_TITLE, fill="#00FF00")
    DRAW.line([(0, 18), (WIDTH, 18)], fill="#003300", width=1)

    global VIEW, SELECTION, SCROLL
    items_per_page = 8
    lines = []

    if VIEW == 'aps':
        # Sort APs by client count desc, then ESSID
        now = time.time()
        rows = []
        for bssid, ap in APS.items():
            age = now - ap.get("last_seen", 0)
            rows.append((len(ap.get("clients", [])), ap.get("essid", ""), bssid, ap.get("channel"), ap.get("power"), int(age)))
        rows.sort(key=lambda x: (-x[0], x[1]))
        for cnt, essid, bssid, ch, pwr, age in rows:
            lines.append(f"{essid[:12]:12} c:{str(ch or '?'):>2} n:{cnt:>2}")
    else:
        # Clients by recent activity
        now = time.time()
        rows = []
        for client, info in CLIENTS.items():
            age = now - info.get("last_seen", 0)
            last_ap = info.get("last_ap") or "?"
            probe = info.get("probes")[0] if info.get("probes") else "-"
            rows.append((age, client, last_ap, probe))
        rows.sort(key=lambda x: x[0])
        for age, client, last_ap, probe in rows:
            lines.append(f"{client[-8:]} {probe[:8]}")

    # Pagination
    total = len(lines)
    if SELECTION < 0: SELECTION = 0
    if SELECTION >= total: SELECTION = max(0, total - 1)
    if SELECTION < SCROLL: SCROLL = SELECTION
    if SELECTION >= SCROLL + items_per_page: SCROLL = SELECTION - items_per_page + 1

    y = 22
    for i in range(SCROLL, min(SCROLL + items_per_page, total)):
        sel = (i == SELECTION)
        if sel:
            DRAW.rectangle([(2, y-1), (WIDTH-2, y+12)], fill="#002244")
        DRAW.text((6, y), lines[i], font=FONT, fill="#FFFF00" if sel else "#FFFFFF")
        y += 13

    footer = f"VIEW:{'APs' if VIEW=='aps' else 'Clients'} {'PAUSE' if PAUSED else 'LIVE'} {'LOG' if LOGGING else ''}"
    DRAW.text((4, 113), "KEY1=Log KEY2=View LEFT=Pause KEY3=Exit", font=FONT, fill="#888888")
    LCD.LCD_ShowImage(IMG, 0, 0)

# ---------------------------
# Main
# ---------------------------

def cleanup(*_):
    global RUNNING
    RUNNING = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

if __name__ == '__main__':
    try:
        if not is_root():
            draw_message(["Root required", "Run as sudo"], "red")
            time.sleep(3)
            sys.exit(1)
        if not SCAPY_OK:
            draw_message(["Missing scapy", "pip3 install scapy"], "red")
            time.sleep(3)
            sys.exit(1)
        if not WIFI_OK:
            draw_message(["WiFi integration", "module missing"], "red")
            time.sleep(3)
            sys.exit(1)

        # Interface selection
        options = [i for i in get_available_interfaces() if i.startswith('wlan')]
        if 'wlan1' in options:
            options.remove('wlan1'); options.insert(0, 'wlan1')
        if not options:
            draw_message(["No WiFi interfaces"], "red")
            time.sleep(3)
            sys.exit(1)
        sel = 0
        last_t = 0.0
        debounce = 0.25
        while True:
            now = time.time()
            draw_interface_select(options, sel)
            if GPIO.input(PINS["UP"]) == 0 and now - last_t > debounce:
                last_t = now; sel = (sel - 1) % len(options)
            elif GPIO.input(PINS["DOWN"]) == 0 and now - last_t > debounce:
                last_t = now; sel = (sel + 1) % len(options)
            elif GPIO.input(PINS["OK"]) == 0 and now - last_t > debounce:
                last_t = now; WIFI_INTERFACE = options[sel]; break
            elif GPIO.input(PINS["LEFT"]) == 0 and now - last_t > debounce:
                last_t = now; sys.exit(0)
            elif GPIO.input(PINS["KEY3"]) == 0 and now - last_t > debounce:
                last_t = now; sys.exit(0)
            time.sleep(0.05)

        # Enable monitor mode
        draw_message([f"Enabling monitor", f"on {WIFI_INTERFACE}..."], "yellow")
        MONITOR_IFACE = monitor_mode_helper.activate_monitor_mode(WIFI_INTERFACE)
        if not MONITOR_IFACE:
            draw_message(["Monitor mode", "failed"], "red")
            time.sleep(3)
            sys.exit(1)
        time.sleep(0.5)

        # Prepare logging directory
        os.makedirs(LOG_DIR(), exist_ok=True)
        open_log()

        # Start sniffer thread
        def sniffer():
            try:
                sniff(iface=MONITOR_IFACE, prn=handle_packet, store=0, stop_filter=lambda p: not RUNNING)
            except Exception as e:
                print(f"[ERROR] sniff failed: {e}", file=sys.stderr)
        t = threading.Thread(target=sniffer, daemon=True)
        t.start()

        # UI loop
        last_t = 0.0
        debounce = 0.25
        while RUNNING:
            draw_main()
            now = time.time()
            if GPIO.input(PINS["KEY3"]) == 0 and now - last_t > debounce:
                last_t = now; break
            if GPIO.input(PINS["KEY1"]) == 0 and now - last_t > debounce:
                last_t = now
                LOGGING = not LOGGING
                if LOGGING and not CURRENT_LOG:
                    open_log()
            if GPIO.input(PINS["KEY2"]) == 0 and now - last_t > debounce:
                last_t = now
                VIEW = 'clients' if VIEW == 'aps' else 'aps'
                SELECTION = SCROLL = 0
            if GPIO.input(PINS["LEFT"]) == 0 and now - last_t > debounce:
                last_t = now
                PAUSED = not PAUSED
            if GPIO.input(PINS["UP"]) == 0 and now - last_t > debounce:
                last_t = now
                SELECTION = max(0, SELECTION - 1)
            if GPIO.input(PINS["DOWN"]) == 0 and now - last_t > debounce:
                last_t = now
                SELECTION = SELECTION + 1
            time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        # Log fatal error
        try:
            with open('/tmp/wifi_client_mapper_error.log', 'w') as f:
                import traceback
                f.write(f"FATAL: {e}\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
    finally:
        try:
            LCD.LCD_Clear()
        except Exception:
            pass
        try:
            if MONITOR_IFACE:
                monitor_mode_helper.deactivate_monitor_mode(MONITOR_IFACE)
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
