#!/usr/bin/env python3
# NAME: KTOXAP
# Author: wickednull
"""
KTOx Payload – Launch a local Wi‑Fi network with the full KTOx WebUI.
No internet needed. Connect to 'KTOx‑Control' / ktox-payload
Then visit:
   http://192.168.4.1:8080   (dashboard)
   http://192.168.4.1:4200   (web shell)
The LCD shows SSID, IP, and connected clients. Press KEY3 to stop.
"""

import os, sys, time, signal, subprocess, threading
from pathlib import Path

# ---------- hardware (independent from main ktox process) ----------
try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False

PINS = {"KEY3": 16, "KEY2": 20}

WIDTH, HEIGHT = 128, 128
BG = (10, 0, 0); HEADER = (139, 0, 0); ACCENT = (231, 76, 60)
WHITE = (255, 255, 255); FG = (171, 178, 185); WARN = (212, 172, 13)

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
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(path):
            try:
                FONT = ImageFont.truetype(path, 10)
                FONT_SM = ImageFont.truetype(path, 8)
                return
            except: pass
    FONT = ImageFont.load_default()
    FONT_SM = ImageFont.load_default()

def cleanup_screen():
    if HAS_HW:
        try: LCD.LCD_Clear()
        except: pass
        try: GPIO.cleanup()
        except: pass

def is_key3_pressed():
    if not HAS_HW: return False
    try: return GPIO.input(PINS["KEY3"]) == 0
    except: return False

def redraw(ssid, ip, clients):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,WIDTH,13), fill=HEADER)
    d.text((4,2), "OFFLINE AP", font=FONT, fill=ACCENT)
    y = 22
    d.text((6,y), "SSID:", font=FONT, fill=FG)
    d.text((42,y), ssid, font=FONT, fill=WHITE)
    y += 14
    d.text((6,y), "IP:", font=FONT, fill=FG)
    d.text((42,y), ip, font=FONT, fill=WHITE)
    y += 14
    d.text((6,y), "WebUI:", font=FONT, fill=FG)
    d.text((42,y), f"http://{ip}:8080", font=FONT_SM, fill=ACCENT)
    y += 14
    d.text((6,y), "Shell:", font=FONT, fill=FG)
    d.text((42,y), f"http://{ip}:4200", font=FONT_SM, fill=ACCENT)
    y += 16
    d.rectangle((6, y, 122, y+20), outline=ACCENT)
    d.text((10, y+2), f"Clients: {clients}", font=FONT, fill=WARN)
    y += 26
    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    d.text((4, HEIGHT-10), "KEY3 to stop", font=FONT_SM, fill=ACCENT)
    if HAS_HW: LCD.LCD_ShowImage(img, 0, 0)

# ---------- web service control (KTOx specific) ----------
INSTALL_PATH = "/root/KTOx"

def kill_port(port):
    """Kill any process listening on a given TCP port."""
    try:
        subprocess.run(["fuser", "-k", f"{port}/tcp"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

def start_web_services():
    """Stop any old instances and start fresh ones bound to 0.0.0.0."""
    # list of (script_name, port)
    services = [
        ("web_server.py", 8080),
        ("device_server.py", 8765),
        ("shell_server.py", 4200),
    ]
    procs = []
    for script, port in services:
        script_path = os.path.join(INSTALL_PATH, script)
        if not os.path.exists(script_path):
            print(f"[OFFLINE_AP] skipping {script} (not found)")
            continue
        kill_port(port)
        # Wait a moment for port to be freed
        time.sleep(0.5)
        # Launch new instance
        env = os.environ.copy()
        env["KTOX_PAYLOAD"] = "0"   # avoid payload hijack
        try:
            p = subprocess.Popen(
                ["python3", script_path],
                cwd=INSTALL_PATH,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            procs.append(p)
            print(f"[OFFLINE_AP] started {script} on port {port}")
        except Exception as e:
            print(f"[OFFLINE_AP] failed to start {script}: {e}")
    return procs

def stop_web_services(procs):
    """Terminate the fresh instances."""
    for p in procs:
        if p.poll() is None:
            p.terminate()
            try: p.wait(timeout=3)
            except: p.kill()
    # Also kill anything left on those ports
    for port in (8080, 8765, 4200):
        kill_port(port)

# ---------- AP management ----------
AP_SSID = "KTOx‑Control"
AP_PSK  = "ktox-payload"
AP_IP   = "192.168.4.1"
AP_IFACE = "wlan0"

def kill_network_managers():
    for svc in ("NetworkManager", "wpa_supplicant"):
        subprocess.run(["systemctl", "stop", svc],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def restore_network_managers():
    subprocess.run(["systemctl", "start", "NetworkManager"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "start", "wpa_supplicant"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def write_hostapd_conf():
    conf = f"""
interface={AP_IFACE}
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
rsn_pairwise=CCMP
""".strip()
    Path("/tmp/ktox_hostapd.conf").write_text(conf)

def write_dnsmasq_conf():
    conf = f"""
interface={AP_IFACE}
bind-interfaces
server=8.8.8.8
domain-needed
bogus-priv
dhcp-range=192.168.4.50,192.168.4.150,12h
""".strip()
    Path("/tmp/ktox_dnsmasq.conf").write_text(conf)

def get_client_count():
    try:
        out = subprocess.check_output(["iw", "dev", AP_IFACE, "station", "dump"],
                                      text=True, timeout=3)
        return out.count("Station")
    except: return 0

def start_ap():
    write_hostapd_conf()
    write_dnsmasq_conf()
    kill_network_managers()
    # set static IP
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
    return ap, dns

def stop_ap(ap_proc, dns_proc):
    if ap_proc and ap_proc.poll() is None:
        ap_proc.terminate()
        try: ap_proc.wait(timeout=5)
        except: ap_proc.kill()
    if dns_proc and dns_proc.poll() is None:
        dns_proc.terminate()
        try: dns_proc.wait(timeout=5)
        except: dns_proc.kill()
    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    restore_network_managers()
    for f in ("/tmp/ktox_hostapd.conf", "/tmp/ktox_dnsmasq.conf"):
        try: os.remove(f)
        except: pass

# ---------- main ----------
def main():
    init_screen()
    redraw("Starting...", "---", 0)   # temporary

    # 1. bring up access point
    ap_proc, dns_proc = start_ap()
    time.sleep(2)   # give hostapd a moment to initialise

    # 2. (re)start web services
    web_procs = start_web_services()

    # 3. show live status
    last_clients = -1
    try:
        while True:
            time.sleep(1)
            if is_key3_pressed():
                break
            if ap_proc.poll() is not None:
                redraw("AP FAILED", AP_IP, 0)
                time.sleep(3)
                break
            clients = get_client_count()
            if clients != last_clients:
                redraw(AP_SSID, AP_IP, clients)
                last_clients = clients
    except KeyboardInterrupt:
        pass
    finally:
        # 4. clean shutdown
        print("[OFFLINE_AP] Stopping...")
        stop_web_services(web_procs)
        stop_ap(ap_proc, dns_proc)
        cleanup_screen()

if __name__ == "__main__":
    main()
