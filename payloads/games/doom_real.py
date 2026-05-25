#!/usr/bin/env python3
"""KTOx Payload: DOOM on LCD.

Primary: Chocolate Doom on framebuffer LCD.
Fallback: DOOM demake (pure LCD) if Chocolate Doom cannot launch.
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


def _find_wad():
    env_path = os.environ.get("KTOX_DOOM_WAD")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    for p in WAD_CANDIDATES:
        if p.exists():
            return p
    return None


def _run(cmd):
    print("[doom_real] $", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def install_dependencies():
    if shutil.which("chocolate-doom") is None:
        _run(["apt-get", "update"])
        _run(["apt-get", "install", "-y", "chocolate-doom"])
    _run(["modprobe", "uinput"])


def _launch_doom_fb(fbdev, wad):
    env = os.environ.copy()
    env["SDL_VIDEODRIVER"] = "fbcon"
    env["SDL_FBDEV"] = fbdev
    env["FRAMEBUFFER"] = fbdev

    cmd = ["chocolate-doom", "-iwad", str(wad), "-nosound", "-nomusic", "-fullscreen"]
    print(f"[doom_real] Launching on {fbdev} ...", flush=True)
    proc = subprocess.Popen(cmd, env=env)

    def _handle_exit(signum, _frame):
        print(f"[doom_real] signal={signum}; terminating game")
        proc.terminate()

    signal.signal(signal.SIGTERM, _handle_exit)
    signal.signal(signal.SIGINT, _handle_exit)

    # Freeze detector: if process exits immediately, treat as failed launch.
    time.sleep(1.2)
    if proc.poll() is not None:
        return proc.returncode or 1

    while proc.poll() is None:
        time.sleep(0.2)
    return proc.returncode or 0


def launch_doom():
    wad = _find_wad()
    if wad is None:
        print("[doom_real] No IWAD found. Falling back to DOOM demake.")
        return _launch_demake()

    for fb in ("/dev/fb1", "/dev/fb0"):
        rc = _launch_doom_fb(fb, wad)
        if rc == 0:
            return 0
        print(f"[doom_real] Chocolate Doom failed on {fb} (rc={rc})")

    print("[doom_real] Falling back to doom_demake.py")
    return _launch_demake()


def _launch_demake():
    demake = Path(__file__).with_name("doom_demake.py")
    if demake.exists():
        return subprocess.call([sys.executable, str(demake)])
    print("[doom_real] Missing doom_demake.py fallback")
    return 2


def main():
    install_dependencies()
    return launch_doom()


if __name__ == "__main__":
    sys.exit(main())
