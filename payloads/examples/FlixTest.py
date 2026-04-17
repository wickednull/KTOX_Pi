#!/usr/bin/env python3
"""
KTOx Payload – KTOxFliX (Seasons + System Stats + QR)
======================================================
- Movies, TV Series with season folders
- Settings: OMDb API key, online metadata, local posters
- Uplink on port 8888 (hidden from LCD)
- LCD: IP, CPU load, CPU temp, RAM usage, QR for library (KEY1)
"""

import os, sys, time, socket, threading, json, hashlib, re, requests
from flask import Flask, render_template_string, send_from_directory, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename

# Try to import qrcode; if missing, install it
try:
    import qrcode
except ImportError:
    os.system("pip install qrcode pillow")
    import qrcode

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
SETTINGS_DIR = "/root/KTOx/loot/KTOxFliX"
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(POSTER_DIR, exist_ok=True)
os.makedirs("/root/KTOx/static", exist_ok=True)
os.makedirs(SETTINGS_DIR, exist_ok=True)

app_lib = Flask("Library")
app_up = Flask("Uplink")

# ----------------------------------------------------------------------
# Settings management
# ----------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "omdb_api_key": "",
    "use_online_metadata": True,
    "use_local_posters": True
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            saved = json.load(f)
            return {**DEFAULT_SETTINGS, **saved}
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

settings = load_settings()

# ----------------------------------------------------------------------
# Metadata helpers
# ----------------------------------------------------------------------
def clean_title(filename):
    name = os.path.splitext(filename)[0]
    name = name.replace('_', ' ').replace('.', ' ').replace('-', ' ')
    name = re.sub(r'\b(1080p|720p|4k|x264|x265|hevc|aac|mp3|web-dl|webrip|bluray|hdtv)\b', '', name, flags=re.IGNORECASE)
    name = ' '.join(name.split())
    return name.capitalize()

def get_tvmaze_series(title):
    if not settings.get("use_online_metadata"):
        return None
    try:
        url = f"https://api.tvmaze.com/singlesearch/shows?q={title}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            summary = data.get('summary', '')
            if summary:
                summary = re.sub(r'<[^>]+>', '', summary)
            return {
                'title': data.get('name'),
                'plot': summary[:200] or 'No description',
                'poster': data.get('image', {}).get('original'),
                'year': data.get('premiered', '')[:4]
            }
    except:
        pass
    return None

def get_omdb_movie(title):
    api_key = settings.get("omdb_api_key", "")
    if not api_key or not settings.get("use_online_metadata"):
        return None
    try:
        url = f"http://www.omdbapi.com/?t={title}&apikey={api_key}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get('Response') == 'True':
                return {
                    'title': data.get('Title'),
                    'plot': data.get('Plot', 'No description'),
                    'poster': data.get('Poster'),
                    'year': data.get('Year', '')
                }
    except:
        pass
    return None

def download_poster(url, identifier):
    safe = hashlib.md5(identifier.encode()).hexdigest()
    dest = os.path.join(POSTER_DIR, f"{safe}.jpg")
    if not os.path.exists(dest):
        try:
            img_data = requests.get(url, timeout=10).content
            with open(dest, 'wb') as f:
                f.write(img_data)
        except:
            return None
    return f"/static/posters/{safe}.jpg"

def get_or_create_placeholder(title, media_type):
    safe = hashlib.md5(f"{media_type}:{title}".encode()).hexdigest()
    local_path = os.path.join(POSTER_DIR, f"{safe}.jpg")
    web_path = f"/static/posters/{safe}.jpg"
    if not os.path.exists(local_path):
        try:
            from PIL import Image as PILImage, ImageDraw as PILDraw
            img = PILImage.new('RGB', (200,300), color=(30,30,50))
            draw = PILDraw.Draw(img)
            draw.text((20, 140), title[:15], fill=(100,100,150))
            img.save(local_path)
        except:
            open(local_path, 'w').close()
    return web_path

