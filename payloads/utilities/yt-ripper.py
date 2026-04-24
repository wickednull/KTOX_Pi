#!/usr/bin/env python3
# NAME: yt-ripper

"""
KTOx Payload – yt-ripper
========================
Mode 1: Web UI dashboard on port 5000
Mode 2: LCD CLI with on-screen keyboard

Mode select:
  UP/DOWN  Choose mode
  OK       Confirm
  KEY3     Exit

Web UI:
  KEY3     Stop server and exit

LCD CLI:
  UP/DOWN    Scroll log
  LEFT/RIGHT Move keyboard selection
  OK         Open/confirm keyboard / select
  KEY2       Cancel keyboard
  KEY3       Exit

Commands in LCD CLI:
  /help
  /jobs
  /mode
  /mode single
  /mode playlist
  /clear
  /exit
  <youtube url>

Audio output:
  /root/Music (or XDG_MUSIC_DIR if configured)

State:
  /root/KTOx/loot/yt-ripper
"""

import os
import re
import json
import time
import threading
import subprocess
from uuid import uuid4
from datetime import datetime

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Directories
# ----------------------------------------------------------------------
def get_music_dir():
    xdg_config = "/root/.config/user-dirs.dirs"
    try:
        if os.path.exists(xdg_config):
            with open(xdg_config, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("XDG_MUSIC_DIR="):
                        value = line.split("=", 1)[1].strip().strip('"')
                        value = value.replace("$HOME", "/root")
                        if value:
                            return value
    except Exception:
        pass
    return "/root/Music"

MUSIC_DIR = get_music_dir()
STATE_DIR = "/root/KTOx/loot/yt-ripper"

os.makedirs(MUSIC_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

LOOT_DIR = MUSIC_DIR
JOBS_FILE = os.path.join(STATE_DIR, "jobs.json")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
LOG_FILE = os.path.join(STATE_DIR, "ripper.log")
PORT = 5000

# ----------------------------------------------------------------------
# Display / hardware constants
# ----------------------------------------------------------------------
WIDTH, HEIGHT = 128, 128
BG = (10, 0, 0)
PANEL = (34, 0, 0)
HEADER = (139, 0, 0)
FG = (171, 178, 185)
ACCENT = (231, 76, 60)
WHITE = (255, 255, 255)
WARN = (212, 172, 13)
DIM = (113, 125, 126)

PINS = {
    "UP": 6,
    "DOWN": 19,
    "LEFT": 5,
    "RIGHT": 26,
    "OK": 13,
    "KEY1": 21,
    "KEY2": 20,
    "KEY3": 16,
}

DEBOUNCE = 0.18

# ----------------------------------------------------------------------
# Hardware init
# ----------------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

def load_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

FONT = load_font(9)
FONT_BOLD = load_font(10)
FONT_SMALL = load_font(8)

_last_press = {k: 0.0 for k in PINS}
_last_state = {k: False for k in PINS}

def wait_btn(timeout=0.12):
    deadline = time.time() + timeout
    while time.time() < deadline:
        now = time.time()
        for name, pin in PINS.items():
            pressed = GPIO.input(pin) == 0
            if pressed and not _last_state[name]:
                _last_state[name] = True
                if now - _last_press[name] >= DEBOUNCE:
                    _last_press[name] = now
                    return name
            elif not pressed and _last_state[name]:
                _last_state[name] = False
        time.sleep(0.01)
    return None

def clear_screen():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return img, ImageDraw.Draw(img)

def show_image(img):
    LCD.LCD_ShowImage(img, 0, 0)

def wrapped_lines(text, width=22):
    out = []
    text = str(text or "")
    while text:
        out.append(text[:width])
        text = text[width:]
    return out or [""]

def show_message(title, lines=None, footer=""):
    img, d = clear_screen()
    d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
    d.text((4, 2), title[:18], font=FONT_BOLD, fill=ACCENT)

    y = 20
    for line in (lines or []):
        for part in wrapped_lines(line, 22):
            if y > HEIGHT - 16:
                break
            d.text((4, y), part, font=FONT, fill=FG)
            y += 11

    if footer:
        d.rectangle((0, HEIGHT - 12, WIDTH, HEIGHT), fill=PANEL)
        d.text((4, HEIGHT - 10), footer[:22], font=FONT_SMALL, fill=ACCENT)

    show_image(img)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass

# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
SETTINGS = {
    "playlist_mode": "single",
}

def load_settings():
    global SETTINGS
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                SETTINGS.update(data)
        except Exception as e:
            log(f"[ERR] load settings: {e}")

def save_settings():
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(SETTINGS, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        log(f"[ERR] save settings: {e}")

def playlist_enabled():
    return SETTINGS.get("playlist_mode", "single") == "playlist"

def set_playlist_mode(mode):
    SETTINGS["playlist_mode"] = "playlist" if mode == "playlist" else "single"
    save_settings()

def toggle_playlist_mode():
    SETTINGS["playlist_mode"] = "single" if playlist_enabled() else "playlist"
    save_settings()

# ----------------------------------------------------------------------
# Dependency checks
# ----------------------------------------------------------------------
def check_dependencies():
    missing = []
    for cmd in ("yt-dlp", "ffmpeg"):
        if subprocess.run(["sh", "-c", f"command -v {cmd} >/dev/null 2>&1"]).returncode != 0:
            missing.append(cmd)
    return missing

# ----------------------------------------------------------------------
# Download manager
# ----------------------------------------------------------------------
class DownloadJob:
    def __init__(self, url, title=None, job_id=None):
        self.job_id = job_id or f"{int(time.time()*1000)}_{uuid4().hex[:6]}"
        self.url = url
        self.title = title or url
        self.status = "queued"
        self.progress = 0.0
        self.message = ""
        self.output_path = None
        self.start_time = None
        self.end_time = None

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "url": self.url,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "output_path": self.output_path,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }

    @classmethod
    def from_dict(cls, data):
        j = cls(data["url"], data.get("title"), data.get("job_id"))
        j.status = data.get("status", "queued")
        j.progress = data.get("progress", 0.0)
        j.message = data.get("message", "")
        j.output_path = data.get("output_path")
        j.start_time = data.get("start_time")
        j.end_time = data.get("end_time")
        return j

class DownloadManager:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = None
        self._load_jobs()
        self._start_worker()

    def _load_jobs(self):
        if not os.path.exists(JOBS_FILE):
            return
        try:
            with open(JOBS_FILE, "r") as f:
                data = json.load(f)
            for jid, item in data.items():
                job = DownloadJob.from_dict(item)
                if job.status == "downloading":
                    job.status = "queued"
                    job.message = "Recovered after restart"
                self.jobs[jid] = job
        except Exception as e:
            log(f"[ERR] loading jobs: {e}")

    def _save_jobs(self):
        with self.lock:
            data = {jid: job.to_dict() for jid, job in self.jobs.items()}
        tmp = JOBS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, JOBS_FILE)

    def add_job(self, url, title=None):
        job = DownloadJob(url, title)
        with self.lock:
            self.jobs[job.job_id] = job
        self._save_jobs()
        log(f"[QUEUE] {job.url} mode={SETTINGS.get('playlist_mode')}")
        return job.job_id

    def snapshot(self):
        with self.lock:
            return {jid: job.to_dict() for jid, job in self.jobs.items()}

    def get_sorted_jobs(self):
        with self.lock:
            vals = list(self.jobs.values())
        vals.sort(key=lambda j: j.start_time or j.job_id, reverse=True)
        return vals

    def _next_job(self):
        with self.lock:
            for job in self.jobs.values():
                if job.status == "queued":
                    return job
        return None

    def _set_job(self, job, **fields):
        with self.lock:
            for k, v in fields.items():
                setattr(job, k, v)
        self._save_jobs()

    def _download(self, job):
        out_template = os.path.join(LOOT_DIR, "%(title).180s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--output", out_template,
            "--newline",
            "--progress",
            "--print", "after_move:FILE=%(filepath)s",
        ]
        if not playlist_enabled():
            cmd.append("--no-playlist")
        cmd.append(job.url)

        try:
            self._set_job(
                job,
                status="downloading",
                start_time=datetime.now().isoformat(),
                progress=0.0,
                message=f"starting ({SETTINGS['playlist_mode']})",
            )

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            pct_re = re.compile(r"(\d+(?:\.\d+)?)%")
            file_re = re.compile(r"FILE=(.+)$")

            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue

                m = pct_re.search(line)
                if m:
                    try:
                        self._set_job(job, progress=float(m.group(1)))
                    except Exception:
                        pass

                fm = file_re.search(line)
                if fm:
                    self._set_job(job, output_path=fm.group(1).strip())

                self._set_job(job, message=line[-120:])

            rc = proc.wait()
            if rc == 0:
                self._set_job(
                    job,
                    status="completed",
                    progress=100.0,
                    end_time=datetime.now().isoformat(),
                    message="completed",
                )
            else:
                self._set_job(
                    job,
                    status="failed",
                    end_time=datetime.now().isoformat(),
                    message=f"yt-dlp exited {rc}",
                )
        except Exception as e:
            self._set_job(
                job,
                status="failed",
                end_time=datetime.now().isoformat(),
                message=str(e)[-120:],
            )

    def _worker(self):
        while not self.stop_event.is_set():
            job = self._next_job()
            if job:
                self._download(job)
            else:
                self.stop_event.wait(0.5)

    def _start_worker(self):
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=2.0)

