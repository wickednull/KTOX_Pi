#!/usr/bin/env python3
import os, sys, time, threading, subprocess, socket, re, urllib.parse
import requests, qrcode
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

app_ui = Flask(__name__)      # Port 80 (The Library)
app_uplink = Flask(__name__)  # Port 8888 (The Uploads)

# --- CSS STYLES ---
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
    .card img { width: 100%; aspect-ratio: 2/3; object-fit: cover; filter: grayscale(1) sepia(1) hue-rotate(-50deg) brightness(0.5); transition: 0.3s; }
    .card:hover img { filter: grayscale(0) brightness(1); }
    .card-meta { padding: 8px; font-size: 10px; border-top: 1px solid var(--dark-red); }
    .btn { background: var(--dark-red); color: white; border: 1px solid var(--red); padding: 12px; cursor: pointer; font-family: inherit; width: 100%; font-weight: bold; }
    input { background: #111; border: 1px solid var(--dark-red); color: var(--cyan); padding: 12px; width: 100%; box-sizing: border-box; margin-bottom: 15px; font-family: inherit; }
</style>
"""

# --- UI TEMPLATES ---
LIBRARY_HTML = CYBER_CSS + """
<nav><div class="logo">KTOx//CYBER_VOID</div><div style="color:var(--cyan);font-size:10px;">DECRYPTED_LINK</div></nav>
<div class="container">
    <div class="grid">
        {% for v in videos %}
        <a href="/play/{{ v }}" class="card">
            <img src="/thumb/{{ v | replace('/', '_') }}.jpg">
            <div class="card-meta"><span style="color:var(--cyan)">DATA//</span> {{ v | upper }}</div>
        </a>
        {% endfor %}
    </div>
</div>
"""

UPLINK_HTML = CYBER_CSS + """
<nav><div class="logo">KTOx//DATA_INJECTOR</div><div style="color:var(--red);font-size:10px;">AUTH_SECURE</div></nav>
<div class="container" style="max-width: 500px; margin: auto; padding-top: 50px;">
    <h3 style="color:var(--cyan); margin-bottom: 30px;">> BEGIN_DATA_INJECTION</h3>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="text" name="subdir" placeholder="TARGET_DIRECTORY (OPTIONAL)">
        <label style="font-size:9px; color:#666;">FILES</label>
        <input type="file" name="files_direct" multiple>
        <label style="font-size:9px; color:#666;">FOLDERS</label>
        <input type="file" name="files_folder" multiple webkitdirectory>
        <button class="btn" type="submit">START_UPLINK</button>
    </form>
</div>
"""

# --- HELPERS ---
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

# --- THE LCD TOGGLE FIX ---
def lcd_thread():
    time.sleep(2)
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values(): GPIO.setup(p, GPIO.IN, GPIO.PUD_UP)
    
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    ip = get_ip()
    show_qr = False

    while True:
        # Check Button State Every Loop
        if GPIO.input(PINS["KEY1"]) == 0:
            show_qr = not show_qr
            # Visual feedback on click
            click_img = Image.new("RGB", (128,128), "red")
            lcd.LCD_ShowImage(click_img, 0,0)
            time.sleep(0.3) # Debounce & wait for finger release

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
            d.text((5,25), f"IP: {ip}", fill="#00f3ff")
            d.text((5,45), f"CPU: {t:.1f}C", fill="red" if t > 70 else "green")
            d.text((5,65), f"TX: {tx}MB", fill="#ccc")
            d.text((5,80), f"RX: {rx}MB", fill="#ccc")
            d.text((5,105), "[KEY1] SCAN UPLINK", fill="red")
            lcd.LCD_ShowImage(img, 0, 0)
        
        # Keep the loop fast so it catches the button press to "EXIT"
        time.sleep(0.2) 

# --- FLASK SERVERS ---
@app_ui.route('/')
def index():
    vids = []
    for r, d, f in os.walk(VIDEO_DIR):
        for file in f:
            if file.lower().endswith(VIDEO_EXTS):
                vids.append(os.path.relpath(os.path.join(r, file), VIDEO_DIR))
    return render_template_string(LIBRARY_HTML, videos=sorted(vids))

@app_ui.route('/thumb/<f>')
def thumb(f): return send_from_directory(THUMB_DIR, f)

@app_ui.route('/stream/<path:f>')
def stream(f): return send_from_directory(VIDEO_DIR, f)

@app_ui.route('/play/<path:f>')
def play(f):
    return render_template_string("<body style='background:#000;margin:0;display:flex;align-items:center;height:100vh;'><video controls autoplay style='width:100%;'><source src='/stream/{{f}}'></video></body>", f=f)

@app_uplink.route('/')
def uplink(): return render_template_string(UPLINK_HTML)

@app_uplink.route('/upload', methods=['POST'])
def do_upload():
    subdir = request.form.get('subdir', '').strip()
    target = os.path.join(VIDEO_DIR, subdir)
    os.makedirs(target, exist_ok=True)
    all_files = request.files.getlist('files_direct') + request.files.getlist('files_folder')
    for f in all_files:
        if f.filename:
            f.save(os.path.join(target, secure_filename(f.filename)))
    return redirect('/')

if __name__ == "__main__":
    if HAS_HW:
        threading.Thread(target=lcd_thread, daemon=True).start()
    
    # Run Uplink in background
    threading.Thread(target=lambda: app_uplink.run(host='0.0.0.0', port=8888, debug=False, use_reloader=False), daemon=True).start()
    
    # Main Library
    app_ui.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)
