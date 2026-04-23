#!/usr/bin/env python3
# NAME: YouTube MP3 Ripper

"""
KTOx Payload – YouTube MP3 Ripper
=================================
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

Loot:
  /root/KTOx/loot/YouTube
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
# Paths / constants
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/YouTube"
JOBS_FILE = os.path.join(LOOT_DIR, "jobs.json")
CONFIG_FILE = os.path.join(LOOT_DIR, "config.json")
LOG_FILE = os.path.join(LOOT_DIR, "ripper.log")
PORT = 5000

os.makedirs(LOOT_DIR, exist_ok=True)

WIDTH, HEIGHT = 128, 128
BG = (10, 0, 0)
PANEL = (34, 0, 0)
HEADER = (139, 0, 0)
FG = (171, 178, 185)
ACCENT = (231, 76, 60)
WHITE = (255, 255, 255)
GOOD = (30, 132, 73)
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
# Hardware
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
    line = f"{ts} {msg}"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
SETTINGS = {
    "playlist_mode": "single",   # "single" or "playlist"
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

    def get_jobs_snapshot(self):
        with self.lock:
            return {jid: job.to_dict() for jid, job in self.jobs.items()}

    def get_sorted_jobs(self):
        with self.lock:
            vals = list(self.jobs.values())
        vals.sort(key=lambda j: j.start_time or j.job_id, reverse=True)
        return vals

    def _next_queued_job(self):
        with self.lock:
            for job in self.jobs.values():
                if job.status == "queued":
                    return job
        return None

    def _set_job(self, job, **updates):
        with self.lock:
            for k, v in updates.items():
                setattr(job, k, v)
        self._save_jobs()

    def _download(self, job):
        out_template = os.path.join(LOOT_DIR, "%(title).180s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--newline",
            "--progress",
            "--output", out_template,
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
                message=f"Starting ({SETTINGS.get('playlist_mode')})",
            )

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            percent_re = re.compile(r"(\d+(?:\.\d+)?)%")
            file_re = re.compile(r"FILE=(.+)$")

            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip()
                if not line:
                    continue

                m = percent_re.search(line)
                if m:
                    try:
                        pct = float(m.group(1))
                        self._set_job(job, progress=min(max(pct, 0.0), 100.0))
                    except Exception:
                        pass

                fm = file_re.search(line)
                if fm:
                    self._set_job(job, output_path=fm.group(1).strip())

                if "[download]" in line or "[ExtractAudio]" in line or "Destination" in line:
                    self._set_job(job, message=line[-100:])

            rc = proc.wait()
            if rc == 0:
                self._set_job(
                    job,
                    status="completed",
                    progress=100.0,
                    end_time=datetime.now().isoformat(),
                    message=f"Completed ({SETTINGS.get('playlist_mode')})",
                )
                log(f"[DONE] {job.url}")
            else:
                self._set_job(
                    job,
                    status="failed",
                    end_time=datetime.now().isoformat(),
                    message=f"yt-dlp exited {rc}",
                )
                log(f"[FAIL] {job.url} rc={rc}")

        except Exception as e:
            self._set_job(
                job,
                status="failed",
                end_time=datetime.now().isoformat(),
                message=str(e)[-100:],
            )
            log(f"[ERR] download {job.url}: {e}")

    def _worker_loop(self):
        while not self.stop_event.is_set():
            job = self._next_queued_job()
            if job:
                self._download(job)
            else:
                self.stop_event.wait(0.5)

    def _start_worker(self):
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
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
    missing = check_dependencies()
    if missing:
        show_message("Missing deps", missing, "Install and retry")
        time.sleep(2)
        return

    from flask import Flask, render_template_string, request, jsonify
    from werkzeug.serving import make_server
    import socket

    app = Flask(__name__)

    HTML = """
    <!doctype html>
    <html>
    <head>
      <title>KTOx Audio Ripper</title>
      <style>
        *{box-sizing:border-box}
        body{background:#0a0000;color:#c0c0c0;font-family:monospace;padding:20px}
        .box{max-width:820px;margin:auto;background:#140404;border:2px solid #8b0000;border-radius:10px;padding:20px}
        h1{color:#e74c3c;margin-bottom:16px}
        input,button{
          font-family:monospace;padding:10px;background:#240808;color:#eee;border:1px solid #8b0000
        }
        input{width:72%}
        button{cursor:pointer}
        .job{margin-top:12px;padding:10px;border:1px solid #8b0000;background:#100000}
        .bar{height:16px;background:#220000;border-radius:8px;overflow:hidden;margin:8px 0}
        .fill{height:100%;background:#e74c3c}
        .muted{color:#aaa;font-size:12px}
        .toolbar{margin:10px 0 16px 0}
      </style>
    </head>
    <body>
      <div class="box">
        <h1>KTOx AUDIO RIPPER</h1>
        <form id="f">
          <input id="url" placeholder="YouTube URL / playlist URL" required>
          <button type="submit">QUEUE</button>
        </form>

        <div class="toolbar">
          <button type="button" onclick="toggleMode()">
            Mode: <span id="pmode">...</span>
          </button>
        </div>

        <div id="jobs"></div>
      </div>

      <script>
        function esc(s){
          return (s||"").replace(/[&<>]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[m]));
        }

        async function loadSettings(){
          const r = await fetch('/api/settings');
          const s = await r.json();
          document.getElementById('pmode').textContent = s.playlist_mode || 'single';
        }

        async function toggleMode(){
          await fetch('/api/settings/toggle_playlist', {method:'POST'});
          await loadSettings();
        }

        async function loadJobs(){
          const r = await fetch('/api/jobs');
          const jobs = await r.json();
          const c = document.getElementById('jobs');
          c.innerHTML = '';
          Object.values(jobs).reverse().forEach(job => {
            const div = document.createElement('div');
            div.className = 'job';
            div.innerHTML = `
              <div><b>${esc(job.title || job.url)}</b></div>
              <div class="bar"><div class="fill" style="width:${job.progress||0}%"></div></div>
              <div class="muted">${esc(job.status)} | ${esc(job.message||"")}</div>
              ${job.output_path ? `<div class="muted">${esc(job.output_path)}</div>` : ``}
            `;
            c.appendChild(div);
          });
        }

        document.getElementById('f').addEventListener('submit', async (e)=>{
          e.preventDefault();
          const url = document.getElementById('url').value.trim();
          if(!url) return;
          await fetch('/api/download', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({url})
          });
          document.getElementById('url').value = '';
          loadJobs();
        });

        setInterval(loadJobs, 2000);
        setInterval(loadSettings, 3000);
        loadJobs();
        loadSettings();
      </script>
    </body>
    </html>
    """

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
        return jsonify(manager.get_jobs_snapshot())

    @app.route("/api/settings")
    def api_settings():
        return jsonify(SETTINGS)

    @app.route("/api/settings/toggle_playlist", methods=["POST"])
    def api_toggle_playlist():
        toggle_playlist_mode()
        return jsonify(SETTINGS)

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

    server = ServerThread(app)
    server.start()

    show_message(
        "Web UI running",
        [f"http://{ip}:{PORT}", f"mode={SETTINGS['playlist_mode']}"],
        "KEY3 to stop"
    )

    while True:
        btn = wait_btn(0.2)
        if btn == "KEY3":
            break

    server.shutdown()
    time.sleep(0.5)

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
            w = 11 if len(key) <= 2 else 20
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
            elif key in ("http", "https", "www", ".com"):
                buf += key
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
    return [f"Queued {jid[-6:]}", f"mode={SETTINGS['playlist_mode']}"], None

def run_cli():
    missing = check_dependencies()
    if missing:
        show_message("Missing deps", missing, "Install and retry")
        time.sleep(2)
        return

    lines = [
        "KTOx YouTube CLI",
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
