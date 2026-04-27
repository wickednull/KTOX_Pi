#!/usr/bin/env python3
"""
RaspyJack Payload -- WiFi Probe Request Dump
=============================================
Author: 7h30th3r0n3

Passive WiFi probe request logger.  Puts a USB WiFi dongle into
monitor mode and sniffs Dot11ProbeReq frames with scapy.  Builds a
dictionary of {MAC: set(SSIDs)} and displays live stats on the LCD.

Setup / Prerequisites
---------------------
- USB WiFi dongle with monitor mode support (e.g. Alfa AWUS036ACH)

Controls:
  UP / DOWN  -- Scroll device list
  KEY1       -- Start / Stop capture
  KEY2       -- Export to JSON loot
  KEY3       -- Exit

Loot: /root/KTOx/loot/ProbesDump/probes_YYYYMMDD_HHMMSS.json
"""

import os
import sys
import json
import time
import threading
import subprocess
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config
from PIL import Image, ImageDraw, ImageFont
from _display_helper import ScaledDraw, scaled_font
from _input_helper import get_button
from _debug_helper import log as _dbg

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)
from wifi.monitor_mode_helper import (
    activate_monitor_mode, deactivate_monitor_mode, find_monitor_capable_interface,
)

try:
    from scapy.all import Dot11, Dot11Elt, Dot11ProbeReq, sniff as scapy_sniff
    SCAPY_OK = True
except ImportError:
    SCAPY_OK = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
WIDTH, HEIGHT = LCD_1in44.LCD_WIDTH, LCD_1in44.LCD_HEIGHT
ROWS_VISIBLE = 7
ROW_H = 12

KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
LOOT_DIR = os.path.join(os.environ.get("KTOX_DIR", "/root/KTOx"), "loot", "ProbesDump")

# Channels to hop through (2.4 GHz)
CHANNELS_24 = list(range(1, 14))

# ---------------------------------------------------------------------------
# Shared state (protected by lock)
# ---------------------------------------------------------------------------
lock = threading.Lock()
probes = {}          # {mac_upper: set(ssid_strings)}
signal_map = {}      # {mac_upper: last_rssi}
running = False
scroll = 0
mon_iface = None


# ---------------------------------------------------------------------------
# Capture threads
# ---------------------------------------------------------------------------

def _hop_thread():
    """Channel hopper for 2.4 GHz bands."""
    idx = 0
    while running:
        if mon_iface:
            ch = CHANNELS_24[idx % len(CHANNELS_24)]
            try:
                subprocess.run(
                    ["sudo", "iw", "dev", mon_iface, "set", "channel", str(ch)],
                    capture_output=True, timeout=3)
            except Exception:
                pass
            idx += 1
        time.sleep(0.3)


def _packet_handler(pkt):
    """Scapy callback for each captured packet."""
    if not pkt.haslayer(Dot11ProbeReq):
        return
    dot = pkt[Dot11]
    src = dot.addr2
    if not src or src == "ff:ff:ff:ff:ff:ff":
        return

    ssid = ""
    if pkt.haslayer(Dot11Elt):
        try:
            raw = pkt[Dot11Elt].info
            if raw:
                ssid = raw.decode("utf-8", errors="ignore")
        except Exception:
            pass

    rssi = getattr(pkt, "dBm_AntSignal", None)
    mac = src.upper()

    with lock:
        if mac not in probes:
            probes[mac] = set()
        if ssid:
            probes[mac].add(ssid)
        if rssi is not None:
            signal_map[mac] = rssi


