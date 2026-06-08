#!/usr/bin/env python3
"""Runtime controls for payload monitor mode and memory saving."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SESSION_PATH = Path("/dev/shm/ktox_monitor_session.json")
PAYLOAD_ROOT_MARKERS = ("/root/KTOx/payloads", "/root/KTOX/payloads")
CORE_PROCESS_MARKERS = (
    "web_server.py",
    "device_server.py",
    "ktox_device.py",
    "ktox_device_pi.py",
    "ktox_device_root.py",
    "caddy",
    "sshd",
    "systemd",
)
OPTIONAL_SERVICE_NAMES = ("bluetooth", "avahi-daemon", "cups", "triggerhappy")


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except Exception as exc:
        return 127, str(exc)


def _wifi_iface_mode(iface: str) -> str:
    rc, out = _run(["iw", "dev", iface, "info"], timeout=4)
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("type "):
                return line.split(None, 1)[1].strip()
    return ""


def _list_wifi_ifaces() -> list[str]:
    sys_class = Path("/sys/class/net")
    try:
        names = sorted(p.name for p in sys_class.iterdir())
    except Exception:
        names = []
    return [name for name in names if name.startswith(("wl", "mon"))]


def find_monitor_capable_interface() -> str | None:
    for iface in _list_wifi_ifaces():
        if _wifi_iface_mode(iface) == "monitor":
            return iface
    for iface in _list_wifi_ifaces():
        if iface != "wlan0":
            return iface
    return next((iface for iface in _list_wifi_ifaces() if iface == "wlan0"), None)


def payload_requires_monitor(path: str | os.PathLike[str]) -> bool:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False
    markers = (
        "activate_monitor_mode(",
        "enable_monitor_mode(",
        "airmon-ng start",
        "set type monitor",
        "mode monitor",
        "iwconfig",
    )
    return "monitor" in text and any(marker in text for marker in markers)


def _import_monitor_helper():
    for module_name in ("wifi.monitor_mode_helper", "monitor_mode_helper"):
        try:
            module = __import__(module_name, fromlist=["dummy"])
            return module
        except Exception:
            continue
    return None


def start_payload_monitor(path: str | os.PathLike[str]) -> dict:
    """Start monitor mode when a payload appears to require it."""
    if not payload_requires_monitor(path):
        return {"required": False, "started": False, "iface": None}

    iface = find_monitor_capable_interface()
    if not iface:
        return {"required": True, "started": False, "iface": None, "error": "no_wifi_interface"}

    if _wifi_iface_mode(iface) == "monitor":
        session = {"required": True, "started": False, "iface": iface, "already_monitor": True}
        _write_session(session)
        return session

    helper = _import_monitor_helper()
    try:
        if helper and hasattr(helper, "activate_monitor_mode"):
            mon_iface = helper.activate_monitor_mode(iface)
            iface = mon_iface or iface
        else:
            _run(["airmon-ng", "check", "kill"], timeout=10)
            rc, _ = _run(["airmon-ng", "start", iface], timeout=20)
            if rc != 0:
                _run(["ip", "link", "set", iface, "down"], timeout=5)
                _run(["iw", "dev", iface, "set", "type", "monitor"], timeout=5)
                _run(["ip", "link", "set", iface, "up"], timeout=5)
        session = {"required": True, "started": True, "iface": iface, "ts": time.time()}
        _write_session(session)
        return session
    except Exception as exc:
        return {"required": True, "started": False, "iface": iface, "error": str(exc)}


def _write_session(session: dict) -> None:
    try:
        SESSION_PATH.write_text(json.dumps(session), encoding="utf-8")
    except Exception:
        pass


def _read_session() -> dict:
    try:
        if SESSION_PATH.exists():
            return json.loads(SESSION_PATH.read_text(encoding="utf-8") or "{}")
    except Exception:
        pass
    return {}


def stop_payload_monitor(session: dict | None = None) -> dict:
    """Stop monitor mode from a payload session and remove stale session state."""
    session = session or _read_session()
    iface = session.get("iface") or find_monitor_capable_interface()
    stopped = False
    errors: list[str] = []
    helper = _import_monitor_helper()

    if iface and _wifi_iface_mode(iface) == "monitor":
        try:
            if helper and hasattr(helper, "deactivate_monitor_mode"):
                helper.deactivate_monitor_mode(iface)
            else:
                rc, out = _run(["airmon-ng", "stop", iface], timeout=15)
                if rc != 0 and _wifi_iface_mode(iface) == "monitor":
                    _run(["ip", "link", "set", iface, "down"], timeout=5)
                    _run(["iw", "dev", iface, "set", "type", "managed"], timeout=5)
                    _run(["ip", "link", "set", iface, "up"], timeout=5)
                    if out:
                        errors.append(out)
            stopped = _wifi_iface_mode(iface) != "monitor"
        except Exception as exc:
            errors.append(str(exc))

    try:
        SESSION_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    return {"stopped": stopped, "iface": iface, "errors": errors}


def _payload_pids() -> list[int]:
    current = os.getpid()
    rc, out = _run(["ps", "-eo", "pid=,args="], timeout=8)
    if rc != 0:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        args = parts[1]
        if pid == current:
            continue
        if any(marker in args for marker in PAYLOAD_ROOT_MARKERS) and not any(marker in args for marker in CORE_PROCESS_MARKERS):
            pids.append(pid)
    return pids


def resource_saver() -> dict:
    """Free memory and lower heat by stopping transient attack/runtime work."""
    result = {"monitor": stop_payload_monitor(), "killed_pids": [], "services": [], "cache": False}

    for pid in _payload_pids():
        try:
            os.kill(pid, signal.SIGTERM)
            result["killed_pids"].append(pid)
        except Exception:
            continue
    time.sleep(0.5)
    for pid in _payload_pids():
        try:
            os.kill(pid, signal.SIGKILL)
            if pid not in result["killed_pids"]:
                result["killed_pids"].append(pid)
        except Exception:
            continue

    for service in OPTIONAL_SERVICE_NAMES:
        rc, _ = _run(["systemctl", "is-active", "--quiet", service], timeout=3)
        if rc == 0:
            stop_rc, stop_out = _run(["systemctl", "stop", service], timeout=10)
            result["services"].append({"name": service, "stopped": stop_rc == 0, "detail": stop_out})

    _run(["sync"], timeout=5)
    try:
        Path("/proc/sys/vm/drop_caches").write_text("3\n", encoding="utf-8")
        result["cache"] = True
    except Exception:
        result["cache"] = False

    _run(["swapoff", "-a"], timeout=20)
    _run(["swapon", "-a"], timeout=20)
    return result
