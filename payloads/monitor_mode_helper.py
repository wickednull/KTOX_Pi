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
        for rel in (
            os.path.join("payloads", "wifi", "monitor_mode_helper.py"),
            os.path.join("wifi", "monitor_mode_helper.py"),
        ):
            fpath = os.path.join(root, rel)
            if not os.path.isfile(fpath):
                continue
            spec = importlib.util.spec_from_file_location(
                "_wifi_monitor_mode_helper", fpath
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(
        "monitor_mode_helper.py not found in known payload/wifi locations under: " +
        ", ".join(_ROOT_CANDIDATES)
    )


_mmh = _load()

# Re-export public API
activate_monitor_mode          = _mmh.activate_monitor_mode
deactivate_monitor_mode        = _mmh.deactivate_monitor_mode
find_monitor_capable_interface = _mmh.find_monitor_capable_interface
resolve_monitor_interface      = getattr(_mmh, "resolve_monitor_interface", lambda preferred=None: None)

# Re-export helpers used by some payloads directly
_run                    = _mmh._run
_has_cmd                = _mmh._has_cmd
_iface_exists           = _mmh._iface_exists
_iface_mode             = getattr(_mmh, "_iface_mode", getattr(_mmh, "get_type"))
_is_onboard             = getattr(_mmh, "_is_onboard", getattr(_mmh, "is_onboard"))
_current_monitor_ifaces = _mmh._current_monitor_ifaces
_get_phy                = _mmh._get_phy
_ensure_up              = _mmh._ensure_up
_start_interfering_services = getattr(_mmh, "_start_interfering_services", lambda: None)

__all__ = [
    "activate_monitor_mode",
    "deactivate_monitor_mode",
    "find_monitor_capable_interface",
    "resolve_monitor_interface",
]
