"""
Shared input helper for KTOx payloads.
Checks WebUI virtual input, keyboard, then GPIO.
Includes RaspyJack-compatible flip detection and remote text input.
"""

import os, sys, json, time, uuid

try:
    import ktox_input
except Exception:
    try:
        _ktox_pi = os.path.join(os.environ.get("KTOX_DIR", "/root/KTOx"), "ktox_pi")
        if _ktox_pi not in sys.path:
            sys.path.insert(0, _ktox_pi)
        import ktox_input
    except Exception:
        ktox_input = None

try:
    import keyboard_input
    HAS_KEYBOARD = keyboard_input.HAS_EVDEV
except Exception:
    try:
        _ktox_pi = os.path.join(os.environ.get("KTOX_DIR", "/root/KTOx"), "ktox_pi")
        if _ktox_pi not in sys.path:
            sys.path.insert(0, _ktox_pi)
        import keyboard_input
        HAS_KEYBOARD = keyboard_input.HAS_EVDEV
    except Exception:
        HAS_KEYBOARD = False
        keyboard_input = None

_VIRTUAL_TO_BTN = {
    "KEY_UP_PIN": "UP",
    "KEY_DOWN_PIN": "DOWN",
    "KEY_LEFT_PIN": "LEFT",
    "KEY_RIGHT_PIN": "RIGHT",
    "KEY_PRESS_PIN": "OK",
    "KEY1_PIN": "KEY1",
    "KEY2_PIN": "KEY2",
    "KEY3_PIN": "KEY3",
}

# Display flip mapping: swap button meanings when device is flipped 180°
_FLIP_MAP = {
    "UP": "DOWN", "DOWN": "UP",
    "LEFT": "RIGHT", "RIGHT": "LEFT",
    "KEY1": "KEY3", "KEY3": "KEY1",
    "OK": "OK", "KEY2": "KEY2",
}

_flip_enabled = None  # None = not yet loaded, lazy init on first use
_CONF_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_conf.json"),
    "/root/KTOx/gui_conf.json",
    "/root/Raspyjack/gui_conf.json",
]
_TEXT_SESSION_FILE = os.environ.get("KTOX_TEXT_SESSION_FILE") or os.environ.get("RJ_TEXT_SESSION_FILE", "/dev/shm/ktox_text_session.json")
_TEXT_SESSION_TIMEOUT = float(os.environ.get("KTOX_TEXT_SESSION_TIMEOUT") or os.environ.get("RJ_TEXT_SESSION_TIMEOUT", "30"))


def _is_flip_enabled():
    """Lazy-load flip setting from gui_conf.json on first call, cache result."""
    global _flip_enabled
    if _flip_enabled is not None:
        return _flip_enabled
    _flip_enabled = False
    for p in _CONF_PATHS:
        if os.path.isfile(p):
            try:
                with open(p, "r") as f:
                    _flip_enabled = json.load(f).get("DISPLAY", {}).get("flip", False)
            except Exception:
                pass
            break
    return _flip_enabled


def _flip(btn):
    """Apply flip mapping if device is flipped 180°."""
    if _is_flip_enabled() and btn:
        return _FLIP_MAP.get(btn, btn)
    return btn


def get_virtual_button():
    """Return a WebUI virtual button name or None."""
    if ktox_input is None:
        return None
    try:
        name = ktox_input.get_virtual_button()
    except Exception:
        return None
    if not name:
        return None
    return _flip(_VIRTUAL_TO_BTN.get(name))


def get_button(pins, gpio):
    """
    Return a button name using WebUI virtual input, keyboard, or GPIO.
    """
    mapped = get_virtual_button()
    if mapped:
        return mapped
    if HAS_KEYBOARD:
        try:
            k = keyboard_input.get_keyboard_button(timeout_ms=10)
            if k:
                return _flip(_VIRTUAL_TO_BTN.get(k, k))
        except Exception:
            pass
    for btn, pin in pins.items():
        if gpio.input(pin) == 0:
            return _flip(btn)
    return None


def get_held_buttons():
    """Return set of currently held WebUI button names (for continuous input like games)."""
    if ktox_input is None:
        return set()
    try:
        held = ktox_input.get_held_buttons()
    except Exception:
        return set()
    mapped = {_VIRTUAL_TO_BTN.get(b, b) for b in held if b in _VIRTUAL_TO_BTN}
    if _is_flip_enabled():
        return {_FLIP_MAP.get(b, b) for b in mapped}
    return mapped


def _write_text_session(payload):
    """Write text session config to shared file for WebSocket handler."""
    directory = os.path.dirname(_TEXT_SESSION_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{_TEXT_SESSION_FILE}.tmp.{os.getpid()}"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(temp_path, _TEXT_SESSION_FILE)
    except Exception:
        pass


def open_remote_text_session(title="Input", default="", charset="full", max_len=64):
    """
    Open a remote text input session from an M5 or web client.
    Returns session_id for later use with get_remote_text_event().
    """
    session_id = uuid.uuid4().hex
    payload = {
        "active": True,
        "session_id": session_id,
        "title": str(title or "Input")[:32],
        "default": str(default or "")[:128],
        "charset": str(charset or "full"),
        "max_len": int(max_len),
        "started_at": time.time(),
        "timeout": _TEXT_SESSION_TIMEOUT,
    }
    _write_text_session(payload)
    if ktox_input is not None:
        try:
            ktox_input.flush_text_events()
        except Exception:
            pass
    return session_id


def close_remote_text_session(session_id=None):
    """Close a remote text input session."""
    current = {}
    try:
        if os.path.isfile(_TEXT_SESSION_FILE):
            with open(_TEXT_SESSION_FILE, "r", encoding="utf-8") as handle:
                current = json.load(handle) or {}
    except Exception:
        current = {}
    if session_id and current.get("session_id") not in (None, session_id):
        return
    payload = {
        "active": False,
        "session_id": session_id or current.get("session_id", ""),
        "closed_at": time.time(),
    }
    try:
        _write_text_session(payload)
    except Exception:
        pass


def get_remote_text_event(session_id=None):
    """
    Get next remote text input event for this session.
    Returns dict with 'key' (for char) or 'special' (for BACKSPACE, ENTER, ESCAPE), or None.
    """
    if ktox_input is None:
        return None
    for _ in range(4):
        try:
            event = ktox_input.get_text_event()
        except Exception:
            return None
        if not event:
            return None
        if not isinstance(event, dict):
            continue
        event_session = event.get("session_id")
        if session_id and event_session and event_session != session_id:
            continue
        return event
    return None


def flush_input():
    """Clear all queued and held button state."""
    if ktox_input is not None:
        try:
            ktox_input.flush()
        except Exception:
            pass
