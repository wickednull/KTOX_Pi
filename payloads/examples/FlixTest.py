#!/usr/bin/env python3
"""
KTOx Payload – KTOxFliX
================================
- Works without metadata (uses filename as title)
- Placeholder posters
- Cyberpunk UI, separate categories
"""

import os, sys, time, socket, threading, json, hashlib
from flask import Flask, render_template_string, send_from_directory, request, redirect, url_for
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
VIDEO_DIR = "/root/Videos"
POSTER_DIR = "/root/KTOx/static/posters"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(POSTER_DIR, exist_ok=True)
os.makedirs("/root/KTOx/static", exist_ok=True)

app_lib = Flask("Library")
app_up = Flask("Uplink")

# ----------------------------------------------------------------------
# Simple title from filename (no external metadata)
# ----------------------------------------------------------------------
def clean_title(filename):
    name = os.path.splitext(filename)[0]
    # Replace underscores, dots, dashes with spaces
    name = name.replace('_', ' ').replace('.', ' ').replace('-', ' ')
    # Remove common tags like 1080p, x264, etc.
    import re
    name = re.sub(r'\b(1080p|720p|4k|x264|x265|hevc|aac|mp3|web-dl|webrip|bluray|hdtv)\b', '', name, flags=re.IGNORECASE)
    # Clean up extra spaces
    name = ' '.join(name.split())
    return name.capitalize()

def get_or_create_placeholder(title, media_type):
    """Return a placeholder poster path (no download)."""
    safe = hashlib.md5(f"{media_type}:{title}".encode()).hexdigest()
    local_path = os.path.join(POSTER_DIR, f"{safe}.jpg")
    web_path = f"/static/posters/{safe}.jpg"
    if not os.path.exists(local_path):
        try:
            from PIL import Image as PILImage
            img = PILImage.new('RGB', (200,300), color=(30,30,50))
            # Add text on placeholder
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((20, 140), title[:15], fill=(100,100,150))
            img.save(local_path)
        except:
            # If PIL fails, just create empty file
            open(local_path, 'w').close()
    return web_path

# ----------------------------------------------------------------------
# Scan library – separate movies and series
# ----------------------------------------------------------------------
def scan_library():
    movies = []
    series = []
    for entry in sorted(os.listdir(VIDEO_DIR)):
        full = os.path.join(VIDEO_DIR, entry)
        if os.path.isdir(full):
            episodes = [f for f in os.listdir(full) if f.lower().endswith(VIDEO_EXTS)]
            if episodes:
                title = clean_title(entry)
                poster = get_or_create_placeholder(title, 'series')
                series.append({
                    'type': 'series',
                    'name': title,
                    'plot': 'TV Series',
                    'poster': poster,
                    'path': entry,
                    'episodes': episodes
                })
        elif entry.lower().endswith(VIDEO_EXTS):
            title = clean_title(entry)
            poster = get_or_create_placeholder(title, 'movie')
            movies.append({
                'type': 'movie',
                'name': title,
                'plot': 'Movie',
                'poster': poster,
                'year': '',
                'path': entry
            })
    return movies, series

