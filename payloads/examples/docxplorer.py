#!/usr/bin/env python3
"""
KTOx Payload – Document Browser
================================
Browse and view PDF, text, and image files from any directory.
Web server on port 5000.
Controls: KEY1=QR, KEY3=exit.
"""

import os
import sys
import time
import socket
import threading
from flask import Flask, render_template_string, send_from_directory, request, abort, redirect
from werkzeug.utils import secure_filename

# ----------------------------------------------------------------------
# Hardware & LCD
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("KTOx hardware not found")
    sys.exit(1)

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

f9 = font(9)

# ----------------------------------------------------------------------
# Flask web server
# ----------------------------------------------------------------------
START_DIR = "/root"
ALLOWED_EXTS = {'.pdf', '.txt', '.md', '.jpg', '.jpeg', '.png', '.gif'}
PORT = 5000
app = Flask(__name__)

def size_fmt(size):
    for unit in ['B','KB','MB','GB']:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"

def list_dir(path):
    items = []
    try:
        for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.is_dir():
                items.append(('dir', entry.name, entry.path, 0))
            else:
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in ALLOWED_EXTS:
                    items.append(('file', entry.name, entry.path, entry.stat().st_size))
    except PermissionError:
        pass
    return items

BROWSER_HTML = """
<!DOCTYPE html>
<html>
<head><title>KTOx Document Browser</title>
<style>
body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:20px}
.container{max-width:1000px;margin:auto}
h1{color:#f00;border-left:4px solid #f00;padding-left:20px}
.path-bar{background:#111;border:1px solid #0f0;padding:10px;margin:20px 0;display:flex;gap:10px}
.path-bar span{flex:1}
.path-bar a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:4px 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:15px}
.card{background:#111;border:1px solid #300;border-radius:8px;padding:15px;text-align:center;cursor:pointer}
.card:hover{border-color:#0f0;transform:translateY(-2px)}
.icon{font-size:2rem}
.name{font-size:0.8rem;word-break:break-word}
.size{font-size:0.7rem;color:#888}
footer{margin-top:30px;text-align:center;color:#444}
</style>
</head>
<body>
<div class="container">
<h1>⎯ KTOx DOCUMENT BROWSER ⎯</h1>
<div class="path-bar"><span>{{ path }}</span><a href="/">Home</a><a href="/browse?path={{ parent }}">Up</a></div>
<div class="grid">
{% for item in items %}
<div class="card" onclick="location.href='{{ item.url }}'">
<div class="icon">{{ item.icon }}</div>
<div class="name">{{ item.name[:30] }}</div>
<div class="size">{{ item.size }}</div>
</div>
{% endfor %}
</div>
<footer>Click folder to enter, file to view</footer>
</div>
</body>
</html>
"""

VIEW_HTML = """
<!DOCTYPE html>
<html>
<head><title>{{ name }} - KTOx</title>
<style>
body{background:#000;color:#0f0;padding:20px}
.container{max-width:1000px;margin:auto;background:#0a0505;border:1px solid #f00;border-radius:12px;padding:20px}
h2{color:#f00}
.back{display:inline-block;margin-top:20px;color:#0f0;border:1px solid #0f0;padding:6px 12px;border-radius:30px;text-decoration:none}
pre{white-space:pre-wrap;background:#111;padding:10px;border-radius:8px}
img{max-width:100%}
embed,iframe{width:100%;height:600px}
</style>
</head>
<body>
<div class="container">
<h2>{{ name }}</h2>
{% if ext == 'pdf' %}
<embed src="/file?path={{ path }}" type="application/pdf">
{% elif ext in ['jpg','jpeg','png','gif'] %}
<img src="/file?path={{ path }}">
{% else %}
<pre>{{ content }}</pre>
{% endif %}
<br><a href="javascript:history.back()" class="back">← Back</a>
</div>
</body>
</html>
"""

@app.route('/')
def index():
    return redirect('/browse?path=' + START_DIR)

@app.route('/browse')
def browse():
    path = request.args.get('path', START_DIR)
    if not os.path.isdir(path):
        path = START_DIR
    items = []
    for typ, name, full, size in list_dir(path):
        if typ == 'dir':
            items.append({'url': f'/browse?path={full}', 'icon': '📁', 'name': name, 'size': ''})
        else:
            items.append({'url': f'/view?path={full}', 'icon': '📄', 'name': name, 'size': size_fmt(size)})
    parent = os.path.dirname(path)
    return render_template_string(BROWSER_HTML, path=path, parent=parent, items=items)

@app.route('/view')
def view():
    path = request.args.get('path')
    if not path or not os.path.isfile(path):
        abort(404)
    ext = os.path.splitext(path)[1].lower()[1:]
    name = os.path.basename(path)
    content = ''
    if ext in ['txt','md']:
        with open(path, 'r', errors='replace') as f:
            content = f.read()
    return render_template_string(VIEW_HTML, name=name, ext=ext, path=path, content=content)

@app.route('/file')
def send_file():
    path = request.args.get('path')
    if not path or not os.path.isfile(path):
        abort(404)
    return send_from_directory(os.path.dirname(path), os.path.basename(path))

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ----------------------------------------------------------------------
# LCD drawing (exactly like working example)
# ----------------------------------------------------------------------
def draw(lines, title="DOC BROWSER", title_color="#8B0000", text_color="#FFBBBB"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=title_color)
    d.text((4, 3), title[:20], font=f9, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        d.text((4, y), line[:23], font=f9, fill=text_color)
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "K1=QR  K3=EXIT", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    # Start Flask in a daemon thread
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(1)  # give Flask time to start

    ip = get_ip()
    draw([f"Server: {ip}:{PORT}", "", "K1=QR  K3=EXIT"], title="DOC BROWSER")

    show_qr = False
    qr_img = None
    held = {}

    while True:
        now = time.time()
        if show_qr:
            if qr_img is None:
                try:
                    import qrcode
                    qr = qrcode.QRCode(box_size=3, border=2)
                    qr.add_data(f"http://{ip}:{PORT}")
                    qr_img = qr.make_image(fill_color="white", back_color="black").get_image().resize((128,128))
                except:
                    qr_img = False
            if qr_img and qr_img != False:
                img = Image.new("RGB", (W, H), "#0A0000")
                img.paste(qr_img, (0,0))
                LCD.LCD_ShowImage(img, 0, 0)
            else:
                draw(["QR error"], title="DOC BROWSER")
        else:
            draw([f"IP: {ip}:{PORT}", "", "Document browser running", "", "K1=QR  K3=EXIT"], title="DOC BROWSER")

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

        time.sleep(0.1)

    # Clean exit
    LCD.LCD_Clear()
    GPIO.cleanup()
    os._exit(0)

if __name__ == "__main__":
    try:
        import qrcode
    except ImportError:
        os.system("pip install qrcode pillow")
    main()
