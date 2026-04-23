#!/usr/bin/env python3
"""
KTOx Payload – YouTube MP3 Ripper (Multi‑Mode)
===============================================
Mode 1: Web UI – Cyberpunk Flask web dashboard on port 5000.
Mode 2: CLI – Terminal on KTOx LCD (DarkSec‑style shell) with download manager.

Controls in mode selection:
  UP/DOWN – choose mode
  OK      – confirm

Web UI controls:
  KEY3 – stop server and exit

CLI controls:
  Type YouTube URLs directly to download (queued in background)
  Type /jobs to see status, /help for commands, /exit to quit
  KEY3 – exit payload

Loot: /root/KTOx/loot/YouTube/
"""

import sys
import os
import time
import json
import subprocess
import threading
import signal
import select
import fcntl
import pty
import struct
import termios
import re
from datetime import datetime

# ----------------------------------------------------------------------
# Auto‑install dependencies (shared)
# ----------------------------------------------------------------------
def auto_install_deps():
    missing = []
    if subprocess.run("which yt-dlp >/dev/null 2>&1", shell=True).returncode != 0:
        missing.append("yt-dlp")
    if subprocess.run("which ffmpeg >/dev/null 2>&1", shell=True).returncode != 0:
        missing.append("ffmpeg")
    if missing:
        print(f"Installing: {missing}")
        subprocess.run(["apt", "update"], capture_output=True)
        subprocess.run(["apt", "install", "-y"] + missing, capture_output=True)
        subprocess.run(["pip", "install", "yt-dlp"], capture_output=True)

# ----------------------------------------------------------------------
# Download Manager Core
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/YouTube"
os.makedirs(LOOT_DIR, exist_ok=True)
JOBS_FILE = os.path.join(LOOT_DIR, "jobs.json")

class DownloadJob:
    def __init__(self, url, title=None, job_id=None):
        self.url = url
        self.title = title or url
        self.job_id = job_id or str(int(time.time()))
        self.status = "queued"
        self.progress = 0
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

