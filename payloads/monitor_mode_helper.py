#!/usr/bin/env python3
"""
payloads/monitor_mode_helper.py — Thin compatibility shim
==========================================================
All monitor mode logic lives in wifi/monitor_mode_helper.py.
This file re-exports the public API so that legacy payloads using
``import monitor_mode_helper`` continue to work unchanged.
"""

import sys
import os

# Add project root to path so wifi/ package is reachable
_root = os.path.abspath(os.path.join(__file__, "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

from wifi.monitor_mode_helper import (          # noqa: F401  (re-export)
    activate_monitor_mode,
    deactivate_monitor_mode,
    find_monitor_capable_interface,
    _run,
    _has_cmd,
    _iface_exists,
    _iface_mode,
    _is_onboard,
)

__all__ = [
    "activate_monitor_mode",
    "deactivate_monitor_mode",
    "find_monitor_capable_interface",
]