def get_metadata_for_item(entry, full_path, media_type):
    title = clean_title(entry)
    info = {'title': title, 'plot': 'No description', 'poster_url': None, 'year': ''}
    if settings.get("use_local_posters"):
        for ext in ['.jpg', '.jpeg', '.png']:
            poster_file = os.path.join(full_path, 'poster' + ext)
            if os.path.exists(poster_file):
                safe = hashlib.md5(f"{media_type}:{entry}".encode()).hexdigest()
                dest = os.path.join(POSTER_DIR, f"{safe}.jpg")
                if not os.path.exists(dest):
                    try:
                        from PIL import Image as PILImage
                        img = PILImage.open(poster_file)
                        img.save(dest)
                    except:
                        pass
                info['poster_url'] = f"/static/posters/{safe}.jpg"
                return info
    if settings.get("use_online_metadata"):
        if media_type == 'series':
            tvmaze = get_tvmaze_series(title)
            if tvmaze:
                info['title'] = tvmaze['title']
                info['plot'] = tvmaze['plot']
                if tvmaze['poster']:
                    poster_url = download_poster(tvmaze['poster'], f"series:{entry}")
                    if poster_url:
                        info['poster_url'] = poster_url
                        return info
        else:
            omdb = get_omdb_movie(title)
            if omdb:
                info['title'] = omdb['title']
                info['plot'] = omdb['plot']
                info['year'] = omdb['year']
                if omdb['poster'] and omdb['poster'] != 'N/A':
                    poster_url = download_poster(omdb['poster'], f"movie:{title}")
                    if poster_url:
                        info['poster_url'] = poster_url
                        return info
    info['poster_url'] = get_or_create_placeholder(title, media_type)
    return info

def clear_poster_cache():
    for f in os.listdir(POSTER_DIR):
        os.remove(os.path.join(POSTER_DIR, f))

# ----------------------------------------------------------------------
# Scan library with season detection
# ----------------------------------------------------------------------
def scan_series_structure(path):
    seasons = []
    items = os.listdir(path)
    subdirs = [i for i in items if os.path.isdir(os.path.join(path, i))]
    season_folders = [s for s in subdirs if re.search(r'(season|saison|stagione|temporada|第[0-9]+季|[0-9]+[ ]*季)', s, re.IGNORECASE) or s.lower().startswith('season')]
    if season_folders:
        for sf in sorted(season_folders):
            sf_path = os.path.join(path, sf)
            episodes = [f for f in os.listdir(sf_path) if f.lower().endswith(VIDEO_EXTS)]
            if episodes:
                seasons.append({
                    'name': sf,
                    'path': os.path.relpath(sf_path, VIDEO_DIR),
                    'episodes': sorted(episodes)
                })
    else:
        episodes = [f for f in items if f.lower().endswith(VIDEO_EXTS)]
        if episodes:
            seasons.append({
                'name': "Season 1",
                'path': os.path.relpath(path, VIDEO_DIR),
                'episodes': sorted(episodes)
            })
    return seasons

def scan_library():
    movies = []
    series = []
    for entry in sorted(os.listdir(VIDEO_DIR)):
        full = os.path.join(VIDEO_DIR, entry)
        if os.path.isdir(full):
            seasons = scan_series_structure(full)
            if seasons:
                meta = get_metadata_for_item(entry, full, 'series')
                series.append({
                    'name': meta['title'],
                    'poster': meta['poster_url'],
                    'path': entry,
                    'seasons': seasons
                })
        elif entry.lower().endswith(VIDEO_EXTS):
            meta = get_metadata_for_item(entry, full, 'movie')
            movies.append({
                'name': meta['title'],
                'poster': meta['poster_url'],
                'path': entry,
                'year': meta['year']
            })
    return movies, series

