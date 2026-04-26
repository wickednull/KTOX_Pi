"""
Shared input helper for KTOx payloads.
Checks WebUI virtual input, keyboard, then GPIO.
"""

import os, sys

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
    return _VIRTUAL_TO_BTN.get(name)


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
                return _VIRTUAL_TO_BTN.get(k, k)
        except Exception:
            pass
    for btn, pin in pins.items():
        if gpio.input(pin) == 0:
            return btn
    return None


def get_held_buttons():
    """Return set of currently held WebUI button names (for continuous input like games)."""
    if ktox_input is None:
        return set()
    try:
        held = ktox_input.get_held_buttons()
    except Exception:
        return set()
    return {_VIRTUAL_TO_BTN.get(b, b) for b in held if b in _VIRTUAL_TO_BTN}


def flush_input():
    """Clear all queued and held button state."""
    if ktox_input is not None:
        try:
            ktox_input.flush()
        except Exception:
            pass
