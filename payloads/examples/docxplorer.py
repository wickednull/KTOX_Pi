#!/usr/bin/env python3
"""
KTOx Payload – Document Explorer (Full File Browser)
======================================================
- Browse any directory on the KTOx filesystem
- View PDF, TXT, MD, JPG, PNG, GIF files
- Upload files to the current directory
- LCD: IP, system stats, QR code for library (KEY1)
- Web UI with cyberpunk theme
"""

import os, sys, time, socket, threading, mimetypes
from flask import Flask, render_template_string, send_from_directory, request, redirect, url_for, abort
from werkzeug.utils import secure_filename

# Hardware
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
START_DIR = "/root"
ALLOWED_EXTENSIONS = {'.pdf', '.txt', '.md', '.jpg', '.jpeg', '.png', '.gif'}
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
LIB_PORT = 80
UP_PORT = 8888

app_lib = Flask("DocumentExplorer")
app_up = Flask("Uplink")

# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
def size_fmt(size):
    for unit in ['B','KB','MB','GB']:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"

def safe_path(path):
    """Prevent directory traversal."""
    if not path:
        return START_DIR
    # Resolve to absolute path, ensure it doesn't go above root
    full = os.path.normpath(os.path.join(START_DIR, path))
    # Also allow going to other directories? We'll allow full system access but start at /root
    # For safety, we don't restrict beyond START_DIR? Actually user might want to browse anywhere.
    # We'll allow any path, but ensure it exists.
    if os.path.exists(full):
        return full
    # If the path is absolute, try that
    if os.path.exists(path):
        return path
    return START_DIR

def list_directory(path):
    items = []
    try:
        for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.is_dir():
                items.append({
                    'name': entry.name,
                    'type': 'dir',
                    'path': entry.path,
                    'size': '',
                    'size_fmt': ''
                })
            else:
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in ALLOWED_EXTENSIONS:
                    size = entry.stat().st_size
                    items.append({
                        'name': entry.name,
                        'type': 'file',
                        'path': entry.path,
                        'size': size,
                        'size_fmt': size_fmt(size),
                        'ext': ext[1:]
                    })
    except PermissionError:
        pass
    return items