# ----------------------------------------------------------------------
# Web UI Templates (full, included)
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
        .tabs {
            display: flex;
            border-bottom: 1px solid #330000;
            margin: 0 30px;
        }
        .tab {
            padding: 12px 24px;
            cursor: pointer;
            font-size: 1rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            transition: 0.2s;
            border-bottom: 2px solid transparent;
        }
        .tab.active {
            color: #ff0000;
            border-bottom: 2px solid #ff0000;
            text-shadow: 0 0 5px rgba(255,0,0,0.5);
        }
        .tab:hover {
            color: #ff8888;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 25px;
            padding: 30px;
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
        .section {
            display: none;
        }
        .section.active {
            display: block;
        }
        .settings-panel {
            background: #0a0505;
            border: 1px solid #ff0000;
            border-radius: 12px;
            padding: 25px;
            max-width: 500px;
            margin: 30px auto;
        }
        .settings-panel label {
            display: block;
            margin: 15px 0 5px;
            color: #ff8888;
        }
        .settings-panel input, .settings-panel select {
            background: #1a1a1a;
            border: 1px solid #ff0000;
            color: #0f0;
            padding: 8px;
            width: 100%;
            font-family: monospace;
        }
        .settings-panel button {
            background: #2a0a0a;
            border: 1px solid #ff0000;
            color: #ff0000;
            padding: 8px 16px;
            cursor: pointer;
            margin-top: 15px;
            font-family: monospace;
        }
        .settings-panel button:hover {
            background: #ff0000;
            color: #000;
        }
        .status-msg {
            margin-top: 10px;
            color: #ffcc00;
        }
        ::-webkit-scrollbar { width: 6px; background: #111; }
        ::-webkit-scrollbar-thumb { background: #ff0000; border-radius: 3px; }
        @media (max-width: 600px) {
            .grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 15px; padding: 15px; }
            .tabs { margin: 0 15px; }
            .tab { padding: 8px 16px; font-size: 0.8rem; }
            .logo { font-size: 1.2rem; }
        }
    </style>
</head>
<body>
    <nav>
        <div class="logo glitch">KTOx<span>FLIX</span></div>
        <div class="port-badge">PORT 80 // ACTIVE</div>
    </nav>
    <div class="tabs">
        <div class="tab active" data-tab="movies">🎬 MOVIES</div>
        <div class="tab" data-tab="series">📺 TV SERIES</div>
        <div class="tab" data-tab="settings">⚙️ SETTINGS</div>
    </div>
    <div id="movies-section" class="section active">
        <div class="grid">
            {% for item in movies %}
            <a href="/detail/movie/{{ item.path }}" class="card">
                <img src="{{ item.poster }}" onerror="this.src='/static/placeholder.jpg'">
                <div class="card-title">{{ item.name[:35] }}</div>
            </a>
            {% endfor %}
            {% if not movies %}
            <div style="color:#666; text-align:center; padding:40px;">No movies found. Upload via port 8888.</div>
            {% endif %}
        </div>
    </div>
    <div id="series-section" class="section">
        <div class="grid">
            {% for item in series %}
            <a href="/detail/series/{{ item.path }}" class="card">
                <img src="{{ item.poster }}" onerror="this.src='/static/placeholder.jpg'">
                <div class="card-title">{{ item.name[:35] }}</div>
            </a>
            {% endfor %}
            {% if not series %}
            <div style="color:#666; text-align:center; padding:40px;">No TV series found. Create folders inside /root/Videos.</div>
            {% endif %}
        </div>
    </div>
    <div id="settings-section" class="section">
        <div class="settings-panel">
            <h2 style="color:#ff0000;">⚙️ SETTINGS</h2>
            <label>OMDb API Key (for movies)</label>
            <input type="text" id="omdb_key" placeholder="Enter your OMDb API key" value="{{ omdb_key }}">
            <label>Use Online Metadata (TVMaze + OMDb)</label>
            <input type="checkbox" id="online_meta" {% if use_online %}checked{% endif %}>
            <label>Use Local Posters (poster.jpg in folder)</label>
            <input type="checkbox" id="local_posters" {% if use_local %}checked{% endif %}>
            <button id="saveSettings">💾 SAVE SETTINGS</button>
            <button id="clearCache">🗑️ CLEAR POSTER CACHE</button>
            <div id="settingsStatus" class="status-msg"></div>
        </div>
    </div>
    <script>
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const target = tab.getAttribute('data-tab');
                document.querySelectorAll('.section').forEach(section => section.classList.remove('active'));
                document.getElementById(target + '-section').classList.add('active');
            });
        });

        document.getElementById('saveSettings').addEventListener('click', () => {
            const omdb_key = document.getElementById('omdb_key').value;
            const online_meta = document.getElementById('online_meta').checked;
            const local_posters = document.getElementById('local_posters').checked;
            fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ omdb_api_key: omdb_key, use_online_metadata: online_meta, use_local_posters: local_posters })
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('settingsStatus').innerText = data.message;
                setTimeout(() => location.reload(), 1500);
            })
            .catch(err => document.getElementById('settingsStatus').innerText = 'Error saving');
        });

        document.getElementById('clearCache').addEventListener('click', () => {
            fetch('/api/clear_cache', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                document.getElementById('settingsStatus').innerText = data.message;
            });
        });
    </script>
