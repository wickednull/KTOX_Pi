#!/usr/bin/env python3
"""
KTOx Payload – CYBER_VOID (KTOxFliX Enhanced)
===============================================
Port 80: Movie Library with auto‑fetched posters & plot summaries
Port 8888: Data Uplink (folder/file upload)

Controls (LCD):
  KEY1   Toggle QR code (for uplink port)
  KEY3   Exit
"""

import os, sys, time, socket, logging, threading, subprocess, requests, json, re
import qrcode
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, request, send_from_directory, abort, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
from PIL import Image as PILImage, ImageDraw, ImageFont

# Ensure KTOx pathing
KTOX_ROOT = "/root/KTOx"
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ── Configuration ─────────────────────────────────────────────────────────────
VIDEO_DIR  = "/root/Videos"
THUMB_DIR  = "/root/Videos/thumbnails"
POSTER_DIR = "/root/Videos/posters"
METADATA_FILE = "/root/Videos/metadata.json"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}

os.makedirs(THUMB_DIR, exist_ok=True)
os.makedirs(POSTER_DIR, exist_ok=True)

app_ui = Flask("Library")
app_up = Flask("Uplink")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ── Google Scraper (robust) ───────────────────────────────────────────────────
def find_poster_url(title: str) -> str | None:
    """Search Google Images for a high‑quality poster URL."""
    try:
        query = f"{title} movie poster"
        search_url = f"https://www.google.com/search?q={query}&tbm=isch"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
        }
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tags = soup.find_all('script')
        for script in script_tags:
            if script.string and 'AF_initDataCallback' in script.string:
                match = re.search(r'AF_initDataCallback\({key: \'ds:1\', hash: \'\\d+\', data:(.*), sideChannel: {}}\);', script.string)
                if match:
                    data_str = match.group(1)
                    data = json.loads(data_str)
                    # Traverse the nested structure
                    image_results = data[56][1][0][0][1][0]
                    for image_data in image_results:
                        if image_data[0][0][1]:
                            image_url = image_data[0][0][1][3][0]
                            image_height = image_data[0][0][1][2]
                            image_width = image_data[0][0][1][1]
                            if image_height > 500 and image_width > 200:
                                return image_url
    except Exception as e:
        print(f"Poster scrape error for {title}: {e}")
    return None

def find_movie_details(title: str) -> str | None:
    """Search Google for plot summary."""
    try:
        query = f"{title} movie"
        search_url = f"https://www.google.com/search?q={query}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
        }
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        plot_div = soup.find('div', {'data-attrid': 'description'})
        if plot_div:
            return plot_div.get_text()
    except Exception as e:
        print(f"Plot scrape error for {title}: {e}")
    return None

def download_poster(url, save_path):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(r.content)
            return True
    except:
        pass
    return False

def load_metadata():
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_metadata(meta):
    with open(METADATA_FILE, 'w') as f:
        json.dump(meta, f, indent=2)

def ensure_poster(video_name, title):
    """Return local poster path, downloading if missing."""
    base = os.path.splitext(video_name)[0]
    poster_path = os.path.join(POSTER_DIR, base + ".jpg")
    if os.path.exists(poster_path):
        return poster_path
    # Try to fetch from Google
    url = find_poster_url(title)
    if url and download_poster(url, poster_path):
        return poster_path
    # Fallback: generate a placeholder
    img = PILImage.new('RGB', (200, 300), color=(20, 20, 40))
    img.save(poster_path)
    return poster_path

# ── Background metadata fetcher ───────────────────────────────────────────────
def background_metadata_updater():
    """Scan video directory, fetch missing posters/plots in background."""
    while True:
        time.sleep(5)  # wait for server to start
        meta = load_metadata()
        changed = False
        for root, dirs, files in os.walk(VIDEO_DIR):
            for f in files:
                if f.lower().endswith(VIDEO_EXTS):
                    rel_path = os.path.relpath(os.path.join(root, f), VIDEO_DIR)
                    if rel_path not in meta:
                        title = os.path.splitext(f)[0].replace('_', ' ').replace('.', ' ')
                        poster_local = ensure_poster(rel_path, title)
                        plot = find_movie_details(title) or "No description available."
                        meta[rel_path] = {
                            'title': title,
                            'poster': poster_local,
                            'plot': plot
                        }
                        changed = True
                        time.sleep(2)  # be gentle with Google
        if changed:
            save_metadata(meta)
        time.sleep(300)  # rescan every 5 minutes