def _sniff_thread():
    """Scapy capture loop."""
    if not SCAPY_OK or not mon_iface:
        return
    try:
        scapy_sniff(
            iface=mon_iface,
            prn=_packet_handler,
            stop_filter=lambda _: not running,
            store=0,
        )
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _export_loot():
    """Write probe data to JSON loot file. Returns filename."""
    os.makedirs(LOOT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"probes_{ts}.json"
    filepath = os.path.join(LOOT_DIR, filename)

    with lock:
        data = {
            mac: {
                "ssids": sorted(ssids),
                "rssi": signal_map.get(mac),
            }
            for mac, ssids in probes.items()
        }

    with open(filepath, "w") as fh:
        json.dump(data, fh, indent=2)

    return filename

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _draw_frame(lcd, font):
    """Render current state to the LCD."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ScaledDraw(img)

    # Header
    d.rectangle((0, 0, 127, 13), fill=(10, 0, 0))
    d.text((2, 1), "PROBE DUMP", font=font, fill=(30, 132, 73))
    d.ellipse((118, 3, 122, 7), fill=(30, 132, 73) if running else "#FF0000")

    with lock:
        total_devs = len(probes)
        all_ssids = set()
        for ssids in probes.values():
            all_ssids.update(ssids)
        total_ssids = len(all_ssids)
        device_list = sorted(probes.items(), key=lambda kv: len(kv[1]), reverse=True)

    # Summary line
    d.text((2, 16), f"Dev:{total_devs}  SSID:{total_ssids}", font=font, fill=(171, 178, 185))

    # Scrollable device list
    visible = device_list[scroll:scroll + ROWS_VISIBLE]
    for i, (mac, ssids) in enumerate(visible):
        y = 28 + i * ROW_H
        short_mac = mac[-8:]
        ssid_preview = ", ".join(sorted(ssids))[:12] if ssids else "<hidden>"
        line = f"{short_mac} {ssid_preview}"
        d.text((2, y), line, font=font, fill=(242, 243, 244))

    # Scroll indicator
    total = len(device_list)
    if total > ROWS_VISIBLE:
        bar_h = max(4, int(ROWS_VISIBLE / total * 80))
        bar_y = 28 + int(scroll / total * 80)
        d.rectangle((126, bar_y, 127, bar_y + bar_h), fill=(34, 0, 0))

    # Footer
    d.rectangle((0, 116, 127, 127), fill=(10, 0, 0))
    status = "K1:Stop" if running else "K1:Start"
    d.text((2, 117), f"{status} K2:Exp K3:Quit", font=font, fill=(113, 125, 126))

    lcd.LCD_ShowImage(img, 0, 0)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global running, scroll, mon_iface

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD_Config.GPIO_Init()
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    lcd.LCD_Clear()
    font = scaled_font()

    # Splash
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ScaledDraw(img)
    d.text((8, 20), "WIFI PROBE DUMP", font=font, fill=(30, 132, 73))
    d.text((4, 40), "Passive probe logger", font=font, fill=(113, 125, 126))
    d.text((4, 60), "KEY1  Start / Stop", font=font, fill=(86, 101, 115))
    d.text((4, 72), "KEY2  Export JSON", font=font, fill=(86, 101, 115))
    d.text((4, 84), "KEY3  Exit", font=font, fill=(86, 101, 115))
    d.text((4, 96), "U/D   Scroll list", font=font, fill=(86, 101, 115))
    lcd.LCD_ShowImage(img, 0, 0)

    try:
        while True:
            btn = get_button(PINS, GPIO)

            if btn == "KEY3":
                break

            elif btn == "KEY1":
                if running:
                    running = False
                    time.sleep(0.5)
                else:
                    if not mon_iface:
                        raw = find_monitor_capable_interface()
                        if raw:
                            mon_iface = activate_monitor_mode(raw)
                    if mon_iface:
                        running = True
                        threading.Thread(target=_hop_thread, daemon=True).start()
                        threading.Thread(target=_sniff_thread, daemon=True).start()
                    else:
                        img2 = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
                        d2 = ScaledDraw(img2)
                        d2.text((4, 50), "No USB WiFi found!", font=font, fill=(231, 76, 60))
                        lcd.LCD_ShowImage(img2, 0, 0)
                        time.sleep(1.5)
                time.sleep(0.3)

            elif btn == "KEY2":
                fname = _export_loot()
                img2 = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
                d2 = ScaledDraw(img2)
                d2.text((4, 50), "Exported!", font=font, fill=(30, 132, 73))
                d2.text((4, 65), fname[:22], font=font, fill=(113, 125, 126))
                lcd.LCD_ShowImage(img2, 0, 0)
                time.sleep(1.5)

            elif btn == "UP":
                scroll = max(0, scroll - 1)
                time.sleep(0.15)

            elif btn == "DOWN":
                with lock:
                    max_scroll = max(0, len(probes) - ROWS_VISIBLE)
                scroll = min(scroll + 1, max_scroll)
                time.sleep(0.15)

            _draw_frame(lcd, font)
            time.sleep(0.05)

    finally:
        running = False
        time.sleep(0.3)
        deactivate_monitor_mode(mon_iface)
        try:
            lcd.LCD_Clear()
        except Exception:
            pass
        GPIO.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
