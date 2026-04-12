#!/usr/bin/env python3
"""
payloads/monitor_mode_helper.py — Compatibility shim
=====================================================
Loads wifi/monitor_mode_helper.py by direct file path so there is no
dependency on sys.path or Python package structure.  All legacy payloads
that do ``import monitor_mode_helper`` will get the canonical implementation.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))   # payloads/
_ROOT_CANDIDATES = [
    "/root/KTOx",
    os.path.dirname(_HERE),                           # parent of payloads/
    os.path.abspath(os.path.join(_HERE, "..")),
]


def _load():
    for root in _ROOT_CANDIDATES:
        fpath = os.path.join(root, "wifi", "monitor_mode_helper.py")
        if os.path.isfile(fpath):
            spec = importlib.util.spec_from_file_location(
                "_wifi_monitor_mode_helper", fpath
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(
        "wifi/monitor_mode_helper.py not found in: " +
        ", ".join(_ROOT_CANDIDATES)
    )


_mmh = _load()

# Re-export public API
activate_monitor_mode          = _mmh.activate_monitor_mode
deactivate_monitor_mode        = _mmh.deactivate_monitor_mode
find_monitor_capable_interface = _mmh.find_monitor_capable_interface

# Re-export helpers used by some payloads directly
_run                    = _mmh._run
_has_cmd                = _mmh._has_cmd
_iface_exists           = _mmh._iface_exists
_iface_mode             = _mmh._iface_mode
_is_onboard             = _mmh._is_onboard
_current_monitor_ifaces = _mmh._current_monitor_ifaces
_get_phy                = _mmh._get_phy
_ensure_up              = _mmh._ensure_up

__all__ = [
    "activate_monitor_mode",
    "deactivate_monitor_mode",
    "find_monitor_capable_interface",
]
