#!/usr/bin/env python3
"""
KTOx Payload -- USB Gadget Mode Setup
======================================
Detect, enable, and disable USB gadget mode on the
Raspberry Pi Zero 2 W running Kali Linux.

Gadget mode lets the Pi act as a USB HID keyboard, mass
storage device, or Ethernet adapter when plugged into a
target host via the OTG USB port.

What this does
--------------
- Detects current gadget mode state (dtoverlay, modules, UDC)
- Enables gadget mode at runtime (loads modules immediately)
- Persists settings to /boot/firmware/config.txt + /etc/modules
- Disables gadget mode cleanly (unloads modules, removes config)

Controls
--------
  UP / DOWN  -- Scroll status list
  OK         -- Load modules now (runtime enable, no reboot)
  KEY1       -- Enable persistent (config.txt + modules + load)
  KEY2       -- Disable persistent (remove config + unload)
  KEY3       -- Exit
"""

import os
import sys
import time
import subprocess
import threading

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..", "..")))

import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config
from PIL import Image, ImageDraw, ImageFont
from payloads._display_helper import ScaledDraw, scaled_font
from payloads._input_helper import get_button

# ---------------------------------------------------------------------------
# Hardware init
# ---------------------------------------------------------------------------
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = LCD.width, LCD.height
font = scaled_font()
font_sm = scaled_font(8)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Kali on Pi uses /boot/firmware/ on newer images, /boot/ on older ones
_BOOT_CANDIDATES = [
    "/boot/firmware/config.txt",
    "/boot/config.txt",
]
MODULES_FILE = "/etc/modules"
CONFIGFS_GADGET = "/sys/kernel/config/usb_gadget"
UDC_PATH = "/sys/class/udc"

DT_OVERLAY_LINE = "dtoverlay=dwc2,dr_mode=peripheral"
REQUIRED_MODULES = ["dwc2", "libcomposite"]

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
lock = threading.Lock()
status_msg = ""
busy = False
scroll = 0

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _find_boot_config():
    """Return the active boot config.txt path."""
    for p in _BOOT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return _BOOT_CANDIDATES[0]  # default even if missing


def _dtoverlay_present(cfg_path):
    """Return True if dwc2 dtoverlay is in config.txt."""
    try:
        with open(cfg_path) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "dtoverlay=dwc2" in stripped:
                    return True
    except Exception:
        pass
    return False


def _module_loaded(name):
    """Return True if a kernel module is currently loaded."""
    try:
        with open("/proc/modules") as f:
            for line in f:
                if line.split()[0] == name:
                    return True
    except Exception:
        pass
    return False


def _module_in_etc(name):
    """Return True if module is listed in /etc/modules."""
    try:
        with open(MODULES_FILE) as f:
            for line in f:
                if line.strip() == name:
                    return True
    except Exception:
        pass
    return False


def _configfs_mounted():
    """Return True if configfs is mounted at /sys/kernel/config."""
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "/sys/kernel/config":
                    return True
    except Exception:
        pass
    return False


def _udc_list():
    """Return list of available UDC controller names."""
    try:
        return os.listdir(UDC_PATH)
    except Exception:
        return []


def _active_gadgets():
    """Return list of active gadget names in configfs."""
    try:
        return [
            g for g in os.listdir(CONFIGFS_GADGET)
            if os.path.isdir(os.path.join(CONFIGFS_GADGET, g))
        ]
    except Exception:
        return []


def _gadget_devices():
    """Return list of active USB gadget device nodes."""
    devs = []
    for name in ["hidg0", "hidg1", "g_ether", "usb0"]:
        if os.path.exists(f"/dev/{name}"):
            devs.append(name)
    # Also check usb0 via network interfaces
    try:
        ifaces = os.listdir("/sys/class/net")
        for iface in ifaces:
            if iface.startswith("usb") and iface not in devs:
                devs.append(iface)
    except Exception:
        pass
    return devs


