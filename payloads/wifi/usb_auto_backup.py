#!/usr/bin/env python3
"""
KTOx payload - USB Auto Backup
================================
Ported from Raspyjack by 7h30th3r0n3.
Watches for USB drive insertion and automatically backs up all loot
(/root/KTOx/loot/) to the drive. Shows progress on LCD.

Features:
- Auto-detects USB mass storage device insertion via udev/lsblk
- Mounts the drive automatically
- Copies all loot files preserving directory structure
- Shows file count and progress on LCD
- Safely unmounts when done
- Notifies via Discord webhook on completion

Controls:
- KEY3: exit
"""
import sys, os, time, subprocess, threading, json
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
LOOT_DIR  = "/root/KTOx/loot"
MOUNT_PT  = "/mnt/ktox_backup"
WEBHOOK_F = "/root/KTOx/discord_webhook.txt"
W, H = 128, 128

os.makedirs(MOUNT_PT, exist_ok=True)


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
    except Exception:
        return ""


def notify(msg):
    url = get_webhook()
    if not url:
        return
    try:
        import requests
        requests.post(url, json={"content": f"**[KTOx Backup]** {msg}"}, timeout=5)
    except Exception:
        pass


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

    def show(self, title, lines, col="#00ff88"):
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


def find_usb():
    out = run("lsblk -rpo NAME,TRAN,TYPE | grep -E 'usb.*disk'")
    if not out:
        return None
    dev = out.split()[0]
    # Find first partition
    parts = run(f"lsblk -rpo NAME,TYPE {dev} | grep part")
    if parts:
        return parts.split()[0]
    return dev


def count_loot():
    total = 0
    for root, _, files in os.walk(LOOT_DIR):
        total += len(files)
    return total


def do_backup(dev, disp):
    disp.show("MOUNTING", [f"Device: {dev}", "Please wait..."])
    run(f"mount {dev} {MOUNT_PT} 2>/dev/null")

    # Check mount worked
    if not run(f"mountpoint -q {MOUNT_PT}; echo $?") == "0":
        # Try with vfat
        run(f"mount -t vfat {dev} {MOUNT_PT} 2>/dev/null")

    dest = os.path.join(MOUNT_PT, f"ktox_loot_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(dest, exist_ok=True)

    total = count_loot()
    disp.show("BACKING UP", [
        f"Files: {total}",
        f"Dest: {dest[-20:]}",
        "Copying..."
    ])

    result = run(f"cp -r {LOOT_DIR}/. {dest}/ 2>&1", timeout=120)
    copied = count_loot()

    disp.show("SYNCING", ["Flushing to disk...", "Do not remove USB"])
    run("sync", timeout=30)
    run(f"umount {MOUNT_PT}", timeout=10)

    msg = f"Backup complete: {copied} files → {dest}"
    notify(msg)
    disp.show("BACKUP DONE", [
        f"{copied} files copied",
        "USB safe to remove",
        "",
        "KEY3 to exit"
    ], col="#00ff88")
    return True


def main():
    disp = Display()
    disp.show("USB BACKUP", [
        "Waiting for USB...",
        "",
        "Insert USB drive",
        "to start backup",
        "",
        "KEY3=exit"
    ])

    try:
        while True:
            if disp.btn() == "KEY3":
                break

            dev = find_usb()
            if dev:
                disp.show("USB FOUND", [f"Device: {dev}", "Starting backup..."])
                time.sleep(1)
                do_backup(dev, disp)
                # Wait for KEY3 after backup
                while disp.btn() != "KEY3":
                    time.sleep(0.1)
                break

            time.sleep(2)

    except KeyboardInterrupt:
        pass
    finally:
        if HAS_HW:
            try: GPIO.cleanup()
            except: pass
        print("[USBBackup] Exited.")


if __name__ == "__main__":
    main()
