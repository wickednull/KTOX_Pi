#!/usr/bin/env python3
"""
KTOx *payload* – **Matrix Tap**
=================================
Live network packet sniffer rendered as Matrix-style falling-rain on the LCD.
Captured data — IP addresses, DNS hostnames, port numbers, HTTP hosts, and raw
hex bytes — is injected into scrolling rain columns so every character you see
is real traffic from your network.

Colour coding
  Bright green  – standard TCP/UDP traffic
  Cyan          – DNS queries / responses
  Yellow        – HTTP/HTTPS hosts
  Red           – alerts (port scans, ARP probes)
  White head    – leading character of each column (brightest point)

Requires: scapy  (pip3 install scapy)
          root / CAP_NET_RAW

Controls:
  OK     : Pause / resume sniffer
  UP     : Speed up rain
  DOWN   : Slow down rain
  KEY1   : Cycle filter (all → TCP → UDP → DNS → ARP)
  KEY3   : Exit
"""

import sys
import os
import time
import math
import random
import signal
import threading
import struct
import socket
import re

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from payloads._input_helper import get_button

# ── Hardware ──────────────────────────────────────────────────────────────────
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
WIDTH, HEIGHT = 128, 128

GPIO.setmode(GPIO.BCM)
for _p in PINS.values():
    GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

# Use a monospace font, 8px wide × 10px tall → 16 columns × 12 rows
FONT = ImageFont.load_default()   # 6×10 on most systems
try:
    FONT = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 8)
except Exception:
    pass

CHAR_W = 8    # pixels per character cell (width)
CHAR_H = 10   # pixels per character cell (height)
COLS   = WIDTH  // CHAR_W   # 16 columns
ROWS   = HEIGHT // CHAR_H   # 12 rows

# ── Colour palette ────────────────────────────────────────────────────────────
COL_BG        = (0, 0, 0)
COL_HEAD      = (200, 255, 200)   # leading-char white-green
COL_TCP       = (0, 210, 0)       # bright green
COL_TCP_TRAIL = (0, 80, 0)        # dim green trail
COL_DNS       = (0, 200, 220)     # cyan
COL_DNS_TRAIL = (0, 60, 80)
COL_HTTP      = (220, 220, 0)     # yellow
COL_HTTP_TRAIL= (70, 70, 0)
COL_ARP       = (220, 60, 60)     # red
COL_ARP_TRAIL = (70, 0, 0)
COL_DEFAULT   = (0, 180, 40)
COL_DEF_TRAIL = (0, 50, 10)

FILTER_NAMES = ["ALL", "TCP", "UDP", "DNS", "ARP"]

# ── State ─────────────────────────────────────────────────────────────────────
running    = True
capturing  = True
rain_speed = 0.08          # seconds between frame ticks
filter_idx = 0
pkt_lock   = threading.Lock()
pkt_queue: list[dict] = []  # items: {chars, color, trail}
total_pkts = 0

