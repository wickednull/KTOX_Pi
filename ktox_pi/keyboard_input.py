#!/usr/bin/env python3
"""
KTOx keyboard input handler
----------------------------
Monitors USB and Bluetooth keyboards via evdev and maps key presses to button
names, allowing hardware keyboard control of the menu and payloads.

Based on the proven approach from the micro-shell payload.

Keyboard mappings:
  Arrow keys (UP/DOWN/LEFT/RIGHT)  → Navigation
  Enter, Space                     → OK/SELECT (KEY_PRESS_PIN)
  Escape                           → BACK (KEY1_PIN)
  Home, H                          → HOME (KEY2_PIN)
  Delete, Q                        → STOP/LOCK (KEY3_PIN)
"""

import os
import threading
import queue
import time
import select
import fcntl
from typing import Optional

try:
    from evdev import InputDevice, ecodes, list_devices
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
_devices: list = []  # Keep device objects alive
_devices_lock = threading.Lock()
_poller = None


def _find_keyboards():
    """
    Find keyboard devices. Uses the same approach as the working shell payload.
    Find all keyboards and keep them alive.
    """
    if not HAS_EVDEV:
        return []

    keyboards = []
    try:
        for path in list_devices():
            try:
                dev = InputDevice(path)
                if ecodes.EV_KEY in dev.capabilities():
                    keyboards.append(dev)
            except Exception:
                pass
    except Exception:
        pass
    return keyboards


def _monitor_keyboards():
    """
    Background thread: monitor keyboard devices for key presses.
    Uses select.poll() approach from the proven shell payload.
    """
    global _stop_monitoring, _devices, _poller

    # Find keyboards once at startup (like the shell does)
    with _devices_lock:
        _devices = _find_keyboards()

    if not _devices:
        # No keyboards found at startup, wait and retry once
        time.sleep(0.5)
        with _devices_lock:
            _devices = _find_keyboards()

    if not _devices:
        # Still no keyboards, just monitor for future connections
        while not _stop_monitoring:
            time.sleep(1)
            try:
                candidates = _find_keyboards()
                if candidates:
                    with _devices_lock:
                        _devices = candidates
                    break
            except Exception:
                pass
        if _stop_monitoring:
            return

    # Set up polling (like the shell's poller.register)
    try:
        _poller = select.poll()
        for dev in _devices:
            # Set non-blocking mode (like the shell does at line 128-129)
            try:
                if hasattr(dev, 'set_blocking'):
                    dev.set_blocking(False)
                else:
                    fcntl.fcntl(dev.fd, fcntl.F_SETFL,
                               fcntl.fcntl(dev.fd, fcntl.F_GETFL) | os.O_NONBLOCK)
            except Exception:
                pass
            # Register with poller (like the shell at line 131)
            try:
                _poller.register(dev.fd, select.POLLIN)
            except Exception:
                pass
    except Exception:
        return

    # Main event loop (like the shell's while running loop)
    while not _stop_monitoring:
        try:
            # Poll with timeout (like the shell's poller.poll(50))
            for fd, _ in _poller.poll(50):
                try:
                    # Find device with this fd
                    dev = None
                    with _devices_lock:
                        for d in _devices:
                            if d.fd == fd:
                                dev = d
                                break

                    if dev is None:
                        continue

                    # Read all buffered events (like the shell)
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY and event.value == 1:  # Key press
                            button = _KEY_MAP.get(event.code)
                            if button:
                                try:
                                    _q.put_nowait(button)
                                except Exception:
                                    pass
                except (OSError, IOError):
                    # Device disconnected - remove from monitoring
                    try:
                        _poller.unregister(fd)
                    except Exception:
                        pass
                    with _devices_lock:
                        _devices = [d for d in _devices if d.fd != fd]
                except Exception:
                    pass

        except Exception:
            time.sleep(0.05)


def get_keyboard_button(timeout: float = 0.05) -> Optional[str]:
    """
    Return next keyboard button name (e.g. 'KEY_UP_PIN') or None.
    Blocks briefly to allow background thread to queue keyboard events.
    timeout: seconds to wait (default 0.05 = 50ms, matches hardware debounce)
    """
    if not HAS_EVDEV:
        return None
    try:
        return _q.get(timeout=timeout)
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
    global _stop_monitoring, _devices, _poller
    _stop_monitoring = True

    # Unregister and cleanup
    if _poller is not None:
        try:
            for dev in _devices:
                try:
                    _poller.unregister(dev.fd)
                except Exception:
                    pass
        except Exception:
            pass

    with _devices_lock:
        for dev in _devices:
            try:
                dev.close()
            except Exception:
                pass
        _devices.clear()

    flush()


# Start on import
_ensure_started()
