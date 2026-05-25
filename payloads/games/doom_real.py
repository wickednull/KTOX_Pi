#!/usr/bin/env python3
"""KTOx Payload: Real DOOM launcher for framebuffer LCD.

Runs Chocolate Doom on Raspberry Pi console framebuffers with optional uinput setup.
KEY3 exits launcher; process receives SIGTERM on exit.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

WAD_CANDIDATES = [
    Path("/root/.local/share/games/doom/doom1.wad"),
    Path("/root/.local/share/games/doom/doom.wad"),
    Path("/opt/ktox/doom/doom1.wad"),
    Path("/opt/ktox/doom/doom.wad"),
]


def _find_wad() -> Path | None:
    env_path = os.environ.get("KTOX_DOOM_WAD")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    for p in WAD_CANDIDATES:
        if p.exists():
            return p
    return None


def _is_installed(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str]) -> int:
    print("[doom_real] $", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def install_dependencies() -> None:
    if _is_installed("chocolate-doom"):
        print("[doom_real] chocolate-doom already installed")
    else:
        _run(["apt-get", "update"])
        _run(["apt-get", "install", "-y", "chocolate-doom"])

    # uinput is part of kernel; best effort.
    _run(["modprobe", "uinput"])


def launch_doom() -> int:
    wad = _find_wad()
    if wad is None:
        print("[doom_real] No IWAD found. Set KTOX_DOOM_WAD or place doom1.wad in:")
        for c in WAD_CANDIDATES:
            print(f"  - {c}")
        return 2

    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "fbcon")
    env.setdefault("SDL_FBDEV", "/dev/fb1")
    env.setdefault("FRAMEBUFFER", "/dev/fb1")

    cmd = [
        "chocolate-doom",
        "-iwad",
        str(wad),
        "-nosound",
        "-nomusic",
        "-window",
        "0",
    ]

    print("[doom_real] Launching Chocolate Doom on framebuffer...", flush=True)
    proc = subprocess.Popen(cmd, env=env)

    def _handle_exit(signum, frame):
        print(f"[doom_real] signal={signum}; terminating game")
        proc.terminate()

    signal.signal(signal.SIGTERM, _handle_exit)
    signal.signal(signal.SIGINT, _handle_exit)

    while proc.poll() is None:
        time.sleep(0.2)
    return proc.returncode or 0


def main() -> int:
    install_dependencies()
    return launch_doom()


if __name__ == "__main__":
    sys.exit(main())
