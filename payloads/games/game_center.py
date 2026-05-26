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
        "engine": "PicoDrive via RetroArch",
        "apt": ["retroarch", "libretro-picodrive"],
        "binaries": ["retroarch"],
        "core_candidates": ["/usr/lib/*/libretro/picodrive_libretro.so", "/usr/lib/libretro/picodrive_libretro.so"],
        "ext": [".md", ".gen"],
        "browser_core": "segaMD",
        "launch": "retroarch -L {core} {rom}",
        "notes": "Fast, reliable 16-bit profile for the Zero 2 W.",
    },
    "psx": {
        "name": "PlayStation 1",
        "engine": "PCSX-ReARMed via RetroArch",
        "apt": ["retroarch", "libretro-pcsx-rearmed"],
        "binaries": ["retroarch"],
        "core_candidates": ["/usr/lib/*/libretro/pcsx_rearmed_libretro.so", "/usr/lib/libretro/pcsx_rearmed_libretro.so"],
        "ext": [".cue", ".chd", ".pbp"],
        "browser_core": "psx",
        "launch": "retroarch -L {core} {rom}",
        "notes": "Experimental but possible for lighter PS1 titles.",
    },
    "doom": {
        "name": "DOOM WADs",
        "engine": "Chocolate Doom",
        "apt": ["chocolate-doom"],
        "binaries": ["chocolate-doom"],
        "ext": [".wad"],
        "browser_core": None,
        "launch": "chocolate-doom -iwad {rom}",
        "notes": "Native runtime, excellent fit for the device.",
    },
}

HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KTOx Game Center</title>
  <style>
    :root{
      color-scheme:dark;
      --bg:#05060a; --panel:#0b1020; --panel2:#10182d; --line:#26365d;
      --text:#edf5ff; --muted:#8ea3c7; --red:#ef4444; --cyan:#67e8f9;
      --green:#34d399; --yellow:#fbbf24;
    }
    *{box-sizing:border-box} body{margin:0;background:
      linear-gradient(rgba(103,232,249,.035) 1px,transparent 1px),
      linear-gradient(90deg,rgba(239,68,68,.035) 1px,transparent 1px),
      radial-gradient(circle at 15% 0%,rgba(239,68,68,.18),transparent 36%),
      radial-gradient(circle at 80% 12%,rgba(103,232,249,.12),transparent 34%),var(--bg);
      background-size:28px 28px,28px 28px,auto,auto,auto;
      color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif;letter-spacing:0}
    header{position:sticky;top:0;z-index:5;border-bottom:1px solid rgba(103,232,249,.22);
      background:rgba(5,6,10,.86);backdrop-filter:blur(14px)}
    .bar{max-width:1220px;margin:auto;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;gap:16px}
    .brand{font-weight:900;font-size:22px;text-transform:uppercase}.brand span{color:var(--red);text-shadow:0 0 16px rgba(239,68,68,.55)}
    .status{display:flex;gap:8px;flex-wrap:wrap}.chip{border:1px solid var(--line);background:rgba(16,24,45,.72);border-radius:8px;padding:6px 9px;color:var(--muted);font-size:12px}
    main{max-width:1220px;margin:auto;padding:18px;display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:16px}
    section,.card{border:1px solid var(--line);background:linear-gradient(180deg,rgba(16,24,45,.9),rgba(8,12,24,.86));border-radius:8px;box-shadow:0 16px 38px rgba(0,0,0,.36)}
    section{padding:14px}.topline{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}
    h1,h2,h3,p{margin:0} h2{font-size:16px;text-transform:uppercase;color:#dbeafe} .muted{color:var(--muted);font-size:12px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
    .card{padding:12px}.card h3{font-size:15px;margin-bottom:5px}.meta{font-size:12px;color:var(--muted);min-height:34px}
    .tags{margin:10px 0}.tag{display:inline-block;border:1px solid rgba(103,232,249,.28);color:#bae6fd;padding:2px 6px;border-radius:6px;font-size:11px;margin:0 4px 4px 0}
    button,a.button{border:1px solid rgba(103,232,249,.34);background:#13284d;color:white;border-radius:7px;padding:8px 10px;text-decoration:none;cursor:pointer;font-weight:700;font-size:12px}
    button:hover,a.button:hover{filter:brightness(1.12)}button.good{border-color:rgba(52,211,153,.45);background:#14513f}button.danger{border-color:rgba(239,68,68,.45);background:#5d151f}
    .library{display:grid;gap:8px}.rom{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;border:1px solid rgba(148,163,184,.16);background:rgba(2,6,23,.52);border-radius:8px;padding:10px}
    .rom strong{display:block;font-size:13px}.rom small{color:var(--muted)}
    .console{margin-bottom:12px}.console-title{display:flex;justify-content:space-between;align-items:center;border:1px solid rgba(103,232,249,.22);border-radius:8px 8px 0 0;background:rgba(6,16,34,.75);padding:9px 10px}
    .console-title strong{font-size:13px;text-transform:uppercase}.console-body{display:grid;gap:8px;border:1px solid rgba(103,232,249,.12);border-top:0;border-radius:0 0 8px 8px;padding:8px;background:rgba(2,6,23,.28)}
    .actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}.actions button{white-space:nowrap}
    button.secondary{background:#1f2f52;border-color:rgba(148,163,184,.32)}
    .terminal{height:380px;overflow:auto;background:#020617;border:1px solid rgba(103,232,249,.18);border-radius:8px;padding:12px;font-family:"JetBrains Mono",Consolas,monospace;font-size:12px;color:#b7f7d8;white-space:pre-wrap}
    .upload{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.upload input{max-width:100%;border:1px solid var(--line);background:#050a16;color:var(--text);padding:8px;border-radius:7px}
    @media(max-width:900px){main{grid-template-columns:1fr}.bar{align-items:flex-start;flex-direction:column}.terminal{height:300px}}
  </style>
</head>
<body>
  <header><div class="bar">
    <div><div class="brand">KTOx <span>Game Center</span></div><div class="muted">Payload webserver on {{host}} - Pi Zero 2 W emulator profile</div></div>
    <div class="status"><div class="chip">ROM root: {{rom_root}}</div><div class="chip">Port {{port}}</div></div>
  </div></header>
  <main>
    <div>
      <section>
        <div class="topline"><div><h2>Emulator Rack</h2><p class="muted">Install, inspect, and launch from the payload server.</p></div><button onclick="refreshAll()">Refresh</button></div>
        <div id="emulators" class="grid"></div>
      </section>
      <section style="margin-top:16px">
        <div class="topline"><div><h2>Game Library</h2><p class="muted">Organized by console. Browser play opens a web emulator; Pi launch starts the native emulator on the device.</p></div></div>
        <form class="upload" method="post" enctype="multipart/form-data" action="/api/roms/upload">
          <input type="file" name="rom_file" required>
          <button class="good">Upload ROM</button>
        </form>
        <div id="roms" class="library" style="margin-top:12px"></div>
      </section>
    </div>
    <aside>
      <section>
        <div class="topline"><div><h2>Install Terminal</h2><p class="muted">Live output from apt and setup commands.</p></div><button onclick="clearLog()">Clear</button></div>
        <div id="terminal" class="terminal">Waiting for command...</div>
      </section>
      <section style="margin-top:16px">
        <h2>Run Status</h2>
        <div id="runStatus" class="muted" style="margin-top:8px">No emulator launched.</div>
      </section>
    </aside>
  </main>
  <script>
    const term = document.getElementById('terminal');
    const fmtBytes = n => !n ? '0 B' : (n < 1048576 ? (n/1024).toFixed(1)+' KB' : (n/1048576).toFixed(1)+' MB');
    async function api(path, opts){ const r = await fetch(path, opts); return await r.json(); }
    async function installEmu(id){
      await api('/api/emulators/'+id+'/install', {method:'POST'});
      pollLog();
      refreshAll();
    }
    function playBrowser(path){
      window.location.href = '/play?path=' + encodeURIComponent(path);
    }
    async function launchPiRom(path){
      const data = await api('/api/roms/launch', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path})});
      document.getElementById('runStatus').textContent = data.ok ? `Launched ${data.rom} with ${data.emulator}` : (data.error || 'Launch failed');
      refreshAll();
    }
    async function stopEmulator(){
      const data = await api('/api/run/stop', {method:'POST'});
      document.getElementById('runStatus').textContent = data.message || 'Stopped';
      refreshAll();
    }
    async function refreshAll(){
      const data = await api('/api/state');
      document.getElementById('emulators').innerHTML = data.emulators.map(e => `
        <div class="card">
          <h3>${e.name}</h3><div class="meta"><b>${e.engine}</b><br>${e.notes}</div>
          <div class="tags">${e.ext.map(x=>`<span class="tag">${x}</span>`).join('')}</div>
          <div class="muted">Status: <b style="color:${e.installed ? 'var(--green)' : 'var(--yellow)'}">${e.installed ? 'installed' : 'missing'}</b></div>
          ${!e.installed && e.runtime_missing && e.runtime_missing.length ? `<div class="muted">Missing: ${e.runtime_missing.join(', ')}</div>` : ''}
          <div style="margin-top:10px"><button class="good" onclick="installEmu('${e.id}')">${e.installed ? 'Repair / Update' : 'Install'}</button></div>
        </div>`).join('');
      const groups = {};
      for (const rom of data.roms) {
        if (!groups[rom.emulator]) groups[rom.emulator] = { label: rom.system, items: [] };
        groups[rom.emulator].items.push(rom);
      }
      document.getElementById('roms').innerHTML = data.roms.length ? Object.entries(groups).map(([id, group]) => `
        <div class="console">
          <div class="console-title"><strong>${group.label}</strong><span class="muted">${group.items.length} ROM${group.items.length === 1 ? '' : 's'}</span></div>
          <div class="console-body">${group.items.map(r => {
            const safe = r.path.replaceAll('\\','\\\\').replaceAll("'","\\'");
            return `<div class="rom"><div><strong>${r.name}</strong><small>${fmtBytes(r.size)} - ${r.path}</small></div>
              <div class="actions">
                ${r.browser_playable ? `<button class="good" onclick="playBrowser('${safe}')">Play in Browser</button>` : `<button class="secondary" disabled>Native Only</button>`}
                <button class="secondary" onclick="launchPiRom('${safe}')">Launch on Pi</button>
              </div></div>`;
          }).join('')}</div>
        </div>`).join('') : '<div class="card muted">No ROMs yet. Upload .gb, .gbc, .nes, .sfc, .smc, .gba, .md, .gen, .cue, .chd, .pbp, or .wad files.</div>';
      document.getElementById('runStatus').innerHTML = data.running && data.running.active
        ? `<b style="color:var(--green)">Running</b>: ${data.running.rom || ''}<br><button class="danger" style="margin-top:8px" onclick="stopEmulator()">Stop Emulator</button>`
        : 'No emulator launched.';
    }
    async function pollLog(){
      const data = await api('/api/install/log');
      term.textContent = data.log || 'Waiting for command...';
      term.scrollTop = term.scrollHeight;
      if(data.running) setTimeout(pollLog, 1200);
    }
    async function clearLog(){ await api('/api/install/log/clear', {method:'POST'}); pollLog(); }
    refreshAll(); pollLog(); setInterval(refreshAll, 5000);
  </script>
</body></html>
"""

PLAYER_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{name}} - KTOx Game Center</title>
  <style>
    :root{color-scheme:dark;--bg:#05060a;--line:#26365d;--text:#edf5ff;--muted:#8ea3c7;--red:#ef4444;--cyan:#67e8f9}
    *{box-sizing:border-box}body{margin:0;background:#05060a;color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif}
    header{height:54px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 16px;border-bottom:1px solid rgba(103,232,249,.22);background:rgba(5,6,10,.9)}
    a{color:var(--cyan);text-decoration:none}.title{min-width:0}.title strong{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.title span{color:var(--muted);font-size:12px}
    #game{width:100vw;height:calc(100vh - 54px);background:#000}
    .warn{padding:14px;color:#ffd7a1;background:#261402;border:1px solid #6b3d10;margin:14px;border-radius:8px}
  </style>
</head>
<body>
  <header>
    <a href="/">Back to Library</a>
    <div class="title"><strong>{{name}}</strong><span>{{system}} - browser core {{core}}</span></div>
  </header>
  <div id="game"></div>
  <script>
    window.EJS_player = "#game";
    window.EJS_core = "{{core}}";
    window.EJS_gameName = "{{name}}";
    window.EJS_gameUrl = "{{rom_url}}";
    window.EJS_pathtodata = "https://cdn.emulatorjs.org/stable/data/";
    window.EJS_startOnLoaded = true;
  </script>
  <script src="https://cdn.emulatorjs.org/stable/data/loader.js"></script>
</body>
</html>"""


def _state_setup() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ROMS_DIR.mkdir(parents=True, exist_ok=True)
    for key in EMULATORS:
        (ROMS_DIR / key).mkdir(parents=True, exist_ok=True)


def _local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _which(name: str) -> str | None:
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _find_core(patterns: list[str]) -> str | None:
    import glob
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def _runtime_missing(meta: dict) -> list[str]:
    missing = []
    for binary in meta.get("binaries", []):
        if not _which(binary):
            missing.append(f"binary:{binary}")
    if meta.get("core_candidates") and not _find_core(meta["core_candidates"]):
        missing.append("libretro core")
    return missing


def _emulator_installed(meta: dict) -> bool:
    return not _runtime_missing(meta)


def _read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _append_install(line: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with INSTALL_LOG.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(line.rstrip("\n") + "\n")


def _run_logged(command: list[str]) -> int:
    _append_install("$ " + " ".join(shlex.quote(part) for part in command))
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    if proc.stdout:
        for line in proc.stdout:
            _append_install(line.rstrip("\n"))
    rc = proc.wait()
    _append_install(f"[exit {rc}]")
    return rc


def _install_worker(emu_id: str) -> None:
    meta = EMULATORS[emu_id]
    _write_json(INSTALL_STATUS, {"running": True, "emulator": emu_id, "ok": False, "error": None, "ts": time.time()})
    _append_install(f"== {datetime.now().isoformat(timespec='seconds')} installing {meta['name']} ==")
    try:
        rc = _run_logged(["apt-get", "update"])
        if rc != 0:
            raise RuntimeError("apt-get update failed")
        rc = _run_logged(["apt-get", "install", "-y", "--no-install-recommends", *meta["apt"]])
        if rc != 0:
            raise RuntimeError("apt-get install failed")
        missing = _runtime_missing(meta)
        if missing:
            raise RuntimeError("install completed, but missing " + ", ".join(missing))
        _append_install(f"[OK] {meta['engine']} is ready")
        _write_json(INSTALL_STATUS, {"running": False, "emulator": emu_id, "ok": True, "error": None, "ts": time.time()})
    except Exception as exc:
        _append_install(f"[ERR] {exc}")
        _write_json(INSTALL_STATUS, {"running": False, "emulator": emu_id, "ok": False, "error": str(exc), "ts": time.time()})


def _rom_emulator(path: Path) -> tuple[str, dict] | tuple[None, None]:
    ext = path.suffix.lower()
    for emu_id, meta in EMULATORS.items():
        if ext in meta["ext"]:
            return emu_id, meta
    return None, None


def _list_roms() -> list[dict]:
    _state_setup()
    roms = []
    for path in sorted(ROMS_DIR.rglob("*"), key=lambda p: str(p).lower()):
        if not path.is_file():
            continue
        emu_id, meta = _rom_emulator(path)
        if not meta:
            continue
        stat = path.stat()
        roms.append({
            "name": path.name,
            "path": str(path.relative_to(ROMS_DIR)).replace("\\", "/"),
            "system": meta["name"],
            "emulator": emu_id,
            "browser_core": meta.get("browser_core"),
            "browser_playable": bool(meta.get("browser_core")),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    return sorted(roms, key=lambda r: (str(r["system"]).lower(), str(r["name"]).lower()))


def _safe_rom_path(raw: str) -> Path | None:
    target = (ROMS_DIR / raw.strip().lstrip("/")).resolve()
    try:
        target.relative_to(ROMS_DIR.resolve())
        return target
    except Exception:
        return None


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _start_server() -> dict:
    pid = _read_pid()
    if _is_running(pid):
        return {"ok": True, "message": f"already running ({pid})", "pid": pid}
    log = LOG_FILE.open("a", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([sys.executable, __file__, "--serve"], stdout=log, stderr=log, start_new_session=True)
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return {"ok": True, "message": f"started ({proc.pid})", "pid": proc.pid}


def _stop_server() -> dict:
    pid = _read_pid()
    if not _is_running(pid):
        PID_FILE.unlink(missing_ok=True)
        return {"ok": True, "message": "already stopped"}
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        return {"ok": False, "message": f"stop failed: {exc}"}
    time.sleep(0.4)
    PID_FILE.unlink(missing_ok=True)
    return {"ok": True, "message": f"stopped ({pid})"}


@APP.get("/")
def home():
    return render_template_string(HTML, host=request.host_url.rstrip("/"), rom_root=str(ROMS_DIR), port=PORT)


@APP.get("/play")
def play_rom():
    raw_path = str(request.args.get("path", ""))
    target = _safe_rom_path(raw_path)
    if target is None or not target.exists():
        return render_template_string(
            '<div class="warn">ROM not found. <a href="/">Back to Library</a></div>'
        ), 404
    _emu_id, meta = _rom_emulator(target)
    if not meta or not meta.get("browser_core"):
        return render_template_string(
            '<div class="warn">This ROM is native-only in Game Center. <a href="/">Back to Library</a></div>'
        ), 400
    rel = str(target.relative_to(ROMS_DIR)).replace("\\", "/")
    return render_template_string(
        PLAYER_HTML,
        name=target.name,
        system=meta["name"],
        core=meta["browser_core"],
        rom_url=url_for("api_raw_rom", path=rel),
    )


@APP.get("/api/state")
def api_state():
    emulators = []
    for emu_id, meta in EMULATORS.items():
        item = dict(meta)
        item["id"] = emu_id
        missing = _runtime_missing(meta)
        item["installed"] = not missing
        item["runtime_missing"] = missing
        item.pop("launch", None)
        item.pop("core_candidates", None)
        emulators.append(item)
    return jsonify({
        "ok": True,
        "emulators": emulators,
        "roms": _list_roms(),
        "install": _read_json(INSTALL_STATUS, {"running": False}),
        "running": _read_json(RUN_STATUS, {"active": False}),
    })


@APP.post("/api/emulators/<emu_id>/install")
def api_install(emu_id: str):
    if emu_id not in EMULATORS:
        return jsonify({"ok": False, "error": "unknown emulator"}), 404
    status = _read_json(INSTALL_STATUS, {"running": False})
    if status.get("running"):
        return jsonify({"ok": True, "running": True, "message": "installer already running"})
    threading.Thread(target=_install_worker, args=(emu_id,), daemon=True).start()
    return jsonify({"ok": True, "running": True})


@APP.get("/api/install/log")
def api_install_log():
    status = _read_json(INSTALL_STATUS, {"running": False})
    try:
        log = INSTALL_LOG.read_text(encoding="utf-8", errors="replace")[-20000:]
    except Exception:
        log = ""
    return jsonify({"ok": True, "running": bool(status.get("running")), "status": status, "log": log})


@APP.post("/api/install/log/clear")
def api_install_log_clear():
    INSTALL_LOG.write_text("", encoding="utf-8")
    return jsonify({"ok": True})


@APP.post("/api/roms/upload")
def api_upload_rom():
    _state_setup()
    uploaded = request.files.get("rom_file")
    if not uploaded or not uploaded.filename:
        return jsonify({"ok": False, "error": "missing rom_file"}), 400
    name = Path(uploaded.filename).name
    ext = Path(name).suffix.lower()
    target_group = "misc"
    for emu_id, meta in EMULATORS.items():
        if ext in meta["ext"]:
            target_group = emu_id
            break
    out_dir = ROMS_DIR / target_group
    out_dir.mkdir(parents=True, exist_ok=True)
    uploaded.save(out_dir / name)
    return redirect(url_for("home"))


@APP.get("/api/roms")
def api_roms():
    return jsonify({"ok": True, "roms": _list_roms(), "rom_root": str(ROMS_DIR)})


@APP.get("/api/roms/download/<path:rom_path>")
def api_download_rom(rom_path: str):
    target = _safe_rom_path(rom_path)
    if target is None or not target.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    return send_from_directory(target.parent, target.name, as_attachment=True)


@APP.get("/api/roms/raw")
def api_raw_rom():
    target = _safe_rom_path(str(request.args.get("path", "")))
    if target is None or not target.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    return send_from_directory(target.parent, target.name, as_attachment=False)


@APP.post("/api/roms/launch")
def api_launch_rom():
    data = request.get_json(silent=True) or {}
    target = _safe_rom_path(str(data.get("path", "")))
    if target is None or not target.exists():
        return jsonify({"ok": False, "error": "ROM not found"}), 404
    emu_id, meta = _rom_emulator(target)
    if not meta:
        return jsonify({"ok": False, "error": "unsupported ROM type"}), 400
    missing = _runtime_missing(meta)
    if missing:
        return jsonify({"ok": False, "error": f"{meta['engine']} is missing " + ", ".join(missing)}), 409
    core = ""
    if meta.get("core_candidates"):
        core = _find_core(meta["core_candidates"]) or ""
        if not core:
            return jsonify({"ok": False, "error": "RetroArch core not found after install"}), 409
    cmd_text = meta["launch"].format(core=shlex.quote(core), rom=shlex.quote(str(target)))
    proc = subprocess.Popen(cmd_text, shell=True, cwd=str(ROMS_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    _write_json(RUN_STATUS, {"active": True, "pid": proc.pid, "rom": target.name, "emulator": emu_id, "ts": time.time()})
    return jsonify({"ok": True, "pid": proc.pid, "rom": target.name, "emulator": meta["name"], "command": cmd_text})


@APP.post("/api/run/stop")
def api_stop_run():
    status = _read_json(RUN_STATUS, {"active": False})
    pid = status.get("pid")
    if pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
    _write_json(RUN_STATUS, {"active": False})
    return jsonify({"ok": True, "message": "emulator stopped"})


def _run_serve_mode() -> None:
    _state_setup()
    print(f"[game_center] serving on 0.0.0.0:{PORT}", flush=True)
    APP.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def _run_lcd_mode() -> None:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    from _input_helper import get_button

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    message = ""
    try:
        while True:
            pid = _read_pid()
            running = _is_running(pid)
            url = f"http://{_local_ip()}:{PORT}"
            img = Image.new("RGB", (128, 128), (8, 0, 0))
            d = ImageDraw.Draw(img)
            d.rectangle((0, 0, 128, 18), fill=(110, 0, 0))
            d.text((3, 2), "GAME CENTER", font=bold, fill=(255, 240, 240))
            d.text((3, 24), "ONLINE" if running else "OFFLINE", font=bold, fill=(75, 255, 160) if running else (255, 190, 90))
            d.text((3, 42), url[:22], font=font, fill=(120, 240, 255))
            d.text((3, 56), url[22:44], font=font, fill=(120, 240, 255))
            d.text((3, 75), f"PID: {pid if running else '-'}", font=font, fill=(230, 230, 230))
            if message:
                d.text((3, 91), message[:23], font=font, fill=(255, 220, 120))
            d.line((0, 113, 128, 113), fill=(120, 0, 0))
            d.text((2, 116), "OK start  K1 stop  K3 exit", font=font, fill=(255, 210, 90))
            lcd.LCD_ShowImage(img, 0, 0)
            btn = get_button(PINS, GPIO)
            if btn == "KEY3":
                break
            if btn in ("OK", "UP", "RIGHT"):
                message = _start_server().get("message", "")
            if btn in ("KEY1", "DOWN", "LEFT"):
                message = _stop_server().get("message", "")
            time.sleep(0.12)
    finally:
        try:
            lcd.LCD_Clear()
        except Exception:
            pass
        GPIO.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        _run_serve_mode()
        return
    try:
        _run_lcd_mode()
    except Exception as exc:
        print(f"[game_center] LCD mode unavailable ({exc}); serving directly")
        _run_serve_mode()


if __name__ == "__main__":
    main()
