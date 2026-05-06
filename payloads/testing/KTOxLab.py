#!/usr/bin/env python3
"""
KTOxLab - Advanced Packet & Forensics Laboratory
================================================
Real-time packet capture, credential extraction, file carving, and forensics analysis.

Features:
  • Live packet capture & analysis on all interfaces
  • Credential extraction (HTTP, FTP, Telnet, SMTP, DNS)
  • File carving from network traffic
  • DNS intelligence & domain analysis
  • Timeline reconstruction of network events
  • LCD dashboard for quick stats

Controls:
  UP/DOWN     - Navigate menu
  OK          - Select / Start capture
  KEY1        - Back / Stop capture
  KEY3        - Exit
"""

import os
import sys
import time
import signal
import subprocess
import json
import threading
from pathlib import Path
from datetime import datetime
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT2 = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ROOT3 = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ROOT2, _ROOT3):
    if _p not in sys.path:
        sys.path.append(_p)

import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config
from PIL import Image, ImageDraw, ImageFont
if os.path.exists(os.path.join(_ROOT2, "_display_helper.py")):
    from _display_helper import ScaledDraw, scaled_font
    from _input_helper import get_button, flush_input
else:
    from payloads._display_helper import ScaledDraw, scaled_font
    from payloads._input_helper import get_button, flush_input

try:
    from scapy.all import sniff, IP, TCP, UDP, DNS, DNSQR, DNSRR, Raw
    SCAPY_OK = True
except ImportError:
    SCAPY_OK = False

# ── Hardware ──────────────────────────────────────────────────────────────────
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for _p in PINS.values():
    GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = LCD.width, LCD.height
font = scaled_font()
small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8) if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") else font

# ── Constants ─────────────────────────────────────────────────────────────────
LOOT_DIR = Path("/root/KTOx/loot/forensics")
LOOT_DIR.mkdir(parents=True, exist_ok=True)

# KTOx colour palette (red/black)
_BG     = (10,  0,   0)    # very dark red-black
_HDR    = (139, 0,   0)    # dark red
_BLOOD  = (192, 57,  43)   # bright red
_EMBER  = (231, 76,  60)   # orange-red
_WHITE  = (242, 243, 244)
_ASH    = (171, 178, 185)  # light grey
_STEEL  = (113, 125, 126)  # medium grey
_DIM    = (86,  101, 115)  # dark grey
_RUST   = (146, 43,  33)   # rust red
_GOOD   = (30,  132, 73)   # green
_FOOTER = (34,  0,   0)    # very dark footer

running = True


def _sig(s, f):
    global running
    running = False


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)

# ═══════════════════════════════════════════════════════════════════════════════

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
WIDTH, HEIGHT = 128, 128
BG = (10, 0, 0)
HEADER = (139, 0, 0)
ACCENT = (231, 76, 60)
WHITE = (242, 243, 244)
FG = (171, 178, 185)
GOOD = (46, 204, 113)

LCD = None
FONT = None
FONT_SM = None
RUNNING = True
CAPTURING = False
PACKET_COUNT = 0
CREDENTIALS_FOUND = defaultdict(list)
FILES_CARVED = []
DNS_QUERIES = defaultdict(int)
TIMELINE_EVENTS = []

# Setup GPIO if hardware available
if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ═══════════════════════════════════════════════════════════════════════════════
# LCD INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def init_screen():
    global LCD, FONT, FONT_SM
    if not HAS_HW:
        return

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

    if HAS_HELPERS:
        FONT = scaled_font(10)
        FONT_SM = scaled_font(8)
    else:
        for fpath in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
            if os.path.exists(fpath):
                try:
                    FONT = ImageFont.truetype(fpath, 10)
                    FONT_SM = ImageFont.truetype(fpath, 8)
                    return
                except:
                    pass
        FONT = ImageFont.load_default()
        FONT_SM = ImageFont.load_default()

def cleanup_screen():
    if HAS_HW and LCD:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    flush_input() if HAS_HELPERS else None

# ═══════════════════════════════════════════════════════════════════════════════
# LCD DRAWING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def draw_menu():
    """Draw main menu"""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ScaledDraw(img) if HAS_HELPERS else ImageDraw.Draw(img)

    d.rectangle((0, 0, WIDTH, 14), fill=HEADER)
    d.text((4, 1), "KTOxLab", font=FONT, fill=ACCENT)

    y = 20
    options = [
        "1. Live Capture",
        "2. View Results",
        "3. Reports",
        "4. Clear Data"
    ]

    for opt in options:
        d.text((4, y), opt, font=FONT_SM, fill=WHITE)
        y += 14

    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    d.text((4, HEIGHT-10), "OK=Select", font=FONT_SM, fill=ACCENT)

    if HAS_HW and LCD:
        LCD.LCD_ShowImage(img, 0, 0)

