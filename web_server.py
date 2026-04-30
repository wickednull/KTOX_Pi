#!/usr/bin/env python3
# NAME: KTOXAP
# AUTHOR: wickednull
# DESC:  Offline Access Point – restarts web services on the new AP IP so WebUI works.
#        Connect to KTOx‑Control / ktox-payload → http://192.168.4.1:8080

"""
KEY3 – exit (AP stays alive)  … or stop if already running.
KEY1 – exit without stopping (when AP is active).
"""

import os, time, signal, subprocess
from pathlib import Path

# ── Hardware (independent from ktox_device) ──────────────────────────────
try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False

PINS = {"KEY3": 16, "KEY1": 21}
WIDTH, HEIGHT = 128, 128
BG = (10, 0, 0); HEADER = (139, 0, 0); ACCENT = (231, 76, 60)
WHITE = (255, 255, 255); FG = (171, 178, 185); WARN = (212, 172, 13); GOOD = (46, 204, 113)

LCD = image = draw = None
FONT = FONT_SM = None

def init_screen():
    global LCD, image, draw, FONT, FONT_SM
    if not HAS_HW: return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    for fpath in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(fpath):
            try:
                FONT = ImageFont.truetype(fpath, 10)
                FONT_SM = ImageFont.truetype(fpath, 8)
                return
            except: pass
    FONT = ImageFont.load_default(); FONT_SM = ImageFont.load_default()

def cleanup_screen():
    if HAS_HW:
        try: LCD.LCD_Clear()
        except: pass
        try: GPIO.cleanup()
        except: pass

def is_button(pin_name):
    if not HAS_HW: return False
    try: return GPIO.input(PINS[pin_name]) == 0
    except: return False

# ── LCD drawing ──────────────────────────────────────────────────────────
def redraw(ssid, ip, clients, web_ok, ws_ok, stop_mode=False):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,WIDTH,13), fill=HEADER)
    d.text((4,2), "KTOXAP", font=FONT, fill=ACCENT)
    y = 20
    d.text((4,y), f"SSID: {ssid}", font=FONT, fill=WHITE)
    y += 14
    d.text((4,y), f"IP:   {ip}", font=FONT, fill=WHITE)
    y += 14
    d.text((4,y), f"Web: {':8080' if web_ok else 'DOWN'}", font=FONT_SM, fill=GOOD if web_ok else ACCENT)
    y += 12
    d.text((4,y), f"WS:  {':8765' if ws_ok else 'DOWN'}", font=FONT_SM, fill=GOOD if ws_ok else ACCENT)
    y += 16
    d.rectangle((4, y, 124, y+18), outline=ACCENT)
    d.text((8, y+2), f"Clients: {clients}", font=FONT, fill=WARN)
    y += 22
    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    if stop_mode:
        d.text((4, HEIGHT-10), "KEY3=Stop  KEY1=Exit", font=FONT_SM, fill=ACCENT)
    else:
        d.text((4, HEIGHT-10), "KEY3=Exit (AP stays)", font=FONT_SM, fill=ACCENT)
    if HAS_HW: LCD.LCD_ShowImage(img, 0, 0)

# ── Web service control ──────────────────────────────────────────────────
KTOX_PATH = "/root/KTOx"

def kill_web_services():
    subprocess.run(["pkill", "-f", "web_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "device_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # give processes time to release ports
    time.sleep(2)

def start_web_services():
    env = os.environ.copy()
    env["KTOX_PAYLOAD"] = "0"   # avoid payload hijack
    for srv, port in [("web_server.py", 8080), ("device_server.py", 8765)]:
        path = os.path.join(KTOX_PATH, srv)
        if os.path.exists(path):
            subprocess.Popen(["python3", path], cwd=KTOX_PATH, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)   # let it bind

def is_port_listening(port):
    try:
        out = subprocess.check_output(["ss", "-tlnp"], text=True)
        return f":{port}" in out
    except: return False

# ── AP management ───────────────────────────────────────────────────────
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
    for svc in ("NetworkManager", "wpa_supplicant"):
        subprocess.run(["systemctl", "stop", svc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    write_hostapd_conf()
    write_dnsmasq_conf()

    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "addr", "add", f"{AP_IP}/24", "dev", AP_IFACE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "up"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["sysctl", "net.ipv4.ip_forward=1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    dns = subprocess.Popen(["dnsmasq", "--conf-file=/tmp/ktox_dnsmasq.conf", "--no-daemon"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ap = subprocess.Popen(["hostapd", "/tmp/ktox_hostapd.conf"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(PID_FILE, 'w') as f:
        f.write(f"{ap.pid}\n{dns.pid}")

def stop_ap_services():
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            lines = f.read().strip().split('\n')
        for line in lines:
            try: os.kill(int(line.strip()), signal.SIGTERM)
            except: pass
        os.remove(PID_FILE)
    subprocess.run(["pkill", "-9", "hostapd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "dnsmasq"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "start", "NetworkManager"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "start", "wpa_supplicant"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for f in ("/tmp/ktox_hostapd.conf", "/tmp/ktox_dnsmasq.conf"):
        try: os.remove(f)
        except: pass

def get_client_count():
    try:
        out = subprocess.check_output(["iw", "dev", AP_IFACE, "station", "dump"], text=True, timeout=3)
        return out.count("Station")
    except: return 0

def is_ap_active():
    if not os.path.exists(PID_FILE): return False
    with open(PID_FILE) as f:
        lines = f.read().strip().split('\n')
    try:
        os.kill(int(lines[0]), 0)
        return True
    except: return False

# ── Main toggle ────────────────────────────────────────────────────────
def main():
    init_screen()

    if is_ap_active():
        stop_mode = True
    else:
        stop_mode = False
        # 1. Kill old web services so they release old IP bindings
        kill_web_services()
        # 2. Start AP
        start_ap_services()
        time.sleep(2)   # let hostapd settle
        # 3. Start fresh web services (now AP IP is available)
        start_web_services()
        # Wait a moment for ports to come up
        time.sleep(3)

    last_clients = -1
    try:
        while True:
            if is_button("KEY3"):
                if stop_mode:
                    stop_ap_services()
                    cleanup_screen()
                    return
                else:
                    break   # exit without stopping
            if stop_mode and is_button("KEY1"):
                break       # exit without stopping

            clients = get_client_count()
            web_ok = is_port_listening(8080)
            ws_ok  = is_port_listening(8765)
            if clients != last_clients or True:   # refresh every cycle
                redraw(AP_SSID, AP_IP, clients, web_ok, ws_ok, stop_mode)
                last_clients = clients
            time.sleep(0.6)
    finally:
        cleanup_screen()

if __name__ == "__main__":
    main()