</body>
</html>
"""

SEASONS_LIST = """
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
        .season-list {
            clear: both;
            margin-top: 30px;
            border-top: 1px solid #330000;
            padding-top: 20px;
        }
        .season {
            background: #1a0505;
            margin: 8px 0;
            padding: 10px;
            border-left: 4px solid #ff0000;
            transition: 0.2s;
        }
        .season a {
            color: #ff8888;
            text-decoration: none;
            font-family: monospace;
            font-size: 1.2rem;
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
        <div class="season-list">
            <h3 style="color:#ff0000;">▶ SEASONS</h3>
            {% for season in seasons %}
            <div class="season"><a href="/detail/season/{{ season.path }}">⚡ {{ season.name }}</a></div>
            {% endfor %}
        </div>
        <div style="text-align: center;"><a href="/" class="back">⏎ RETURN TO LIBRARY</a></div>
    </div>
</body>
</html>
"""

EPISODE_LIST = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ season_name }} // KTOxFLIX</title>
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
        <h2>{{ series_name }} - {{ season_name }}</h2>
        <div class="episode-list">
            <h3 style="color:#ff0000;">▶ EPISODES</h3>
            {% for ep in episodes %}
            <div class="episode"><a href="/play/{{ season_path }}/{{ ep }}">⚡ {{ ep }}</a></div>
            {% endfor %}
        </div>
        <div style="text-align: center;"><a href="/detail/series/{{ series_path }}" class="back">⏎ BACK TO SEASONS</a></div>
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
            <source src="/stream/{{ season_path }}/{{ episode }}" type="video/mp4">
        </video>
        <br>
        <a href="/detail/season/{{ season_path }}" class="back">⏎ BACK TO EPISODES</a>
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
    return render_template_string(LIBRARY_HTML,
        movies=movies, series=series,
        omdb_key=settings.get("omdb_api_key", ""),
        use_online=settings.get("use_online_metadata", True),
        use_local=settings.get("use_local_posters", True)
    )

@app_lib.route('/detail/series/<path:series_path>')
def series_detail(series_path):
    full_path = os.path.join(VIDEO_DIR, series_path)
    seasons = scan_series_structure(full_path)
    if not seasons:
        return redirect('/')
    meta = get_metadata_for_item(series_path, full_path, 'series')
    return render_template_string(SEASONS_LIST,
        series={'name': meta['title'], 'path': series_path},
        poster=meta['poster_url'],
        seasons=seasons
    )

@app_lib.route('/detail/season/<path:season_path>')
def season_detail(season_path):
    full_season = os.path.join(VIDEO_DIR, season_path)
    if not os.path.isdir(full_season):
        return redirect('/')
    episodes = [f for f in os.listdir(full_season) if f.lower().endswith(VIDEO_EXTS)]
    episodes = sorted(episodes)
    series_path = os.path.dirname(season_path)
    series_full = os.path.join(VIDEO_DIR, series_path)
    meta = get_metadata_for_item(series_path, series_full, 'series')
    return render_template_string(EPISODE_LIST,
        series_name=meta['title'],
        season_name=os.path.basename(season_path),
        poster=meta['poster_url'],
        episodes=episodes,
        series_path=series_path,
        season_path=season_path
    )

@app_lib.route('/detail/movie/<path:movie_path>')
def movie_detail(movie_path):
    full_path = os.path.join(VIDEO_DIR, movie_path)
    meta = get_metadata_for_item(movie_path, full_path, 'movie')
    return render_template_string(MOVIE_DETAIL,
        movie={'name': meta['title'], 'path': movie_path, 'poster': meta['poster_url']}
    )

@app_lib.route('/play/<path:season_path>/<path:episode>')
def play_episode(season_path, episode):
    return render_template_string(PLAYER_HTML,
        episode=episode,
        season_path=season_path
    )

@app_lib.route('/stream/<path:video_path>')
def stream(video_path):
    return send_from_directory(VIDEO_DIR, video_path)

@app_lib.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory("/root/KTOx/static", filename)

@app_lib.route('/api/settings', methods=['POST'])
def api_settings():
    data = request.json
    settings['omdb_api_key'] = data.get('omdb_api_key', '')
    settings['use_online_metadata'] = data.get('use_online_metadata', True)
    settings['use_local_posters'] = data.get('use_local_posters', True)
    save_settings(settings)
    return jsonify({'message': 'Settings saved. Reloading...'})

@app_lib.route('/api/clear_cache', methods=['POST'])
def api_clear_cache():
    clear_poster_cache()
    return jsonify({'message': 'Poster cache cleared.'})

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
# System stats helpers
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
# LCD and main thread (with QR pre‑generation)
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
    qr_image = None  # will be generated when needed

    threading.Thread(target=run_library, daemon=True).start()
    threading.Thread(target=run_uplink, daemon=True).start()

    try:
        while True:
            now = time.time()
            img = Image.new("RGB", (128,128), "#0A0000")
            draw = ImageDraw.Draw(img)

            if show_qr:
                if qr_image is None:
                    # Generate QR code only once
                    qr = qrcode.QRCode(box_size=3, border=2)
                    qr.add_data(f"http://{ip}")  # port 80
                    qr.make(fit=True)
                    qr_image = qr.make_image(fill_color="white", back_color="black").get_image().resize((128,128))
                img.paste(qr_image, (0,0))
            else:
                draw.rectangle([(0,0),(128,18)], fill=(120,0,0))
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",9)
                except:
                    font = ImageFont.load_default()
                draw.text((4,3), "KTOxFLIX", fill="black", font=font)
                draw.text((4,20), f"IP: {ip}", fill="white", font=font)
                draw.text((4,32), "PORT 80: LIBRARY", fill="cyan", font=font)
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
                if show_qr and qr_image is None:
                    qr_image = None  # force regeneration on next frame
                time.sleep(0.3)

            time.sleep(0.5)
    finally:
        lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    # Install dependencies if missing
    try:
        import requests
    except ImportError:
        os.system("pip install requests")
    placeholder = "/root/KTOx/static/placeholder.jpg"
    if not os.path.exists(placeholder):
        try:
            from PIL import Image as PILImage
            img = PILImage.new('RGB', (200,300), color=(30,30,50))
            img.save(placeholder)
        except:
            pass
    print("Starting KTOxFliX (with fixed QR)...")
    main()