def draw_capturing():
    """Draw live capture screen"""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ScaledDraw(img) if HAS_HELPERS else ImageDraw.Draw(img)

    d.rectangle((0, 0, WIDTH, 14), fill=HEADER)
    d.text((4, 1), "Live Capture", font=FONT, fill=ACCENT)

    y = 20
    d.text((4, y), f"Packets: {PACKET_COUNT}", font=FONT_SM, fill=WHITE)
    y += 12
    d.text((4, y), f"Creds: {len(CREDENTIALS_FOUND)}", font=FONT_SM, fill=GOOD if CREDENTIALS_FOUND else WHITE)
    y += 12
    d.text((4, y), f"Files: {len(FILES_CARVED)}", font=FONT_SM, fill=GOOD if FILES_CARVED else WHITE)
    y += 12
    d.text((4, y), f"DNS: {len(DNS_QUERIES)}", font=FONT_SM, fill=WHITE)

    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    d.text((4, HEIGHT-10), "KEY1=Stop", font=FONT_SM, fill=ACCENT)

    if HAS_HW and LCD:
        LCD.LCD_ShowImage(img, 0, 0)

def draw_results():
    """Draw results summary"""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ScaledDraw(img) if HAS_HELPERS else ImageDraw.Draw(img)

    d.rectangle((0, 0, WIDTH, 14), fill=HEADER)
    d.text((4, 1), "Results", font=FONT, fill=ACCENT)

    y = 20
    d.text((4, y), f"Packets: {PACKET_COUNT}", font=FONT_SM, fill=WHITE)
    y += 12
    d.text((4, y), f"Credentials: {len(CREDENTIALS_FOUND)}", font=FONT_SM, fill=GOOD if CREDENTIALS_FOUND else FG)
    y += 12
    d.text((4, y), f"Files Carved: {len(FILES_CARVED)}", font=FONT_SM, fill=GOOD if FILES_CARVED else FG)
    y += 12
    d.text((4, y), f"DNS Queries: {len(DNS_QUERIES)}", font=FONT_SM, fill=FG)
    y += 14

    d.text((4, y), "Data saved to loot/", font=FONT_SM, fill=FG)

    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    d.text((4, HEIGHT-10), "KEY3=Exit", font=FONT_SM, fill=ACCENT)

    if HAS_HW and LCD:
        LCD.LCD_ShowImage(img, 0, 0)

# ═══════════════════════════════════════════════════════════════════════════════
# PACKET ANALYSIS FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def extract_credentials(packet):
    """Extract credentials from packet"""
    global CREDENTIALS_FOUND, TIMELINE_EVENTS

    if not packet.haslayer(Raw):
        return

    payload = packet[Raw].load

    # HTTP Basic Auth
    if b'Authorization: Basic' in payload:
        match = re.search(b'Authorization: Basic ([A-Za-z0-9+/=]+)', payload)
        if match:
            try:
                import base64
                decoded = base64.b64decode(match.group(1)).decode()
                CREDENTIALS_FOUND['HTTP_Basic'].append(decoded)
                TIMELINE_EVENTS.append((datetime.now(), "HTTP Basic Auth captured", decoded))
            except:
                pass

    # FTP credentials
    if b'USER ' in payload or b'PASS ' in payload:
        user_match = re.search(b'USER ([^\r\n]+)', payload)
        pass_match = re.search(b'PASS ([^\r\n]+)', payload)
        if user_match or pass_match:
            user = user_match.group(1).decode() if user_match else "unknown"
            passwd = pass_match.group(1).decode() if pass_match else "unknown"
            cred = f"FTP - {user}:{passwd}"
            CREDENTIALS_FOUND['FTP'].append(cred)
            TIMELINE_EVENTS.append((datetime.now(), "FTP credentials captured", cred))

    # Telnet credentials
    if b'login:' in payload.lower() or b'password:' in payload.lower():
        CREDENTIALS_FOUND['Telnet'].append(payload.decode(errors='ignore')[:50])
        TIMELINE_EVENTS.append((datetime.now(), "Telnet activity detected", str(payload)[:50]))

def analyze_dns(packet):
    """Analyze DNS queries"""
    global DNS_QUERIES, TIMELINE_EVENTS

    if packet.haslayer(DNS):
        if packet[DNS].opcode == 0:  # Query
            if packet[DNS].qdcount > 0:
                qname = packet[DNS].qd.qname.decode('utf-8').rstrip('.')
                DNS_QUERIES[qname] += 1
                TIMELINE_EVENTS.append((datetime.now(), "DNS Query", qname))

