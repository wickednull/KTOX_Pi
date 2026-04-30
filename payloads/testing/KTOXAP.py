#!/usr/bin/env python3
# NAME: KTOXAP
# Author: wickednull
"""
KTOx Payload – Broadcast a local Wi‑Fi network so you can access the WebUI
even without any existing connection.

After launch, connect to:
    SSID:      KTOx‑Control
    Password:  ktox-payload
Then visit  http://192.168.4.1:8080

The LCD shows the SSID, IP, and connected client count.
Press KEY3 at any time to stop the AP and restore normal Wi‑Fi.
"""

import os
import sys
import time
import signal
import subprocess
import threading
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# Hardware initialisation (independent from KTOx main process)
# ══════════════════════════════════════════════════════════════════════════════

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("[OFFLINE_AP] Hardware libs missing – headless mode")

PINS = {
    "KEY3": 16,      # the only button we really need
    "KEY2": 20,      # optionally we could use KEY2 as well
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

def init_screen():
    global LCD, image, draw, FONT, FONT_SM
    if not HAS_HW:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(PINS["KEY3"], GPIO.IN, pull_up_down=GPIO.PUD_UP)
    # optionally KEY2
    GPIO.setup(PINS["KEY2"], GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # load fonts
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(path):
            try:
                FONT = ImageFont.truetype(path, 10)
                FONT_SM = ImageFont.truetype(path, 8)
                return
            except Exception:
                pass
    FONT = ImageFont.load_default()
    FONT_SM = ImageFont.load_default()

def cleanup_screen():
    if HAS_HW:
        try:
            LCD.LCD_Clear()
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass

def is_key3_pressed():
    """Non‑blocking check for KEY3 (physical button)."""
    if not HAS_HW:
        return False
    try:
        return GPIO.input(PINS["KEY3"]) == 0
    except Exception:
        return False

def redraw(ssid, ip, clients, running=True):
    """Paint the LCD status page."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    # header
    d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
    d.text((4, 2), "OFFLINE AP", font=FONT, fill=ACCENT)
    # content
    y = 22
    d.text((6, y), "SSID:", font=FONT, fill=FG)
    d.text((40, y), ssid, font=FONT, fill=WHITE)
    y += 14
    d.text((6, y), "IP:  ", font=FONT, fill=FG)
    d.text((40, y), ip, font=FONT, fill=WHITE)
    y += 14
    d.text((6, y), "WEBUI:", font=FONT, fill=FG)
    d.text((40, y), f"http://{ip}:8080", font=FONT_SM, fill=ACCENT)
    y += 16
    d.text((6, y), "Shell:", font=FONT, fill=FG)
    d.text((40, y), f"http://{ip}:4200", font=FONT_SM, fill=ACCENT)
    y += 16
    d.rectangle((6, y, 122, y+20), outline=ACCENT)
    d.text((10, y+2), f"Clients: {clients}", font=FONT, fill=WARN)
    y += 26
    # footer
    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    d.text((4, HEIGHT-10), "KEY3 to stop", font=FONT_SM, fill=ACCENT)

    if HAS_HW:
        LCD.LCD_ShowImage(img, 0, 0)

# ══════════════════════════════════════════════════════════════════════════════
# AP management
# ══════════════════════════════════════════════════════════════════════════════

AP_SSID   = "KTOx‑Control"
AP_PSK    = "ktox-payload"
AP_IP     = "192.168.4.1"
AP_NET    = "192.168.4.0/24"
AP_IFACE  = "wlan0"
AP_CHANNEL = 6

def kill_existing_services():
    """Stop anything that might hold wlan0 (NetworkManager, wpa_supplicant)."""
    for svc in ("NetworkManager", "wpa_supplicant"):
        subprocess.run(["systemctl", "stop", svc],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Make sure the interface is down
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def restore_services():
    """Bring back normal Wi‑Fi management."""
    subprocess.run(["systemctl", "start", "NetworkManager"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "start", "wpa_supplicant"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def write_hostapd_conf():
    conf_path = "/tmp/ktox_hostapd.conf"
    conf = f"""
interface={AP_IFACE}
driver=nl80211
ssid={AP_SSID}
hw_mode=g
channel={AP_CHANNEL}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase={AP_PSK}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
"""
    Path(conf_path).write_text(conf.strip())
    return conf_path

def write_dnsmasq_conf():
    conf_path = "/tmp/ktox_dnsmasq.conf"
    conf = f"""
interface={AP_IFACE}
bind-interfaces
server=8.8.8.8
domain-needed
bogus-priv
dhcp-range=192.168.4.50,192.168.4.150,12h
"""
    Path(conf_path).write_text(conf.strip())
    return conf_path

def get_client_count():
    try:
        out = subprocess.check_output(["iw", "dev", AP_IFACE, "station", "dump"],
                                      text=True, timeout=3)
        # count lines that start with "Station"
        return out.count("Station")
    except Exception:
        return 0

def start_ap():
    # Write configs
    hostapd_conf = write_hostapd_conf()
    dnsmasq_conf = write_dnsmasq_conf()

    # Kill conflicting services and prepare interface
    kill_existing_services()

    # Set static IP
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "addr", "add", f"{AP_IP}/24", "dev", AP_IFACE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "up"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Enable forwarding (optional, for internet passthrough if you have eth0)
    subprocess.run(["sysctl", "net.ipv4.ip_forward=1"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Start dnsmasq
    dns_proc = subprocess.Popen(
        ["dnsmasq", "--conf-file=" + dnsmasq_conf, "--no-daemon"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Start hostapd (foreground)
    ap_proc = subprocess.Popen(
        ["hostapd", hostapd_conf],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    return ap_proc, dns_proc

def ensure_web_services():
    """Ensure the KTOx web server and shell server are running."""
    # The main ktox_device.py already starts these on boot, but double-check.
    # We'll start them if they're not already listening.
    def start_if_missing(name, port):
        if subprocess.run(["ss", "-tlnp", f"\"sport = :{port}\""],
                          shell=True, stdout=subprocess.DEVNULL).returncode != 0:
            path = f"/root/KTOx/{name}"
            if os.path.exists(path):
                subprocess.Popen(["python3", path],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    start_if_missing("web_server.py", 8080)
    start_if_missing("shell_server.py", 4200)   # WebShell, if present

# ══════════════════════════════════════════════════════════════════════════════
# Main payload flow
# ══════════════════════════════════════════════════════════════════════════════

def main():
    init_screen()
    redraw("Starting...", "---", 0, running=False)   # temporary screen

    ap_proc, dns_proc = start_ap()
    ensure_web_services()

    # Show active screen
    redraw(AP_SSID, AP_IP, 0)

    # Monitor loop
    last_clients = -1
    try:
        while True:
            time.sleep(1)

            # Check KEY3 to stop
            if is_key3_pressed():
                break

            # Update client count on LCD (only if changed)
            clients = get_client_count()
            if clients != last_clients:
                redraw(AP_SSID, AP_IP, clients)
                last_clients = clients

            # If hostapd dies, exit
            if ap_proc.poll() is not None:
                redraw("AP FAILED", AP_IP, 0)
                time.sleep(3)
                break
    except KeyboardInterrupt:
        pass
    finally:
        # Clean shutdown
        print("[OFFLINE_AP] Shutting down...")
        if ap_proc and ap_proc.poll() is None:
            ap_proc.terminate()
            try: ap_proc.wait(timeout=5)
            except: ap_proc.kill()
        if dns_proc and dns_proc.poll() is None:
            dns_proc.terminate()
            try: dns_proc.wait(timeout=5)
            except: dns_proc.kill()

        # Restore original networking
        subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["ip", "link", "set", AP_IFACE, "down"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        restore_services()
        # Remove temp configs
        try: os.remove("/tmp/ktox_hostapd.conf")
        except: pass
        try: os.remove("/tmp/ktox_dnsmasq.conf")
        except: pass

        cleanup_screen()

if __name__ == "__main__":
    main()