def get_status():
    """Return a list of (label, value, ok) tuples describing current state."""
    cfg = _find_boot_config()
    dt_ok = _dtoverlay_present(cfg)
    dwc2_loaded = _module_loaded("dwc2")
    composite_loaded = _module_loaded("libcomposite")
    dwc2_etc = _module_in_etc("dwc2")
    composite_etc = _module_in_etc("libcomposite")
    configfs = _configfs_mounted()
    udcs = _udc_list()
    gadgets = _active_gadgets()
    devs = _gadget_devices()

    cfg_name = os.path.basename(os.path.dirname(cfg)) + "/" + os.path.basename(cfg)

    rows = [
        ("Boot config",  cfg_name,                        True),
        ("dtoverlay",    "YES" if dt_ok else "NO",         dt_ok),
        ("dwc2 loaded",  "YES" if dwc2_loaded else "NO",   dwc2_loaded),
        ("composite",    "YES" if composite_loaded else "NO", composite_loaded),
        ("dwc2 /etc",    "YES" if dwc2_etc else "NO",      dwc2_etc),
        ("compos /etc",  "YES" if composite_etc else "NO", composite_etc),
        ("configfs",     "YES" if configfs else "NO",      configfs),
        ("UDC",          ", ".join(udcs) if udcs else "none", bool(udcs)),
        ("Gadgets",      ", ".join(gadgets) if gadgets else "none", True),
        ("Devices",      ", ".join(devs) if devs else "none",       True),
    ]
    return rows


def gadget_mode_ready():
    """True when modules are loaded and UDC is available."""
    return (
        _module_loaded("dwc2")
        and _module_loaded("libcomposite")
        and bool(_udc_list())
    )


# ---------------------------------------------------------------------------
# Enable / disable actions
# ---------------------------------------------------------------------------

