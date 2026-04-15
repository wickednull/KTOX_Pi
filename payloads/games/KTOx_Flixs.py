#!/usr/bin/env python3
import os, sys, time, threading, subprocess, socket, re, urllib.parse
import requests, qrcode
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, send_from_directory, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

# --- HARDWARE INITIALIZATION ---
HAS_HW = False
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except Exception:
    print("HW_STATUS: LCD Hardware not detected. Running in Headless mode.")

# --- CONFIGURATION ---
VIDEO_DIR = "/root/Videos"
THUMB_DIR = "/root/Videos/thumbnails"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

os.makedirs(THUMB_DIR, exist_ok=True)

app_ui = Flask("Library")      # Port 80
app_uplink = Flask("Uplink")   # Port 8888

# --- CYBERPUNK STYLES ---
CYBER_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    :root { --red: #ff0000; --dark-red: #2b0000; --cyan: #00f3ff; --bg: #050505; }
    body { background: var(--bg); color: #ccc; font-family: 'Share Tech Mono', monospace; margin:0; line-height: 1.4; }
    nav { padding: 15px 5%; background: #000; border-bottom: 2px solid var(--red); display: flex; justify-content: space-between; align-items: center; }
    .logo { color: var(--red); font-size: 22px; letter-spacing: 4px; text-shadow: 2px 0 var(--cyan); }
    .container { padding: 20px 5%; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 15px; }
    .card { background: #000; border: 1px solid var(--dark-red); text-decoration: none; color: inherit; transition: 0.3s; overflow:hidden; position: relative; }
    .card:hover { border-color: var(--cyan); transform: translateY(-3px); box-shadow: 0 0 15px var(--dark-red); }
    .card img { width: 100%; aspect-ratio: 2/3; object-fit: cover; filter: grayscale(1) sepia(1) hue-rotate(-50deg) brightness(0.4); transition: 0.3s; }
    .card:hover img { filter: grayscale(0) brightness(1); }
    .card-meta { padding: 8px; font-size: 10px; border-top: 1px solid var(--dark-red); }
    .btn { background: var(--dark-red); color: white; border: 1px solid var(--red); padding: 12px; cursor: pointer; font-family: inherit; width: 100%; font-weight: bold; }
    input { background: #111; border: 1px solid var(--dark-red); color: var(--cyan); padding: 12px; width: 100%; box-sizing: border-box; margin-bottom: 15px; font-family: inherit; }
    #prog-wrap { display: none; margin-top: 20px; }
    #prog-cont { width: 100%; background: #111; border: 1px solid var(--cyan); height: 15px; }
    #prog-bar { width: 0%; background: var(--cyan); height: 100%; box-shadow: 0 0 10px var(--cyan); transition: width 0.1s; }
</style>
"""

# --- UI TEMPLATES ---
LIBRARY_HTML = CYBER_CSS + """
<nav><div class="logo">KTOx//CYBER_VOID</div><div style="color:var(--cyan);font-size:10px;">NODE_ACTIVE</div></nav>
<div class="container">
    <div class="grid">
        {% for v in videos %}
        <a href="/play/{{ v }}" class="card">
            <img src="/thumb/{{ v | replace('/', '_') }}.jpg">
            <div class="card-meta"><span style="color:var(--cyan)">DATA_STREAM//</span> {{ v | upper }}</div>
        </a>
        {% endfor %}
    </div>
</div>
"""

UPLINK_HTML = CYBER_CSS + """
<nav><div class="logo">KTOx//DATA_INJECTOR</div><div style="color:var(--red);font-size:10px;">PORT_8888</div></nav>
<div class="container" style="max-width: 500px; margin: auto; padding-top: 30px;">
    <h3 style="color:var(--cyan)">> SYSTEM_UPLINK_INITIALIZED</h3>
    <form id="up-form">
        <input type="text" id="subdir" placeholder="TARGET_SUBDIRECTORY (OPTIONAL)">
        <label style="font-size:10px; color:#555;">FILE_UPLINK</label>
        <input type="file" id="f-direct" multiple>
        <label style="font-size:10px; color:#555;">FOLDER_INJECTION</label>
        <input type="file" id="f-folder" multiple webkitdirectory>
        <button type="button" class="btn" onclick="startUplink()">EXECUTE_INJECTION</button>
    </form>
    <div id="prog-wrap">
        <div id="prog-cont"><div id="prog-bar"></div></div>
        <div id="st-text" style="color:var(--cyan); font-size:11px; text-align:center; margin-top:5px;">UPLINKING: 0%</div>
    </div>
</div>
<script>
    function startUplink() {
        const fd = new FormData();
        fd.append('subdir', document.getElementById('subdir').value);
        for (let f of document.getElementById('f-direct').files) { fd.append('files', f); }
        for (let f of document.getElementById('f-folder').files) { fd.append('files', f); }
        
        const xhr = new XMLHttpRequest();
        document.getElementById('prog-wrap').style.display = 'block';
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const p = Math.round((e.loaded / e.total) * 100);
                document.getElementById('prog-bar').style.width = p + '%';
                document.getElementById('st-text').innerText = 'UPLINKING: ' + p + '%';
            }
        });
        xhr.onload = () => { location.reload(); };
        xhr.open('POST', '/upload', true);
        xhr.send(fd);
    }
</script>
"""

# --- CORE LOGIC ---
def get_stats():
    t, rx, tx = 0, 0, 0
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            t = float(f.read().strip()) / 1000.0
        with open("/proc/net/dev", "r") as f:
            for l in f:
                if "wlan0" in l:
                    p = l.split()
                    rx, tx = round(int(p[1])/1e6, 1), round(int(p[9])/1e6, 1)
    except: pass
    return t, rx, tx

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except: return "127.0.0.1"

def generate_thumbnails():
    for r, d, f in os.walk(VIDEO_DIR):
        for file in f:
            if file.lower().endswith(VIDEO_EXTS):
                rel = os.path.relpath(os.path.join(r, file), VIDEO_DIR)
                t_p = os.path.join(THUMB_DIR, rel.replace('/', '_') + ".jpg")
                if not os.path.exists(t_p):
                    subprocess.run(["ffmpeg", "-ss", "5", "-i", os.path.join(VIDEO_DIR, rel), 
                                   "-vf", "scale=240:-1", "-vframes", "1", t_p], stderr=subprocess.DEVNULL)

# --- LCD THREAD (PORT 80 ADDED) ---
def lcd_thread():
    time.sleep(3)
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values(): GPIO.setup(p, GPIO.IN, GPIO.PUD_UP)
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    ip = get_ip()
    show_qr = False

    while True:
        if GPIO.input(PINS["KEY1"]) == 0:
            show_qr = not show_qr
            lcd.LCD_ShowImage(Image.new("RGB", (128,128), "red"), 0, 0)
            time.sleep(0.4) 

        if show_qr:
            qr = qrcode.QRCode(box_size=3, border=2)
            qr.add_data(f"http://{ip}:8888")
            img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((128,128))
            lcd.LCD_ShowImage(img, 0, 0)
        else:
            t, rx, tx = get_stats()
            img = Image.new("RGB", (128,128), "black")
            d = ImageDraw.Draw(img)
            d.rectangle((0,0,128,16), fill="#2b0000")
            d.text((5,2), "KTOx//CYBER_VOID", fill="red")
            
            # Port Display
            d.text((5,22), f"VID_NODE: {ip}:80", fill="#00f3ff")
            d.text((5,37), f"UP_NODE : {ip}:8888", fill="red")
            
            # System Stats
            d.text((5,55), f"CPU_TEMP: {t:.1f}C", fill="red" if t > 70 else "green")
            d.text((5,75), f"DATA_OUT: {tx}MB", fill="#ccc")
            d.text((5,90), f"DATA_IN : {rx}MB", fill="#ccc")
            
            d.text((5,110), "[KEY1] QR_UPLINK", fill="red")
            lcd.LCD_ShowImage(img, 0, 0)
        time.sleep(0.2)

# --- ROUTES PORT 80 ---
@app_ui.route('/')
def index():
    v = []
    for r, d, f in os.walk(VIDEO_DIR):
        for file in f:
            if file.lower().endswith(VIDEO_EXTS):
                v.append(os.path.relpath(os.path.join(r, file), VIDEO_DIR))
    return render_template_string(LIBRARY_HTML, videos=sorted(v))

@app_ui.route('/thumb/<f>')
def thumb(f): return send_from_directory(THUMB_DIR, f)

@app_ui.route('/stream/<path:f>')
def stream(f): return send_from_directory(VIDEO_DIR, f)

@app_ui.route('/play/<path:f>')
def play(f):
    return render_template_string("<body style='background:#000;margin:0;display:flex;align-items:center;justify-content:center;height:100vh;'><video controls autoplay style='max-width:100%;max-height:100%;'><source src='/stream/{{f}}'></video></body>", f=f)

# --- ROUTES PORT 8888 ---
@app_uplink.route('/')
def uplink_pg(): return render_template_string(UPLINK_HTML)

@app_uplink.route('/upload', methods=['POST'])
def handle_up():
    target = os.path.join(VIDEO_DIR, request.form.get('subdir', '').strip())
    os.makedirs(target, exist_ok=True)
    for f in request.files.getlist('files'):
        if f.filename:
            path = os.path.join(target, f.filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
    threading.Thread(target=generate_thumbnails).start()
    return jsonify({"status": "ok"})

# --- EXECUTION ---
if __name__ == "__main__":
    if HAS_HW:
        threading.Thread(target=lcd_thread, daemon=True).start()
    
    threading.Thread(target=generate_thumbnails, daemon=True).start()
    
    threading.Thread(target=lambda: app_uplink.run(host='0.0.0.0', port=8888, debug=False, use_reloader=False), daemon=True).start()
    
    print(f"VID_NODE ACTIVE: http://{get_ip()}:80")
    print(f"UP_NODE ACTIVE : http://{get_ip()}:8888")
    
    app_ui.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)
