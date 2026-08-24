#!/usr/bin/env python3
"""Process manager for the optional KTOX Kali noVNC desktop."""

from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import quote
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
KTOX_ROOT = SCRIPT_PATH.parents[2]
RUNTIME_DIR = Path(os.environ.get("KTOX_NOVNC_RUNTIME_DIR", "/dev/shm/ktox_novnc"))
PID_PATH = RUNTIME_DIR / "pids.json"
STATUS_PATH = RUNTIME_DIR / "status.json"
INSTALL_STATUS_PATH = RUNTIME_DIR / "install_status.json"
LOG_PATH = Path(os.environ.get("KTOX_NOVNC_LOG_FILE", "/tmp/ktox_novnc.log"))
PASSWORD_PATH = Path(os.environ.get("KTOX_NOVNC_PASSWORD_FILE", str(RUNTIME_DIR / "vnc.pass")))
DEFAULT_HOST = os.environ.get("KTOX_NOVNC_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("KTOX_NOVNC_PORT", "6080"))
DEFAULT_VNC_PORT = int(os.environ.get("KTOX_VNC_PORT", "5901"))
DEFAULT_DISPLAY = os.environ.get("KTOX_DESKTOP_DISPLAY", ":1")
DEFAULT_GEOMETRY = os.environ.get("KTOX_DESKTOP_GEOMETRY", "1280x720x24")
DEFAULT_MODE = os.environ.get("KTOX_DESKTOP_MODE", "virtual").strip().lower()
USE_EXISTING_DISPLAY = os.environ.get("KTOX_DESKTOP_USE_EXISTING", "").strip().lower() in {"1", "true", "yes", "on"}
XAUTHORITY_PATH = os.environ.get("KTOX_XAUTHORITY", "").strip()


ProcessMap = dict[str, int]
_INSTALL_LOCK = threading.Lock()
_INSTALLING = False
NOVNC_APT_PACKAGES = ("xvfb", "x11vnc", "novnc", "websockify", "openbox", "xterm")


def preferred_ip() -> str:
    """Return the best LAN IP to show to users."""
    for iface in ("wlan0", "eth0", "tailscale0"):
        try:
            res = subprocess.run(
                ["ip", "-4", "addr", "show", iface],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "inet " in line:
                        return line.split("inet ", 1)[1].split("/", 1)[0].strip()
        except Exception:
            pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _display_host(host: str | None = None) -> str:
    host = host or DEFAULT_HOST
    return preferred_ip() if host in ("0.0.0.0", "::", "") else host


def public_url(host: str | None = None, port: int | None = None) -> str:
    return f"http://{_display_host(host)}:{int(port or DEFAULT_PORT)}"


def _desktop_password() -> str:
    configured = os.environ.get("KTOX_NOVNC_PASSWORD", "").strip()
    if configured:
        return configured
    try:
        if PASSWORD_PATH.exists():
            existing = PASSWORD_PATH.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        password = "ktox-" + os.urandom(4).hex()
        PASSWORD_PATH.write_text(password + "\n", encoding="utf-8")
        try:
            PASSWORD_PATH.chmod(0o600)
        except Exception:
            pass
        return password
    except Exception:
        return "ktox-desktop"


def embed_url(host: str | None = None, port: int | None = None) -> str:
    password = quote(_desktop_password(), safe="")
    return f"{public_url(host, port)}/vnc.html?autoconnect=true&resize=remote&path=websockify&password={password}"


def _cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def desktop_mode() -> str:
    """Return whether noVNC should create a virtual desktop or attach to an existing X display."""
    if USE_EXISTING_DISPLAY:
        return "existing"
    if DEFAULT_MODE in {"existing", "physical", "real", "console", "display0"}:
        return "existing"
    return "virtual"


def _novnc_web_dir() -> str | None:
    for raw in (
        os.environ.get("KTOX_NOVNC_WEB_DIR"),
        "/usr/share/novnc",
        "/usr/local/share/novnc",
        str(KTOX_ROOT / "vendor" / "noVNC"),
    ):
        if raw and Path(raw).exists():
            return raw
    return None


def _available_window_manager() -> list[str] | None:
    candidates = (
        ["startxfce4"],
        ["xfce4-session"],
        ["openbox-session"],
        ["lxsession"],
        ["fluxbox"],
        ["icewm-session"],
        ["xterm"],
    )
    for cmd in candidates:
        if _cmd_exists(cmd[0]):
            return cmd
    return None


def dependency_status() -> dict[str, Any]:
    web_dir = _novnc_web_dir()
    has_websockify = _cmd_exists("websockify")
    has_novnc_proxy = _cmd_exists("novnc_proxy")
    mode = desktop_mode()
    missing: list[str] = []
    if mode == "virtual" and not _cmd_exists("Xvfb"):
        missing.append("xvfb")
    if not _cmd_exists("x11vnc"):
        missing.append("x11vnc")
    if not (has_websockify or has_novnc_proxy):
        missing.append("websockify or novnc")
    if not web_dir and not has_novnc_proxy:
        missing.append("novnc web files")
    wm = _available_window_manager()
    if mode == "virtual" and wm is None:
        missing.append("desktop/window manager")
    return {
        "installed": not missing,
        "missing": missing,
        "mode": mode,
        "controls": "existing Kali X display" if mode == "existing" else "virtual Kali desktop on this device",
        "web_dir": web_dir,
        "has_websockify": has_websockify,
        "has_novnc_proxy": has_novnc_proxy,
        "window_manager": " ".join(wm or []),
    }


def _read_install_status() -> dict[str, Any]:
    try:
        if not INSTALL_STATUS_PATH.exists():
            return {"installing": False, "ok": None, "error": None, "packages": list(NOVNC_APT_PACKAGES)}
        data = json.loads(INSTALL_STATUS_PATH.read_text(encoding="utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"installing": False, "ok": None, "error": None, "packages": list(NOVNC_APT_PACKAGES)}


def _write_install_status(payload: dict[str, Any]) -> None:
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        current = _read_install_status()
        current.update(payload)
        current.setdefault("packages", list(NOVNC_APT_PACKAGES))
        current["updated_at"] = int(time.time())
        INSTALL_STATUS_PATH.write_text(json.dumps(current), encoding="utf-8")
    except Exception:
        pass


def install_status() -> dict[str, Any]:
    data = _read_install_status()
    data.setdefault("installing", False)
    data.setdefault("packages", list(NOVNC_APT_PACKAGES))
    return data


def _apt_command(*args: str) -> list[str]:
    if os.geteuid() == 0:
        return ["apt-get", *args]
    sudo = shutil.which("sudo")
    if sudo:
        return [sudo, "-n", "apt-get", *args]
    return ["apt-get", *args]


def _run_apt_step(args: list[str], timeout: int) -> tuple[bool, str]:
    env = os.environ.copy()
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(args)} timed out"
    except Exception as exc:
        return False, str(exc)
    if res.returncode == 0:
        return True, "ok"
    msg = (res.stderr or res.stdout or "").strip()
    if not msg:
        msg = f"{' '.join(args)} failed with exit code {res.returncode}"
    return False, msg[-1000:]


def _install_dependencies_worker() -> dict[str, Any]:
    before = dependency_status()
    if before.get("installed"):
        _write_install_status({"installing": False, "ok": True, "error": None, "message": "dependencies already installed"})
        return status() | {"installing": False, "ok": True, "message": "dependencies already installed"}

    if not shutil.which("apt-get"):
        _write_install_status({"installing": False, "ok": False, "error": "apt-get is not available on this system"})
        return status() | {"ok": False, "error": "apt-get is not available on this system"}

    _write_install_status({
        "installing": True,
        "ok": False,
        "error": None,
        "message": "updating package lists",
        "missing_before": before.get("missing", []),
    })
    ok, msg = _run_apt_step(_apt_command("update", "-qq"), 600)
    if not ok:
        _write_install_status({"installing": False, "ok": False, "error": msg, "message": "apt update failed"})
        return status() | {"ok": False, "error": msg, "message": "apt update failed"}

    _write_install_status({"installing": True, "ok": False, "error": None, "message": "installing noVNC desktop packages"})
    install_args = _apt_command("install", "-y", "--no-install-recommends", *NOVNC_APT_PACKAGES)
    ok, msg = _run_apt_step(install_args, 1200)
    if not ok:
        _write_install_status({"installing": False, "ok": False, "error": msg, "message": "apt install failed"})
        return status() | {"ok": False, "error": msg, "message": "apt install failed"}

    after = dependency_status()
    if not after.get("installed"):
        missing = after.get("missing", [])
        err = "still missing: " + ", ".join(missing)
        _write_install_status({"installing": False, "ok": False, "error": err, "message": "dependencies still missing", "missing_after": missing})
        return status() | {"ok": False, "error": err, "message": "dependencies still missing"}

    _write_install_status({"installing": False, "ok": True, "error": None, "message": "dependencies installed", "missing_after": []})
    return status() | {"ok": True, "message": "dependencies installed"}


def _install_dependencies_thread() -> None:
    global _INSTALLING
    try:
        _install_dependencies_worker()
    finally:
        with _INSTALL_LOCK:
            _INSTALLING = False


def install_dependencies() -> dict[str, Any]:
    """Install the optional noVNC desktop dependencies with apt-get."""
    global _INSTALLING
    with _INSTALL_LOCK:
        if _INSTALLING:
            return install_status() | {"installing": True, "ok": False, "error": "installation already in progress"}
        _INSTALLING = True
    try:
        return _install_dependencies_worker()
    finally:
        with _INSTALL_LOCK:
            _INSTALLING = False


def install_dependencies_async() -> dict[str, Any]:
    global _INSTALLING
    with _INSTALL_LOCK:
        if _INSTALLING:
            return install_status() | {"installing": True, "ok": False, "error": "installation already in progress"}
        _INSTALLING = True
    _write_install_status({"installing": True, "ok": False, "error": None, "message": "installation started"})
    thread = threading.Thread(target=_install_dependencies_thread, daemon=True)
    thread.start()
    return status() | {"ok": True, "installing": True, "message": "installation started"}


def _read_pids() -> ProcessMap:
    try:
        raw = json.loads(PID_PATH.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in raw.items() if v}
    except Exception:
        return {}


def _write_pids(pids: ProcessMap) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(json.dumps(pids), encoding="utf-8")


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _running_pids() -> ProcessMap:
    pids = _read_pids()
    return {name: pid for name, pid in pids.items() if _pid_running(pid)}


def is_running() -> bool:
    pids = _running_pids()
    return bool(pids.get("novnc")) and bool(pids.get("vnc"))


def _write_status(extra: dict[str, Any] | None = None) -> None:
    deps = dependency_status()
    pids = _running_pids()
    running = is_running()
    payload: dict[str, Any] = {
        "running": running,
        "pid": pids.get("novnc"),
        "pids": pids,
        "installed": deps.get("installed", False),
        "missing": deps.get("missing", []),
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "vnc_port": DEFAULT_VNC_PORT,
        "display": DEFAULT_DISPLAY,
        "geometry": DEFAULT_GEOMETRY,
        "mode": deps.get("mode", desktop_mode()),
        "controls": deps.get("controls"),
        "ip": preferred_ip(),
        "url": public_url(),
        "embed_url": embed_url(),
        "proxy_path": f"/desktop/vnc.html?autoconnect=true&resize=remote&path=desktop/websockify&password={quote(_desktop_password(), safe='')}",
        "password": _desktop_password(),
        "log": str(LOG_PATH),
        "updated_at": int(time.time()),
        "install": install_status(),
    }
    payload.update(deps)
    if extra:
        payload.update(extra)
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def status() -> dict[str, Any]:
    _write_status()
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        deps = dependency_status()
        return {"running": False, "installed": deps.get("installed", False), "missing": deps.get("missing", [])}


def _spawn(name: str, cmd: list[str], env: dict[str, str], log_fh) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=str(KTOX_ROOT),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return int(proc.pid)


def _stop_pid(pid: int) -> None:
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass


def start_server(host: str | None = None, port: int | None = None) -> dict[str, Any]:
    if is_running():
        return status() | {"ok": True, "message": "already running"}

    deps = dependency_status()
    if not deps.get("installed"):
        _write_status({"ok": False, "message": "missing dependencies"})
        return status() | {"ok": False, "message": "missing dependencies"}

    host = host or DEFAULT_HOST
    port = int(port or DEFAULT_PORT)
    display = DEFAULT_DISPLAY
    vnc_port = DEFAULT_VNC_PORT
    mode = desktop_mode()
    env = os.environ.copy()
    env.update({"DISPLAY": display, "PYTHONUNBUFFERED": "1"})
    if XAUTHORITY_PATH:
        env["XAUTHORITY"] = XAUTHORITY_PATH
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    pids: ProcessMap = {}
    try:
        with LOG_PATH.open("ab") as log_fh:
            log_fh.write(f"\n--- KTOX noVNC start {time.strftime('%Y-%m-%d %H:%M:%S')} mode={mode} display={display} ---\n".encode())
            if mode == "virtual":
                pids["xvfb"] = _spawn("xvfb", ["Xvfb", display, "-screen", "0", DEFAULT_GEOMETRY, "-nolisten", "tcp"], env, log_fh)
                time.sleep(1)
                wm = _available_window_manager()
                if wm:
                    pids["desktop"] = _spawn("desktop", wm, env, log_fh)
            password = _desktop_password()
            PASSWORD_PATH.write_text(password + "\n", encoding="utf-8")
            try:
                PASSWORD_PATH.chmod(0o600)
            except Exception:
                pass
            pids["vnc"] = _spawn(
                "vnc",
                ["x11vnc", "-display", display, "-localhost", "-rfbport", str(vnc_port), "-forever", "-shared", "-passwdfile", str(PASSWORD_PATH), "-quiet"],
                env,
                log_fh,
            )
            time.sleep(1)
            if _cmd_exists("websockify"):
                web_dir = str(deps.get("web_dir") or "/usr/share/novnc")
                pids["novnc"] = _spawn(
                    "novnc",
                    ["websockify", f"{host}:{port}", f"127.0.0.1:{vnc_port}", "--web", web_dir],
                    env,
                    log_fh,
                )
            else:
                pids["novnc"] = _spawn(
                    "novnc",
                    ["novnc_proxy", "--listen", str(port), "--vnc", f"127.0.0.1:{vnc_port}"],
                    env,
                    log_fh,
                )
        _write_pids(pids)
        time.sleep(2)
        result = status()
        if not result.get("running"):
            stop_server()
            return result | {"ok": False, "message": f"noVNC failed to start; see {LOG_PATH}"}
        return result | {"ok": True, "message": "started"}
    except Exception as exc:
        for pid in pids.values():
            _stop_pid(pid)
        _write_pids({})
        _write_status({"ok": False, "message": str(exc)})
        return status() | {"ok": False, "message": str(exc)}


def stop_server() -> dict[str, Any]:
    pids = _read_pids()
    for pid in reversed(list(pids.values())):
        _stop_pid(pid)
    time.sleep(1)
    for pid in reversed(list(pids.values())):
        if _pid_running(pid):
            try:
                os.killpg(int(pid), signal.SIGKILL)
            except Exception:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
    try:
        PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    _write_status({"ok": True, "message": "stopped"})
    return status() | {"ok": True, "message": "stopped"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage KTOX noVNC desktop")
    parser.add_argument("action", choices=("status", "start", "stop"))
    args = parser.parse_args()
    if args.action == "start":
        print(json.dumps(start_server(), indent=2))
    elif args.action == "stop":
        print(json.dumps(stop_server(), indent=2))
    else:
        print(json.dumps(status(), indent=2))
