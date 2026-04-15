#!/usr/bin/env python3
"""
KTOx Payload – CYBER_VOID
===================================
Master Media Server & Data Injector
Port 80: Movie Library | Port 8888: Data Uplink

Controls:
  KEY1   Toggle QR Uplink Code
  KEY3   Reset / Exit
"""

import os, sys, time, socket, logging, threading, subprocess
import qrcode
from flask import Flask, render_template_string, request, send_from_directory, abort, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

# Ensure KTOx pathing
KTOX_ROOT = "/root/KTOx"
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ── Configuration ─────────────────────────────────────────────────────────────
VIDEO_DIR  = "/root/Videos"
THUMB_DIR  = "/root/Videos/thumbnails"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}

os.makedirs(THUMB_DIR, exist_ok=True)

app_ui = Flask("Library")
app_up = Flask("Uplink")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ── Templates ─────────────────────────────────────────────────────────────────
CYBER_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    :root { --red: #ff0000; --cyan: #00f3ff; --bg: #050505; }
    body { background: var(--bg); color: #ccc; font-family: 'Share Tech Mono', monospace; margin:0; }
    nav { padding: 15px; background: #000; border-bottom: 2px solid var(--red); display: flex; justify-content: space-between; }
    .container { padding: 20px; max-width: 600px; margin: auto; }
    .input-group { margin-bottom: 20px; border-left: 2px solid #222; padding-left: 15px; }
    label { font-size: 10px; color: #666; display: block; margin-bottom: 5px; text-transform: uppercase; }
    input[type="text"], input[type="file"] { 
        background: #111; border: 1px solid #333; color: var(--cyan); 
        padding: 10px; width: 100%; box-sizing: border-box; font-family: inherit;
    }
    .btn { 
        background: #2b0000; color: white; border: 1px solid var(--red); 
        padding: 15px; width: 100%; cursor: pointer; font-weight: bold; font-family: inherit;
    }
    #prog-wrap { display: none; margin-top: 20px; border: 1px solid var(--cyan); height: 24px; position: relative; }
    #prog-bar { width: 0%; background: var(--cyan); height: 100%; transition: width 0.1s; }
    #prog-text { position: absolute; width: 100%; text-align: center; font-size: 11px; color: white; top: 4px; mix-blend-mode: difference; font-weight: bold; }
</style>
"""

# ── Routes ────────────────────────────────────────────────────────────────────
@app_up.route('/')
def uplink_home():
    return render_template_string(CYBER_CSS + """
    <nav><div style="color:cyan">KTOx//DATA_UPLINK</div><div style="font-size:10px;">PORT_8888</div></nav>
    <div class="container">
        <div class="input-group">
            <label>1. Target Directory</label>
            <input type="text" id="sd" placeholder="Optional (e.g. Action / Season 1)">
        </div>
        
        <div class="input-group">
            <label>2. Select Data Type</label>
            <div style="display:flex; gap:10px;">
                <div style="flex:1">
                    <label style="font-size:8px">Single/Multiple Files</label>
                    <input type="file" id="fi_files" multiple>
                </div>
                <div style="flex:1">
                    <label style="font-size:8px">Entire Folder</label>
                    <input type="file" id="fi_folder" multiple webkitdirectory>
                </div>
            </div>
        </div>
        
        <button onclick="up()" class="btn">EXECUTE INJECTION</button>
        
        <div id="prog-wrap">
            <div id="prog-bar"></div>
            <div id="prog-text">INITIALIZING...</div>
        </div>
    </div>
    <script>
    function up(){
        const fileInput = document.getElementById('fi_files');
        const folderInput = document.getElementById('fi_folder');
        
        if(fileInput.files.length === 0 && folderInput.files.length === 0) {
            return alert("No data selected for injection.");
        }
        
        const fd = new FormData();
        fd.append('subdir', document.getElementById('sd').value);
        
        // Append both potential sources
        for(let f of fileInput.files){ fd.append('files', f); }
        for(let f of folderInput.files){ fd.append('files', f); }
        
        const xhr = new XMLHttpRequest();
        document.getElementById('prog-wrap').style.display='block';
        
        xhr.upload.onprogress = (e) => {
            const p = Math.round((e.loaded / e.total) * 100);
            document.getElementById('prog-bar').style.width = p + '%';
            document.getElementById('prog-text').innerText = 'UPLINKING: ' + p + '%';
        };
        
        xhr.onload = () => { 
            document.getElementById('prog-text').innerText = 'INJECTION SUCCESSFUL';
            setTimeout(()=>location.reload(), 1500); 
        };
        xhr.open('POST', '/upload'); 
        xhr.send(fd);
    }
    </script>""")

@app_up.route('/upload', methods=['POST'])
def upload():
    target = os.path.join(VIDEO_DIR, request.form.get('subdir', '').strip())
    os.makedirs(target, exist_ok=True)
    files = request.files.getlist('files')
    for f in files:
        if f.filename:
            # Reconstruct path if it's a folder upload, else just the filename
            path = os.path.join(target, f.filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
    return jsonify({"status": "ok"})

# ── Library & Core Logic (Standard KTOx Style) ───────────────────────────────
@app_ui.route('/')
def index():
    vids = [os.path.relpath(os.path.join(r, f), VIDEO_DIR) for r, d, fs in os.walk(VIDEO_DIR) for f in fs if f.lower().endswith(VIDEO_EXTS)]
    return render_template_string(CYBER_CSS + """
    <nav><div style="color:red">KTOx//CYBER_VOID</div><div style="font-size:10px;">PORT_80</div></nav>
    <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 15px; padding: 20px;">
        {% for v in videos %}
        <a href="/play/{{ v }}" style="background:#000; border:1px solid #2b0000; text-decoration:none; color:inherit;">
            <img src="/thumb/{{ v | replace('/', '_') }}.jpg" style="width:100%; aspect-ratio:2/3; object-fit:cover; filter:brightness(0.4);">
            <div style="padding:5px; font-size:10px; color:#888;">{{ v | upper }}</div>
        </a>
        {% endfor %}
    </div>""", videos=sorted(vids))

# [Standard Thumbnail, Stream, and Play routes omitted for brevity but required for full function]
@app_ui.route('/thumb/<f>')
def thumb(f): return send_from_directory(THUMB_DIR, f)
@app_ui.route('/stream/<path:f>')
def stream(f): return send_from_directory(VIDEO_DIR, f)
@app_ui.route('/play/<path:f>')
def play(f): return render_template_string("<body style='background:#000;margin:0;'><video controls autoplay style='width:100%;height:100vh;'><source src='/stream/{{f}}'></video></body>", f=f)

def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"

def main():
    if not HAS_HW:
        threading.Thread(target=lambda: app_ui.run(host="0.0.0.0", port=80), daemon=True).start()
        app_up.run(host="0.0.0.0", port=8888)
        return

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    lcd = LCD_1in44.LCD(); lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT); lcd.LCD_Clear()
    
    ip = _get_ip(); show_qr = False; held = {}
    threading.Thread(target=lambda: app_ui.run(host="0.0.0.0", port=80), daemon=True).start()
    threading.Thread(target=lambda: app_up.run(host="0.0.0.0", port=8888), daemon=True).start()

    try:
        while True:
            now = time.time()
            img = Image.new("RGB", (128,128), "black"); draw = ImageDraw.Draw(img)
            if show_qr:
                qr = qrcode.QRCode(box_size=3, border=2)
                qr.add_data(f"http://{ip}:8888")
                img.paste(qr.make_image().convert("RGB").resize((128,128)), (0,0))
            else:
                draw.rectangle([(0,0),(128,18)], fill=(120,0,0))
                draw.text((4,3), "CYBER_VOID", fill="black")
                draw.text((4,30), f"IP: {ip}", fill="white")
                draw.text((4,50), "PORT 80: LIB", fill="cyan")
                draw.text((4,65), "PORT 8888: UP", fill="red")
                draw.text((4,113), "K1:QR  K3:EXIT", fill=(150,150,150))
            lcd.LCD_ShowImage(img, 0, 0)

            # Input logic
            pressed = {name: GPIO.input(pin)==0 for name,pin in PINS.items()}
            for name, is_down in pressed.items():
                if is_down:
                    if name not in held: held[name] = now
                else: held.pop(name, None)
            if pressed.get("KEY3") and (now - held.get("KEY3", now)) <= 0.05: break
            if pressed.get("KEY1") and (now - held.get("KEY1", now)) <= 0.05:
                show_qr = not show_qr
                time.sleep(0.3)
            time.sleep(0.1)
    finally:
        lcd.LCD_Clear(); GPIO.cleanup()

if __name__ == "__main__":
    main()