class DownloadManager:
    def __init__(self):
        self.jobs = {}
        self.current_job = None
        self._load_jobs()
        self._start_worker()

    def _load_jobs(self):
        if os.path.exists(JOBS_FILE):
            try:
                with open(JOBS_FILE, "r") as f:
                    data = json.load(f)
                for jid, j in data.items():
                    job = DownloadJob(j["url"], j["title"], jid)
                    job.status = j["status"]
                    job.progress = j["progress"]
                    job.message = j["message"]
                    job.output_path = j["output_path"]
                    self.jobs[jid] = job
            except:
                pass

    def _save_jobs(self):
        with open(JOBS_FILE, "w") as f:
            json.dump({jid: job.to_dict() for jid, job in self.jobs.items()}, f, indent=2)

    def add_job(self, url, title=None):
        job = DownloadJob(url, title)
        self.jobs[job.job_id] = job
        self._save_jobs()
        return job.job_id

    def _worker(self):
        while True:
            job = None
            for j in self.jobs.values():
                if j.status == "queued":
                    job = j
                    break
            if job:
                self.current_job = job
                job.status = "downloading"
                job.start_time = datetime.now().isoformat()
                self._save_jobs()
                self._download(job)
                job.end_time = datetime.now().isoformat()
                self._save_jobs()
                self.current_job = None
                self._save_jobs()
            time.sleep(2)

    def _download(self, job):
        try:
            out_template = os.path.join(LOOT_DIR, "%(title)s.%(ext)s")
            cmd = [
                "yt-dlp",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--output", out_template,
                "--progress",
                "--newline",
                job.url
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in iter(proc.stdout.readline, ""):
                if "[download]" in line and "%" in line:
                    try:
                        percent = float(line.split("%")[0].split()[-1])
                        job.progress = percent
                        self._save_jobs()
                    except:
                        pass
                job.message = line.strip()[-80:]
                self._save_jobs()
            proc.wait()
            if proc.returncode == 0:
                job.status = "completed"
                job.progress = 100
                for f in os.listdir(LOOT_DIR):
                    if f.endswith(".mp3") and job.title in f:
                        job.output_path = os.path.join(LOOT_DIR, f)
                        break
            else:
                job.status = "failed"
                job.message = "Download failed"
        except Exception as e:
            job.status = "failed"
            job.message = str(e)
        finally:
            self._save_jobs()

    def _start_worker(self):
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()

manager = DownloadManager()

# ----------------------------------------------------------------------
# KTOx hardware init (for mode selection and CLI)
# ----------------------------------------------------------------------
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
FONT = font(9)
FONT_BOLD = font(10)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def show_message(msg, sub=""):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((64, 50), msg, font=FONT_BOLD, fill=(30, 132, 73), anchor="mm")
    if sub:
        d.text((64, 65), sub[:22], font=FONT, fill=(113, 125, 126), anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1.5)

# ----------------------------------------------------------------------
# Mode selection menu
# ----------------------------------------------------------------------
def mode_selection():
    options = ["Web UI (Cyberpunk)", "CLI (LCD Terminal)"]
    idx = 0
    while True:
        img = Image.new("RGB", (W, H), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
        d.text((4, 2), "SELECT MODE", font=FONT_BOLD, fill=(231, 76, 60))
        y = 20
        for i, opt in enumerate(options):
            if i == idx:
                d.rectangle((0, y-1, W, y+9), fill=(60, 0, 0))
                d.text((4, y), f"> {opt}", font=FONT, fill=(255, 255, 255))
            else:
                d.text((4, y), f"  {opt}", font=FONT, fill=(171, 178, 185))
            y += 14
        d.rectangle((0, H-12, W, H), fill=(34, 0, 0))
        d.text((4, H-10), "UP/DOWN OK  K3=Exit", font=FONT, fill=(192, 57, 43))
        LCD.LCD_ShowImage(img, 0, 0)
        btn = wait_btn(0.2)
        if btn == "UP":
            idx = (idx - 1) % len(options)
        elif btn == "DOWN":
            idx = (idx + 1) % len(options)
        elif btn == "OK":
            return idx
        elif btn == "KEY3":
            return None

# ----------------------------------------------------------------------
# MODE 1: Web UI (Flask)
# ----------------------------------------------------------------------
def run_webui():
    from flask import Flask, render_template_string, request, jsonify
    app = Flask(__name__)

    HTML = """
    <!DOCTYPE html>
    <html>
    <head><title>KTOx Audio Ripper</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0000;color:#c0c0c0;font-family:'Courier New',monospace;padding:20px}
        .container{max-width:800px;margin:0 auto;background:#1a0505;border:2px solid #8b0000;border-radius:8px;padding:20px}
        h1{color:#e74c3c;text-shadow:0 0 5px #e74c3c;border-bottom:1px solid #8b0000;margin-bottom:20px}
        input,button{background:#2a0a0a;border:1px solid #8b0000;color:#e0e0e0;padding:8px;font-family:monospace}
        input{width:70%}
        button{cursor:pointer;transition:0.2s}
        button:hover{background:#8b0000;color:#fff;box-shadow:0 0 8px #e74c3c}
        .job{border:1px solid #8b0000;margin:10px 0;padding:10px;border-radius:4px;background:#120000}
        .title{font-weight:bold;color:#e74c3c}
        .progress-bar{background:#2a0a0a;height:20px;border-radius:10px;overflow:hidden;margin:8px 0}
        .progress-fill{background:#e74c3c;height:100%;width:0%}
        .status{font-size:12px;color:#aaa}
    </style>
    </head>
    <body>
    <div class="container">
        <h1>▐ KTOx AUDIO RIPPER ▐</h1>
        <form id="downloadForm">
            <input type="text" id="url" placeholder="YouTube URL, playlist or channel" required>
            <button type="submit">▶ RIP</button>
        </form>
        <div id="jobs"></div>
        <footer>dark red & black // yt-dlp + ffmpeg</footer>
    </div>
    <script>
        function loadJobs(){
            fetch('/api/jobs').then(r=>r.json()).then(jobs=>{
                const container=document.getElementById('jobs');
                container.innerHTML='';
                for(const[id,job] of Object.entries(jobs).reverse()){
                    const div=document.createElement('div');div.className='job';
                    div.innerHTML=`
                        <div class="title">${escapeHtml(job.title||job.url)}</div>
                        <div class="progress-bar"><div class="progress-fill" style="width:${job.progress}%"></div></div>
                        <div class="status">${job.status} - ${job.message.substring(0,80)}</div>
                        ${job.output_path?`<div class="status">📁 ${job.output_path}</div>`:''}
                    `;
                    container.appendChild(div);
                }
            });
        }
        function escapeHtml(s){return s.replace(/[&<>]/g,function(m){if(m==='&')return'&amp;';if(m==='<')return'&lt;';if(m==='>')return'&gt;';return m;});}
        document.getElementById('downloadForm').addEventListener('submit',function(e){
            e.preventDefault();
            const url=document.getElementById('url').value;
            fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})})
                .then(()=>{document.getElementById('url').value='';loadJobs();});
        });
        setInterval(loadJobs,2000);
        loadJobs();
    </script>
    </body>
    </html>
    """

    @app.route('/')
    def index():
        return render_template_string(HTML)

    @app.route('/api/download', methods=['POST'])
    def api_download():
        url = request.json.get('url')
        if not url:
            return jsonify({"error": "no url"}), 400
        job_id = manager.add_job(url)
        return jsonify({"job_id": job_id})

    @app.route('/api/jobs')
    def api_jobs():
        return jsonify({jid: job.to_dict() for jid, job in manager.jobs.items()})

    def start_server():
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

    # Show IP on LCD
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        ip = "127.0.0.1"
    show_message(f"WebUI at {ip}:5000", "Press KEY3 to stop")

    threading.Thread(target=start_server, daemon=True).start()
    while True:
        if GPIO.input(PINS["KEY3"]) == 0:
            break
        time.sleep(0.2)

# ----------------------------------------------------------------------
# MODE 2: CLI Terminal (DarkSec style with job commands)
# ----------------------------------------------------------------------
def run_cli():
    # PTY setup
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execv("/bin/bash", ["bash", "--login"])
    fcntl.fcntl(master_fd, fcntl.F_SETFL,
                fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

    def set_size():
        try:
            winsize = struct.pack("HHHH", 10, 30, W, H)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
        except:
            pass
    set_size()

    ansi_escape = re.compile(r'\x1b(?:\[[0-9;?]*[A-Za-z@`~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[PX^_][^\x1b]*\x1b\\|[@-Z\\-_])')
    scrollback = []
    current_line = ""
    running = True

    def redraw():
        img = Image.new("RGB", (W, H), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 12), fill=(139, 0, 0))
        d.text((4, 2), "YT RIPPER | /help", font=FONT_BOLD, fill=(231, 76, 60))
        visible = scrollback[-6:] + [current_line]
        y = 16
        for line in visible[-6:]:
            d.text((4, y), line[:22], font=FONT, fill=(171, 178, 185))
            y += 11
        d.rectangle((0, H-12, W, H), fill=(34, 0, 0))
        d.text((4, H-10), "K3=exit  /jobs", font=FONT, fill=(192, 57, 43))
        LCD.LCD_ShowImage(img, 0, 0)

    def write_pty(s):
        try:
            os.write(master_fd, s.encode())
        except:
            pass

    def process_output():
        nonlocal current_line
        try:
            data = os.read(master_fd, 4096).decode(errors="replace")
        except:
            return
        if not data:
            return
        clean = ansi_escape.sub("", data)
        for ch in clean:
            if ch == "\n":
                scrollback.append(current_line)
                current_line = ""
            elif ch == "\r":
                current_line = ""
            elif ch in ("\x08", "\x7f"):
                current_line = current_line[:-1]
            elif ord(ch) < 32:
                pass
            else:
                current_line += ch
        if len(scrollback) > 100:
            scrollback = scrollback[-100:]
        redraw()

    # Custom command handler
    def handle_command(cmd):
        cmd = cmd.strip()
        if cmd.startswith("/"):
            parts = cmd[1:].split()
            if not parts:
                return
            if parts[0] == "jobs":
                status = "\n".join([f"{j.status}: {j.title[:30]} {j.progress:.0f}%" if j.progress else f"{j.status}: {j.title[:30]}" for j in manager.jobs.values()])
                write_pty(f"\r\n\x1b[33mJobs:\x1b[0m\r\n{status}\r\n")
            elif parts[0] == "help":
                write_pty("\r\nCommands:\r\n  /jobs - show download status\r\n  /exit - exit payload\r\n  Type any YouTube URL to download\r\n")
            elif parts[0] == "exit":
                return False
            else:
                write_pty(f"\r\nUnknown command: {parts[0]}\r\n")
        else:
            # Assume it's a URL. Add to manager.
            manager.add_job(cmd)
            write_pty(f"\r\nAdded to queue: {cmd[:60]}\r\n")
        return True

    # Initial shell prompt
    write_pty("\r\nKTOx YouTube Ripper CLI\r\nType /help for commands.\r\n$ ")
    redraw()

    poller = select.poll()
    poller.register(master_fd, select.POLLIN)

    while running:
        # Check GPIO
        btn = wait_btn(0.05)
        if btn == "KEY3":
            running = False
            break

        # Process PTY output
        events = poller.poll(0)
        for fd, _ in events:
            if fd == master_fd:
                process_output()

        # Read from PTY (user input) and handle custom commands
        try:
            buf = os.read(master_fd, 1024).decode(errors="replace")
            if buf:
                # Look for newline (user pressed enter)
                if "\n" in buf or "\r" in buf:
                    line = current_line
                    if line.startswith("/") or ("http" in line and "." in line):
                        ok = handle_command(line)
                        if not ok:
                            running = False
                            break
                        write_pty("$ ")
                    else:
                        # Pass through to shell normally
                        pass
        except:
            pass

        time.sleep(0.05)

    # Cleanup
    try:
        os.write(master_fd, "exit\n".encode())
    except:
        pass
    LCD.LCD_Clear()
    GPIO.cleanup()

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    auto_install_deps()
    mode = mode_selection()
    if mode is None:
        LCD.LCD_Clear()
        GPIO.cleanup()
        return
    if mode == 0:
        run_webui()
    else:
        run_cli()
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
