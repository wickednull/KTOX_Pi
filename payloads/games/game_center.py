#!/usr/bin/env python3
"""KTOx Payload: Game Center web launcher for Pi Zero 2 W.

Starts a lightweight Flask UI to install/run browser-playable emulators and manage ROM files.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, url_for

APP = Flask(__name__)
PORT = int(os.environ.get("KTOX_GAME_CENTER_PORT", "8099"))
ROMS_DIR = Path(os.environ.get("KTOX_ROMS_DIR", "/root/KTOx/roms"))

EMULATORS = {
    "nes": {
        "name": "NES (jsnes)",
        "apt": [],
        "web": "https://binji.github.io/binjnes/",
        "ext": [".nes"],
    },
    "gb": {
        "name": "Game Boy (Binjgb)",
        "apt": [],
        "web": "https://binji.github.io/binjgb/",
        "ext": [".gb", ".gbc"],
    },
    "doom": {
        "name": "DOOM (Chocolate Doom local)",
        "apt": ["chocolate-doom"],
        "web": "",
        "ext": [".wad"],
    },
}

TEMPLATE = """
<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>KTOx Game Center</title><style>body{font-family:Arial;margin:20px;max-width:900px}button{margin:3px;padding:8px 12px}code{background:#eee;padding:2px 6px}</style>
</head><body><h2>KTOx Game Center</h2>
<p>Host: <code>{{ host }}</code></p>
<h3>Emulators</h3>
<ul>{% for key, e in emulators.items() %}<li><b>{{e.name}}</b>
<form style='display:inline' method='post' action='/install/{{key}}'><button>Install</button></form>
{% if e.web %}<a href='{{e.web}}' target='_blank'><button type='button'>Open Web Emulator</button></a>{% endif %}
</li>{% endfor %}</ul>
<h3>ROM Manager</h3>
<form method='post' enctype='multipart/form-data' action='/rom/upload'>
<input type='file' name='rom_file'><button>Upload ROM</button></form>
<p><a href='/rom/list'>List ROMs (JSON)</a></p>
</body></html>
"""


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()


def _ensure_dirs() -> None:
    ROMS_DIR.mkdir(parents=True, exist_ok=True)
    for key in EMULATORS:
        (ROMS_DIR / key).mkdir(parents=True, exist_ok=True)


@APP.get("/")
def home():
    host = request.host_url.rstrip("/")
    return render_template_string(TEMPLATE, host=host, emulators=EMULATORS)


@APP.post("/install/<emu>")
def install_emu(emu: str):
    meta = EMULATORS.get(emu)
    if not meta:
        return jsonify({"ok": False, "error": "unknown emulator"}), 404

    packages = meta["apt"]
    logs = []
    failed = False
    if packages:
        rc, out = _run(["apt-get", "update"])
        logs.append({"cmd": "apt-get update", "rc": rc, "output": out[-1200:]})
        failed = failed or rc != 0

        rc, out = _run(["apt-get", "install", "-y", *packages])
        logs.append({"cmd": f"apt-get install -y {' '.join(packages)}", "rc": rc, "output": out[-1200:]})
        failed = failed or rc != 0

    if failed:
        return jsonify({"ok": False, "emulator": emu, "error": "install failed", "logs": logs}), 500
    return jsonify({"ok": True, "emulator": emu, "logs": logs})


@APP.post("/rom/upload")
def upload_rom():
    f = request.files.get("rom_file")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "missing rom_file"}), 400

    name = Path(f.filename).name
    ext = Path(name).suffix.lower()
    target_group = "misc"
    for key, meta in EMULATORS.items():
        if ext in meta["ext"]:
            target_group = key
            break

    out_dir = ROMS_DIR / target_group
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    f.save(target)
    return redirect(url_for("list_roms"))


@APP.get("/rom/list")
def list_roms():
    _ensure_dirs()
    rows = []
    for f in sorted(ROMS_DIR.rglob("*")):
        if f.is_file():
            rows.append({
                "name": f.name,
                "path": str(f.relative_to(ROMS_DIR)),
                "size": f.stat().st_size,
            })
    return jsonify({"ok": True, "rom_root": str(ROMS_DIR), "roms": rows})


@APP.get("/rom/download/<path:p>")
def download_rom(p: str):
    roms_root = ROMS_DIR.resolve()
    pth = (ROMS_DIR / p).resolve()
    try:
        pth.relative_to(roms_root)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400
    if not pth.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    return send_from_directory(pth.parent, pth.name, as_attachment=True)


def main() -> None:
    if not shutil.which("python3"):
        raise SystemExit("python3 required")
    _ensure_dirs()
    print(f"[game_center] Starting web UI on 0.0.0.0:{PORT}")
    APP.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
