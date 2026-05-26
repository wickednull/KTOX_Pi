#!/usr/bin/env python3
"""KTOx Payload: Game Center web launcher + LCD status panel.

- LCD mode (default): start/stop server and show URL/status.
- Serve mode (--serve): run Flask API/UI for emulator/ROM management.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, url_for

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

PID_FILE = Path("/tmp/ktox_game_center.pid")
LOG_FILE = Path("/tmp/ktox_game_center.log")
PORT = int(os.environ.get("KTOX_GAME_CENTER_PORT", "8099"))
ROMS_DIR = Path(os.environ.get("KTOX_ROMS_DIR", "/root/KTOx/roms"))

APP = Flask(__name__)
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

EMULATORS = {
    "nes": {"name": "NES", "engine": "FCEUX", "apt": ["fceux"], "ext": [".nes"], "notes": "Stable 8-bit emulator, lightweight."},
    "snes": {"name": "SNES", "engine": "Snes9x", "apt": ["snes9x"], "ext": [".smc", ".sfc"], "notes": "Works on Pi Zero 2 W; use frame skip for heavy ROMs."},
    "gb": {"name": "Game Boy / Color", "engine": "Gambatte (RetroArch)", "apt": ["retroarch", "libretro-gambatte"], "ext": [".gb", ".gbc"], "notes": "Excellent compatibility and low CPU usage."},
    "gba": {"name": "Game Boy Advance", "engine": "mgba", "apt": ["mgba-sdl"], "ext": [".gba"], "notes": "Good compatibility; may need audio tweaks."},
    "genesis": {"name": "Genesis / Mega Drive", "engine": "PicoDrive (RetroArch)", "apt": ["retroarch", "libretro-picodrive"], "ext": [".md", ".gen", ".bin"], "notes": "Great speed on Pi Zero 2 W."},
    "psx": {"name": "PlayStation 1", "engine": "PCSX-ReARMed / Beetle PSX (RetroArch)", "apt": ["retroarch", "libretro-beetle-psx"], "ext": [".cue", ".bin", ".chd", ".pbp", ".iso", ".img"], "notes": "Uses Debian/Kali Beetle package; prefer PCSX-ReARMed when available for low-power devices."},
    "doom": {"name": "DOOM", "engine": "Chocolate Doom", "apt": ["chocolate-doom"], "ext": [".wad"], "notes": "Native local classic DOOM runtime."},
}

TEMPLATE = """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>KTOx Game Center</title>
<style>
:root{--bg:#0b1020;--panel:#111a30;--panel2:#15213d;--text:#e6eeff;--muted:#9db0d8;--accent:#67e8f9;--ok:#34d399;--warn:#fbbf24}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#070b16,#0f1730);font-family:Inter,Arial,sans-serif;color:var(--text)}
.wrap{max-width:1080px;margin:0 auto;padding:20px}.hero{background:var(--panel);border:1px solid #1f335c;border-radius:12px;padding:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:12px}.card{background:var(--panel2);border:1px solid #284170;border-radius:12px;padding:12px}
h1,h2,h3{margin:.2rem 0}.muted{color:var(--muted)} code{background:#081126;border:1px solid #233a67;padding:2px 6px;border-radius:6px}
.badge{display:inline-block;background:#102748;border:1px solid #2d4f84;color:#b9d5ff;padding:3px 7px;border-radius:999px;font-size:.75rem;margin-bottom:7px}
.btn{display:inline-block;border:1px solid #2d4f84;background:#14315e;color:#fff;border-radius:8px;padding:8px 10px;text-decoration:none;cursor:pointer}
.btn:hover{filter:brightness(1.12)}.btn-ok{border-color:#2f7f68;background:#155e4c}.footer{margin-top:14px;font-size:.9rem;color:var(--muted)}
.small{font-size:.9rem}.tag{padding:2px 6px;border:1px solid #39598f;border-radius:99px;font-size:.75rem;margin-right:4px;display:inline-block;margin-bottom:4px}
</style></head><body>
<div class='wrap'>
<div class='hero'>
<h1>KTOx Game Center</h1>
<div class='muted'>Pi Zero 2 W profile • clean UI • ROM upload + emulator install</div>
<div style='margin-top:8px'>Host: <code>{{ host }}</code> • ROM root: <code>{{ rom_root }}</code></div>
<div class='footer'>Tip: install only the emulators you actually plan to use to save SD space.</div>
</div>

<h2 style='margin-top:16px'>Emulators that run on Pi Zero 2 W</h2>
<div class='grid'>
{% for key, e in emulators.items() %}
<div class='card'>
<div class='badge'>{{ key|upper }}</div>
<h3>{{ e.name }}</h3>
<div class='small'><b>Engine:</b> {{ e.engine }}</div>
<div class='small muted' style='margin:6px 0 8px'>{{ e.notes }}</div>
<div class='small'><b>ROM extensions:</b><br>{% for x in e.ext %}<span class='tag'>{{ x }}</span>{% endfor %}</div>
<form style='margin-top:8px' method='post' action='/install/{{key}}'><button class='btn btn-ok'>Install {{ e.engine }}</button></form>
</div>
{% endfor %}
</div>

<h2 style='margin-top:16px'>ROM Manager</h2>
<div class='card'>
<form method='post' enctype='multipart/form-data' action='/rom/upload'>
<input type='file' name='rom_file' required>
<button class='btn'>Upload ROM</button>
</form>
<div class='footer'>After upload, ROMs are auto-sorted by extension into emulator folders.</div>
<p><a class='btn' href='/rom/list'>List ROMs (JSON)</a> <a class='btn' href='/emulators'>Emulator API (JSON)</a></p>
</div>
</div></body></html>"""

def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()

def _ensure_dirs():
    ROMS_DIR.mkdir(parents=True, exist_ok=True)
    for key in EMULATORS:
        (ROMS_DIR / key).mkdir(parents=True, exist_ok=True)

def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def _read_pid():
    try:return int(PID_FILE.read_text().strip())
    except Exception:return None

def _is_running(pid):
    if not pid:return False
    try:os.kill(pid,0);return True
    except Exception:return False

def _start_server():
    pid=_read_pid()
    if _is_running(pid):return {"ok":True,"message":f"already running ({pid})","pid":pid}
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log=open(LOG_FILE,"a")
    proc=subprocess.Popen([sys.executable,__file__,"--serve"],stdout=log,stderr=log,start_new_session=True)
    PID_FILE.write_text(str(proc.pid))
    return {"ok":True,"message":f"started ({proc.pid})","pid":proc.pid}

def _stop_server():
    pid=_read_pid()
    if not _is_running(pid):PID_FILE.unlink(missing_ok=True);return {"ok":True,"message":"already stopped"}
    try:os.kill(pid,15)
    except Exception as e:return {"ok":False,"message":f"stop failed: {e}"}
    time.sleep(0.4);PID_FILE.unlink(missing_ok=True)
    return {"ok":True,"message":f"stopped ({pid})"}

@APP.get("/")
def home():
    return render_template_string(TEMPLATE, host=request.host_url.rstrip("/"), rom_root=str(ROMS_DIR), emulators=EMULATORS)

@APP.get("/emulators")
def list_emulators():
    return jsonify({"ok": True, "count": len(EMULATORS), "emulators": EMULATORS})

@APP.post("/install/<emu>")
def install_emu(emu):
    meta = EMULATORS.get(emu)
    if not meta:return jsonify({"ok": False, "error": "unknown emulator"}), 404
    logs=[];failed=False
    for cmd in (["apt-get","update"],["apt-get","install","-y",*meta["apt"]]) if meta["apt"] else []:
        rc,out=_run(cmd);logs.append({"cmd":" ".join(cmd),"rc":rc,"output":out[-1200:]});failed=failed or rc!=0
    if failed:return jsonify({"ok":False,"emulator":emu,"error":"install failed","logs":logs}),500
    return jsonify({"ok":True,"emulator":emu,"logs":logs})

@APP.post('/rom/upload')
def upload_rom():
    f=request.files.get('rom_file')
    if not f or not f.filename:return jsonify({"ok":False,"error":"missing rom_file"}),400
    name=Path(f.filename).name;ext=Path(name).suffix.lower();target_group='misc'
    for key,meta in EMULATORS.items():
        if ext in meta['ext']:target_group=key;break
    out_dir=ROMS_DIR/target_group;out_dir.mkdir(parents=True,exist_ok=True);f.save(out_dir/name)
    return redirect(url_for('list_roms'))

@APP.get('/rom/list')
def list_roms():
    _ensure_dirs();rows=[]
    for f in sorted(ROMS_DIR.rglob('*')):
        if f.is_file():rows.append({"name":f.name,"path":str(f.relative_to(ROMS_DIR)),"size":f.stat().st_size})
    return jsonify({"ok":True,"rom_root":str(ROMS_DIR),"roms":rows})

@APP.get('/rom/download/<path:p>')
def download_rom(p):
    pth=(ROMS_DIR/p).resolve()
    try:pth.relative_to(ROMS_DIR.resolve())
    except ValueError:return jsonify({"ok":False,"error":"invalid path"}),400
    if not pth.exists():return jsonify({"ok":False,"error":"not found"}),404
    return send_from_directory(pth.parent,pth.name,as_attachment=True)

def _run_serve_mode():
    _ensure_dirs();print(f"[game_center] Starting web UI on 0.0.0.0:{PORT}", flush=True);APP.run(host='0.0.0.0',port=PORT)

# keep lcd mode unchanged for device integration

def _run_lcd_mode():
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    from _input_helper import get_button
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    lcd=LCD_1in44.LCD();lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',9)
    bold=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',11)
    msg=""
    while True:
        pid=_read_pid();running=_is_running(pid);url=f"http://{_local_ip()}:{PORT}"
        img=Image.new('RGB',(128,128),(10,0,0));d=ImageDraw.Draw(img)
        d.rectangle((0,0,128,18),fill=(0,110,32) if running else (90,25,25));d.text((3,2),'Game Center',font=bold,fill='white')
        d.text((3,21),'RUNNING' if running else 'STOPPED',font=bold,fill=(80,255,140) if running else (255,180,80));d.text((3,38),'URL:',font=font,fill='yellow')
        for i, chunk in enumerate([url[j:j+21] for j in range(0, len(url), 21)][:3]):d.text((3,49+i*10),chunk,font=font,fill='cyan')
        d.text((3,82),f'PID: {pid if running else "-"}',font=font,fill='white')
        if msg:d.text((3,95),msg[:22],font=font,fill=(255,220,120))
        d.line((0,113,128,113),fill=(90,90,90));d.text((2,116),'OK=start DOWN=stop K3=back',font=font,fill='yellow');lcd.LCD_ShowImage(img,0,0)
        btn=get_button(PINS,GPIO)
        if btn in ('KEY3','LEFT'):break
        if btn in ('OK','UP','RIGHT'):msg=_start_server().get('message','')
        elif btn in ('DOWN','KEY1'):msg=_stop_server().get('message','')
        time.sleep(0.12)

def main():
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--serve',action='store_true');args=parser.parse_args()
    if args.serve:_run_serve_mode();return
    try:_run_lcd_mode()
    except Exception:
        print('[game_center] LCD unavailable. Starting server directly.');_run_serve_mode()

if __name__ == '__main__':main()
