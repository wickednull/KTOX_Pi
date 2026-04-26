#!/usr/bin/env python3
"""
KTOx keyboard input handler - USB/Bluetooth keyboard support
Synchronous module (no background threads) for direct integration with getButton()
"""

import os
import select
import fcntl
from typing import Optional, List, Dict

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
        ecodes.KEY_H:      "KEY2_PIN",
        ecodes.KEY_DELETE: "KEY3_PIN",
        ecodes.KEY_Q:      "KEY3_PIN",
    }
except ImportError:
    HAS_EVDEV = False
    _KEY_MAP = {}

_keyboards = None
_poller = None


def _find_keyboards():
    """Find all connected keyboard devices with EV_KEY capability."""
    if not HAS_EVDEV:
        return []

    keyboards = []
    try:
        for dev_path in list_devices():
            try:
                dev = InputDevice(dev_path)
                if ecodes.EV_KEY in dev.capabilities():
                    # Set non-blocking mode
                    try:
                        if hasattr(dev, 'set_blocking'):
                            dev.set_blocking(False)
                        else:
                            fcntl.fcntl(dev.fd, fcntl.F_SETFL,
                                       fcntl.fcntl(dev.fd, fcntl.F_GETFL) | os.O_NONBLOCK)
                    except Exception:
                        pass
                    keyboards.append(dev)
            except Exception:
                pass
    except Exception:
        pass

    return keyboards


def init():
    """Initialize keyboard monitoring. Call once at startup."""
    global _keyboards, _poller

    if not HAS_EVDEV:
        return

    _keyboards = _find_keyboards()

    if _keyboards:
        _poller = select.poll()
        for dev in _keyboards:
            try:
                _poller.register(dev.fd, select.POLLIN)
            except Exception:
                pass


def get_keyboard_button(timeout_ms: int = 50) -> Optional[str]:
    """
    Check for keyboard input. Non-blocking or short timeout.

    Returns the mapped button name (e.g. 'KEY_UP_PIN') or None.
    timeout_ms: milliseconds to wait for events (default 50ms)
    """
    global _keyboards, _poller

    if not HAS_EVDEV or not _keyboards or not _poller:
        return None

    try:
        # Poll with timeout in milliseconds
        readable = _poller.poll(timeout_ms)

        for fd, _ in readable:
            try:
                # Find the device with this fd
                dev = None
                for keyboard in _keyboards:
                    if keyboard.fd == fd:
                        dev = keyboard
                        break

                if dev is None:
                    continue

                # Read all events from this device
                for event in dev.read():
                    # Only process key press events (value == 1)
                    if event.type == ecodes.EV_KEY and event.value == 1:
                        button = _KEY_MAP.get(event.code)
                        if button:
                            return button
            except (OSError, IOError):
                # Device disconnected or read error
                try:
                    _poller.unregister(fd)
                except Exception:
                    pass
                _keyboards = [d for d in _keyboards if d.fd != fd]
            except Exception:
                pass
    except Exception:
        pass

    return None


def close():
    """Cleanup keyboard resources."""
    global _keyboards, _poller

    if _poller is not None:
        try:
            for dev in _keyboards or []:
                try:
                    _poller.unregister(dev.fd)
                except Exception:
                    pass
        except Exception:
            pass
        _poller = None

    if _keyboards:
        for dev in _keyboards:
            try:
                dev.close()
            except Exception:
                pass
        _keyboards = None


# Initialize on import
if HAS_EVDEV:
    init()
