#!/usr/bin/env python3
"""
KTOx payload — Stop Monitor Mode
==================================
Restores the USB WiFi dongle from monitor mode back to managed mode
and restarts NetworkManager / wpa_supplicant.

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
        deactivate_monitor_mode,
        _iface_mode,
        _iface_exists,
        _current_monitor_ifaces,
    )
    MON_OK = True
except ImportError:
    try:
        import monitor_mode_helper as _mmh
        deactivate_monitor_mode = _mmh.deactivate_monitor_mode
        MON_OK = True
        def _iface_mode(i): return ""
        def _iface_exists(i): return False
        def _current_monitor_ifaces(): return []
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
    for ln in lines:
        print(f"  {ln}")
    if not (_lcd and _font):
        return
    try:
        img = Image.new("RGB", (WIDTH, HEIGHT), "black")
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, WIDTH, 12), fill=(20, 20, 20))
        d.text((2, 1), "STOP MON MODE", font=_font, fill=(0, 200, 255))
        y = 16
        for i, ln in enumerate(lines[:7]):
            col = title_color if i == 0 else body_color
            d.text((2, y), str(ln)[:22], font=_font, fill=col)
            y += 15
        _lcd.LCD_ShowImage(img, 0, 0)
    except Exception as e:
        print(f"[WARN] LCD show failed: {e}")


def _wait_key3():
    if not HAS_HW:
        time.sleep(3)
        return
    _show(["", "Press KEY3 to exit"], body_color=(100, 100, 100))
    while _running:
        if GPIO.input(PINS["KEY3"]) == 0:
            break
        time.sleep(0.05)


def main():
    _init_hw()

    if not MON_OK:
        _show(["IMPORT ERROR", "monitor_mode_helper", "not found!"],
              title_color=(255, 0, 0))
        _wait_key3()
        return 1

    # Step 1 — find monitor interfaces
    _show(["Step 1/2", "Scanning for monitor", "interfaces..."])
    time.sleep(0.4)

    # Find all interfaces currently in monitor mode
    mon_ifaces = _current_monitor_ifaces()

    if not mon_ifaces:
        _show(["NO MONITOR INTERFACES",
               "Nothing is in monitor",
               "mode right now.",
               "NM/wpa will restart."],
              title_color=(0, 200, 255))
        print("[INFO] No interfaces in monitor mode found.")
        # Still restart services in case they were stopped earlier
        try:
            from wifi.monitor_mode_helper import _start_interfering_services
            _start_interfering_services()
        except Exception:
            pass
        _wait_key3()
        return 0

    _show([f"Found: {', '.join(mon_ifaces)}", "Step 2/2",
           "Restoring managed...", "Please wait..."])
    print(f"[INFO] Deactivating monitor mode on: {mon_ifaces}")
    time.sleep(0.3)

    # Step 2 — deactivate each
    failed = []
    for iface in mon_ifaces:
        ok = deactivate_monitor_mode(iface)
        if not ok:
            failed.append(iface)

    if not failed:
        _show(["MANAGED MODE RESTORED",
               f"Was: {', '.join(mon_ifaces)}",
               "NM/wpa restarted",
               "WiFi back online shortly"],
              title_color=(0, 255, 0))
        print("[OK] Monitor mode deactivated successfully.")
        _wait_key3()
        return 0
    else:
        _show(["PARTIAL FAILURE",
               f"Failed: {', '.join(failed)}",
               "Check debug log:",
               "/root/KTOx/loot/",
               "ktox_debug.log"],
              title_color=(255, 150, 0))
        print(f"[WARN] Failed to deactivate: {failed}")
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
