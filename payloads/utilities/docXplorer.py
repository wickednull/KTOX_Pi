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
:root{--bg-0:#0a0000;--bg-1:#220000;--header:#8b0000;--accent:#e74c3c;--warn:#d4ac0d;--fg:#abb2b9;--fg-muted:#717d7e}
body{background:linear-gradient(135deg,var(--bg-0),var(--bg-1));color:var(--fg);font-family:'Courier New',monospace;
     padding:16px;margin:0;overflow-x:hidden}
.container{max-width:1200px;margin:auto}
h1{color:var(--white);border-left:4px solid var(--accent);padding-left:16px;text-shadow:0 0 6px var(--accent);
   letter-spacing:2px;margin-bottom:16px}
.path-bar{background:var(--bg-1);border:1px solid rgba(231,76,60,0.3);padding:10px;margin:16px 0;display:flex;
          gap:10px;border-radius:4px;box-shadow:0 0 10px rgba(231,76,60,0.2)}
.path-bar span{flex:1;color:var(--fg-muted);font-family:monospace;font-size:0.85rem;word-break:break-all}
.path-bar a{color:var(--white);text-decoration:none;border:1px solid var(--accent);padding:6px 12px;
           background:linear-gradient(135deg,var(--header),var(--bg-1));border-radius:3px;
           box-shadow:0 0 10px rgba(231,76,60,0.3);cursor:pointer}
.path-bar a:hover{background:linear-gradient(135deg,var(--accent),#c0392b);box-shadow:0 0 20px rgba(231,76,60,0.5)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin:16px 0}
.card{background:var(--bg-1);border:1px solid rgba(231,76,60,0.3);border-radius:4px;padding:12px;text-align:center;
      cursor:pointer;transition:all 0.3s ease;box-shadow:0 0 10px rgba(231,76,60,0.2)}
.card:hover{border-color:var(--accent);transform:translateY(-3px);box-shadow:0 0 20px rgba(231,76,60,0.5);
           background:var(--bg-0)}
.icon{font-size:2.5rem;margin-bottom:8px}
.name{font-size:0.8rem;word-break:break-word;color:var(--fg)}
.size{font-size:0.7rem;color:var(--fg-muted);margin-top:4px}
footer{margin-top:24px;text-align:center;color:var(--fg-muted);padding-top:12px;border-top:1px solid rgba(231,76,60,0.2)}
.white{color:#f5f5f5}
.scanlines{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;
          background:repeating-linear-gradient(0deg,rgba(0,0,0,0.1),rgba(0,0,0,0.1) 1px,transparent 1px,transparent 2px);
          z-index:9999}
</style>
</head>
<body>
<div class="container">
<h1>📄 KTOx DOCUMENT BROWSER</h1>
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
<div class="scanlines"></div>
</body>
</html>
"""

VIEW_HTML = """
<!DOCTYPE html>
<html>
<head><title>{{ name }} - KTOx</title>
<style>
:root{--bg-0:#0a0000;--bg-1:#220000;--header:#8b0000;--accent:#e74c3c;--fg:#abb2b9;--fg-muted:#717d7e;--white:#f5f5f5}
body{background:linear-gradient(135deg,var(--bg-0),var(--bg-1));color:var(--fg);padding:16px;margin:0;font-family:'Courier New',monospace}
.container{max-width:1000px;margin:auto;background:var(--bg-1);border:1px solid rgba(231,76,60,0.3);border-radius:6px;
           padding:20px;box-shadow:inset 0 0 8px rgba(0,0,0,0.8)}
h2{color:var(--accent);text-shadow:0 0 6px var(--accent);margin-bottom:16px;border-bottom:1px solid rgba(231,76,60,0.2);
   padding-bottom:8px}
.back{display:inline-block;margin-top:20px;color:var(--white);border:1px solid var(--accent);padding:8px 16px;
      border-radius:4px;text-decoration:none;background:linear-gradient(135deg,var(--header),var(--bg-1));
      box-shadow:0 0 10px rgba(231,76,60,0.3)}
.back:hover{background:linear-gradient(135deg,var(--accent),#c0392b);box-shadow:0 0 20px rgba(231,76,60,0.5)}
pre{white-space:pre-wrap;background:var(--bg-0);padding:12px;border-radius:4px;border:1px solid rgba(231,76,60,0.2);
    color:var(--fg);font-family:monospace;overflow-x:auto;font-size:0.85rem}
img{max-width:100%;border-radius:4px;border:1px solid rgba(231,76,60,0.2)}
embed,iframe{width:100%;height:600px;border-radius:4px;border:1px solid rgba(231,76,60,0.2)}
.scanlines{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;
          background:repeating-linear-gradient(0deg,rgba(0,0,0,0.1),rgba(0,0,0,0.1) 1px,transparent 1px,transparent 2px);
          z-index:9999}
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
<div class="scanlines"></div>
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
    d.text((4, 3), title[:20], font=f9, fill=(231, 76, 60))
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
