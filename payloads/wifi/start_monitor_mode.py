#!/usr/bin/env python3
"""
KTOx payload — Start Monitor Mode
===================================
Puts the USB WiFi dongle (wlan1 / first non-onboard adapter) into monitor mode.
Shows step-by-step progress on the LCD so you can see exactly where it fails.

Controls:
  KEY3 — exit after result is shown
"""
import sys
import os
import time
import signal

# ── Path setup ────────────────────────────────────────────────────────────────
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else \
    os.path.abspath(os.path.join(__file__, '..', '..', '..'))
for _p in (KTOX_ROOT, os.path.join(KTOX_ROOT, 'wifi')):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# ── Hardware ──────────────────────────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError as e:
    print(f"[WARN] Hardware not available: {e}")
    HAS_HW = False

# ── Monitor mode helper ───────────────────────────────────────────────────────
try:
    from wifi.monitor_mode_helper import (
        activate_monitor_mode,
        find_monitor_capable_interface,
        _iface_mode,
        _iface_exists,
        _is_onboard,
    )
    MON_OK = True
except ImportError:
    try:
        import monitor_mode_helper as _mmh
        activate_monitor_mode       = _mmh.activate_monitor_mode
        find_monitor_capable_interface = _mmh.find_monitor_capable_interface
        MON_OK = True
    except ImportError:
        MON_OK = False

PINS = {"OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
WIDTH, HEIGHT = 128, 128
_running = True


def _cleanup(*_):
    global _running
    _running = False


signal.signal(signal.SIGINT, _cleanup)
signal.signal(signal.SIGTERM, _cleanup)

# ── LCD helpers ───────────────────────────────────────────────────────────────

_lcd = None
_font = None


def _init_hw():
    global _lcd, _font
    if not HAS_HW:
        return
    try:
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        _lcd = LCD_1in44.LCD()
        _lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        try:
            _font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except Exception:
            _font = ImageFont.load_default()
    except Exception as e:
        print(f"[WARN] LCD init failed: {e}")


def _show(lines, title_color=(255, 255, 0), body_color=(0, 220, 0)):
    """Render up to 8 lines on the LCD."""
    for ln in lines:
        print(f"  {ln}")
    if not (_lcd and _font):
        return
    try:
        img = Image.new("RGB", (WIDTH, HEIGHT), "black")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, WIDTH, 12), fill=(20, 20, 20))
        d.text((2, 1), "MONITOR MODE", font=_font, fill=(0, 200, 255))
        y = 16
        for i, ln in enumerate(lines[:7]):
            col = title_color if i == 0 else body_color
            d.text((2, y), str(ln)[:22], font=_font, fill=col)
            y += 15
        _lcd.LCD_ShowImage(img, 0, 0)
    except Exception as e:
        print(f"[WARN] LCD show failed: {e}")


def _wait_key3():
    """Block until KEY3 is pressed."""
    if not HAS_HW:
        time.sleep(3)
        return
    _show(["", "Press KEY3 to exit"], body_color=(100, 100, 100))
    while _running:
        if GPIO.input(PINS["KEY3"]) == 0:
            break
        time.sleep(0.05)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _init_hw()

    if not MON_OK:
        _show(["IMPORT ERROR", "monitor_mode_helper", "not found!"],
              title_color=(255, 0, 0))
        _wait_key3()
        return 1

    # Step 1 — find the interface
    _show(["Step 1/4", "Detecting USB WiFi..."])
    time.sleep(0.5)

    target = find_monitor_capable_interface()
    if not target:
        _show(["NO USB DONGLE FOUND",
               "wlan0 = onboard only",
               "Plug in USB adapter",
               "(Alfa / RTL / Atheros)"],
              title_color=(255, 80, 0))
        print("[ERROR] No monitor-capable interface found.")
        _wait_key3()
        return 1

    _show([f"Step 2/4", f"Found: {target}", "Checking state..."])
    time.sleep(0.3)

    # Step 2 — check current state
    already = _iface_mode(target)
    if already == "monitor":
        _show(["ALREADY IN", "MONITOR MODE", f"Interface: {target}",
               "Nothing to do."],
              title_color=(0, 255, 0))
        print(f"[OK] {target} is already in monitor mode.")
        _wait_key3()
        return 0

    if _is_onboard(target):
        _show(["ONBOARD CHIP DETECTED",
               f"{target} = brcmfmac",
               "No monitor support",
               "Use USB dongle"],
              title_color=(255, 50, 50))
        print(f"[ERROR] {target} is onboard Broadcom — not suitable.")
        _wait_key3()
        return 1

    # Step 3 — activate
    _show([f"Step 3/4", f"Activating on {target}...",
           "Stopping NM/wpa...", "Please wait ~15s"])
    print(f"[INFO] Activating monitor mode on {target}...")
    time.sleep(0.2)

    mon_iface = activate_monitor_mode(target)

    # Step 4 — result
    if mon_iface:
        _show(["MONITOR MODE ACTIVE",
               f"Interface: {mon_iface}",
               "",
               "Run wifi payloads now",
               "Stop: use Stop Mon Md"],
              title_color=(0, 255, 0))
        print(f"[OK] Monitor mode active on: {mon_iface}")
        _wait_key3()
        return 0
    else:
        _show(["FAILED TO ACTIVATE",
               f"on {target}",
               "Check debug log:",
               "/root/KTOx/loot/",
               "ktox_debug.log"],
              title_color=(255, 0, 0), body_color=(200, 150, 0))
        print(f"[ERROR] activate_monitor_mode({target}) returned None")
        print(f"[INFO] Check /root/KTOx/loot/ktox_debug.log for details")
        _wait_key3()
        return 1


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: requires root (run with sudo)")
        sys.exit(1)
    try:
        rc = main()
    finally:
        if _lcd:
            try:
                _lcd.LCD_Clear()
            except Exception:
                pass
        if HAS_HW:
            try:
                GPIO.cleanup()
            except Exception:
                pass
    raise SystemExit(rc)
