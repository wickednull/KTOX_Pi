#!/usr/bin/env python3
"""
KTOx Payload – Web File Explorer
===================================
Starts a Flask web server on port 8888 for browsing, uploading,
and downloading files from the KTOx device.

LCD Shows: IP address, port, status (running/stopped)

Controls:
  KEY1   Start / Stop server toggle
  KEY3   Exit payload
"""

import os, sys, time, socket, logging, threading

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

try:
    from flask import Flask, render_template_string, request, send_from_directory, abort, redirect, url_for
    from werkzeug.utils import secure_filename
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

# ── Config ────────────────────────────────────────────────────────────────────
HTTP_PORT    = 8888
EXPLORE_ROOT = "/root"
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}

# ── Flask app ─────────────────────────────────────────────────────────────────
HTML_TPL = """<!DOCTYPE html>
<html>
<head>
<title>KTOx File Explorer</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
     background:#0d1117;color:#c9d1d9;padding:16px}
h1{color:#00ff41;font-size:1.4rem;margin-bottom:16px}
.container{max-width:900px;margin:0 auto;background:#161b22;
           padding:20px;border-radius:8px;border:1px solid #30363d}
.path{font-family:monospace;color:#8b949e;font-size:.85rem;
      margin-bottom:12px;word-break:break-all}
.breadcrumb{margin-bottom:16px;font-size:.9rem}
.breadcrumb a{color:#58a6ff;text-decoration:none}
.breadcrumb a:hover{text-decoration:underline}
.breadcrumb span{color:#8b949e;margin:0 4px}
table{width:100%;border-collapse:collapse}
thead{background:#21262d}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #21262d;font-size:.9rem}
th{color:#8b949e;font-weight:600;font-size:.8rem;text-transform:uppercase}
tr:hover td{background:#1c2128}
.name a{color:#58a6ff;text-decoration:none}
.name a:hover{text-decoration:underline}
.dir-icon{color:#e3b341;margin-right:6px}
.file-icon{color:#8b949e;margin-right:6px}
.size{color:#8b949e;font-family:monospace;font-size:.85rem}
.dl-btn{background:#238636;color:#fff;border:none;padding:4px 10px;
        border-radius:4px;cursor:pointer;font-size:.8rem;text-decoration:none;
        display:inline-block}
.dl-btn:hover{background:#2ea043}
.del-btn{background:#b91c1c;color:#fff;border:none;padding:4px 10px;
         border-radius:4px;cursor:pointer;font-size:.8rem;margin-left:4px}
.del-btn:hover{background:#dc2626}
.upload-section{margin-top:24px;padding-top:20px;border-top:1px solid #30363d}
.upload-section h3{color:#c9d1d9;margin-bottom:12px;font-size:1rem}
.upload-form{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type="file"]{background:#21262d;color:#c9d1d9;padding:8px;
                   border-radius:4px;border:1px solid #30363d;flex:1;min-width:200px}
.upload-btn{background:#1f6feb;color:#fff;border:none;padding:8px 16px;
            border-radius:4px;cursor:pointer;font-weight:600}
.upload-btn:hover{background:#388bfd}
.back-btn{display:inline-block;margin-bottom:12px;color:#8b949e;
          text-decoration:none;font-size:.9rem}
.back-btn:hover{color:#c9d1d9}
.empty{color:#8b949e;padding:20px;text-align:center;font-style:italic}
.stats{color:#8b949e;font-size:.8rem;margin-top:8px}
</style>
</head>
<body>
<div class="container">
  <h1>&#x1F4C1; KTOx File Explorer</h1>
  <div class="path">{{ current_path }}</div>

  <!-- Breadcrumb -->
  <div class="breadcrumb">
    <a href="{{ url_for('browse', path='') }}">root</a>
    {% for crumb in breadcrumbs %}
      <span>/</span><a href="{{ url_for('browse', path=crumb.path) }}">{{ crumb.name }}</a>
    {% endfor %}
  </div>

  {% if current_path != explore_root %}
  <a href="{{ url_for('browse', path=parent_path) }}" class="back-btn">&#x2190; Parent Directory</a>
  {% endif %}

  <table>
    <thead><tr><th>Name</th><th>Size</th><th>Actions</th></tr></thead>
    <tbody>
    {% if not items %}
    <tr><td colspan="3" class="empty">(empty directory)</td></tr>
    {% endif %}
    {% for item in items %}
    <tr>
      <td class="name">
        {% if item.is_dir %}
          <span class="dir-icon">&#x1F4C2;</span>
          <a href="{{ url_for('browse', path=item.rel_path) }}">{{ item.name }}/</a>
        {% else %}
          <span class="file-icon">&#x1F4C4;</span>{{ item.name }}
        {% endif %}
      </td>
      <td class="size">{{ item.size }}</td>
      <td>
        {% if not item.is_dir %}
          <a href="{{ url_for('download', path=item.rel_path) }}" class="dl-btn">&#x2B07; Download</a>
          <form method="POST" action="{{ url_for('delete_file', path=item.rel_path) }}"
                style="display:inline"
                onsubmit="return confirm('Delete {{ item.name }}?')">
            <button type="submit" class="del-btn">&#x1F5D1; Del</button>
          </form>
        {% else %}
          <a href="{{ url_for('browse', path=item.rel_path) }}" class="dl-btn">Open</a>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
    </tbody>
  </table>

  <div class="stats">{{ items|length }} items</div>

  <div class="upload-section">
    <h3>&#x2B06; Upload to this directory</h3>
    <form method="POST" action="{{ url_for('upload', path=current_path_rel) }}"
          enctype="multipart/form-data" class="upload-form">
      <input type="file" name="file" required multiple>
      <button type="submit" class="upload-btn">Upload</button>
    </form>
  </div>
</div>
</body>
</html>"""

