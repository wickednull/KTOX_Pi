#!/usr/bin/env python3
"""
KTOx Payload: Hunter Core
Signal Hunter + Ghost Listener + AutoTrap
"""

import os
import time
import subprocess

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except:
    HAS_HW = False
    print("No hardware detected")

# ── CONFIG ─────────────────────────────────────────
W, H = 128, 128

PINS = {
    "UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,
    "OK":13,"KEY1":21,"KEY2":20,"KEY3":16
}

KNOWN_SSIDS = set()
PROBES = []
AUTO_TRAP = False

LCD = None
_draw = None
_image = None
_font = None

# ── INIT ───────────────────────────────────────────
def init_hw():
    global LCD, _draw, _image, _font

    if not HAS_HW:
        return

    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()

    _image = Image.new("RGB", (W,H), (10, 0, 0))
    _draw = ImageDraw.Draw(_image)
    _font = ImageFont.load_default()

def push():
    if HAS_HW:
        LCD.LCD_ShowImage(_image,0,0)

# ── UI ─────────────────────────────────────────────
def draw(lines, title="Hunter Core"):
    _draw.rectangle((0,0,W,H), fill=(10, 0, 0))
    _draw.rectangle((0,0,W,16), fill=(80,0,0))
    _draw.text((3,2), title, font=_font, fill=(231, 76, 60))

    y = 18
    for l in lines[:9]:
        _draw.text((3,y), l[:20], font=_font, fill="#FFCCCC")
        y += 11

    _draw.text((3,116),"K2=Trap K3=Exit", font=_font, fill="#FF8888")
    push()

# ── WIFI SCAN ──────────────────────────────────────
def scan_wifi():
    try:
        iface = subprocess.getoutput(
            "iw dev | grep Interface | awk '{print $2}'"
        ).splitlines()[0]

        raw = subprocess.getoutput(
            f"iwlist {iface} scanning | egrep 'ESSID|Signal level'"
        )

        nets = []
        lines = raw.splitlines()

        for i in range(0, len(lines), 2):
            try:
                ssid = lines[i].split(":")[1].replace('"','')
                sig = lines[i+1].split("=")[2]
                nets.append((ssid, sig))
            except:
                continue

        return nets
    except:
        return []

# ── GHOST LISTENER ─────────────────────────────────
def ghost_listener():
    try:
        iface = subprocess.getoutput(
            "iw dev | grep Interface | awk '{print $2}'"
        ).splitlines()[0]

        cmd = f"timeout 6 tcpdump -i {iface} -e -I -l type mgt subtype probe-req"

        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )

        found = []

        for line in proc.stdout:
            line = line.decode(errors="ignore")

            if "SSID" in line:
                try:
                    ssid = line.split("SSID")[1].strip().replace('"','')
                    if ssid and ssid not in PROBES:
                        PROBES.append(ssid)
                        found.append(ssid)
                except:
                    continue

        return found[:4] if found else []
    except:
        return []

# ── AUTOTRAP ───────────────────────────────────────
def auto_trap_engine():
    if not AUTO_TRAP:
        return []

    triggered = []

    for ssid in PROBES[-6:]:
        if ssid.lower() in ["wifi","home","guest","linksys","netgear"]:
            triggered.append(f"Trap:{ssid[:12]}")

            # 🔥 FUTURE HOOK:
            # launch_fake_ap(ssid)

    return triggered[:3]

# ── HELPERS ────────────────────────────────────────
def detect_new(networks):
    new = []
    for ssid, _ in networks:
        if ssid and ssid not in KNOWN_SSIDS:
            KNOWN_SSIDS.add(ssid)
            new.append(ssid)
    return new

def strongest(networks):
    if not networks:
        return "No signal"

    try:
        best = sorted(
            networks,
            key=lambda x: int(x[1].split()[0]),
            reverse=True
        )[0]
        return f"{best[0][:10]} {best[1]}"
    except:
        return "Signal err"

# ── MAIN ───────────────────────────────────────────
def main():
    global AUTO_TRAP

    init_hw()

    while True:
        nets = scan_wifi()
        new = detect_new(nets)
        probes = ghost_listener()
        traps = auto_trap_engine()

        lines = []

        if new:
            lines.append("NEW:")
            lines += [n[:16] for n in new[:2]]

        lines.append("Top:")
        lines.append(strongest(nets))

        if probes:
            lines.append("Probe:")
            lines += [p[:16] for p in probes[:2]]

        if traps:
            lines += traps

        status = "AUTO:ON" if AUTO_TRAP else "AUTO:OFF"
        lines.append(status)

        draw(lines)

        # BUTTONS
        if GPIO.input(PINS["KEY2"]) == 0:
            AUTO_TRAP = not AUTO_TRAP
            time.sleep(0.4)

        if GPIO.input(PINS["KEY3"]) == 0:
            break

        time.sleep(2)

    if HAS_HW:
        GPIO.cleanup()
        LCD.LCD_Clear()

if __name__ == "__main__":
    main()