manager = DownloadManager()

# ----------------------------------------------------------------------
# Mode selection
# ----------------------------------------------------------------------
def mode_selection():
    options = ["Web UI", "LCD CLI"]
    idx = 0

    while True:
        img, d = clear_screen()
        d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
        d.text((4, 2), "SELECT MODE", font=FONT_BOLD, fill=ACCENT)

        y = 24
        for i, opt in enumerate(options):
            if i == idx:
                d.rectangle((2, y - 1, WIDTH - 2, y + 10), fill=(60, 0, 0))
                d.text((6, y), f"> {opt}", font=FONT, fill=WHITE)
            else:
                d.text((6, y), f"  {opt}", font=FONT, fill=FG)
            y += 16

        d.text((4, 62), f"Mode: {SETTINGS['playlist_mode']}", font=FONT_SMALL, fill=WARN)

        d.rectangle((0, HEIGHT - 12, WIDTH, HEIGHT), fill=PANEL)
        d.text((4, HEIGHT - 10), "UP/DN OK K3 exit", font=FONT_SMALL, fill=ACCENT)
        show_image(img)

        btn = wait_btn(0.15)
        if btn == "UP":
            idx = (idx - 1) % len(options)
        elif btn == "DOWN":
            idx = (idx + 1) % len(options)
        elif btn == "OK":
            return idx
        elif btn == "KEY3":
            return None