if HAS_FLASK:
    _app = Flask(__name__)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    def _abs(path):
        p = os.path.normpath(os.path.join(EXPLORE_ROOT, path or ""))
        if not p.startswith(EXPLORE_ROOT):
            abort(403)
        return p

    def _fmt_size(n):
        if n < 1024: return f"{n}B"
        if n < 1024**2: return f"{n/1024:.1f}KB"
        if n < 1024**3: return f"{n/1024**2:.1f}MB"
        return f"{n/1024**3:.1f}GB"

    def _build_crumbs(path):
        crumbs, parts, acc = [], (path or "").split("/"), ""
        for part in parts:
            if not part: continue
            acc = (acc+"/"+part).lstrip("/")
            crumbs.append({"name": part, "path": acc})
        return crumbs

    @_app.route("/")
    def index():
        return redirect(url_for("browse", path=""))

    @_app.route("/browse/", defaults={"path": ""})
    @_app.route("/browse/<path:path>")
    def browse(path):
        full = _abs(path)
        if not os.path.isdir(full): abort(404)
        items = []
        try:
            for entry in sorted(os.scandir(full), key=lambda e: (not e.is_dir(), e.name.lower())):
                rel = os.path.relpath(entry.path, EXPLORE_ROOT)
                sz  = ""
                if entry.is_file():
                    try: sz = _fmt_size(entry.stat().st_size)
                    except Exception: sz = "?"
                items.append({"name":entry.name,"is_dir":entry.is_dir(),
                               "rel_path":rel,"size":sz})
        except PermissionError:
            items = []

        parent = os.path.relpath(os.path.dirname(full), EXPLORE_ROOT)
        if parent == ".": parent = ""

        return render_template_string(
            HTML_TPL,
            items=items,
            current_path=full,
            current_path_rel=path,
            explore_root=EXPLORE_ROOT,
            parent_path=parent,
            breadcrumbs=_build_crumbs(path),
        )

    @_app.route("/download/<path:path>")
    def download(path):
        full = _abs(path)
        if not os.path.isfile(full): abort(404)
        return send_from_directory(os.path.dirname(full), os.path.basename(full),
                                   as_attachment=True)

    @_app.route("/upload/<path:path>", methods=["POST"])
    def upload(path):
        full = _abs(path)
        if not os.path.isdir(full): abort(404)
        files = request.files.getlist("file")
        for f in files:
            if f and f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(full, fname))
        return redirect(url_for("browse", path=path))

    @_app.route("/delete/<path:path>", methods=["POST"])
    def delete_file(path):
        full = _abs(path)
        parent_rel = os.path.relpath(os.path.dirname(full), EXPLORE_ROOT)
        if parent_rel == ".": parent_rel = ""
        try:
            if os.path.isfile(full):
                os.remove(full)
        except Exception: pass
        return redirect(url_for("browse", path=parent_rel))


