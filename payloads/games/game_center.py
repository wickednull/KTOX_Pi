#!/usr/bin/env python3
"""
KTOx Payload: Game Center

Runs a cyberpunk-styled emulator and ROM manager on port 8099.
The LCD payload mode starts/stops the webserver and shows the URL.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, url_for

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PORT = int(os.environ.get("KTOX_GAME_CENTER_PORT", "8099"))
DEFAULT_ROMS_DIR = ROOT_DIR / "roms" if os.name == "nt" else Path("/root/KTOx/roms")
ROMS_DIR = Path(os.environ.get("KTOX_ROMS_DIR", str(DEFAULT_ROMS_DIR)))
TMP_DIR = Path(tempfile.gettempdir())
PID_FILE = TMP_DIR / "ktox_game_center.pid"
LOG_FILE = TMP_DIR / "ktox_game_center.log"
STATE_DIR = TMP_DIR / "ktox_game_center"
INSTALL_LOG = STATE_DIR / "install.log"
INSTALL_STATUS = STATE_DIR / "install_status.json"
RUN_STATUS = STATE_DIR / "run_status.json"

APP = Flask(__name__)
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

EMULATORS = {
    "gb": {
        "name": "Game Boy / Color",
        "engine": "Gambatte via RetroArch",
        "apt": ["retroarch", "libretro-gambatte"],
        "binaries": ["retroarch"],
        "core_candidates": ["/usr/lib/*/libretro/gambatte_libretro.so", "/usr/lib/libretro/gambatte_libretro.so"],
        "ext": [".gb", ".gbc"],
        "browser_core": "gb",
        "launch": "retroarch -L {core} {rom}",
        "notes": "Best low-power choice for GB/GBC on Pi Zero 2 W.",
    },
    "nes": {
        "name": "NES",
        "engine": "Nestopia via RetroArch",
        "apt": ["retroarch", "libretro-nestopia"],
        "binaries": ["retroarch"],
        "core_candidates": ["/usr/lib/*/libretro/nestopia_libretro.so", "/usr/lib/*/libretro/nestopia.libretro", "/usr/lib/libretro/nestopia_libretro.so"],
        "ext": [".nes"],
        "browser_core": "nes",
        "launch": "retroarch -L {core} {rom}",
        "notes": "High-compatibility NES core with a reliable Debian ARM package.",
    },
    "snes": {
        "name": "SNES",
        "engine": "Snes9x via RetroArch",
        "apt": ["retroarch", "libretro-snes9x"],
        "binaries": ["retroarch"],
        "core_candidates": ["/usr/lib/*/libretro/snes9x_libretro.so", "/usr/lib/libretro/snes9x_libretro.so"],
        "ext": [".smc", ".sfc"],
        "browser_core": "snes",
        "launch": "retroarch -L {core} {rom}",
        "notes": "Libretro Snes9x core; lighter titles work best on Pi Zero 2 W.",
    },
    "gba": {
        "name": "Game Boy Advance",
        "engine": "mGBA via RetroArch",
        "apt": ["retroarch", "libretro-mgba"],
        "binaries": ["retroarch"],
        "core_candidates": ["/usr/lib/*/libretro/mgba_libretro.so", "/usr/lib/*/libretro/mgba.libretro", "/usr/lib/libretro/mgba_libretro.so"],
        "ext": [".gba"],
        "browser_core": "gba",
        "launch": "retroarch -L {core} {rom}",
        "notes": "Libretro mGBA core; more dependable install path than mgba-sdl.",
    },
    "genesis": {
        "name": "Genesis / Mega Drive",
        "engine": "Genesis Plus GX via RetroArch",
        "apt": ["retroarch", "libretro-genesisplusgx"],
        "binaries": ["retroarch"],
        "core_candidates": [
            "/usr/lib/*/libretro/genesis_plus_gx_libretro.so",
            "/usr/lib/*/libretro/genesis_plus_gx.libretro",
            "/usr/lib/libretro/genesis_plus_gx_libretro.so",
        ],
        "ext": [".md", ".gen", ".smd", ".32x"],
    },
    "ps1": {
        "name": "PlayStation",
        "engine": "PCSX ReARMed via RetroArch",
        "apt": ["retroarch", "libretro-pcsx-rearmed"],
        "binaries": ["retroarch"],
        "core_candidates": [
            "/usr/lib/*/libretro/pcsx_rearmed_libretro.so",
            "/usr/lib/libretro/pcsx_rearmed_libretro.so",
        ],
        "ext": [".bin", ".cue", ".iso", ".img", ".pbp", ".chd"],
        "browser_core": "psx",
        "launch": "retroarch -L {core} {rom}",
        "notes": "Use .cue when available for multi-track .bin dumps.",
    },
}
