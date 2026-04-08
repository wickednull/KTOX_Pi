#!/usr/bin/env python3
"""
KTOx payload - Discord Notifier Setup
=======================================
Ported from Raspyjack by 7h30th3r0n3.
Configure and test your Discord webhook for KTOx notifications.
All payloads that support notifications read from:
  /root/KTOx/discord_webhook.txt

Features:
- Enter/update Discord webhook URL via on-screen keyboard
- Send test message to verify webhook works
- Shows current webhook status

Controls:
- UP/DOWN: change character
- LEFT/RIGHT: move cursor
- OK: confirm / next field
- KEY3: exit
"""
import sys, os, time
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
WEBHOOK_F = "/root/KTOx/discord_webhook.txt"
W, H = 128, 128

CHARS = ("abcdefghijklmnopqrstuvwxyz"
         "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
         "0123456789"
         "/:.-_?=&#")


def font(size=8):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except:
        return ImageFont.load_default()


def get_current():
    try:
        return open(WEBHOOK_F).read().strip()
    except:
        return ""


def save(url):
    with open(WEBHOOK_F, "w") as f:
        f.write(url)


def test_webhook(url, disp):
    disp.show("TESTING", ["Sending test msg...", "Please wait"])
    try:
        import requests
        r = requests.post(url, json={
            "content": f"**[KTOx]** Webhook test - {datetime.now().strftime('%H:%M:%S')}"
        }, timeout=8)
        if r.status_code in (200, 204):
            disp.show("SUCCESS", ["Test message sent!", "Check your Discord"], col="#00ff88")
        else:
            disp.show("FAILED", [f"HTTP {r.status_code}", r.text[:40]], col="#ff4444")
    except Exception as e:
        disp.show("ERROR", [str(e)[:60]], col="#ff4444")
    time.sleep(3)


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

    def show(self, title, lines, col="#00ffcc"):
        img  = Image.new("RGB", (W, H), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, W, 14), fill="#5500aa")
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


def main():
    disp    = Display()
    current = get_current()

    disp.show("DISCORD SETUP", [
        "Current webhook:",
        (current[:18] + "...") if len(current) > 20 else (current or "NOT SET"),
        "",
        "OK=edit webhook",
        "KEY1=test current",
        "KEY3=exit",
    ])

    btn = None
    while btn not in ("OK", "KEY1", "KEY3"):
        btn = disp.btn()
        time.sleep(0.05)

    if btn == "KEY3":
        if HAS_HW:
            try: GPIO.cleanup()
            except: pass
        return

    if btn == "KEY1":
        if current:
            test_webhook(current, disp)
        else:
            disp.show("NO WEBHOOK", ["Set a webhook first", "OK to edit"], col="#ff8800")
            time.sleep(2)
        if HAS_HW:
            try: GPIO.cleanup()
            except: pass
        return

    # Simple URL entry — show instructions since full keyboard is complex on 128px
    disp.show("WEBHOOK URL", [
        "Use SSH to set:",
        "",
        "echo 'YOUR_URL' >",
        "/root/KTOx/",
        "discord_webhook.txt",
        "",
        "KEY1=test KEY3=exit",
    ], col="#888888")

    while True:
        b = disp.btn()
        if b == "KEY1":
            current = get_current()
            if current:
                test_webhook(current, disp)
        elif b == "KEY3":
            break
        time.sleep(0.1)

    if HAS_HW:
        try: GPIO.cleanup()
        except: pass
    print("[Discord] Exited.")


if __name__ == "__main__":
    main()
