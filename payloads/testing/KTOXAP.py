#!/usr/bin/env python3
# NAME: KTOXAP
# AUTHOR: wickednull
# DESC:  Start/stop a local Wi‑Fi AP with live LCD status.
#        Connect to KTOx‑Control / ktox-payload → http://192.168.4.1:8080

"""
KTOx Payload – Offline Access Point (toggle)
Use the LCD buttons:
    KEY3    – exit (AP stays alive)  … or stop if already running
    KEY1    – exit without stopping (when AP is active)
"""

import os
import time
import signal
import subprocess
import threading
from pathlib import Path

# ── Hardware (independent from ktox_device) ──────────────────────────────
try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("[KTOXAP] No hardware libs – headless mode")

PINS = {
    "KEY3": 16,      # stop / toggle
    "KEY1": 21,      # force‑exit without stopping (when AP active)
}

WIDTH, HEIGHT = 128, 128
BG       = (10, 0, 0)
HEADER   = (139, 0, 0)
ACCENT   = (231, 76, 60)
WHITE    = (255, 255, 255)
FG       = (171, 178, 185)
WARN     = (212, 172, 13)

LCD      = None
image    = None
draw     = None
FONT     = None
FONT_SM  = None

_debounce_last = 0.0

# ── Screen helpers ────────────────────────────────────────────────────────
def init_screen():
    global LCD, image, draw, FONT, FONT_SM
    if not HAS_HW:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(path):
            try:
                FONT = ImageFont.truetype(path, 10)
                FONT_SM = ImageFont.truetype(path, 8)
                return
            except:
                pass
    FONT = ImageFont.load_default()
    FONT_SM = ImageFont.load_default()

def cleanup_screen():
    if HAS_HW:
        try:
            LCD.LCD_Clear()
        except:
            pass
        try:
            GPIO.cleanup()
        except:
            pass

def is_button(pin_name):
    """Non‑blocking check for a button press."""
    if not HAS_HW:
        return False
    try:
        return GPIO.input(PINS[pin_name]) == 0
    except:
        return False

def redraw(ssid, ip, clients, stop_mode=False):
    """Update the LCD status page."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    # Header
    d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
    d.text((4, 2), "KTOXAP", font=FONT, fill=ACCENT)
    y = 20
    d.text((4, y), f"SSID: {ssid}", font=FONT, fill=WHITE)
    y += 14
    d.text((4, y), f"IP:   {ip}", font=FONT, fill=WHITE)
    y += 14
    d.text((4, y), "WebUI: 8080", font=FONT_SM, fill=ACCENT)
    y += 12
    d.text((4, y), "Shell:  4200", font=FONT_SM, fill=ACCENT)
    y += 16
    d.rectangle((4, y, 124, y+18), outline=ACCENT)
    d.text((8, y+2), f"Clients: {clients}", font=FONT, fill=WARN)
    y += 22
    # Footer – different depending on mode
    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    if stop_mode:
        d.text((4, HEIGHT-10), "KEY3=Stop  KEY1=Exit", font=FONT_SM, fill=ACCENT)
    else:
        d.text((4, HEIGHT-10), "KEY3=Exit (AP stays)", font=FONT_SM, fill=ACCENT)
    if HAS_HW:
        LCD.LCD_ShowImage(img, 0, 0)

# ── AP management ─────────────────────────────────────────────────────────
AP_SSID = "KTOx‑Control"
AP_PSK  = "ktox-payload"
AP_IP   = "192.168.4.1"
AP_IFACE = "wlan0"
PID_FILE = "/tmp/ktox_ap.pid"

def write_hostapd_conf():
    conf = f"""interface={AP_IFACE}
driver=nl80211
ssid={AP_SSID}
hw_mode=g
channel=6
wmm_enabled=0
auth_algs=1
wpa=2
wpa_passphrase={AP_PSK}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP""".strip()
    Path("/tmp/ktox_hostapd.conf").write_text(conf)

def write_dnsmasq_conf():
    conf = f"""interface={AP_IFACE}
bind-interfaces
server=8.8.8.8
domain-needed
bogus-priv
dhcp-range=192.168.4.50,192.168.4.150,12h""".strip()
    Path("/tmp/ktox_dnsmasq.conf").write_text(conf)

def start_ap_services():
    """Start hostapd + dnsmasq, return Popen objects (orphaned)."""
    for svc in ("NetworkManager", "wpa_supplicant"):
        subprocess.run(["systemctl", "stop", svc],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    write_hostapd_conf()
    write_dnsmasq_conf()

    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "addr", "add", f"{AP_IP}/24", "dev", AP_IFACE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "up"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["sysctl", "net.ipv4.ip_forward=1"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    dns = subprocess.Popen(["dnsmasq", "--conf-file=/tmp/ktox_dnsmasq.conf", "--no-daemon"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ap = subprocess.Popen(["hostapd", "/tmp/ktox_hostapd.conf"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Write PID file for later reference
    with open(PID_FILE, 'w') as f:
        f.write(f"{ap.pid}\n{dns.pid}")
    return ap, dns

def stop_ap_services():
    """Kill processes recorded in PID file and restore normal networking."""
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            lines = f.read().strip().split('\n')
        for line in lines:
            try:
                pid = int(line.strip())
                os.kill(pid, signal.SIGTERM)
            except:
                pass
        os.remove(PID_FILE)
    # Also try to kill by name
    subprocess.run(["pkill", "-9", "hostapd"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "dnsmasq"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "start", "NetworkManager"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "start", "wpa_supplicant"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for f in ("/tmp/ktox_hostapd.conf", "/tmp/ktox_dnsmasq.conf"):
        try: os.remove(f)
        except: pass

def get_client_count():
    try:
        out = subprocess.check_output(["iw", "dev", AP_IFACE, "station", "dump"],
                                      text=True, timeout=3)
        return out.count("Station")
    except:
        return 0

def is_ap_active():
    """Check if the AP is currently running (by PID file)."""
    if not os.path.exists(PID_FILE):
        return False
    with open(PID_FILE) as f:
        lines = f.read().strip().split('\n')
    # just check if first PID still exists
    try:
        pid = int(lines[0])
        os.kill(pid, 0)
        return True
    except:
        return False

# ── Payload logic ─────────────────────────────────────────────────────────
def main():
    init_screen()
    already_active = is_ap_active()

    if not already_active:
        # ─── Start AP ────────────────────────────────────────────────
        start_ap_services()
        time.sleep(2)   # let hostapd settle
        stop_mode = False
    else:
        # ─── Already running → show status + stop option ─────────────
        stop_mode = True

    # Live monitoring loop
    last_clients = -1
    try:
        while True:
            # check buttons
            if is_button("KEY3"):
                if stop_mode:
                    # Stop AP and then exit
                    stop_ap_services()
                    # Clear screen and exit
                    cleanup_screen()
                    return
                else:
                    # Exit without stopping
                    break
            if stop_mode and is_button("KEY1"):
                # Exit without stopping (leave AP alive)
                break

            # update screen
            clients = get_client_count()
            if clients != last_clients or last_clients == -1:
                redraw(AP_SSID, AP_IP, clients, stop_mode=stop_mode)
                last_clients = clients
            time.sleep(0.5)
    finally:
        # When exiting normally (not stopping), we just clean up the LCD;
        # the AP processes remain. On stop, they were already killed.
        cleanup_screen()

if __name__ == "__main__":
    main()