# Matrix rain columns: each column has its own scrolling state
class Column:
    def __init__(self, x_col: int):
        self.x    = x_col               # column index
        self.chars: list[str] = []      # character buffer (ROWS long)
        self.head: int = 0              # current head row
        self.active = False
        self.color  = COL_TCP
        self.trail  = COL_TCP_TRAIL
        self.speed_mod = random.uniform(0.5, 1.5)   # per-column speed variation
        self.tick   = 0.0
        self._refill()

    def _refill(self):
        self.chars = [' '] * ROWS
        self.head  = -random.randint(0, ROWS)

    def inject(self, text: str, color, trail):
        """Replace column's char buffer with new data string."""
        clean = [c if c.isprintable() and c != ' ' else
                 random.choice('0123456789ABCDEF') for c in text]
        # pad/trim to ROWS
        while len(clean) < ROWS:
            clean.append(random.choice('0123456789abcdef:./'))
        self.chars = clean[:ROWS]
        self.color = color
        self.trail = trail
        self.active = True

    def step(self):
        """Advance head by one row."""
        self.head += 1
        if self.head > ROWS + 4:
            self.active = False
            self._refill()
            self.head = -random.randint(0, ROWS // 2)


columns = [Column(c) for c in range(COLS)]


def _brightness(base_color: tuple, frac: float) -> tuple:
    """Scale colour by frac (0.0–1.0)."""
    return tuple(int(c * frac) for c in base_color)


# ── Packet sniffer ────────────────────────────────────────────────────────────
def _extract_strings(pkt) -> list[dict]:
    """Pull meaningful strings out of a Scapy packet. Returns list of hits."""
    hits = []
    try:
        proto = type(pkt).__name__
        # Get layers
        has_ip  = pkt.haslayer('IP')
        has_tcp = pkt.haslayer('TCP')
        has_udp = pkt.haslayer('UDP')
        has_dns = pkt.haslayer('DNS')
        has_arp = pkt.haslayer('ARP')

        if has_arp:
            arp = pkt.getlayer('ARP')
            s = f"ARP{arp.psrc}>{arp.pdst}"
            hits.append({'chars': s, 'color': COL_ARP, 'trail': COL_ARP_TRAIL})
            return hits

        if has_dns:
            dns = pkt.getlayer('DNS')
            # DNS query name
            try:
                qname = dns.qd.qname.decode(errors='replace').rstrip('.')
                if qname:
                    hits.append({'chars': qname, 'color': COL_DNS,
                                 'trail': COL_DNS_TRAIL})
            except Exception:
                pass
            # DNS answer
            try:
                if dns.an:
                    rdata = str(dns.an.rdata)
                    hits.append({'chars': rdata, 'color': COL_DNS,
                                 'trail': COL_DNS_TRAIL})
            except Exception:
                pass
            return hits

        if has_ip:
            ip = pkt.getlayer('IP')
            src = ip.src
            dst = ip.dst

            if has_tcp:
                tcp = pkt.getlayer('TCP')
                sport, dport = tcp.sport, tcp.dport
                # HTTP host header
                if dport in (80, 8080) or sport in (80, 8080):
                    try:
                        raw = bytes(pkt.getlayer('Raw').load)
                        m = re.search(rb'Host:\s*([^\r\n]+)', raw)
                        if m:
                            host = m.group(1).decode(errors='replace')
                            hits.append({'chars': f"HTTP:{host}",
                                         'color': COL_HTTP, 'trail': COL_HTTP_TRAIL})
                            return hits
                    except Exception:
                        pass
                s = f"{src}:{sport}>{dst}:{dport}"
                hits.append({'chars': s, 'color': COL_TCP, 'trail': COL_TCP_TRAIL})

            elif has_udp:
                udp = pkt.getlayer('UDP')
                s = f"{src}:{udp.sport}>{dst}:{udp.dport}"
                hits.append({'chars': s, 'color': COL_DEFAULT, 'trail': COL_DEF_TRAIL})

            else:
                s = f"{src}>{dst}proto{ip.proto}"
                hits.append({'chars': s, 'color': COL_DEFAULT, 'trail': COL_DEF_TRAIL})

    except Exception:
        pass
    return hits


def _packet_handler(pkt):
    global total_pkts
    if not capturing:
        return
    hits = _extract_strings(pkt)
    if hits:
        with pkt_lock:
            total_pkts += 1
            pkt_queue.extend(hits)
            # Cap queue so we don't drift
            if len(pkt_queue) > 64:
                del pkt_queue[:32]


def _build_filter() -> str:
    f = FILTER_NAMES[filter_idx]
    if f == "ALL":
        return ""
    if f == "TCP":
        return "tcp"
    if f == "UDP":
        return "udp"
    if f == "DNS":
        return "udp port 53"
    if f == "ARP":
        return "arp"
    return ""


def _sniff_loop():
    while running:
        if not capturing:
            time.sleep(0.3)
            continue
        try:
            from scapy.all import sniff, conf
            flt = _build_filter()
            sniff(
                prn=_packet_handler,
                filter=flt,
                store=0,
                timeout=3,
                stop_filter=lambda _: not running or not capturing,
            )
        except Exception:
            time.sleep(1)


# ── Renderer ──────────────────────────────────────────────────────────────────
_frame_tick = 0.0


def _inject_from_queue():
    """Feed pending packet strings into idle columns."""
    with pkt_lock:
        if not pkt_queue:
            return
        item = pkt_queue.pop(0)

    # Find an idle column or pick the least-active one
    idle = [c for c in columns if not c.active]
    if idle:
        col = random.choice(idle)
    else:
        # All active: pick a random one to hijack
        col = random.choice(columns)
    col.inject(item['chars'], item['color'], item['trail'])


def _draw_rain(draw: ImageDraw.Draw):
    for col in columns:
        cx = col.x * CHAR_W
        head = col.head
        for row in range(ROWS):
            cy = row * CHAR_H
            char = col.chars[row] if 0 <= row < len(col.chars) else ' '
            dist = head - row   # how far below the head
            if dist == 0:
                # Head character: bright white-green
                draw.text((cx, cy), char, font=FONT, fill=COL_HEAD)
            elif 0 < dist <= ROWS:
                # Trail: fade based on distance from head
                frac = max(0.08, 1.0 - dist / ROWS * 1.2)
                color = _brightness(col.trail if dist > ROWS // 3 else col.color, frac)
                if char != ' ':
                    draw.text((cx, cy), char, font=FONT, fill=color)
            elif dist < 0 and dist > -3:
                # Just ahead of head: very dim ghost
                if char != ' ':
                    draw.text((cx, cy), char, font=FONT,
                              fill=_brightness(col.color, 0.15))


def _draw_overlay(draw: ImageDraw.Draw):
    """HUD: packet count, filter, speed."""
    # Bottom bar
    bar_y = HEIGHT - 11
    draw.rectangle([(0, bar_y - 1), (WIDTH, HEIGHT)], fill=(0, 0, 0))
    filter_str = FILTER_NAMES[filter_idx]
    state_str  = ">" if capturing else "||"
    with pkt_lock:
        count = total_pkts
    txt = f"{state_str} {filter_str} {count}pkts"
    draw.text((2, bar_y), txt, font=FONT, fill=(0, 140, 0))


def _render_frame() -> Image.Image:
    img  = Image.new("RGB", (WIDTH, HEIGHT), COL_BG)
    draw = ImageDraw.Draw(img)
    _draw_rain(draw)
    _draw_overlay(draw)
    return img


# ── Column tick ───────────────────────────────────────────────────────────────
def _tick_columns():
    for col in columns:
        col.tick += rain_speed
        if col.tick >= rain_speed * col.speed_mod * (1.0 / rain_speed):
            col.step()
            col.tick = 0.0
    # Simpler: just step all, the speed control is via rain_speed sleep
    for col in columns:
        col.step()


# ── Signal handlers ───────────────────────────────────────────────────────────
def _cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, _cleanup)
signal.signal(signal.SIGTERM, _cleanup)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global running, capturing, rain_speed, filter_idx

    # Start sniffer
    sniff_thread = threading.Thread(target=_sniff_loop, daemon=True)
    sniff_thread.start()

    # Seed columns with placeholder data so rain starts immediately
    for col in columns:
        col.inject(
            ''.join(random.choices('0123456789ABCDEF:.', k=ROWS)),
            COL_TCP, COL_TCP_TRAIL
        )

    while running:
        t0 = time.time()

        btn = get_button(PINS, GPIO)
        if btn == "KEY3":
            break
        elif btn == "OK":
            capturing = not capturing
        elif btn == "UP":
            rain_speed = max(0.02, rain_speed - 0.01)
        elif btn == "DOWN":
            rain_speed = min(0.25, rain_speed + 0.01)
        elif btn == "KEY1":
            filter_idx = (filter_idx + 1) % len(FILTER_NAMES)

        # Feed new packet data into columns
        for _ in range(min(3, len(pkt_queue))):
            _inject_from_queue()

        # Advance all column heads
        for col in columns:
            col.step()

        # Render
        frame = _render_frame()
        LCD.LCD_ShowImage(frame, 0, 0)

        elapsed = time.time() - t0
        sleep_t = max(0.0, rain_speed - elapsed)
        time.sleep(sleep_t)

    LCD.LCD_Clear()
    GPIO.cleanup()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Matrix Tap requires root (raw packet capture).", file=sys.stderr)
        sys.exit(1)
    main()
