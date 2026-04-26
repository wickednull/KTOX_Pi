#!/usr/bin/env python3
"""
KTOx keyboard input handler
----------------------------
Monitors USB and Bluetooth keyboards via evdev and maps key presses to button
names, allowing hardware keyboard control of the menu and payloads.

Keyboard mappings:
  Arrow keys (UP/DOWN/LEFT/RIGHT)  → Navigation
  Enter, Space, Spacebar           → OK/SELECT (KEY_PRESS_PIN)
  Escape                           → BACK (KEY1_PIN)
  Home, H                          → HOME (KEY2_PIN)
  Delete, Q                        → STOP/LOCK (KEY3_PIN)

If evdev is not available, this module silently disables itself and returns
None from get_keyboard_button(). The system will continue to work with GPIO
and WebUI buttons.
"""

import os
import threading
import queue
import time
from typing import Optional

try:
    import evdev
    from evdev import ecodes
    HAS_EVDEV = True
    # Map evdev keycodes to KTOx button names
    _KEY_MAP = {
        ecodes.KEY_UP:     "KEY_UP_PIN",
        ecodes.KEY_DOWN:   "KEY_DOWN_PIN",
        ecodes.KEY_LEFT:   "KEY_LEFT_PIN",
        ecodes.KEY_RIGHT:  "KEY_RIGHT_PIN",
        ecodes.KEY_ENTER:  "KEY_PRESS_PIN",
        ecodes.KEY_SPACE:  "KEY_PRESS_PIN",
        ecodes.KEY_ESC:    "KEY1_PIN",
        ecodes.KEY_HOME:   "KEY2_PIN",
        ecodes.KEY_H:      "KEY2_PIN",  # Alt: H for home
        ecodes.KEY_DELETE: "KEY3_PIN",
        ecodes.KEY_Q:      "KEY3_PIN",  # Alt: Q for quit/stop
    }
except ImportError:
    HAS_EVDEV = False
    _KEY_MAP = {}

_q: "queue.Queue[str]" = queue.Queue()
_listener_thread: Optional[threading.Thread] = None
_stop_monitoring = False


def _find_keyboard_devices():
    """Scan /dev/input/ for keyboard devices."""
    if not HAS_EVDEV:
        return []

    devices = []
    try:
        for dev_path in [f"/dev/input/{f}" for f in os.listdir("/dev/input/") if f.startswith("event")]:
            try:
                dev = evdev.InputDevice(dev_path)
                # Check if device has keyboard capability
                if ecodes.EV_KEY in dev.capabilities():
                    devices.append(dev)
            except Exception:
                pass
    except Exception:
        pass
    return devices


def _monitor_keyboards():
    """Background thread: monitor all connected keyboards for key presses."""
    global _stop_monitoring

    # evdev.InputDevice context manager auto-closes on error
    devices = _find_keyboard_devices()
    if not devices:
        time.sleep(1)
        # Retry periodically for hot-plugged devices
        if not _stop_monitoring:
            threading.Thread(target=_monitor_keyboards, daemon=True).start()
        return

    # Multi-device polling: use select to wait for events from any device
    try:
        import selectors
        sel = selectors.DefaultSelector()
        for dev in devices:
            sel.register(dev, selectors.EVENT_READ)

        while not _stop_monitoring:
            events = sel.select(timeout=0.5)
            for key, mask in events:
                try:
                    dev = key.fileobj
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY and event.value == 1:  # Key press (value=1)
                            button = _KEY_MAP.get(event.code)
                            if button:
                                try:
                                    _q.put_nowait(button)
                                except Exception:
                                    pass
                except Exception:
                    pass

        sel.close()
    except Exception:
        pass

    # Restart monitoring if devices were disconnected
    if not _stop_monitoring:
        time.sleep(0.5)
        threading.Thread(target=_monitor_keyboards, daemon=True).start()


def get_keyboard_button() -> Optional[str]:
    """Return next keyboard button name (e.g. 'KEY_UP_PIN') or None."""
    if not HAS_EVDEV:
        return None
    try:
        return _q.get_nowait()
    except queue.Empty:
        return None


def flush():
    """Clear all queued keyboard button presses."""
    try:
        while True:
            _q.get_nowait()
    except queue.Empty:
        pass


def _ensure_started():
    """Start keyboard monitoring thread if not already running."""
    global _listener_thread, _stop_monitoring
    if not HAS_EVDEV:
        return
    if _listener_thread is None or not _listener_thread.is_alive():
        _stop_monitoring = False
        _listener_thread = threading.Thread(target=_monitor_keyboards, daemon=True)
        _listener_thread.start()


def stop():
    """Stop keyboard monitoring thread."""
    global _stop_monitoring
    _stop_monitoring = True
    flush()


# Start on import
_ensure_started()