def is_allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------------------------------------------------
# Web UI Templates
# ----------------------------------------------------------------------
BROWSER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>KTOx Document Explorer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            font-family: 'Share Tech Mono', monospace;
            color: #0f0;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 {
            color: #f00;
            text-shadow: 0 0 5px #f00;
            border-left: 4px solid #f00;
            padding-left: 20px;
            margin-bottom: 20px;
        }
        .path-bar {
            background: #111;
            border: 1px solid #0f0;
            padding: 10px;
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .path-bar span { flex: 1; word-break: break-all; }
        .path-bar button {
            background: #0a2a2a;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 4px 10px;
            cursor: pointer;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 20px;
            padding: 10px;
        }
        .card {
            background: #111;
            border: 1px solid #300;
            border-radius: 8px;
            transition: 0.2s;
            text-decoration: none;
            color: inherit;
            display: block;
            padding: 15px;
            text-align: center;
        }
        .card:hover {
            border-color: #0f0;
            transform: translateY(-3px);
            box-shadow: 0 0 15px #0f0;
        }
        .card .icon {
            font-size: 2.5rem;
            margin-bottom: 10px;
        }
        .card .name {
            word-break: break-word;
            font-size: 0.8rem;
        }
        .card .size {
            font-size: 0.7rem;
            color: #888;
            margin-top: 5px;
        }
        .upload-area {
            margin-top: 30px;
            padding: 20px;
            border-top: 1px solid #330000;
            text-align: center;
        }
        .upload-area a {
            color: #0f0;
            text-decoration: none;
            border: 1px solid #0f0;
            padding: 8px 16px;
            border-radius: 30px;
        }
        .upload-area a:hover {
            background: #0f0;
            color: #000;
        }
        footer {
            margin-top: 30px;
            text-align: center;
            color: #444;
            font-size: 0.7rem;
        }
        @media (max-width: 600px) {
            .grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>⎯ KTOx DOCUMENT EXPLORER ⎯</h1>
        <div class="path-bar">
            <span id="currentPath">{{ current_path }}</span>
            <button onclick="parentDir()">⬆ Up</button>
        </div>
        <div class="grid" id="fileGrid">
            {% for item in items %}
            <div class="card" onclick="openItem('{{ item.path }}', '{{ item.type }}')">
                <div class="icon">
                    {% if item.type == 'dir' %}📁
                    {% elif item.ext == 'pdf' %}📄
                    {% elif item.ext in ['jpg','jpeg','png','gif'] %}🖼️
                    {% else %}📝
                    {% endif %}
                </div>
                <div class="name">{{ item.name[:30] }}</div>
                {% if item.type == 'file' %}<div class="size">{{ item.size_fmt }}</div>{% endif %}
            </div>
            {% endfor %}
            {% if not items %}
            <div style="color:#666; text-align:center; grid-column:1/-1; padding:40px;">No documents or folders found.</div>
            {% endif %}
        </div>
        <div class="upload-area">
            <a href="#" id="uploadLink">⤒ UPLOAD TO THIS FOLDER</a>
        </div>
        <footer>KTOx Document Explorer – Click folder to enter, click file to view</footer>
    </div>

    <script>
        let currentPath = "{{ current_path }}";

        function parentDir() {
            let parent = currentPath.split('/').slice(0, -1).join('/');
            if (!parent) parent = '/';
            window.location.href = '/browse?path=' + encodeURIComponent(parent);
        }

        function openItem(path, type) {
            if (type === 'dir') {
                window.location.href = '/browse?path=' + encodeURIComponent(path);
            } else {
                window.location.href = '/view?path=' + encodeURIComponent(path);
            }
        }

        document.getElementById('uploadLink').onclick = function(e) {
            e.preventDefault();
            // Redirect to uplink with current path as subdirectory
            window.location.href = 'http://' + window.location.hostname + ':8888?dir=' + encodeURIComponent(currentPath);
        };
    </script>
</body>
</html>
"""

VIEWER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ name }} - KTOx Document</title>
    <style>
        body { background: #000; color: #0f0; font-family: monospace; margin: 0; padding: 20px; }
        .container { max-width: 1000px; margin: auto; background: #0a0505; border: 1px solid #f00; border-radius: 12px; padding: 20px; }
        h2 { color: #f00; }
        .back { display: inline-block; margin-top: 20px; color: #0f0; text-decoration: none; border: 1px solid #0f0; padding: 6px 12px; border-radius: 30px; }
        .back:hover { background: #0f0; color: #000; }
        pre { white-space: pre-wrap; word-wrap: break-word; background: #111; padding: 10px; border-radius: 8px; }
        img { max-width: 100%; border: 1px solid #0f0; }
        embed, iframe { width: 100%; height: 80vh; border: 1px solid #0f0; }
    </style>
</head>
<body>
    <div class="container">
        <h2>{{ name }}</h2>
        {% if ext == 'pdf' %}
        <embed src="/stream?path={{ path }}" type="application/pdf" width="100%" height="600px">
        {% elif ext in ['jpg','jpeg','png','gif'] %}
        <img src="/stream?path={{ path }}">
        {% else %}
        <pre>{{ content }}</pre>
        {% endif %}
        <br><a href="javascript:history.back()" class="back">⏎ BACK</a>
    </div>
</body>
</html>
"""

UPLINK_HTML = """
<!DOCTYPE html>
<html>
<head><title>KTOx Document Uplink</title>
<style>
    body { background: #000; color: #0f0; font-family: monospace; padding: 20px; }
    .container { max-width: 600px; margin: auto; border: 1px solid #0f0; padding: 20px; border-radius: 12px; }
    h1 { color: #0f0; }
    input, button { background: #111; border: 1px solid #0f0; color: #0f0; padding: 8px; width: 100%; margin-bottom: 10px; }
    button { cursor: pointer; width: auto; }
    .current-dir { margin-top: 15px; padding: 8px; background: #0a0a0a; border: 1px solid #0f0; }
</style>
</head>
<body>
<div class="container">
    <h1>⤒ UPLOAD DOCUMENTS</h1>
    <div class="current-dir">Uploading to: <span id="targetDir">{{ target_dir }}</span></div>
    <form method="POST" action="/upload" enctype="multipart/form-data">
        <input type="file" name="file" multiple>
        <input type="hidden" name="target_dir" id="hiddenDir" value="{{ target_dir }}">
        <button type="submit">UPLOAD</button>
    </form>
    <p style="margin-top: 20px;"><a href="/" style="color:#0f0;">← Back to Explorer</a></p>
</div>
<script>
    // If URL contains ?dir= parameter, pre-fill the target directory
    const urlParams = new URLSearchParams(window.location.search);
    const dir = urlParams.get('dir');
    if (dir) {
        document.getElementById('targetDir').innerText = decodeURIComponent(dir);
        document.getElementById('hiddenDir').value = decodeURIComponent(dir);
    }
</script>
</body>
</html>
"""

# ----------------------------------------------------------------------
# Flask routes
# ----------------------------------------------------------------------
@app_lib.route('/')
def index():
    return redirect(url_for('browse', path=START_DIR))

@app_lib.route('/browse')
def browse():
    path = request.args.get('path', START_DIR)
    full = safe_path(path)
    if not os.path.isdir(full):
        full = START_DIR
    items = list_directory(full)
    return render_template_string(BROWSER_HTML, current_path=full, items=items)

@app_lib.route('/view')
def view_document():
    path = request.args.get('path')
    if not path or not os.path.exists(path):
        abort(404)
    ext = os.path.splitext(path)[1].lower()[1:]
    name = os.path.basename(path)
    if ext in ['txt', 'md']:
        with open(path, 'r', errors='replace') as f:
            content = f.read()
    else:
        content = ''
    return render_template_string(VIEWER_HTML, name=name, ext=ext, path=path, content=content)

@app_lib.route('/stream')
def stream_file():
    path = request.args.get('path')
    if not path or not os.path.exists(path):
        abort(404)
    directory = os.path.dirname(path)
    filename = os.path.basename(path)
    return send_from_directory(directory, filename)

@app_up.route('/')
def uplink():
    target_dir = request.args.get('dir', START_DIR)
    return render_template_string(UPLINK_HTML, target_dir=target_dir)

@app_up.route('/upload', methods=['POST'])
def upload():
    target_dir = request.form.get('target_dir', START_DIR)
    if not os.path.exists(target_dir):
        target_dir = START_DIR
    files = request.files.getlist('file')
    for f in files:
        if f.filename and is_allowed_file(f.filename):
            fname = secure_filename(f.filename)
            f.save(os.path.join(target_dir, fname))
    return redirect(url_for('uplink', dir=target_dir))

# ----------------------------------------------------------------------
# System stats helpers (same as before)
# ----------------------------------------------------------------------
def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read().strip()) / 1000.0
    except:
        return 0.0

def get_cpu_load():
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline().strip()
        parts = line.split()
        idle = int(parts[4])
        total = sum(int(p) for p in parts[1:])
        return 100.0 * (total - idle) / total
    except:
        return 0.0

def get_ram_usage():
    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.readlines()
        total = 0
        avail = 0
        for line in lines:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
        if total > 0:
            return 100.0 * (total - avail) / total
        return 0.0
    except:
        return 0.0

# ----------------------------------------------------------------------
# LCD and main thread (unchanged)
# ----------------------------------------------------------------------
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def run_library():
    app_lib.run(host='0.0.0.0', port=LIB_PORT, debug=False, use_reloader=False)

def run_uplink():
    app_up.run(host='0.0.0.0', port=UP_PORT, debug=False, use_reloader=False)

def main():
    if not HAS_HW:
        threading.Thread(target=run_library, daemon=True).start()
        threading.Thread(target=run_uplink, daemon=True).start()
        while True:
            time.sleep(1)
        return

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    lcd.LCD_Clear()

    threading.Thread(target=run_library, daemon=True).start()
    threading.Thread(target=run_uplink, daemon=True).start()

    ip = None
    for _ in range(10):
        ip = get_ip()
        if ip and ip != '127.0.0.1':
            break
        time.sleep(0.2)
    if not ip or ip == '127.0.0.1':
        ip = "0.0.0.0"

    try:
        import qrcode
        qr_factory = qrcode.QRCode(box_size=3, border=2)
        qr_factory.add_data(f"http://{ip}")
        qr_img = qr_factory.make_image(fill_color="white", back_color="black").get_image().resize((128,128))
    except:
        qr_img = None

    show_qr = False
    held = {}

    try:
        while True:
            now = time.time()
            img = Image.new("RGB", (128,128), "#0A0000")
            draw = ImageDraw.Draw(img)

            if show_qr and qr_img:
                img.paste(qr_img, (0,0))
            else:
                draw.rectangle([(0,0),(128,18)], fill=(120,0,0))
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",9)
                except:
                    font = ImageFont.load_default()
                draw.text((4,3), "DOC EXPLORER", fill="black", font=font)
                draw.text((4,20), f"IP: {ip}:{LIB_PORT}", fill="white", font=font)
                draw.text((4,32), "PORT 80: BROWSER", fill="cyan", font=font)
                temp = get_cpu_temp()
                temp_color = "#00FF00" if temp < 60 else "#FFFF00" if temp < 75 else "#FF0000"
                draw.text((4,44), f"CPU: {get_cpu_load():.0f}%  {temp:.0f}C", fill=temp_color, font=font)
                draw.text((4,56), f"RAM: {get_ram_usage():.0f}%", fill="#FFBBBB", font=font)
                draw.text((4,68), "K1:QR  K3:EXIT", fill="#FF7777", font=font)
                draw.rectangle((0,112),(128,128), fill="#220000")

            lcd.LCD_ShowImage(img, 0, 0)

            pressed = {n: GPIO.input(p)==0 for n,p in PINS.items()}
            for n, down in pressed.items():
                if down:
                    if n not in held: held[n] = now
                else:
                    held.pop(n, None)

            if pressed.get("KEY3") and (now - held.get("KEY3", now)) <= 0.05:
                break
            if pressed.get("KEY1") and (now - held.get("KEY1", now)) <= 0.05:
                show_qr = not show_qr
                time.sleep(0.3)

            time.sleep(0.5)
    finally:
        lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    print("Starting KTOx Document Explorer...")
    main()
