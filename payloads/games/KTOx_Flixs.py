#!/usr/bin/env python3
"""
KTOx Payload – CYBER_VOID
===================================
A dual-port media server and data injector.
Port 80:  Cyberpunk Movie Library
Port 8888: Data Uplink (File/Folder Injections)

Controls:
  KEY1   Toggle QR Uplink Code
  KEY3   Exit Payload
"""

import os, sys, time, socket, logging, threading, subprocess
import qrcode
from flask import Flask, render_template_string, request, send_from_directory, abort, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

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

# ── Config ────────────────────────────────────────────────────────────────────
VIDEO_DIR  = "/root/Videos"
THUMB_DIR  = "/root/Videos/thumbnails"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}

os.makedirs(THUMB_DIR, exist_ok=True)

# ── Flask Apps ────────────────────────────────────────────────────────────────
app_ui = Flask("Library")
app_up = Flask("Uplink")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# --- Templates ---
CYBER_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    :root { --red: #ff0000; --cyan: #00f3ff; --bg: #050505; }
    body { background: var(--bg); color: #ccc; font-family: 'Share Tech Mono', monospace; margin:0; }
    nav { padding: 15px; background: #000; border-bottom: 2px solid var(--red); display: flex; justify-content: space-between; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 15px; padding: 20px; }
    .card { background: #000; border: 1px solid #2b0000; text-decoration: none; color: inherit; transition: 0.3s; }
    .card:hover { border-color: var(--cyan); transform: translateY(-3px); }
    .card img { width: 100%; aspect-ratio: 2/3; object-fit: cover; filter: brightness(0.4); }
    .card:hover img { filter: brightness(1); }
    #prog-wrap { display: none; margin-top: 20px; }
    #prog-bar { width: 0%; background: var(--cyan); height: 10px; box-shadow: 0 0 10px var(--cyan); transition: width 0.1s; }
</style>
"""

# ── Server Threads ────────────────────────────────────────────────────────────
class LibraryThread(threading.Thread):
    def run(self): app_ui.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)

class UplinkThread(threading.Thread):
    def run(self): app_up.run(host="0.0.0.0", port=8888, debug=False, use_reloader=False)

# ── Routes ────────────────────────────────────────────────────────────────────
@app_ui.route('/')
def index():
    vids = [os.path.relpath(os.path.join(r, f), VIDEO_DIR) for r, d, files in os.walk(VIDEO_DIR) for f in files if f.lower().endswith(VIDEO_EXTS)]
    return render_template_string(CYBER_CSS + """
    <nav><div style="color:red">KTOx//CYBER_VOID</div></nav>
    <div class="grid">
        {% for v in videos %}
        <a href="/play/{{ v }}" class="card">
            <img src="/thumb/{{ v | replace('/', '_') }}.jpg">
            <div style="padding:5px; font-size:10px;">{{ v | upper }}</div>
        </a>
        {% endfor %}
    </div>""", videos=sorted(vids))

@app_ui.route('/thumb/<f>')
def thumb(f): return send_from_directory(THUMB_DIR, f)

@app_ui.route('/stream/<path:f>')
def stream(f): return send_from_directory(VIDEO_DIR, f)

@app_ui.route('/play/<path:f>')
def play(f):
    return render_template_string("<body style='background:#000;margin:0;'><video controls autoplay style='width:100%;height:100vh;'><source src='/stream/{{f}}'></video></body>", f=f)

@app_up.route('/')
def uplink_home():
    return render_template_string(CYBER_CSS + """
    <nav><div style="color:cyan">KTOx//DATA_UPLINK</div></nav>
    <div style="padding:20px; max-width:500px; margin:auto;">
        <input type="text" id="sd" placeholder="SUBDIRECTORY">
        <input type="file" id="fi" multiple webkitdirectory>
        <button onclick="up()" style="background:#2b0000; color:white; border:1px solid red; padding:10px; width:100%;">INJECT</button>
        <div id="prog-wrap"><div style="border:1px solid var(--cyan)"><div id="prog-bar"></div></div></div>
    </div>
    <script>
    function up(){
        const fd = new FormData();
        fd.append('subdir', document.getElementById('sd').value);
        for(let f of document.getElementById('fi').files){ fd.append('files', f); }
        const xhr = new XMLHttpRequest();
        document.getElementById('prog-wrap').style.display='block';
        xhr.upload.onprogress = (e) => { document.getElementById('prog-bar').style.width = (e.loaded/e.total*100)+'%'; };
        xhr.onload = () => { location.reload(); };
        xhr.open('POST', '/upload'); xhr.send(fd);
    }
    </script>""")

@app_up.route('/upload', methods=['POST'])
def upload():
    target = os.path.join(VIDEO_DIR, request.form.get('subdir', '').strip())
    os.makedirs(target, exist_ok=True)
    for f in request.files.getlist('files'):
        if f.filename:
            path = os.path.join(target, f.filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
    return jsonify({"status": "ok"})

# ── LCD Helpers ───────────────────────────────────────────────────────────────
def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"

def _load_font(path, size):
    try: return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not HAS_HW:
        LibraryThread().start(); UplinkThread().start()
        while True: time.sleep(1)

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    lcd.LCD_Clear()

    font_bold = _load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    font_sm   = _load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)

    ip = _get_ip()
    show_qr = False
    held = {}

    # Start Servers
    LibraryThread().start()
    UplinkThread().start()

    try:
        while True:
            now = time.time()
            img = Image.new("RGB", (128,128), "black")
            draw = ImageDraw.Draw(img)

            if show_qr:
                qr = qrcode.QRCode(box_size=3, border=2)
                qr.add_data(f"http://{ip}:8888")
                qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((128,128))
                img.paste(qr_img, (0,0))
            else:
                # Dashboard UI
                draw.rectangle([(0,0),(128,18)], fill=(120,0,0))
                draw.text((4,3), "KTOx // CYBER_VOID", font=font_sm, fill="black")
                
                draw.text((4,25), f"IP: {ip}", font=font_sm, fill="white")
                draw.text((4,40), "PORT 80: LIBRARY", font=font_sm, fill=(0,255,255))
                draw.text((4,55), "PORT 8888: UPLINK", font=font_sm, fill=(255,50,50))
                
                # Visual footer
                draw.rectangle([(0,110),(128,128)], fill=(20,20,20))
                draw.text((4,113), "KEY1:QR  KEY3:EXIT", font=font_sm, fill=(150,150,150))

            lcd.LCD_ShowImage(img, 0, 0)

            # --- Input Logic ---
            pressed = {name: GPIO.input(pin)==0 for name,pin in PINS.items()}
            for name, is_down in pressed.items():
                if is_down:
                    if name not in held: held[name] = now
                else: held.pop(name, None)

            def just_pressed(name):
                return pressed.get(name) and (now - held.get(name, now)) <= 0.05

            if just_pressed("KEY3"): break
            if just_pressed("KEY1"):
                show_qr = not show_qr
                time.sleep(0.2)

            time.sleep(0.05)

    except KeyboardInterrupt: pass
    finally:
        lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