# ----------------------------------------------------------------------
# Web UI Templates (no footer)
# ----------------------------------------------------------------------
LIBRARY_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>KTOxFLIX</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #000000;
            background-image: radial-gradient(rgba(255, 0, 0, 0.1) 1px, transparent 1px);
            background-size: 40px 40px;
            font-family: 'Share Tech Mono', 'Courier New', monospace;
            color: #ff3333;
            min-height: 100vh;
        }
        .glitch {
            position: relative;
            text-shadow: 0.05em 0 0 rgba(255,0,0,0.75), -0.05em -0.025em 0 rgba(0,255,255,0.75);
            animation: glitch 0.3s infinite;
        }
        @keyframes glitch {
            0% { text-shadow: 0.05em 0 0 rgba(255,0,0,0.75), -0.05em -0.025em 0 rgba(0,255,255,0.75); }
            50% { text-shadow: -0.05em -0.025em 0 rgba(255,0,0,0.75), 0.025em 0.05em 0 rgba(0,255,255,0.75); }
            100% { text-shadow: 0.025em 0.05em 0 rgba(255,0,0,0.75), 0.05em -0.05em 0 rgba(0,255,255,0.75); }
        }
        nav {
            background: #0a0000;
            border-bottom: 2px solid #ff0000;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            flex-wrap: wrap;
            box-shadow: 0 0 15px rgba(255,0,0,0.3);
        }
        .logo {
            font-size: 1.8rem;
            font-weight: bold;
            letter-spacing: 4px;
        }
        .logo span { color: #00ffff; }
        .port-badge {
            font-size: 0.8rem;
            border: 1px solid #ff0000;
            padding: 4px 12px;
            border-radius: 20px;
            background: rgba(255,0,0,0.1);
        }
        .section {
            padding: 20px 30px 0 30px;
        }
        .section h2 {
            color: #ff0000;
            border-left: 4px solid #ff0000;
            padding-left: 15px;
            margin-bottom: 20px;
            font-size: 1.3rem;
            text-transform: uppercase;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 25px;
            padding: 0 30px 30px 30px;
        }
        .card {
            background: #0a0505;
            border: 1px solid #330000;
            border-radius: 8px;
            transition: all 0.2s ease;
            text-decoration: none;
            color: inherit;
            display: block;
            position: relative;
            overflow: hidden;
        }
        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,0,0,0.2), transparent);
            transition: left 0.5s;
            z-index: 1;
        }
        .card:hover::before { left: 100%; }
        .card:hover {
            transform: translateY(-5px);
            border-color: #ff0000;
            box-shadow: 0 0 20px rgba(255,0,0,0.4);
        }
        .card img {
            width: 100%;
            aspect-ratio: 2/3;
            object-fit: cover;
            border-bottom: 1px solid #330000;
        }
        .card-title {
            padding: 12px;
            font-size: 0.8rem;
            text-align: center;
            text-transform: uppercase;
            letter-spacing: 1px;
            background: #050000;
        }
        ::-webkit-scrollbar { width: 6px; background: #111; }
        ::-webkit-scrollbar-thumb { background: #ff0000; border-radius: 3px; }
        @media (max-width: 600px) {
            .grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 15px; padding: 0 15px 15px 15px; }
            .section { padding: 15px 15px 0 15px; }
            .logo { font-size: 1.2rem; }
        }
    </style>
</head>
<body>
    <nav>
        <div class="logo glitch">KTOx<span>FLIX</span></div>
        <div class="port-badge">PORT 80 // ACTIVE</div>
    </nav>
    {% if movies %}
    <div class="section">
        <h2>🎬 MOVIES</h2>
    </div>
    <div class="grid">
        {% for item in movies %}
        <a href="/detail/movie/{{ item.path }}" class="card">
            <img src="{{ item.poster }}" onerror="this.src='/static/placeholder.jpg'">
            <div class="card-title">{{ item.name[:35] }}</div>
        </a>
        {% endfor %}
    </div>
    {% endif %}
    {% if series %}
    <div class="section">
        <h2>📺 TV SERIES</h2>
    </div>
    <div class="grid">
        {% for item in series %}
        <a href="/detail/series/{{ item.path }}" class="card">
            <img src="{{ item.poster }}" onerror="this.src='/static/placeholder.jpg'">
            <div class="card-title">{{ item.name[:35] }}</div>
        </a>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

SERIES_DETAIL = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ series.name }} // KTOxFLIX</title>
    <style>
        body {
            background: #000;
            font-family: 'Share Tech Mono', monospace;
            color: #ff4444;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 20px auto;
            background: #0a0505;
            border: 1px solid #ff0000;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 0 30px rgba(255,0,0,0.2);
        }
        .poster {
            float: left;
            width: 180px;
            margin-right: 25px;
            border: 2px solid #ff0000;
            box-shadow: 5px 5px 15px rgba(0,0,0,0.8);
        }
        h2 {
            font-size: 1.8rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            text-shadow: 0 0 5px #ff0000;
            margin-top: 0;
        }
        .episode-list {
            clear: both;
            margin-top: 30px;
            border-top: 1px solid #330000;
            padding-top: 20px;
        }
        .episode {
            background: #1a0505;
            margin: 8px 0;
            padding: 10px;
            border-left: 4px solid #ff0000;
            transition: 0.2s;
        }
        .episode:hover {
            background: #2a0a0a;
            transform: translateX(5px);
        }
        .episode a {
            color: #ff8888;
            text-decoration: none;
            font-family: monospace;
        }
        .back {
            display: inline-block;
            margin-top: 30px;
            color: #ff0000;
            text-decoration: none;
            border: 1px solid #ff0000;
            padding: 8px 20px;
            border-radius: 30px;
            transition: 0.2s;
        }
        .back:hover {
            background: #ff0000;
            color: #000;
            box-shadow: 0 0 15px #ff0000;
        }
        @media (max-width: 600px) {
            .poster { float: none; display: block; margin: 0 auto 20px; width: 140px; }
            h2 { text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        {% if poster %}<img class="poster" src="{{ poster }}">{% endif %}
        <h2>{{ series.name }}</h2>
        <div class="episode-list">
            <h3 style="color:#ff0000;">▶ EPISODES</h3>
            {% for ep in episodes %}
            <div class="episode"><a href="/play/{{ series.path }}/{{ ep }}">⚡ {{ ep }}</a></div>
            {% endfor %}
        </div>
        <div style="text-align: center;"><a href="/" class="back">⏎ RETURN TO LIBRARY</a></div>
    </div>
</body>
</html>
"""

MOVIE_DETAIL = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ movie.name }} // KTOxFLIX</title>
    <style>
        body {
            background: #000;
            font-family: 'Share Tech Mono', monospace;
            color: #ff4444;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 20px auto;
            background: #0a0505;
            border: 1px solid #ff0000;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 0 30px rgba(255,0,0,0.2);
        }
        .poster {
            float: left;
            width: 180px;
            margin-right: 25px;
            border: 2px solid #ff0000;
            box-shadow: 5px 5px 15px rgba(0,0,0,0.8);
        }
        h2 {
            font-size: 1.8rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            text-shadow: 0 0 5px #ff0000;
            margin-top: 0;
        }
        video {
            width: 100%;
            margin-top: 25px;
            border: 1px solid #ff0000;
            border-radius: 8px;
        }
        .back {
            display: inline-block;
            margin-top: 30px;
            color: #ff0000;
            text-decoration: none;
            border: 1px solid #ff0000;
            padding: 8px 20px;
            border-radius: 30px;
            transition: 0.2s;
        }
        .back:hover {
            background: #ff0000;
            color: #000;
            box-shadow: 0 0 15px #ff0000;
        }
        @media (max-width: 600px) {
            .poster { float: none; display: block; margin: 0 auto 20px; width: 140px; }
            h2 { text-align: center; }
        }
    </style>
</head>
<body>
    <div class="container">
        {% if poster %}<img class="poster" src="{{ poster }}">{% endif %}
        <h2>{{ movie.name }}</h2>
        <video controls autoplay>
            <source src="/stream/{{ movie.path }}" type="video/mp4">
        </video>
        <div style="text-align: center;"><a href="/" class="back">⏎ RETURN TO LIBRARY</a></div>
    </div>
</body>
</html>
"""

PLAYER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ episode }} // KTOxFLIX</title>
    <style>
        body {
            background: #000;
            font-family: 'Share Tech Mono', monospace;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 20px auto;
            background: #0a0505;
            border: 1px solid #ff0000;
            border-radius: 12px;
            padding: 25px;
            text-align: center;
        }
        h2 {
            color: #ff0000;
            margin-bottom: 20px;
        }
        video {
            width: 100%;
            border: 1px solid #ff0000;
            border-radius: 8px;
        }
        .back {
            display: inline-block;
            margin-top: 30px;
            color: #ff0000;
            text-decoration: none;
            border: 1px solid #ff0000;
            padding: 8px 20px;
            border-radius: 30px;
            transition: 0.2s;
        }
        .back:hover {
            background: #ff0000;
            color: #000;
            box-shadow: 0 0 15px #ff0000;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>▶ {{ episode }}</h2>
        <video controls autoplay>
            <source src="/stream/{{ series_path }}/{{ episode }}" type="video/mp4">
        </video>
        <br>
        <a href="/detail/series/{{ series_path }}" class="back">⏎ BACK TO EPISODES</a>
    </div>
</body>
</html>
"""

UPLINK_HTML = """
<!DOCTYPE html>
<html>
<head><title>KTOx // DATA UPLINK</title>
<style>
    body {
        background: #000;
        color: #0f0;
        font-family: 'Courier New', monospace;
        padding: 30px;
    }
    .container {
        max-width: 600px;
        margin: auto;
        border: 1px solid #0f0;
        padding: 25px;
        border-radius: 12px;
        background: #050505;
        box-shadow: 0 0 20px #0f0;
    }
    h1 { color: #0f0; text-shadow: 0 0 3px #0f0; }
    input, button {
        background: #111;
        border: 1px solid #0f0;
        color: #0f0;
        padding: 10px;
        width: 100%;
        margin-bottom: 15px;
        font-family: monospace;
    }
    button { cursor: pointer; width: auto; }
    button:hover { background: #0f0; color: #000; }
</style>
</head>
<body>
<div class="container">
    <h1>⤒ KTOx DATA UPLINK ⤓</h1>
    <form method="POST" action="/upload" enctype="multipart/form-data">
        <label>Subdirectory (optional):</label>
        <input type="text" name="subdir">
        <label>Files:</label>
        <input type="file" name="files" multiple>
        <label>Folder:</label>
        <input type="file" name="files" multiple webkitdirectory>
        <button type="submit">UPLOAD</button>
    </form>
</div>
</body>
</html>
"""

# ----------------------------------------------------------------------
# Flask routes
# ----------------------------------------------------------------------
@app_lib.route('/')
def library():
    movies, series = scan_library()
    return render_template_string(LIBRARY_HTML, movies=movies, series=series)

@app_lib.route('/detail/series/<path:series_path>')
def series_detail(series_path):
    full_path = os.path.join(VIDEO_DIR, series_path)
    episodes = []
    if os.path.isdir(full_path):
        episodes = sorted([f for f in os.listdir(full_path) if f.lower().endswith(VIDEO_EXTS)])
    title = clean_title(series_path)
    poster = get_or_create_placeholder(title, 'series')
    return render_template_string(SERIES_DETAIL,
        series={'name': title, 'path': series_path},
        poster=poster,
        episodes=episodes
    )

@app_lib.route('/detail/movie/<path:movie_path>')
def movie_detail(movie_path):
    name = clean_title(movie_path)
    poster = get_or_create_placeholder(name, 'movie')
    return render_template_string(MOVIE_DETAIL,
        movie={'name': name, 'path': movie_path, 'poster': poster}
    )

@app_lib.route('/play/<path:series_path>/<path:episode>')
def play_episode(series_path, episode):
    return render_template_string(PLAYER_HTML,
        episode=episode,
        series_path=series_path
    )

@app_lib.route('/stream/<path:video_path>')
def stream(video_path):
    return send_from_directory(VIDEO_DIR, video_path)

@app_lib.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory("/root/KTOx/static", filename)

@app_up.route('/')
def uplink():
    return UPLINK_HTML

@app_up.route('/upload', methods=['POST'])
def upload():
    sub = request.form.get('subdir', '').strip()
    target = os.path.join(VIDEO_DIR, sub)
    os.makedirs(target, exist_ok=True)
    for f in request.files.getlist('files'):
        if f.filename:
            path = os.path.join(target, secure_filename(f.filename))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
    return redirect(url_for('uplink'))

# ----------------------------------------------------------------------
# LCD and main thread
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
    app_lib.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)

def run_uplink():
    app_up.run(host='0.0.0.0', port=8888, debug=False, use_reloader=False)

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

    ip = get_ip()
    show_qr = False
    held = {}

    threading.Thread(target=run_library, daemon=True).start()
    threading.Thread(target=run_uplink, daemon=True).start()

    try:
        while True:
            now = time.time()
            img = Image.new("RGB", (128,128), "black")
            draw = ImageDraw.Draw(img)

            if show_qr:
                import qrcode
                qr = qrcode.QRCode(box_size=3, border=2)
                qr.add_data(f"http://{ip}:8888")
                qr_img = qr.make_image().convert("RGB").resize((128,128))
                img.paste(qr_img, (0,0))
            else:
                draw.rectangle([(0,0),(128,18)], fill=(120,0,0))
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",9)
                except:
                    font = ImageFont.load_default()
                draw.text((4,3), "KTOxFLIX", fill="black", font=font)
                draw.text((4,30), f"IP: {ip}", fill="white", font=font)
                draw.text((4,50), "PORT 80: LIB", fill="cyan", font=font)
                draw.text((4,65), "PORT 8888: UP", fill="red", font=font)
                draw.text((4,113), "K1:QR  K3:EXIT", fill=(150,150,150), font=font)

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

            time.sleep(0.1)
    finally:
        lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    # Create placeholder image if missing
    placeholder = "/root/KTOx/static/placeholder.jpg"
    if not os.path.exists(placeholder):
        try:
            from PIL import Image as PILImage
            img = PILImage.new('RGB', (200,300), color=(30,30,50))
            img.save(placeholder)
        except:
            pass
    print("Starting KTOxFliX (clean version)...")
    main()
