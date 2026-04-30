#!/usr/bin/env python3
# NAME: KTOXAP
# AUTHOR: wickednull
# DESC:  Safe Offline AP – never restarts web services; uses iptables DNAT.
#
# Connects to KTOx‑Control (192.168.4.1/ktox-payload) to access:
#   • WebUI (8080) - Main dashboard
#   • WebSocket (8765) - Real-time communication
#   • WebShell (4200) - Terminal access
#
# Controls:
#   KEY3 - Exit (AP stays active) or Stop (when active)
#   KEY1 - Exit without stopping (when AP active)

import os, time, signal, subprocess, sys
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False

PINS = {"KEY3": 16, "KEY1": 21}
WIDTH, HEIGHT = 128, 128
BG = (10,0,0); HEADER = (139,0,0); ACCENT = (231,76,60)
WHITE = (255,255,255); FG = (171,178,185); WARN = (212,172,13); GOOD = (46, 204, 113)

LCD = image = draw = None
FONT = FONT_SM = None
LAST_BTN = {"KEY3": 0, "KEY1": 0}
DEBOUNCE_MS = 300

def init_screen():
    global LCD, image, draw, FONT, FONT_SM
    if not HAS_HW: return
    GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
    for p in PINS.values(): GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD(); LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    image = Image.new("RGB", (WIDTH, HEIGHT), BG); draw = ImageDraw.Draw(image)
    for fpath in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(fpath):
            try:
                FONT = ImageFont.truetype(fpath,10); FONT_SM = ImageFont.truetype(fpath,8)
                return
            except: pass
    FONT = ImageFont.load_default(); FONT_SM = ImageFont.load_default()

def cleanup_screen():
    if HAS_HW:
        try: LCD.LCD_Clear()
        except: pass
        try: GPIO.cleanup()
        except: pass

def is_button(pin):
    """Debounced button check (300ms debounce)."""
    if not HAS_HW: return False
    try:
        now = int(time.time() * 1000)
        if now - LAST_BTN.get(pin, 0) < DEBOUNCE_MS:
            return False
        if GPIO.input(PINS[pin]) == 0:
            LAST_BTN[pin] = now
            return True
        return False
    except:
        return False

def is_port_listening(port):
    """Check if a port is actively listening."""
    try:
        out = subprocess.check_output(["ss", "-tlnp"], text=True, timeout=2)
        return f":{port}" in out
    except:
        return False

def redraw(ssid, ip, clients, stop_mode=False):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,WIDTH,13), fill=HEADER)
    d.text((4,2), "KTOXAP", font=FONT, fill=ACCENT)
    y=20
    d.text((4,y), f"SSID: {ssid}", font=FONT, fill=WHITE); y+=14
    d.text((4,y), f"IP:   {ip}",   font=FONT, fill=WHITE); y+=14

    web_ok = is_port_listening(8080)
    ws_ok = is_port_listening(8765)
    shell_ok = is_port_listening(4200)

    web_color = GOOD if web_ok else WARN
    ws_color = GOOD if ws_ok else WARN
    shell_color = GOOD if shell_ok else WARN

    d.text((4,y), f"Web: {'✓' if web_ok else '✗'}", font=FONT_SM, fill=web_color); y+=12
    d.text((4,y), f"WS:  {'✓' if ws_ok else '✗'}", font=FONT_SM, fill=ws_color); y+=12
    d.text((4,y), f"Shell: {'✓' if shell_ok else '✗'}", font=FONT_SM, fill=shell_color); y+=14

    d.rectangle((4, y, 124, y+18), outline=ACCENT)
    d.text((8, y+2), f"Clients: {clients}", font=FONT, fill=WARN); y+=22
    d.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill=HEADER)
    if stop_mode:
        d.text((4, HEIGHT-10), "KEY3=Stop  KEY1=Exit", font=FONT_SM, fill=ACCENT)
    else:
        d.text((4, HEIGHT-10), "KEY3=Exit (AP stays)", font=FONT_SM, fill=ACCENT)
    if HAS_HW: LCD.LCD_ShowImage(img, 0, 0)