# ----------------------------------------------------------------------
# Web UI
# ----------------------------------------------------------------------
def run_webui():
    from flask import Flask, render_template_string, request, jsonify
    from werkzeug.serving import make_server
    import socket

    missing = check_dependencies()
    if missing:
        show_message("Missing deps", missing, "Need yt-dlp ffmpeg")
        time.sleep(2)
        return

    app = Flask(__name__)

    HTML = r'''
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>yt-ripper</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>
        /* exact same CSS as original */
        :root{
          --bg:#010101;
          --panel:#0a0000dd;
          --panel2:#120202;
          --line:#7d0000;
          --line2:#470606;
          --text:#dbcfcf;
          --muted:#7f5c5c;
          --red:#ff2b2b;
          --red2:#ff4d4d;
          --glow:0 0 10px rgba(255,43,43,.55), 0 0 22px rgba(231,76,60,.24);
        }
        *{box-sizing:border-box;margin:0;padding:0}
        html,body{height:100%}
        body{
          background:radial-gradient(circle at top, #170000 0%, #060000 48%, #010101 100%);
          color:var(--text);
          font:14px/1.4 "JetBrains Mono","Fira Code","Courier New",monospace;
          overflow-x:hidden;
        }
        #matrix{
          position:fixed; inset:0; width:100%; height:100%;
          z-index:0; opacity:.28; pointer-events:none;
          image-rendering:auto;
          filter:saturate(1.15) contrast(1.05);
        }
        .scanline{
          position:fixed; left:0; right:0; height:3px; top:-10px;
          background:linear-gradient(90deg, transparent, rgba(231,76,60,.75), transparent);
          box-shadow:0 0 12px rgba(231,76,60,.9);
          animation:scan 9s linear infinite;
          z-index:1; pointer-events:none;
        }
        @keyframes scan{from{transform:translateY(-10px)}to{transform:translateY(100vh)}}
        .wrap{position:relative; z-index:2; max-width:1380px; margin:18px auto; padding:18px;}
        .shell{
          border:2px solid var(--line);
          background:linear-gradient(180deg, rgba(16,0,0,.84), rgba(8,0,0,.92));
          border-radius:6px;
          box-shadow:0 0 0 1px rgba(255,0,0,.09) inset, 0 0 36px rgba(139,0,0,.45);
          overflow:hidden;
          backdrop-filter:blur(4px);
        }
        .topbar{
          display:flex; align-items:center; justify-content:space-between;
          padding:10px 14px;
          border-bottom:1px solid var(--line2);
          background:linear-gradient(180deg, rgba(45,0,0,.85), rgba(20,0,0,.9));
        }
        .brand{display:flex; align-items:center; gap:12px}
        .brand h1{
          font-size:22px; letter-spacing:4px; color:var(--red);
          text-shadow:var(--glow);
        }
        .sub{font-size:11px; color:var(--muted)}
        .statusbar{display:flex; gap:10px; flex-wrap:wrap; align-items:center}
        .pill{
          border:1px solid var(--line);
          background:#180404;
          color:#f1b0b0;
          border-radius:999px;
          padding:5px 10px;
          font-size:11px;
        }
        .pill strong{color:#fff}
        .main{
          display:grid;
          grid-template-columns: 1.4fr .9fr;
          gap:18px;
          padding:18px;
        }
        .panel{
          border:1px solid var(--line2);
          border-radius:12px;
          background:rgba(12,0,0,.78);
          box-shadow:0 0 18px rgba(139,0,0,.12) inset;
          overflow:hidden;
        }
        .panel-head{
          display:flex; justify-content:space-between; align-items:center;
          padding:10px 12px;
          border-bottom:1px solid var(--line2);
          background:rgba(34,0,0,.7);
        }
        .panel-head h2{font-size:13px; color:var(--red); letter-spacing:1px}
        .panel-body{padding:12px}
        .skullbox{
          min-height:142px;
          display:grid; place-items:center;
          background:
            radial-gradient(circle at center, rgba(139,0,0,.15), transparent 60%),
            linear-gradient(180deg, rgba(16,0,0,.65), rgba(8,0,0,.9));
          border-bottom:1px solid var(--line2);
        }
        .skull{
          white-space:pre;
          color:var(--red2);
          font-size:12px;
          line-height:1.05;
          text-shadow:0 0 6px rgba(231,76,60,.55);
          opacity:.95;
        }
        .controls{
          display:grid; grid-template-columns: 1fr auto auto; gap:10px;
          margin-bottom:12px;
        }
        .controls input,.controls button,select{
          border:1px solid var(--line);
          background:#160404;
          color:#eee;
          border-radius:10px;
          padding:12px 12px;
          font:inherit;
          outline:none;
        }
        .controls input:focus,select:focus{
          box-shadow:0 0 0 1px var(--red2), 0 0 12px rgba(231,76,60,.2);
        }
        button{cursor:pointer; transition:.16s ease}
        button:hover{background:#280808; box-shadow:0 0 12px rgba(231,76,60,.18)}
        .actions{display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px}
        .btn-primary{background:linear-gradient(180deg, #4a0a0a, #240606); color:#fff}
        .btn-soft{background:#140404; color:#f3b0b0}
        .notes{
          font-size:12px; color:var(--muted);
          line-height:1.5;
          border-top:1px dashed var(--line2);
          padding-top:10px;
        }
        .jobs{max-height:66vh; overflow:auto; padding-right:4px}
        .job{
          border:1px solid var(--line2);
          border-radius:12px;
          padding:10px;
          margin-bottom:10px;
          background:linear-gradient(180deg, rgba(22,0,0,.86), rgba(12,0,0,.95));
        }
        .job-top{
          display:flex; justify-content:space-between; gap:12px; align-items:flex-start;
          margin-bottom:8px;
        }
        .job-title{color:#fff; font-size:12px; word-break:break-word}
        .job-tag{
          font-size:10px; padding:3px 7px; border-radius:999px;
          border:1px solid var(--line); white-space:nowrap;
        }
        .queued{color:#ffd27a}
        .downloading{color:#ff8d8d}
        .completed{color:#8ef0b3}
        .failed{color:#ff7272}
        .bar{
          height:12px; border-radius:999px; overflow:hidden;
          background:#220000; border:1px solid #3c0909;
          margin-bottom:7px;
        }
        .fill{
          height:100%; width:0%;
          background:linear-gradient(90deg, #8b0000, #e74c3c, #ff7676);
          box-shadow:0 0 10px rgba(231,76,60,.45);
          transition:width .25s ease;
        }
        .meta{font-size:11px; color:var(--muted); word-break:break-word}
        .empty{
          color:var(--muted); font-size:13px; text-align:center;
          padding:26px 10px; border:1px dashed var(--line2); border-radius:12px;
        }
        .footer{
          padding:10px 14px; border-top:1px solid var(--line2);
          color:var(--muted); font-size:11px;
          display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px;
        }
        .grid-mini{
          display:grid;
          grid-template-columns:repeat(3, 1fr);
          gap:10px;
          margin-bottom:12px;
        }
        .stat{
          border:1px solid var(--line2);
          border-radius:12px;
          background:#120202;
          padding:10px;
        }
        .stat .k{font-size:10px; color:var(--muted)}
        .stat .v{font-size:18px; color:#fff; margin-top:4px}
        .recent-item{
          border:1px solid var(--line2);
          border-radius:10px;
          background:#120202;
          padding:8px 10px;
          margin-bottom:8px;
          cursor:pointer;
          color:#d7d7d7;
          word-break:break-all;
        }
        .recent-item:hover{
          background:#1d0606;
          box-shadow:0 0 10px rgba(231,76,60,.12);
        }
        .search-results{
          max-height:230px;
          overflow:auto;
          margin-bottom:12px;
          padding-right:2px;
        }
        .search-title{
          color:#fff;
          margin-bottom:3px;
        }
        .search-meta{
          color:var(--muted);
          font-size:11px;
        }
        .inspect-grid{display:grid; grid-template-columns:1fr; gap:8px}
        .inspect-line{font-size:12px; color:#d7d7d7}
        .inspect-line .k{color:#8d6e6e; margin-right:6px}
        .inspect-thumb{
          max-width:100%;
          max-height:180px;
          border:1px solid var(--line2);
          border-radius:10px;
          display:block;
        }
        .error-box{
          color:#ff9d9d;
          border:1px solid #6a1111;
          background:#180404;
          border-radius:10px;
          padding:10px;
          white-space:pre-wrap;
          word-break:break-word;
        }
        @media (max-width: 980px){
          .main{grid-template-columns:1fr}
          .controls{grid-template-columns:1fr}
        }
      </style>
    </head>
    <body>
      <canvas id="matrix"></canvas>
      <div class="scanline"></div>

      <div class="wrap">
        <div class="shell">
          <div class="topbar">
            <div class="brand">
              <div class="skull" id="miniSkull">  .-.
 (o o)
 | O \\
  \\   \\
   `~~~'</div>
              <div>
                <h1>yt-ripper</h1>
                <div class="sub">arasaka net node // queue-driven extraction</div>
              </div>
            </div>
            <div class="statusbar">
              <div class="pill">MODE <strong id="modeLabel">single</strong></div>
              <div class="pill">PORT <strong>5000</strong></div>
              <div class="pill">JOBS <strong id="jobCount">0</strong></div>
            </div>
          </div>

          <div class="main">
            <div class="panel">
              <div class="skullbox">
<pre class="skull" id="heroSkull">
           .ed"""" """$$$$be.
         -"           ^""**$$$e.
       ."                   '$$$c
      /                      "4$$b
     d  3                      $$$$
     $  *                   .$$$$$$
    .$  ^c           $$$$$e$$$$$$$$.
    d$L  4.         4$$$$$$$$$$$$$$b
    $$$$b ^ceeeee.  4$$ECL.F*$$$$$$$
</pre>
              </div>

              <div class="panel-head">
                <h2>QUEUE INPUT</h2>
                <div class="sub">inspect then queue</div>
              </div>

              <div class="panel-body">
                <div class="controls">
                  <input id="urlInput" placeholder="Paste YouTube URL / playlist URL" />
                  <select id="playlistMode">
                    <option value="single">single</option>
                    <option value="playlist">playlist</option>
                  </select>
                  <button class="btn-primary" id="inspectBtn">INSPECT</button>
                </div>

                <div class="controls">
                  <input id="searchInput" placeholder="Search YouTube..." />
                  <button class="btn-soft" id="searchBtn">SEARCH</button>
                  <button class="btn-soft" id="clearSearchBtn">CLEAR</button>
                </div>
                <div class="panel" style="margin-bottom:12px;">
                  <div class="panel-head">
                    <h2>YOUTUBE SEARCH</h2>
                    <div class="sub">tap a result to autofill</div>
                  </div>
                  <div class="panel-body search-results" id="searchResults">
                    <div class="empty">Search by title/artist/keywords.</div>
                  </div>
                </div>

                <div class="actions">
                  <button class="btn-soft" id="queueBtn">QUEUE</button>
                  <button class="btn-soft" id="modeBtn">TOGGLE MODE</button>
                  <button class="btn-soft" id="refreshBtn">REFRESH</button>
                  <button class="btn-soft" id="pasteDemo">DEMO URL</button>
                </div>

                <div class="grid-mini">
                  <div class="stat">
                    <div class="k">queued</div>
                    <div class="v" id="statQueued">0</div>
                  </div>
                  <div class="stat">
                    <div class="k">active</div>
                    <div class="v" id="statActive">0</div>
                  </div>
                  <div class="stat">
                    <div class="k">done</div>
                    <div class="v" id="statDone">0</div>
                  </div>
                </div>

                <div class="panel" style="margin-bottom:12px;">
                  <div class="panel-head">
                    <h2>INSPECTED TARGET</h2>
                    <div class="sub">metadata trace</div>
                  </div>
                  <div class="panel-body" id="inspectCard">
                    <div class="empty">Paste a URL and click INSPECT.</div>
                  </div>
                </div>

                <div class="panel">
                  <div class="panel-head">
                    <h2>RECENT URLS</h2>
                    <div class="sub">tap to seed input</div>
                  </div>
                  <div class="panel-body" id="recentUrls">
                    <div class="empty">No recent URLs yet.</div>
                  </div>
                </div>

                <div class="notes">
                  • Embedded YouTube iframes are not reliable for “rip current” because of browser cross-origin restrictions.<br>
                  • This UI stays on one page and uses Inspect + Queue instead.<br>
                  • Audio saves to the system music directory.<br>
                  • State is kept under /root/KTOx/loot/yt-ripper.
                </div>
              </div>
            </div>

            <div class="panel">
              <div class="panel-head">
                <h2>DOWNLOAD QUEUE</h2>
                <div class="sub">live status</div>
              </div>
              <div class="panel-body jobs" id="jobs"></div>
            </div>
          </div>

          <div class="footer">
            <div>yt-dlp + ffmpeg</div>
            <div id="musicDirLabel">music dir: /root/Music</div>
          </div>
        </div>
      </div>

      <script>
        const skullFrames = [
`           .-.
          (o o)
          | O \\
           \\   \\
            \`~~~'`,
`          .---.
         /     \\
        | () () |
         \\  ^  /
          |||||
          |||||`,
`        .ed"""" """$$$$be.
      -"           ^""**$$$e.
    ."                   '$$$c
   /                      "4$$b
  d  3                      $$$$`,
`           ___
         .'/,-Y"     "~-. 
         l.Y             ^.
         /\\               _\\_
        i            ___/"   "\\
        |          /"   "\\   o !`
        ];

        let lastInspectedUrl = "";

        function esc(s){
          return (s || "").replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
        }

        async function getJSON(url, opts){
          const r = await fetch(url, opts);
          const data = await r.json();
          if(!r.ok) throw new Error(data.error || 'request failed');
          return data;
        }

        async function loadSettings(){
          const s = await getJSON('/api/settings');
          document.getElementById('modeLabel').textContent = s.playlist_mode || 'single';
          document.getElementById('playlistMode').value = s.playlist_mode || 'single';
          if (s.music_dir) {
            document.getElementById('musicDirLabel').textContent = 'music dir: ' + s.music_dir;
          }
        }

        async function setMode(mode){
          await getJSON('/api/settings/mode', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({playlist_mode: mode})
          });
          await loadSettings();
        }

        async function toggleMode(){
          await getJSON('/api/settings/toggle_playlist', {method:'POST'});
          await loadSettings();
        }

        function formatDuration(totalSeconds){
          const total = Number(totalSeconds || 0);
          if(!total) return '--:--';
          const h = Math.floor(total / 3600);
          const m = Math.floor((total % 3600) / 60);
          const s = Math.floor(total % 60);
          return h > 0
            ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
            : `${m}:${String(s).padStart(2,'0')}`;
        }

        async function inspectUrl(){
          const input = document.getElementById('urlInput');
          const url = input.value.trim();
          if(!url) return;

          const card = document.getElementById('inspectCard');
          card.innerHTML = '<div class="empty">Inspecting...</div>';

          try {
            const data = await getJSON('/api/inspect', {
              method:'POST',
              headers:{'Content-Type':'application/json'},
              body: JSON.stringify({url})
            });

            lastInspectedUrl = data.webpage_url || url;

            let duration = 'unknown';
            if(data.duration){
              const total = Number(data.duration);
              const h = Math.floor(total / 3600);
              const m = Math.floor((total % 3600) / 60);
              const s = Math.floor(total % 60);
              duration = h > 0
                ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
                : `${m}:${String(s).padStart(2,'0')}`;
            }

            card.innerHTML = `
              <div class="inspect-grid">
                ${data.thumbnail ? `<img class="inspect-thumb" src="${esc(data.thumbnail)}" alt="thumbnail">` : ``}
                <div class="inspect-line"><span class="k">title</span>${esc(data.title || 'unknown')}</div>
                <div class="inspect-line"><span class="k">uploader</span>${esc(data.uploader || 'unknown')}</div>
                <div class="inspect-line"><span class="k">duration</span>${esc(duration)}</div>
                <div class="inspect-line"><span class="k">type</span>${data.is_playlist ? 'playlist' : 'single video'}</div>
                <div class="inspect-line"><span class="k">entries</span>${data.entry_count || 1}</div>
                <div class="inspect-line"><span class="k">url</span>${esc(data.webpage_url || url)}</div>
              </div>
            `;
          } catch (e) {
            card.innerHTML = `<div class="error-box">${esc(e.message || 'inspect failed')}</div>`;
          }
        }

        async function queueUrl(){
          const input = document.getElementById('urlInput');
          const url = (lastInspectedUrl || input.value).trim();
          if(!url) return;

          await getJSON('/api/download', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({url})
          });

          input.value = '';
          lastInspectedUrl = "";
          document.getElementById('inspectCard').innerHTML =
            '<div class="empty">Paste a URL and click INSPECT.</div>';

          await loadJobs();
          await loadRecent();
        }

        async function searchYouTube(){
          const input = document.getElementById('searchInput');
          const query = input.value.trim();
          if(!query) return;

          const box = document.getElementById('searchResults');
          box.innerHTML = '<div class="empty">Searching...</div>';

          try{
            const results = await getJSON('/api/search', {
              method:'POST',
              headers:{'Content-Type':'application/json'},
              body: JSON.stringify({query})
            });

            if(!results.length){
              box.innerHTML = '<div class="empty">No results found.</div>';
              return;
            }

            box.innerHTML = '';
            results.forEach(v => {
              if(!v.url) return;
              const div = document.createElement('div');
              div.className = 'recent-item';
              div.innerHTML = `
                <div class="search-title">${esc(v.title || 'unknown title')}</div>
                <div class="search-meta">${esc(v.uploader || 'unknown')} | ${esc(formatDuration(v.duration))}</div>
              `;
              div.onclick = async () => {
                const urlInput = document.getElementById('urlInput');
                urlInput.value = v.url;
                lastInspectedUrl = '';
                await inspectUrl();
              };
              box.appendChild(div);
            });
          } catch(_e){
            box.innerHTML = '<div class="empty">Search failed.</div>';
          }
        }

        function clearSearchResults(){
          document.getElementById('searchInput').value = '';
          document.getElementById('searchResults').innerHTML =
            '<div class="empty">Search by title/artist/keywords.</div>';
        }

        async function loadRecent(){
          const recent = await getJSON('/api/recent');
          const box = document.getElementById('recentUrls');

          if(!recent.length){
            box.innerHTML = '<div class="empty">No recent URLs yet.</div>';
            return;
          }

          box.innerHTML = '';
          recent.forEach(url => {
            const div = document.createElement('div');
            div.className = 'recent-item';
            div.textContent = url;
            div.onclick = () => {
              document.getElementById('urlInput').value = url;
            };
            box.appendChild(div);
          });
        }

        async function loadJobs(){
          const jobs = await getJSON('/api/jobs');
          const arr = Object.values(jobs).reverse();
          const jobsEl = document.getElementById('jobs');
          document.getElementById('jobCount').textContent = arr.length;

          let q = 0, a = 0, d = 0;
          jobsEl.innerHTML = '';

          if(!arr.length){
            jobsEl.innerHTML = '<div class="empty">No jobs yet. Paste a URL and queue it.</div>';
          }

          arr.forEach(job => {
            if(job.status === 'queued') q++;
            if(job.status === 'downloading') a++;
            if(job.status === 'completed') d++;

            const tagClass = ['queued','downloading','completed','failed'].includes(job.status) ? job.status : 'queued';

            const div = document.createElement('div');
            div.className = 'job';
            div.innerHTML = `
              <div class="job-top">
                <div class="job-title">${esc(job.title || job.url)}</div>
                <div class="job-tag ${tagClass}">${esc(job.status)}</div>
              </div>
              <div class="bar"><div class="fill" style="width:${Number(job.progress || 0)}%"></div></div>
              <div class="meta">${esc(job.message || '')}</div>
              ${job.output_path ? `<div class="meta">${esc(job.output_path)}</div>` : ''}
              <div class="meta">${esc((job.url || '').slice(0,100))}</div>
            `;
            jobsEl.appendChild(div);
          });

          document.getElementById('statQueued').textContent = q;
          document.getElementById('statActive').textContent = a;
          document.getElementById('statDone').textContent = d;
        }

        document.getElementById('inspectBtn').addEventListener('click', inspectUrl);
        document.getElementById('queueBtn').addEventListener('click', queueUrl);
        document.getElementById('refreshBtn').addEventListener('click', async () => {
          await loadJobs();
          await loadRecent();
          await loadSettings();
        });
        document.getElementById('modeBtn').addEventListener('click', toggleMode);
        document.getElementById('searchBtn').addEventListener('click', searchYouTube);
        document.getElementById('clearSearchBtn').addEventListener('click', clearSearchResults);
        document.getElementById('pasteDemo').addEventListener('click', () => {
          document.getElementById('urlInput').value = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
        });
        document.getElementById('playlistMode').addEventListener('change', e => setMode(e.target.value));
        document.getElementById('urlInput').addEventListener('keydown', e => {
          if(e.key === 'Enter') inspectUrl();
        });
        document.getElementById('searchInput').addEventListener('keydown', e => {
          if(e.key === 'Enter') searchYouTube();
        });

        setInterval(loadJobs, 1800);
        setInterval(loadSettings, 3000);
        setInterval(() => {
          const f = skullFrames[(Math.random() * skullFrames.length) | 0];
          document.getElementById('miniSkull').textContent = f.split('\n').slice(0,6).join('\n');
          if(Math.random() > 0.45){
            document.getElementById('heroSkull').textContent = f;
          }
        }, 2200);

        const canvas = document.getElementById('matrix');
        const ctx = canvas.getContext('2d');

        const glyphSet = 'アァイィウヴエカガキギクグケゲコゴサザシジスズセゼソゾタダチッツテデトドナニヌネノ0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ#$%&*+=-<>[]{}'.split('');
        const skullSet = ['☠','☠','✠','☣','⛧','☢'];
        const runeSet = ['†','‡','₪','Ψ','Ж','≠','¤'];

        let cw = 18;
        let columns = 0;
        let streams = [];
        let W = 0;
        let H = 0;
        let flash = 0;

        function rand(arr){
          return arr[(Math.random() * arr.length) | 0];
        }

        function makeStream(i){
          const skullMode = Math.random() < 0.08;
          return {
            col: i,
            x: i * cw,
            y: -((Math.random() * 40) | 0),
            speed: skullMode ? (0.45 + Math.random() * 0.45) : (0.9 + Math.random() * 1.4),
            length: skullMode ? (8 + ((Math.random() * 10) | 0)) : (10 + ((Math.random() * 18) | 0)),
            skullMode,
            glitch: Math.random() < 0.12,
            chars: Array.from({length: 40}, () => skullMode ? rand(skullSet) : rand(glyphSet)),
            tick: 0,
            swapRate: skullMode ? 5 : 3
          };
        }

        function resize(){
          W = canvas.width = window.innerWidth;
          H = canvas.height = window.innerHeight;
          columns = Math.ceil(W / cw);
          streams = Array.from({length: columns}, (_, i) => makeStream(i));
        }

        function updateStream(s){
          s.tick++;
          s.y += s.speed;

          if(s.tick % s.swapRate === 0){
            for(let i = 0; i < s.chars.length; i++){
              const roll = Math.random();
              if(s.skullMode){
                s.chars[i] = roll < 0.70 ? rand(skullSet) : rand(runeSet);
              } else {
                if(roll < 0.03) s.chars[i] = rand(skullSet);
                else if(roll < 0.08) s.chars[i] = rand(runeSet);
                else s.chars[i] = rand(glyphSet);
              }
            }
          }

          if((s.y - s.length) * cw > H + 100){
            streams[s.col] = makeStream(s.col);
            streams[s.col].y = -((Math.random() * 30) | 0);
          }

          if(Math.random() < 0.0018){
            s.skullMode = !s.skullMode;
            s.speed = s.skullMode ? (0.4 + Math.random() * 0.4) : (0.9 + Math.random() * 1.4);
            s.length = s.skullMode ? (9 + ((Math.random() * 8) | 0)) : (10 + ((Math.random() * 18) | 0));
            s.swapRate = s.skullMode ? 5 : 3;
          }

          if(Math.random() < 0.0025){
            flash = 3;
          }
        }

        function drawStream(s){
          const x = s.x;
          const headIndex = Math.floor(s.y);

          for(let t = 0; t < s.length; t++){
            const row = headIndex - t;
            if(row < 0) continue;

            const y = row * cw;
            if(y > H + cw) continue;

            const ch = s.chars[(t + s.tick) % s.chars.length];
            const isHead = (t === 0);
            const isNearHead = (t < 3);
            const isSkull = skullSet.includes(ch);

            let alpha = 1 - (t / s.length);
            alpha = Math.max(alpha, 0.04);

            if(isHead){
              ctx.fillStyle = `rgba(255,235,235,${0.95})`;
              ctx.shadowColor = 'rgba(255,120,120,0.95)';
              ctx.shadowBlur = s.skullMode ? 18 : 10;
            } else if(isSkull){
              ctx.fillStyle = `rgba(255,90,90,${0.22 + alpha * 0.72})`;
              ctx.shadowColor = 'rgba(255,70,70,0.75)';
              ctx.shadowBlur = isNearHead ? 12 : 7;
            } else if(s.skullMode){
              ctx.fillStyle = `rgba(255,70,70,${0.18 + alpha * 0.55})`;
              ctx.shadowColor = 'rgba(255,50,50,0.35)';
              ctx.shadowBlur = 5;
            } else {
              ctx.fillStyle = `rgba(190,20,20,${0.12 + alpha * 0.55})`;
              ctx.shadowColor = 'rgba(150,20,20,0.2)';
              ctx.shadowBlur = isNearHead ? 4 : 2;
            }

            let dx = 0;
            if(s.glitch && Math.random() < 0.03){
              dx = ((Math.random() * 4) | 0) - 2;
            }

            ctx.fillText(ch, x + dx, y);
          }

          ctx.shadowBlur = 0;
        }

        function draw(){
          ctx.fillStyle = flash > 0 ? 'rgba(20,0,0,0.18)' : 'rgba(0,0,0,0.10)';
          ctx.fillRect(0, 0, W, H);

          ctx.font = '16px monospace';

          for(let i = 0; i < streams.length; i++){
            updateStream(streams[i]);
            drawStream(streams[i]);
          }

          if(flash > 0){
            ctx.fillStyle = `rgba(255,40,40,${0.04 * flash})`;
            ctx.fillRect(0, 0, W, H);
            flash--;
          }

          requestAnimationFrame(draw);
        }

        window.addEventListener('resize', resize);
        resize();
        draw();

        loadSettings();
        loadJobs();
        loadRecent();
      </script>
    </body>
    </html>
    '''

    @app.route("/")
    def index():
        return render_template_string(HTML)

    @app.route("/api/download", methods=["POST"])
    def api_download():
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"error": "missing url"}), 400
        jid = manager.add_job(url)
        return jsonify({"job_id": jid, "playlist_mode": SETTINGS["playlist_mode"]})

    @app.route("/api/jobs")
    def api_jobs():
        return jsonify(manager.snapshot())

    @app.route("/api/settings")
    def api_settings():
        payload = dict(SETTINGS)
        payload["music_dir"] = MUSIC_DIR
        return jsonify(payload)

    @app.route("/api/settings/toggle_playlist", methods=["POST"])
    def api_toggle_playlist():
        toggle_playlist_mode()
        payload = dict(SETTINGS)
        payload["music_dir"] = MUSIC_DIR
        return jsonify(payload)

    @app.route("/api/settings/mode", methods=["POST"])
    def api_set_mode():
        data = request.get_json(silent=True) or {}
        mode = (data.get("playlist_mode") or "").strip().lower()
        set_playlist_mode("playlist" if mode == "playlist" else "single")
        payload = dict(SETTINGS)
        payload["music_dir"] = MUSIC_DIR
        return jsonify(payload)

    @app.route("/api/inspect", methods=["POST"])
    def api_inspect():
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"error": "missing url"}), 400

        # Always allow full playlist inspection – user can choose mode later
        cmd = [
            "yt-dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            url,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if proc.returncode != 0:
                return jsonify({
                    "error": (proc.stderr or proc.stdout or "inspect failed")[-300:]
                }), 400

            info = json.loads(proc.stdout)
            entries = info.get("entries")
            return jsonify({
                "title": info.get("title") or "unknown",
                "webpage_url": info.get("webpage_url") or url,
                "uploader": info.get("uploader") or "",
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail") or "",
                "is_playlist": info.get("_type") == "playlist",
                "entry_count": len(entries) if isinstance(entries, list) else 1,
            })
        except Exception as e:
            return jsonify({"error": str(e)[-300:]}), 400

    @app.route("/api/search", methods=["POST"])
    def api_search():
        data = request.get_json(silent=True) or {}
        query = (data.get("query") or "").strip()
        if not query:
            return jsonify([])

        cmd = [
            "yt-dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--flat-playlist",
            f"ytsearch10:{query}",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if proc.returncode != 0:
                return jsonify([])

            info = json.loads(proc.stdout or "{}")
            entries = info.get("entries", [])
            results = []
            for entry in entries:
                raw_url = (entry.get("webpage_url") or entry.get("url") or "").strip()
                if raw_url and not raw_url.startswith("http"):
                    raw_url = f"https://www.youtube.com/watch?v={raw_url}"
                results.append({
                    "title": entry.get("title") or "unknown title",
                    "url": raw_url,
                    "duration": entry.get("duration"),
                    "uploader": entry.get("uploader") or "",
                })
            return jsonify(results)
        except Exception:
            return jsonify([])

    @app.route("/api/recent")
    def api_recent():
        jobs = list(manager.snapshot().values())
        jobs.reverse()
        seen = []
        urls = []
        for job in jobs:
            u = job.get("url")
            if u and u not in seen:
                seen.append(u)
                urls.append(u)
            if len(urls) >= 8:
                break
        return jsonify(urls)

    class ServerThread(threading.Thread):
        def __init__(self, app):
            super().__init__(daemon=True)
            self.server = make_server("0.0.0.0", PORT, app)
            self.ctx = app.app_context()
            self.ctx.push()

        def run(self):
            self.server.serve_forever()

        def shutdown(self):
            self.server.shutdown()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"

    msg_title = "WebUI Ready"
    msg_lines = [f"http://{ip}:{PORT}", f"music={MUSIC_DIR}"]
    msg_footer = "KEY3 to stop"

    show_message(msg_title, msg_lines, msg_footer)

    server = ServerThread(app)
    server.start()

    try:
        last_refresh = 0
        while True:
            # Periodically refresh the LCD message in case it gets blanked
            if time.time() - last_refresh > 3:
                show_message(msg_title, msg_lines, msg_footer)
                last_refresh = time.time()
            btn = wait_btn(0.2)
            if btn == "KEY3":
                break
    finally:
        server.shutdown()
        time.sleep(0.4)

# ----------------------------------------------------------------------
# LCD virtual keyboard
# ----------------------------------------------------------------------
VKB = [
    ["q","w","e","r","t","y","u","i","o","p"],
    ["a","s","d","f","g","h","j","k","l","BS"],
    ["z","x","c","v","b","n","m",".","/","-"],
    ["http","https","www",".com","SPC"],
    ["CLR","ENT","ESC"],
]

def draw_vkb(buf, row, col):
    img, d = clear_screen()
    d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
    d.text((4, 2), "ENTER URL/CMD", font=FONT_BOLD, fill=ACCENT)

    d.rectangle((2, 16, WIDTH - 2, 31), outline=ACCENT, fill=(25, 0, 0))
    preview = buf[-20:] if buf else "_"
    d.text((4, 20), preview, font=FONT_SMALL, fill=WHITE)

    y = 36
    for r, keys in enumerate(VKB):
        x = 2
        for c, key in enumerate(keys):
            # Adjust width: 10 for single chars, 20 for longer strings
            w = 10 if len(key) <= 2 else 20
            if r == row and c == col:
                d.rectangle((x, y, x + w, y + 12), fill=HEADER)
                d.text((x + 1, y + 2), key[:4], font=FONT_SMALL, fill=WHITE)
            else:
                d.rectangle((x, y, x + w, y + 12), outline=ACCENT, fill=PANEL)
                d.text((x + 1, y + 2), key[:4], font=FONT_SMALL, fill=FG)
            x += w + 2
        y += 15

    d.rectangle((0, HEIGHT - 12, WIDTH, HEIGHT), fill=PANEL)
    d.text((4, HEIGHT - 10), "K2/K3 cancel", font=FONT_SMALL, fill=ACCENT)
    show_image(img)

def vkb_input(initial=""):
    buf = initial
    row, col = 0, 0
    while True:
        col = min(col, len(VKB[row]) - 1)
        draw_vkb(buf, row, col)
        btn = wait_btn(0.15)
        if btn == "UP":
            row = max(0, row - 1)
        elif btn == "DOWN":
            row = min(len(VKB) - 1, row + 1)
        elif btn == "LEFT":
            col = max(0, col - 1)
        elif btn == "RIGHT":
            col = min(len(VKB[row]) - 1, col + 1)
        elif btn == "OK":
            key = VKB[row][col]
            if key == "BS":
                buf = buf[:-1]
            elif key == "SPC":
                buf += " "
            elif key == "CLR":
                buf = ""
            elif key == "ENT":
                return buf
            elif key == "ESC":
                return None
            else:
                buf += key
        elif btn in ("KEY2", "KEY3"):
            return None

# ----------------------------------------------------------------------
# LCD CLI
# ----------------------------------------------------------------------
def handle_cli_command(cmd):
    cmd = (cmd or "").strip()
    if not cmd:
        return ["Empty input"], None

    if cmd == "/help":
        return [
            "/help",
            "/jobs",
            "/mode",
            "/mode single",
            "/mode playlist",
            "/clear",
            "/exit",
        ], None

    if cmd == "/jobs":
        jobs = manager.get_sorted_jobs()[:8]
        if not jobs:
            return ["No jobs queued"], None
        lines = []
        for j in jobs:
            pct = f"{int(j.progress)}%" if j.progress else "--"
            title = (j.title or j.url)[:12]
            lines.append(f"{j.status[:4]} {pct} {title}")
        return lines, None

    if cmd == "/mode":
        return [f"mode={SETTINGS['playlist_mode']}"], None

    if cmd == "/mode single":
        set_playlist_mode("single")
        return ["Mode set: single"], None

    if cmd == "/mode playlist":
        set_playlist_mode("playlist")
        return ["Mode set: playlist"], None

    if cmd == "/clear":
        return ["Screen cleared"], "clear"

    if cmd == "/exit":
        return ["Exiting"], "exit"

    jid = manager.add_job(cmd)
    return [f"Queued {jid[-6:]}", f"music={MUSIC_DIR[-12:]}"], None

def run_cli():
    missing = check_dependencies()
    if missing:
        show_message("Missing deps", missing, "Need yt-dlp ffmpeg")
        time.sleep(2)
        return

    lines = [
        "yt-ripper CLI",
        "OK: enter URL/cmd",
        "/help for commands",
    ]
    scroll = 0

    def redraw():
        img, d = clear_screen()
        d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
        d.text((4, 2), f"YT {SETTINGS['playlist_mode'][:4].upper()}", font=FONT_BOLD, fill=ACCENT)

        start = max(0, len(lines) - 8 - scroll)
        end = len(lines) - scroll if scroll else len(lines)
        visible = lines[start:end][-8:]

        y = 18
        for line in visible:
            d.text((4, y), line[:22], font=FONT, fill=FG)
            y += 11

        jobs = manager.get_sorted_jobs()
        if jobs:
            j = jobs[0]
            d.rectangle((0, HEIGHT - 24, WIDTH, HEIGHT - 12), fill=(25, 0, 0))
            d.text((4, HEIGHT - 22), f"{j.status[:4]} {int(j.progress)}%", font=FONT_SMALL, fill=WARN)

        d.rectangle((0, HEIGHT - 12, WIDTH, HEIGHT), fill=PANEL)
        d.text((4, HEIGHT - 10), "OK input  K3 exit", font=FONT_SMALL, fill=ACCENT)
        show_image(img)

    redraw()

    while True:
        redraw()
        btn = wait_btn(0.15)

        if btn == "KEY3":
            break
        elif btn == "UP":
            scroll = min(scroll + 1, max(0, len(lines) - 1))
        elif btn == "DOWN":
            scroll = max(0, scroll - 1)
        elif btn == "OK":
            typed = vkb_input()
            if typed is None:
                continue
            out, action = handle_cli_command(typed)
            if action == "clear":
                lines = []
            else:
                lines.extend([f"> {typed[:20]}"] + out)
            if action == "exit":
                break
            if len(lines) > 100:
                lines = lines[-100:]
            scroll = 0

# ----------------------------------------------------------------------
# Main / cleanup
# ----------------------------------------------------------------------
def cleanup():
    try:
        manager.stop()
    except Exception:
        pass
    try:
        LCD.LCD_Clear()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass

def main():
    load_settings()

    missing = check_dependencies()
    if missing:
        show_message("Dependencies", missing, "Need yt-dlp ffmpeg")
        time.sleep(2)

    mode = mode_selection()
    if mode is None:
        cleanup()
        return

    if mode == 0:
        run_webui()
    else:
        run_cli()

    cleanup()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
