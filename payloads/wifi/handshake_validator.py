#!/usr/bin/env python3
"""
KTOx payload - Handshake Validator
=====================================
Ported from Raspyjack by 7h30th3r0n3.
Scans all .cap files in the loot directory, validates which ones
contain genuine 4-way WPA handshakes, and shows a summary on the LCD.
Bad captures are flagged. Good ones are ready for cracking.

Controls:
- UP/DOWN: scroll results
- KEY1: delete selected bad cap
- KEY2: send selected cap path to console
- KEY3: exit
"""
import sys, os, time, subprocess, glob
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
LOOT_DIR = "/root/KTOx/loot"
W, H = 128, 128


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout + r.stderr
    except Exception:
        return ""


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
        img  = Image.new("RGB", (W, H), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, W, 14), fill="#004488")
        draw.text((3, 2), title[:20], fill="white", font=font(9))
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


def validate_cap(path):
    out = run(f"aircrack-ng {path} 2>/dev/null")
    if "handshake" in out.lower():
        return True
    if "0 handshake" in out:
        return False
    # Also check with tshark if available
    if run("which tshark"):
        t = run(f"tshark -r {path} -Y 'eapol' -T fields -e eapol.type 2>/dev/null")
        if t.strip():
            return True
    return False


def scan_caps(disp):
    disp.show("SCANNING", ["Searching loot...", "Please wait"])
    caps = glob.glob(f"{LOOT_DIR}/**/*.cap", recursive=True)
    caps += glob.glob(f"{LOOT_DIR}/**/*.pcap", recursive=True)
    results = []
    for i, cap in enumerate(caps):
        name = os.path.basename(cap)
        disp.show("VALIDATING", [
            f"{i+1}/{len(caps)}",
            f"{name[:20]}",
            "Checking..."
        ])
        valid = validate_cap(cap)
        size  = os.path.getsize(cap) // 1024
        results.append({
            "path": cap, "name": name,
            "valid": valid, "size": size
        })
    return results


def main():
    disp = Display()
    disp.show("HS VALIDATOR", ["Scanning loot...", "Please wait"])

    results = scan_caps(disp)

    if not results:
        disp.show("NO CAPS FOUND", [
            "No .cap/.pcap files",
            f"in {LOOT_DIR}",
            "",
            "KEY3=exit"
        ], col="#ff8800")
        while disp.btn() != "KEY3":
            time.sleep(0.1)
        return

    good  = [r for r in results if r["valid"]]
    bad   = [r for r in results if not r["valid"]]
    all_r = good + bad
    cursor = 0

    while True:
        r = all_r[cursor]
        status = "VALID" if r["valid"] else "NO HS"
        col    = "#00ff88" if r["valid"] else "#ff4444"
        disp.show(f"[{cursor+1}/{len(all_r)}] {status}", [
            r["name"][:20],
            r["path"][-20:],
            f"Size: {r['size']}KB",
            "",
            f"Good:{len(good)} Bad:{len(bad)}",
            "KEY1=delete KEY3=exit",
        ], col=col)

        btn = None
        for _ in range(20):
            btn = disp.btn()
            if btn: break
            time.sleep(0.05)

        if btn == "UP":
            cursor = (cursor - 1) % len(all_r)
            time.sleep(0.2)
        elif btn == "DOWN":
            cursor = (cursor + 1) % len(all_r)
            time.sleep(0.2)
        elif btn == "KEY1" and not r["valid"]:
            try:
                os.remove(r["path"])
                all_r.pop(cursor)
                if not all_r:
                    break
                cursor = min(cursor, len(all_r) - 1)
                disp.show("DELETED", [r["name"][:20]])
                time.sleep(1)
            except Exception as e:
                disp.show("DELETE FAIL", [str(e)[:40]], col="#ff4444")
                time.sleep(1)
        elif btn == "KEY3":
            break

    if HAS_HW:
        try: GPIO.cleanup()
        except: pass
    print(f"[Validator] Done. Good: {len(good)}, Bad: {len(bad)}")


if __name__ == "__main__":
    main()