def _run(cmd, timeout=30):
    """Run a command, return (returncode, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def _mount_configfs():
    """Mount configfs if not already mounted."""
    if not _configfs_mounted():
        _run(["mount", "-t", "configfs", "none", "/sys/kernel/config"])


def _load_modules():
    """Load dwc2 and libcomposite at runtime. Returns (ok, msg)."""
    _mount_configfs()
    for mod in REQUIRED_MODULES:
        rc, err = _run(["modprobe", mod])
        if rc != 0 and "already loaded" not in err.lower():
            return False, f"modprobe {mod}: {err[:40]}"
    time.sleep(0.5)
    if not _udc_list():
        return False, "modules loaded but no UDC found — reboot may be needed"
    return True, "modules loaded"


def _unload_modules():
    """Unload gadget modules if no active gadgets. Returns (ok, msg)."""
    if _active_gadgets():
        return False, "active gadgets present — stop them first"
    for mod in reversed(REQUIRED_MODULES):
        _run(["rmmod", mod])
    return True, "modules unloaded"


def _add_to_boot_config():
    """Add dtoverlay=dwc2,dr_mode=peripheral to config.txt."""
    cfg = _find_boot_config()
    if _dtoverlay_present(cfg):
        return True, "already present"
    try:
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(cfg, "a") as f:
            f.write(f"\n# KTOx USB gadget mode\n{DT_OVERLAY_LINE}\n")
        return True, "added to " + os.path.basename(cfg)
    except Exception as e:
        return False, str(e)[:40]


def _remove_from_boot_config():
    """Remove dtoverlay=dwc2 lines from config.txt."""
    cfg = _find_boot_config()
    if not _dtoverlay_present(cfg):
        return True, "not present"
    try:
        with open(cfg) as f:
            lines = f.readlines()
        kept = [
            l for l in lines
            if "dtoverlay=dwc2" not in l and "KTOx USB gadget mode" not in l
        ]
        with open(cfg, "w") as f:
            f.writelines(kept)
        return True, "removed from " + os.path.basename(cfg)
    except Exception as e:
        return False, str(e)[:40]


def _add_to_etc_modules():
    """Add dwc2 and libcomposite to /etc/modules."""
    msgs = []
    for mod in REQUIRED_MODULES:
        if not _module_in_etc(mod):
            try:
                with open(MODULES_FILE, "a") as f:
                    f.write(f"{mod}\n")
                msgs.append(f"+{mod}")
            except Exception as e:
                return False, str(e)[:40]
    return True, " ".join(msgs) if msgs else "already present"


def _remove_from_etc_modules():
    """Remove dwc2 and libcomposite from /etc/modules."""
    try:
        with open(MODULES_FILE) as f:
            lines = f.readlines()
        kept = [l for l in lines if l.strip() not in REQUIRED_MODULES]
        with open(MODULES_FILE, "w") as f:
            f.writelines(kept)
        return True, "removed from /etc/modules"
    except Exception as e:
        return False, str(e)[:40]


# ---------------------------------------------------------------------------
# Actions called from button handlers (run in a thread)
# ---------------------------------------------------------------------------

def action_runtime_enable():
    """Load modules now without touching boot config."""
    global status_msg, busy
    with lock:
        busy = True
        status_msg = "Loading modules..."
    _draw()
    ok, msg = _load_modules()
    with lock:
        status_msg = ("OK: " if ok else "ERR: ") + msg
        busy = False


def action_persist_enable():
    """Add to boot config + /etc/modules + load now."""
    global status_msg, busy
    with lock:
        busy = True
        status_msg = "Updating config..."
    _draw()

    ok1, m1 = _add_to_boot_config()
    ok2, m2 = _add_to_etc_modules()
    ok3, m3 = _load_modules()

    if ok1 and ok2 and ok3:
        msg = "Done — reboot to activate dtoverlay"
    elif not ok3:
        msg = f"Config OK, load err: {m3[:30]}"
    else:
        msg = f"Partial: cfg={ok1} etc={ok2} mod={ok3}"

    with lock:
        status_msg = msg
        busy = False


def action_persist_disable():
    """Remove from boot config + /etc/modules + unload if safe."""
    global status_msg, busy
    with lock:
        busy = True
        status_msg = "Disabling..."
    _draw()

    ok1, m1 = _remove_from_boot_config()
    ok2, m2 = _remove_from_etc_modules()
    ok3, m3 = _unload_modules()

    if ok1 and ok2:
        msg = "Removed from config"
        if ok3:
            msg += " + unloaded"
        else:
            msg += f" ({m3})"
    else:
        msg = f"cfg={m1} etc={m2}"

    with lock:
        status_msg = msg
        busy = False


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw():
    """Render current status to LCD."""
    rows = get_status()
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ScaledDraw(img)

    # Header
    d.rectangle((0, 0, 127, 13), fill="#112211")
    ready = gadget_mode_ready()
    hdr_col = "#00FF44" if ready else "#FF4444"
    d.text((2, 1), "USB GADGET MODE", font=font, fill=hdr_col)

    with lock:
        msg = status_msg
        is_busy = busy
        sc = scroll

    # Status rows
    visible = rows[sc:sc + 7]
    y = 16
    for label, val, ok in visible:
        col_v = "#00CC44" if ok else "#FF4444"
        d.text((2, y), f"{label}:", font=font_sm, fill="#888888")
        d.text((72, y), val[:14], font=font_sm, fill=col_v)
        y += 13

    # Status bar
    d.rectangle((0, 104, 127, 114), fill="#111111")
    bar_col = "#FFAA00" if is_busy else "#555555"
    d.text((2, 105), (msg or "")[:26], font=font_sm, fill=bar_col)

    # Footer
    d.rectangle((0, 115, 127, 127), fill="#111111")
    d.text((2, 116), "OK:Load K1:+Persist K2:-", font=font_sm, fill="#444444")

    LCD.LCD_ShowImage(img, 0, 0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global scroll, status_msg

    _draw()

    try:
        while True:
            btn = get_button(PINS, GPIO)

            with lock:
                is_busy = busy

            if is_busy:
                _draw()
                time.sleep(0.1)
                continue

            if btn == "KEY3":
                break

            elif btn == "UP":
                rows = get_status()
                with lock:
                    scroll = max(0, scroll - 1)
                time.sleep(0.15)

            elif btn == "DOWN":
                rows = get_status()
                with lock:
                    scroll = min(max(0, len(rows) - 7), scroll + 1)
                time.sleep(0.15)

            elif btn == "OK":
                threading.Thread(
                    target=action_runtime_enable, daemon=True
                ).start()
                time.sleep(0.3)

            elif btn == "KEY1":
                threading.Thread(
                    target=action_persist_enable, daemon=True
                ).start()
                time.sleep(0.3)

            elif btn == "KEY2":
                threading.Thread(
                    target=action_persist_disable, daemon=True
                ).start()
                time.sleep(0.3)

            _draw()
            time.sleep(0.05)

    finally:
        try:
            LCD.LCD_Clear()
        except Exception:
            pass
        GPIO.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