# ── Routes (Library) ─────────────────────────────────────────────────────────
CYBER_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    :root { --red: #ff0000; --cyan: #00f3ff; --bg: #050505; }
    body { background: var(--bg); color: #ccc; font-family: 'Share Tech Mono', monospace; margin:0; }
    nav { padding: 15px; background: #000; border-bottom: 2px solid var(--red); display: flex; justify-content: space-between; }
    .container { padding: 20px; max-width: 600px; margin: auto; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 20px; padding: 20px; }
    .movie-card { background: #111; border: 1px solid #2b0000; text-decoration: none; color: inherit; transition: 0.2s; }
    .movie-card:hover { transform: scale(1.02); border-color: var(--cyan); }
    .movie-card img { width: 100%; aspect-ratio: 2/3; object-fit: cover; filter: brightness(0.85); }
    .movie-card div { padding: 8px; font-size: 11px; color: #aaa; text-align: center; }
    .detail { max-width: 800px; margin: 30px auto; background: #0a0a0a; border: 1px solid #333; padding: 20px; }
    .detail img { float: left; width: 200px; margin-right: 20px; border: 1px solid var(--cyan); }
    .detail h2 { color: var(--red); }
    .detail p { line-height: 1.4; }
</style>
"""

@app_ui.route('/')
def index():
    meta = load_metadata()
    videos = []
    for root, dirs, files in os.walk(VIDEO_DIR):
        for f in files:
            if f.lower().endswith(VIDEO_EXTS):
                rel = os.path.relpath(os.path.join(root, f), VIDEO_DIR)
                poster = meta.get(rel, {}).get('poster', '')
                if poster and os.path.exists(poster):
                    poster_url = f"/poster/{rel.replace('/', '_')}.jpg"
                else:
                    poster_url = "/static/placeholder.jpg"
                videos.append({
                    'path': rel,
                    'title': meta.get(rel, {}).get('title', os.path.splitext(f)[0]),
                    'poster': poster_url
                })
    return render_template_string(CYBER_CSS + """
    <nav><div style="color:red">KTOx//CYBER_VOID</div><div style="font-size:10px;">PORT_80</div></nav>
    <div class="grid">
        {% for v in videos %}
        <a href="/detail/{{ v.path }}" class="movie-card">
            <img src="{{ v.poster }}" onerror="this.src='/static/placeholder.jpg'">
            <div>{{ v.title[:30] }}</div>
        </a>
        {% endfor %}
    </div>""", videos=videos)

@app_ui.route('/detail/<path:video_path>')
def detail(video_path):
    meta = load_metadata()
    info = meta.get(video_path, {})
    title = info.get('title', os.path.splitext(os.path.basename(video_path))[0])
    plot = info.get('plot', 'No description available.')
    poster = info.get('poster', '')
    if poster and os.path.exists(poster):
        poster_url = f"/poster/{video_path.replace('/', '_')}.jpg"
    else:
        poster_url = "/static/placeholder.jpg"
    return render_template_string(CYBER_CSS + """
    <nav><a href="/" style="color:cyan; text-decoration:none;">← BACK</a><div>KTOx//DETAIL</div></nav>
    <div class="detail">
        <img src="{{ poster }}">
        <h2>{{ title }}</h2>
        <p>{{ plot }}</p>
        <video controls style="width:100%; margin-top:20px;">
            <source src="/stream/{{ video_path }}">
        </video>
    </div>""", title=title, plot=plot, poster=poster_url, video_path=video_path)

@app_ui.route('/poster/<f>')
def poster(f):
    # Convert back to original path
    original = f.replace('_', '/') if '_' in f else f
    poster_path = os.path.join(POSTER_DIR, original + ".jpg")
    if os.path.exists(poster_path):
        return send_from_directory(POSTER_DIR, original + ".jpg")
    else:
        return send_from_directory("/root/KTOx/static", "placeholder.jpg")

@app_ui.route('/stream/<path:video_path>')
def stream(video_path):
    return send_from_directory(VIDEO_DIR, video_path)

# ── Uplink routes (unchanged) ────────────────────────────────────────────────
@app_up.route('/')
def uplink_home():
    return render_template_string("""
    <style>
    body { background: black; color: #0f0; font-family: monospace; padding: 20px; }
    input, button { background: #111; border: 1px solid #0f0; color: #0f0; padding: 8px; }
    .container { max-width: 600px; margin: auto; }
    </style>
    <div class="container">
        <h1>KTOx DATA UPLINK</h1>
        <form method="POST" action="/upload" enctype="multipart/form-data">
            <label>Target subdirectory (optional):</label><br>
            <input type="text" name="subdir" style="width:100%"><br><br>
            <label>Files:</label><br>
            <input type="file" name="files" multiple><br><br>
            <label>Folder:</label><br>
            <input type="file" name="files" multiple webkitdirectory><br><br>
            <button type="submit">UPLOAD</button>
        </form>
    </div>""")

@app_up.route('/upload', methods=['POST'])
def upload():
    target = os.path.join(VIDEO_DIR, request.form.get('subdir', '').strip())
    os.makedirs(target, exist_ok=True)
    files = request.files.getlist('files')
    for f in files:
        if f.filename:
            path = os.path.join(target, secure_filename(f.filename))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
    return redirect(url_for('uplink_home'))

# ── LCD & main ────────────────────────────────────────────────────────────────
def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"

def main():
    # Start background metadata updater
    threading.Thread(target=background_metadata_updater, daemon=True).start()
    # Start Flask apps
    threading.Thread(target=lambda: app_ui.run(host="0.0.0.0", port=80), daemon=True).start()
    threading.Thread(target=lambda: app_up.run(host="0.0.0.0", port=8888), daemon=True).start()

    if not HAS_HW:
        print("Server running. LCD not available.")
        while True: time.sleep(1)
        return

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    lcd = LCD_1in44.LCD(); lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT); lcd.LCD_Clear()
    ip = _get_ip()
    show_qr = False
    held = {}
    try:
        while True:
            now = time.time()
            img = PILImage.new("RGB", (128,128), "black")
            draw = ImageDraw.Draw(img)
            if show_qr:
                qr = qrcode.QRCode(box_size=3, border=2)
                qr.add_data(f"http://{ip}:8888")
                qr_img = qr.make_image().convert("RGB").resize((128,128))
                img.paste(qr_img, (0,0))
            else:
                draw.rectangle([(0,0),(128,18)], fill=(120,0,0))
                draw.text((4,3), "CYBER_VOID", fill="black", font=ImageFont.load_default())
                draw.text((4,30), f"IP: {ip}", fill="white")
                draw.text((4,50), "PORT 80: LIB", fill="cyan")
                draw.text((4,65), "PORT 8888: UP", fill="red")
                draw.text((4,113), "K1:QR  K3:EXIT", fill=(150,150,150))
            lcd.LCD_ShowImage(img, 0, 0)

            pressed = {name: GPIO.input(pin)==0 for name,pin in PINS.items()}
            for name, is_down in pressed.items():
                if is_down:
                    if name not in held: held[name] = now
                else: held.pop(name, None)
            if pressed.get("KEY3") and (now - held.get("KEY3", now)) <= 0.05:
                break
            if pressed.get("KEY1") and (now - held.get("KEY1", now)) <= 0.05:
                show_qr = not show_qr
                time.sleep(0.3)
            time.sleep(0.1)
    finally:
        lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