def carve_files(packet):
    """Extract files from traffic"""
    global FILES_CARVED, TIMELINE_EVENTS

    if not packet.haslayer(Raw):
        return

    payload = packet[Raw].load

    # PDF detection
    if b'%PDF' in payload:
        match = re.search(b'%PDF.*?%%EOF', payload, re.DOTALL)
        if match:
            filename = LOOT_DIR / f"carved_{len(FILES_CARVED)}.pdf"
            with open(filename, 'wb') as f:
                f.write(match.group(0))
            FILES_CARVED.append(("PDF", str(filename)))
            TIMELINE_EVENTS.append((datetime.now(), "PDF carved", filename.name))

    # JPEG detection
    if b'\xff\xd8\xff' in payload:
        match = re.search(b'\xff\xd8\xff.*?\xff\xd9', payload, re.DOTALL)
        if match:
            filename = LOOT_DIR / f"carved_{len(FILES_CARVED)}.jpg"
            with open(filename, 'wb') as f:
                f.write(match.group(0))
            FILES_CARVED.append(("JPEG", str(filename)))
            TIMELINE_EVENTS.append((datetime.now(), "JPEG carved", filename.name))

    # PNG detection
    if b'\x89PNG' in payload:
        match = re.search(b'\x89PNG.*?\x49END\xae\x42\x60\x82', payload, re.DOTALL)
        if match:
            filename = LOOT_DIR / f"carved_{len(FILES_CARVED)}.png"
            with open(filename, 'wb') as f:
                f.write(match.group(0))
            FILES_CARVED.append(("PNG", str(filename)))
            TIMELINE_EVENTS.append((datetime.now(), "PNG carved", filename.name))

def packet_callback(packet):
    """Process each captured packet"""
    global PACKET_COUNT, CAPTURING

    if not CAPTURING:
        return

    PACKET_COUNT += 1

    # Analyze for credentials
    extract_credentials(packet)

    # Analyze DNS
    analyze_dns(packet)

    # Carve files
    carve_files(packet)

def start_live_capture():
    """Start live packet capture"""
    global CAPTURING, PACKET_COUNT, CREDENTIALS_FOUND, FILES_CARVED, DNS_QUERIES, TIMELINE_EVENTS

    if not HAS_SCAPY:
        print("[KTOxLab] ERROR: Scapy not installed")
        return False

    CAPTURING = True
    PACKET_COUNT = 0
    CREDENTIALS_FOUND.clear()
    FILES_CARVED.clear()
    DNS_QUERIES.clear()
    TIMELINE_EVENTS.clear()

    print("[KTOxLab] Starting live packet capture...")

    try:
        sniff(prn=packet_callback, filter="", store=False, iface=None, timeout=300)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[KTOxLab] Capture error: {e}")

    CAPTURING = False
    return True

def generate_report():
    """Generate forensics report"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = LOOT_DIR / f"KTOxLab_Report_{timestamp}.json"

    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_packets": PACKET_COUNT,
            "credentials_found": len(CREDENTIALS_FOUND),
            "files_carved": len(FILES_CARVED),
            "dns_queries": len(DNS_QUERIES)
        },
        "credentials": dict(CREDENTIALS_FOUND),
        "files": FILES_CARVED,
        "dns_queries": dict(DNS_QUERIES),
        "timeline": [(t.isoformat(), event, data) for t, event, data in TIMELINE_EVENTS]
    }

    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"[KTOxLab] Report saved: {report_file}")
    return report_file

# ═══════════════════════════════════════════════════════════════════════════════
# BUTTON INPUT HANDLING
# ═══════════════════════════════════════════════════════════════════════════════

def is_button(name):
    """Check if button pressed (uses helper if available)"""
    if not HAS_HW:
        return False
    if HAS_HELPERS:
        return get_button(PINS, GPIO) == name
    try:
        return GPIO.input(PINS[name]) == 0
    except:
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PROGRAM
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global RUNNING, CAPTURING

    print("[KTOxLab] Advanced Packet & Forensics Laboratory")
    print(f"[KTOxLab] Loot directory: {LOOT_DIR}")

    init_screen()
    menu_state = "main"

    try:
        while RUNNING:
            if menu_state == "main":
                draw_menu()

                if is_button("OK"):
                    menu_state = "capturing"
                    capture_thread = threading.Thread(target=start_live_capture, daemon=True)
                    capture_thread.start()

                if is_button("KEY2"):
                    menu_state = "results"

                if is_button("KEY3"):
                    break

            elif menu_state == "capturing":
                draw_capturing()

                if is_button("KEY1"):
                    CAPTURING = False
                    time.sleep(1)
                    menu_state = "main"

            elif menu_state == "results":
                draw_results()
                generate_report()

                if is_button("KEY3"):
                    menu_state = "main"

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n[KTOxLab] Interrupted by user")

    finally:
        CAPTURING = False
        cleanup_screen()
        print("[KTOxLab] Cleanup complete")

if __name__ == "__main__":
    main()
