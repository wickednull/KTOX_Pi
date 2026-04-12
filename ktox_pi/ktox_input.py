#!/usr/bin/env python3
"""
KTOx input bridge
----------------------
Listens on a Unix datagram socket for JSON input events coming from the
WebSocket server and exposes a tiny queue API so the main UI can treat them
like real button presses.

Environment:
  RJ_INPUT_SOCK  Path to AF_UNIX datagram socket (default: /dev/shm/ktox_input.sock)

Protocol (JSON, one datagram per message):
  {"type":"input","button":"UP|DOWN|LEFT|RIGHT|OK|KEY1|KEY2|KEY3","state":"press|release"}

"press" events are queued for get_virtual_button().
"press"/"release" events update a shared held-state file (/dev/shm/ktox_held)
that payload subprocesses can read via is_pin_held().
"""

import os, json, threading, socket, queue, atexit, time
from typing import Optional

_SOCK_PATH = os.environ.get("RJ_INPUT_SOCK", "/dev/shm/ktox_input.sock")

# Shared file that payload subprocesses read to detect held buttons.
# Format: comma-separated list of active GPIO pin numbers, e.g. "21,20"
_HELD_PATH = "/dev/shm/ktox_held"

# Map frontend button names to KTOx getButton() return values
_BTN_MAP = {
    "UP": "KEY_UP_PIN",
    "DOWN": "KEY_DOWN_PIN",
    "LEFT": "KEY_LEFT_PIN",
    "RIGHT": "KEY_RIGHT_PIN",
    "OK": "KEY_PRESS_PIN",
    "KEY1": "KEY1_PIN",
    "KEY2": "KEY2_PIN",
    "KEY3": "KEY3_PIN",
}

# Map KTOx pin names to GPIO pin numbers (BCM numbering)
_PIN_NAME_TO_NUM = {
    "KEY_UP_PIN":    6,
    "KEY_DOWN_PIN":  19,
    "KEY_LEFT_PIN":  5,
    "KEY_RIGHT_PIN": 26,
    "KEY_PRESS_PIN": 13,
    "KEY1_PIN":      21,
    "KEY2_PIN":      20,
    "KEY3_PIN":      16,
}

# How long a WebUI "press" simulates a held button (seconds).
# Acts as a fallback if a "release" event is missed.
_HOLD_SECS = 0.35

_q: "queue.Queue[str]" = queue.Queue()
_sock: Optional[socket.socket] = None
_listener_thread: Optional[threading.Thread] = None

# held state in the parent process: {pin_name -> expiry float}
_held: dict = {}
_held_lock = threading.Lock()


def _write_held_file():
    """Write currently held pins to the shared file for subprocesses to read."""
    now = time.monotonic()
    pins = []
    with _held_lock:
        expired = [k for k, exp in _held.items() if now >= exp]
        for k in expired:
            del _held[k]
        for btn_name in _held:
            pin = _PIN_NAME_TO_NUM.get(btn_name)
            if pin is not None:
                pins.append(str(pin))
    try:
        with open(_HELD_PATH, "w") as f:
            f.write(",".join(pins))
    except Exception:
        pass


def _cleanup():
    global _sock
    try:
        if _sock is not None:
            _sock.close()
    except Exception:
        pass
    try:
        if os.path.exists(_SOCK_PATH):
            os.unlink(_SOCK_PATH)
    except Exception:
        pass
    try:
        if os.path.exists(_HELD_PATH):
            os.unlink(_HELD_PATH)
    except Exception:
        pass
    _sock = None


def _listen():
    global _sock
    # Ensure no stale socket file remains
    try:
        if os.path.exists(_SOCK_PATH):
            os.unlink(_SOCK_PATH)
    except Exception:
        pass

    _sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    # Allow other processes to send without special perms
    _sock.bind(_SOCK_PATH)
    try:
        os.chmod(_SOCK_PATH, 0o666)
    except Exception:
        pass

    while True:
        try:
            data, _addr = _sock.recvfrom(4096)
        except Exception:
            # Socket closed or transient error → exit thread
            break
        try:
            msg = json.loads(data.decode("utf-8", "ignore"))
        except Exception:
            continue
        if msg.get("type") != "input":
            continue
        button = str(msg.get("button", ""))
        state = str(msg.get("state", ""))
        mapped = _BTN_MAP.get(button)
        if not mapped:
            continue

        if state == "press":
            # Queue for UI navigation
            try:
                _q.put_nowait(mapped)
            except Exception:
                pass
            # Mark as held with a timer-based expiry (fallback if release is missed)
            with _held_lock:
                _held[mapped] = time.monotonic() + _HOLD_SECS
            _write_held_file()

        elif state == "release":
            with _held_lock:
                _held.pop(mapped, None)
            _write_held_file()


def get_virtual_button() -> Optional[str]:
    """Return next virtual button name (e.g. 'KEY_LEFT_PIN') or None."""
    try:
        return _q.get_nowait()
    except queue.Empty:
        return None


def is_pin_held(pin: int) -> bool:
    """
    Return True if the WebUI is currently holding the button mapped to *pin*.

    Used by sitecustomize.py to patch RPi.GPIO.input() so that payloads which
    poll GPIO directly (without _input_helper) still respond to WebUI presses.

    Works both in the main process and in payload subprocesses (reads shared
    file /dev/shm/ktox_held written by the parent's listener thread).
    """
    # Check in-process held state (works in main process)
    now = time.monotonic()
    with _held_lock:
        expired = [k for k, exp in _held.items() if now >= exp]
        for k in expired:
            del _held[k]
        for btn_name, _exp in _held.items():
            if _PIN_NAME_TO_NUM.get(btn_name) == pin:
                return True

    # Fallback: read shared file (works in payload subprocesses)
    try:
        with open(_HELD_PATH) as f:
            content = f.read().strip()
        if content:
            held_pins = {int(p) for p in content.split(",") if p.strip()}
            return pin in held_pins
    except Exception:
        pass
    return False


def _ensure_started():
    global _listener_thread
    if _listener_thread is None or not _listener_thread.is_alive():
        _listener_thread = threading.Thread(target=_listen, daemon=True)
        _listener_thread.start()


def restart_listener():
    """
    Recreate the Unix socket listener.
    Call this after external processes may have removed the socket file.
    """
    global _listener_thread
    _cleanup()
    _listener_thread = None
    _ensure_started()


# Start on import and register cleanup
_ensure_started()
atexit.register(_cleanup)
