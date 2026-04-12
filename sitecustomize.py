#!/usr/bin/env python3
"""
sitecustomize.py — KTOx payload GPIO shim
==========================================
Python automatically executes this file at interpreter startup for any process
that has /root/KTOx/ in its PYTHONPATH.

KTOx sets PYTHONPATH=/root/KTOx/:... and KTOX_PAYLOAD=1 for every payload
subprocess launched by exec_payload().  This means the shim is loaded in every
payload without requiring any changes to individual payload files.

What it does
------------
Patches RPi.GPIO.input() so that WebUI virtual button presses (delivered via
/dev/shm/ktox_held, written by the parent's ktox_input listener) are
indistinguishable from real hardware button presses.

Payloads that call::

    if GPIO.input(PINS["KEY1"]) == 0:
        ...

will now also respond to WebUI button presses — the held state is written to
/dev/shm/ktox_held by the parent process (ktox_input._write_held_file) and
read back here via ktox_input.is_pin_held().
"""

import os

if os.environ.get("KTOX_PAYLOAD") == "1":
    try:
        # ktox_input is importable because PYTHONPATH includes /root/KTOx/
        # In the subprocess context the listener thread cannot bind the socket
        # (parent already owns it), but is_pin_held() falls through to reading
        # /dev/shm/ktox_held which the parent updates on every press/release.
        import ktox_input as _ki
        import RPi.GPIO as _GPIO

        _orig_input = _GPIO.input

        def _patched_input(pin):
            try:
                if _ki.is_pin_held(int(pin)):
                    return 0  # active-low: 0 == pressed
            except Exception:
                pass
            try:
                return _orig_input(pin)
            except Exception:
                return 1  # default: not pressed

        _GPIO.input = _patched_input

    except Exception:
        # RPi.GPIO or ktox_input not available (e.g. dev machine) — skip silently.
        pass