# ── Server thread ─────────────────────────────────────────────────────────────
class _ServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
    def run(self):
        if HAS_FLASK:
            _app.run(host="0.0.0.0", port=HTTP_PORT, debug=False, use_reloader=False)
        else:
            import http.server, socketserver
            class H(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *a, **kw):
                    super().__init__(*a, directory=EXPLORE_ROOT, **kw)
                def log_message(self, *a): pass
            with socketserver.TCPServer(("", HTTP_PORT), H) as httpd:
                httpd.serve_forever()


# ── LCD helpers ───────────────────────────────────────────────────────────────
def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"

def _load_font(path, size):
    try: return ImageFont.truetype(path, size)
    except Exception: return ImageFont.load_default()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not HAS_HW:
        print(f"[web_file_browser] No hardware. Server: http://0.0.0.0:{HTTP_PORT}")
        srv = _ServerThread(); srv.start()
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
        return

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    lcd.LCD_Clear()

    font_bold = _load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    font_sm   = _load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)

    ip      = _get_ip()
    running = False
    srv     = None
    held    = {}

    # Auto-start server
    srv     = _ServerThread(); srv.start()
    running = True

    try:
        while True:
            # ── Draw ──
            img  = Image.new("RGB", (128,128), "black")
            draw = ImageDraw.Draw(img)

            # Header
            hdr_color = (0,160,50) if running else (120,0,0)
            draw.rectangle([(0,0),(128,18)], fill=hdr_color)
            draw.text((4,3), "WEB FILE EXPLORER", font=font_sm, fill="black")

            # Status
            y = 25
            draw.text((4,y), f"IP:   {ip}", font=font_sm, fill="white"); y+=14
            draw.text((4,y), f"Port: {HTTP_PORT}", font=font_sm, fill="white"); y+=14

            status_col = (0,255,70) if running else (255,70,70)
            status_txt = "RUNNING" if running else "STOPPED"
            draw.text((4,y), "Status:", font=font_sm, fill=(180,180,180)); y+=12
            draw.text((4,y), status_txt, font=font_bold, fill=status_col); y+=16

            if running:
                url = f"http://{ip}:{HTTP_PORT}"
                draw.text((4,y), url, font=font_sm, fill=(100,180,255)); y+=12

            # Footer
            draw.rectangle([(0,110),(128,128)], fill=(20,20,20))
            draw.text((4,113), "KEY1=Toggle  KEY3=Exit", font=font_sm, fill=(130,130,130))

            lcd.LCD_ShowImage(img, 0, 0)

            # ── Input ──
            now = time.time()
            pressed = {name: GPIO.input(pin)==0 for name,pin in PINS.items()}

            for name, is_down in pressed.items():
                if is_down:
                    if name not in held: held[name] = now
                else:
                    held.pop(name, None)

            def just_pressed(name):
                return pressed.get(name) and (now - held.get(name, now)) <= 0.06

            if just_pressed("KEY3"):
                break

            if just_pressed("KEY1"):
                if running:
                    # Flask can't be stopped cleanly once started;
                    # just show stopped state but server keeps running in bg
                    running = False
                else:
                    if srv is None or not srv.is_alive():
                        srv = _ServerThread(); srv.start()
                    running = True
                time.sleep(0.25)

            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        lcd.LCD_Clear()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
