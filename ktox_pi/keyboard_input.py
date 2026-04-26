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
import sys
import threading
import queue
import time
import select
import fcntl
from typing import Optional

try:
    from evdev import InputDevice, ecodes, list_devices, categorize
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
_devices_lock = threading.Lock()
_active_devices = []  # Keep device objects alive


def _find_keyboards():
    """Find all connected keyboard devices."""
    if not HAS_EVDEV:
        return []

    keyboards = []
    try:
        for dev_path in list_devices():
            try:
                dev = InputDevice(dev_path)
                if ecodes.EV_KEY in dev.capabilities():
                    # Set non-blocking mode
                    if hasattr(dev, 'set_blocking'):
                        dev.set_blocking(False)
                    else:
                        fcntl.fcntl(dev.fd, fcntl.F_SETFL,
                                   fcntl.fcntl(dev.fd, fcntl.F_GETFL) | os.O_NONBLOCK)
                    keyboards.append(dev)
            except Exception:
                pass
    except Exception:
        pass
    return keyboards


def _monitor_keyboards():
    """Background thread: monitor all connected keyboards for key presses."""
    global _stop_monitoring, _active_devices

    last_scan = time.monotonic()

    while not _stop_monitoring:
        try:
            now = time.monotonic()
            # Rescan for new keyboards every 2 seconds
            if now - last_scan >= 2.0:
                with _devices_lock:
                    _active_devices = _find_keyboards()
                last_scan = now

            with _devices_lock:
                devices = _active_devices

            if not devices:
                time.sleep(0.5)
                continue

            # Use select() to poll all device file descriptors
            fds = [dev.fd for dev in devices]
            try:
                readable, _, _ = select.select(fds, [], [], 0.5)
            except Exception:
                time.sleep(0.1)
                continue

            for fd in readable:
                try:
                    # Find the device with this fd
                    dev = next((d for d in devices if d.fd == fd), None)
                    if dev is None:
                        continue

                    for event in dev.read():
                        if event.type == ecodes.EV_KEY and event.value == 1:  # Key press
                            button = _KEY_MAP.get(event.code)
                            if button:
                                try:
                                    _q.put_nowait(button)
                                except Exception:
                                    pass
                except (OSError, IOError):
                    # Device disconnected
                    with _devices_lock:
                        _active_devices = [d for d in _active_devices if d.fd != fd]
                except Exception:
                    pass

        except Exception:
            time.sleep(0.5)


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
    """Stop keyboard monitoring thread and close devices."""
    global _stop_monitoring, _active_devices
    _stop_monitoring = True
    with _devices_lock:
        for dev in _active_devices:
            try:
                dev.close()
            except Exception:
                pass
        _active_devices.clear()
    flush()


# Start on import
_ensure_started()