# ── iptables DNAT (no restart) ──────────────────────────────────
def add_redirect(ap_ip, port):
    """Add DNAT rule and FORWARD rule for port redirection."""
    try:
        rule = ["iptables", "-t", "nat", "-C", "PREROUTING",
                "-d", ap_ip, "-p", "tcp", "--dport", str(port),
                "-j", "DNAT", "--to-destination", f"127.0.0.1:{port}"]
        if subprocess.run(rule, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            subprocess.run(["iptables", "-t", "nat", "-A", "PREROUTING",
                            "-d", ap_ip, "-p", "tcp", "--dport", str(port),
                            "-j", "DNAT", "--to-destination", f"127.0.0.1:{port}"], check=True)
            print(f"[KTOXAP] Added DNAT rule for port {port}")
    except Exception as e:
        print(f"[KTOXAP] Warning: DNAT setup failed for {port}: {e}")

def del_redirect(ap_ip, port):
    """Remove DNAT rule for port."""
    try:
        subprocess.run(["iptables", "-t", "nat", "-D", "PREROUTING",
                        "-d", ap_ip, "-p", "tcp", "--dport", str(port),
                        "-j", "DNAT", "--to-destination", f"127.0.0.1:{port}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        print(f"[KTOXAP] Removed DNAT rule for port {port}")
    except:
        pass

# ── AP management (unchanged) ──────────────────────────────────
AP_SSID = "KTOx‑Control"
AP_PSK  = "ktox-payload"
AP_IP   = "192.168.4.1"
AP_IFACE = "wlan0"
PID_FILE = "/tmp/ktox_ap.pid"

def _has_systemd():
    """Check if system uses systemd as init."""
    return os.path.exists("/run/systemd/system")

def _stop_service(svc):
    """Stop a service using available method."""
    if _has_systemd():
        subprocess.run(["systemctl", "stop", svc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # If no systemd, just continue (service may not exist anyway)

def _start_service(svc):
    """Start a service using available method."""
    if _has_systemd():
        subprocess.run(["systemctl", "start", svc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
    """Start offline AP with DNAT routing."""
    print("[KTOXAP] Stopping conflicting services...")
    for svc in ("NetworkManager", "wpa_supplicant"):
        _stop_service(svc)
    subprocess.run(["ip", "link", "set", AP_IFACE, "down"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("[KTOXAP] Configuring AP interface...")
    write_hostapd_conf()
    write_dnsmasq_conf()

    subprocess.run(["ip", "addr", "flush", "dev", AP_IFACE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "addr", "add", f"{AP_IP}/24", "dev", AP_IFACE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", AP_IFACE, "up"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["sysctl", "-w", "net.ipv4.ip_forward=1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("[KTOXAP] Starting hostapd and dnsmasq...")
    dns = subprocess.Popen(["dnsmasq", "--conf-file=/tmp/ktox_dnsmasq.conf", "--no-daemon"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ap = subprocess.Popen(["hostapd", "/tmp/ktox_hostapd.conf"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(PID_FILE, 'w') as f:
        f.write(f"{ap.pid}\n{dns.pid}")

    print("[KTOXAP] Setting up port redirects (DNAT)...")
    add_redirect(AP_IP, 8080)
    add_redirect(AP_IP, 8765)
    add_redirect(AP_IP, 4200)
    print("[KTOXAP] AP ready! SSID: {} | Password: {}".format(AP_SSID, AP_PSK))

def stop_ap_services():
    del_redirect(AP_IP, 8080)
    del_redirect(AP_IP, 8765)
    del_redirect(AP_IP, 4200)

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
    print("[KTOXAP] Restoring network services...")
    _start_service("NetworkManager")
    _start_service("wpa_supplicant")
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

def main():
    print("[KTOXAP] Starting Offline AP mode...")
    init_screen()

    if is_ap_active():
        print("[KTOXAP] AP already active, entering stop mode...")
        stop_mode = True
    else:
        stop_mode = False
        print("[KTOXAP] Starting AP services...")
        start_ap_services()
        time.sleep(2)
        print("[KTOXAP] Waiting for services to stabilize...")
        time.sleep(2)

    last_clients = -1
    last_redraw = 0
    try:
        while True:
            now = time.time()

            if is_button("KEY3"):
                print("[KTOXAP] KEY3 pressed")
                if stop_mode:
                    print("[KTOXAP] Stopping AP...")
                    stop_ap_services()
                    cleanup_screen()
                    print("[KTOXAP] AP stopped. Exiting.")
                    return
                else:
                    print("[KTOXAP] Exiting (AP stays active)")
                    break

            if stop_mode and is_button("KEY1"):
                print("[KTOXAP] KEY1 pressed (exit without stop)")
                break

            clients = get_client_count()
            if clients != last_clients or (now - last_redraw) > 3:
                redraw(AP_SSID, AP_IP, clients, stop_mode=stop_mode)
                last_clients = clients
                last_redraw = now

            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n[KTOXAP] Interrupted by user")
    finally:
        cleanup_screen()
        print("[KTOXAP] Cleanup complete")

if __name__ == "__main__":
    main()
