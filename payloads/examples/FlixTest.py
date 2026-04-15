#!/usr/bin/env python3
import os, sys, time, threading, subprocess, socket, re, urllib.parse
import requests
import qrcode
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, send_from_directory, request, redirect, url_for
from werkzeug.utils import secure_filename

# --- HARDWARE INIT ---
HAS_HW = False
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except Exception as e:
    print(f"HW_IO_ERROR: {e}")

# --- CONFIG ---
VIDEO_DIR = "/root/Videos"
THUMB_DIR = "/root/Videos/thumbnails"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

os.makedirs(THUMB_DIR, exist_ok=True)
app = Flask(__name__)

# --- WEB UI (CYBER-VOID + UPLOAD) ---
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx//CYBER_VOID</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
        :root { --red: #ff0000; --dark-red: #2b0000; --cyan: #00f3ff; --bg: #050505; }
        body { background: var(--bg); color: #ccc; font-family: 'Share Tech Mono', monospace; margin:0; padding-bottom:50px; }
        nav { padding: 15px 5%; background: #000; border-bottom: 2px solid var(--red); display: flex; justify-content: space-between; align-items: center; }
        .logo { color: var(--red); font-size: 22px; letter-spacing: 4px; text-shadow: 2px 0 var(--cyan); }
        .admin-panel { background: #0a0000; border: 1px dashed var(--red); margin: 20px 5%; padding: 20px; }
        .admin-panel h3 { color: var(--cyan); margin: 0 0 15px 0; font-size: 14px; }
        input { background: #111; border: 1px solid var(--dark-red); color: var(--cyan); padding: 8px; margin: 5px 0; width: 100%; box-sizing: border-box; }
        button { background: var(--dark-red); color: white; border: 1px solid var(--red); padding: 10px 20px; cursor: pointer; width: 100%; margin-top: 10px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 15px; padding: 20px 5%; }
        .card { background: #000; border: 1px solid var(--dark-red); text-decoration: none; color: inherit; overflow: hidden; }
        .card img { width: 100%; aspect-ratio: 2/3; object-fit: cover; filter: grayscale(1) sepia(1) hue-rotate(-50deg); transition: 0.3s; }
        .card:hover img { filter: grayscale(0); transform: scale(1.05); }
        .card-meta { padding: 8px; font-size: 10px; }
    </style>
</head>
<body>
    <nav><div class="logo">KTOx//CYBER_VOID</div><div style="color:var(--cyan);font-size:10px;">UPLINK_STABLE</div></nav>
    <div class="admin-panel">
        <h3>>> DATA_INJECTION_PORTAL</h3>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="text" name="subdir" placeholder="TARGET_SUBDIRECTORY (OPTIONAL)">
            <input type="file" name="files" multiple webkitdirectory mozdirectory>
            <button type="submit">EXECUTE UPLINK</button>
        </form>
    </div>
    <div class="grid">
        {% for v in videos %}
        <a href="/play/{{ v }}" class="card">
            <img src="/thumb/{{ v | replace('/', '_') }}.jpg">
            <div class="card-meta"><span style="color:var(--cyan)">{{ v | upper }}</span></div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

# --- LOGIC FUNCTIONS ---
def get_stats():
    t, rx, tx = 0, 0, 0
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            t = float(f.read().strip()) / 1000.0
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if "wlan0" in line:
                    parts = line.split()
                    rx, tx = round(int(parts[1])/1e6, 1), round(int(parts[9])/1e6, 1)
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
    vids = []
    for r, d, f in os.walk(VIDEO_DIR):
        for file in f:
            if file.lower().endswith(VIDEO_EXTS):
                vids.append(os.path.relpath(os.path.join(r, file), VIDEO_DIR))
    
    for v in vids:
        t_path = os.path.join(THUMB_DIR, v.replace('/', '_') + ".jpg")
        if not os.path.exists(t_path):
            full_p = os.path.join(VIDEO_DIR, v)
            subprocess.run(["ffmpeg", "-ss", "5", "-i", full_p, "-vf", "scale=200:-1", "-vframes", "1", t_path], stderr=subprocess.DEVNULL)

# --- THREADED LCD MONITOR ---
def lcd_thread():
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values(): GPIO.setup(p, GPIO.IN, GPIO.PUD_UP)
    
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    ip = get_ip()
    show_qr = False

    while True:
        if GPIO.input(PINS["KEY1"]) == 0:
            show_qr = not show_qr
            time.sleep(0.5)

        if show_qr:
            qr = qrcode.QRCode(box_size=3, border=2)
            qr.add_data(f"http://{ip}")
            img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((128,128))
            lcd.LCD_ShowImage(img, 0, 0)
        else:
            t, rx, tx = get_stats()
            img = Image.new("RGB", (128,128), "black")
            d = ImageDraw.Draw(img)
            d.rectangle((0,0,128,18), fill="#2b0000")
            d.text((5,3), "KTOx//CYBER_VOID", fill="red")
            d.text((5,30), f"IP: {ip}", fill="#00f3ff")
            d.text((5,50), f"CPU: {t:.1f}C", fill="red" if t > 65 else "green")
            d.text((5,70), f"UP: {tx}MB", fill="#ccc")
            d.text((5,85), f"DN: {rx}MB", fill="#ccc")
            d.text((5,110), "[KEY1] QR CODE", fill="#555")
            lcd.LCD_ShowImage(img, 0, 0)
        time.sleep(1)

# --- FLASK ROUTES ---
@app.route('/')
def index():
    vids = []
    for r, d, f in os.walk(VIDEO_DIR):
        for file in f:
            if file.lower().endswith(VIDEO_EXTS):
                vids.append(os.path.relpath(os.path.join(r, file), VIDEO_DIR))
    return render_template_string(INDEX_HTML, videos=sorted(vids))

@app.route('/upload', methods=['POST'])
def upload():
    subdir = secure_filename(request.form.get('subdir', ''))
    target = os.path.join(VIDEO_DIR, subdir)
    os.makedirs(target, exist_ok=True)
    for f in request.files.getlist('files'):
        if f.filename:
            f.save(os.path.join(target, secure_filename(f.filename)))
    threading.Thread(target=generate_thumbnails).start()
    return redirect('/')

@app.route('/stream/<path:f>')
def stream(f): return send_from_directory(VIDEO_DIR, f)

@app.route('/thumb/<f>')
def thumb(f): return send_from_directory(THUMB_DIR, f)

@app.route('/play/<path:f>')
def play(f):
    return render_template_string("<body style='background:#000;margin:0;display:flex;justify-content:center;'><video controls autoplay style='height:100vh;'><source src='/stream/{{f}}'></video></body>", f=f)

if __name__ == "__main__":
    # Start Hardware and Background Tasks
    if HAS_HW:
        threading.Thread(target=lcd_thread, daemon=True).start()
    
    threading.Thread(target=generate_thumbnails, daemon=True).start()
    
    print(f"VOID_UPLINK_READY: http://{get_ip()}")
    app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)
