#!/usr/bin/env python3
import os, sys, time, threading, subprocess, socket, re, urllib.parse
import requests
import qrcode
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, send_from_directory, request, redirect, url_for
from werkzeug.utils import secure_filename

# Hardware imports
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# --- CONFIGURATION ---
VIDEO_DIR = "/root/Videos"
THUMB_DIR = "/root/Videos/thumbnails"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

os.makedirs(THUMB_DIR, exist_ok=True)
app = Flask(__name__)

# --- CYBER-VOID UI WITH UPLOAD PORTAL ---
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx//CYBER_VOID</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
        :root { --red: #ff0000; --dark-red: #2b0000; --cyan: #00f3ff; --bg: #050505; }
        body { 
            background: var(--bg); color: #ccc; font-family: 'Share Tech Mono', monospace; 
            margin: 0; padding-bottom: 50px;
        }
        nav { 
            padding: 15px 5%; background: #000; border-bottom: 2px solid var(--red);
            display: flex; justify-content: space-between; align-items: center; 
        }
        .logo { color: var(--red); font-size: 22px; letter-spacing: 4px; text-shadow: 2px 0 var(--cyan); }
        
        /* Upload Portal Styles */
        .admin-panel { 
            background: #0a0000; border: 1px dashed var(--red); 
            margin: 20px 5%; padding: 20px; border-radius: 4px;
        }
        .admin-panel h3 { color: var(--cyan); margin-top: 0; font-size: 14px; }
        input[type="file"], input[type="text"] { 
            background: #111; border: 1px solid var(--dark-red); color: var(--cyan); 
            padding: 8px; margin: 5px 0; width: 100%; box-sizing: border-box;
        }
        button { 
            background: var(--dark-red); color: white; border: 1px solid var(--red); 
            padding: 10px 20px; cursor: pointer; text-transform: uppercase;
        }
        button:hover { background: var(--red); }

        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 15px; padding: 20px 5%; }
        .card { background: #000; border: 1px solid var(--dark-red); text-decoration: none; color: inherit; }
        .card img { width: 100%; aspect-ratio: 2/3; object-fit: cover; filter: grayscale(100%) sepia(100%) hue-rotate(-50deg) brightness(0.6); }
        .card:hover img { filter: grayscale(0%) brightness(1); }
        .card-meta { padding: 8px; font-size: 10px; }
    </style>
</head>
<body>
    <nav><div class="logo">KTOx//CYBER_VOID</div><div style="color:var(--cyan); font-size:10px;">DATA_UPLINK: ONLINE</div></nav>
    
    <div class="admin-panel">
        <h3>>> SYSTEM_DATA_INJECTION</h3>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <label>TARGET_DIRECTORY (Inside /root/Videos/):</label>
            <input type="text" name="subdir" placeholder="e.g., SciFi or Leave blank for root">
            
            <label>SELECT_DATA_PACKETS (Files or Folders):</label>
            <input type="file" name="files" multiple webkitdirectory mozdirectory>
            <input type="file" name="files" multiple>
            
            <button type="submit">Execute Injection</button>
        </form>
    </div>

    <div class="grid">
        {% for v in videos %}
        <a href="/play/{{ v }}" class="card">
            <img src="/thumb/{{ v | replace('/', '_') }}.jpg">
            <div class="card-meta">
                <span style="color:var(--cyan)">{{ v | upper }}</span>
            </div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

# --- UPLOAD LOGIC ---
@app.route('/upload', methods=['POST'])
def upload_files():
    subdir = request.form.get('subdir', '').strip()
    target_path = os.path.join(VIDEO_DIR, subdir)
    os.makedirs(target_path, exist_ok=True)
    
    uploaded_files = request.files.getlist('files')
    for file in uploaded_files:
        if file.filename:
            # Handle folder structure from webkitdirectory
            filename = secure_filename(os.path.basename(file.filename))
            # If the file was in a folder, we respect that structure
            rel_path = os.path.dirname(file.filename)
            final_dir = os.path.join(target_path, rel_path)
            os.makedirs(final_dir, exist_ok=True)
            
            file.save(os.path.join(final_dir, filename))
            
    # Trigger background thumbnail generation for new data
    threading.Thread(target=generate_thumbnails, daemon=True).start()
    return redirect(url_for('index'))

# --- UPDATED FILE SCANNER (Recursive) ---
def get_all_videos():
    video_list = []
    for root, dirs, files in os.walk(VIDEO_DIR):
        for file in files:
            if file.lower().endswith(VIDEO_EXTS):
                # Get relative path from VIDEO_DIR
                rel_path = os.path.relpath(os.path.join(root, file), VIDEO_DIR)
                video_list.append(rel_path)
    return sorted(video_list)

# --- REFRESHED THUMBNAIL LOGIC ---
def generate_thumbnails():
    videos = get_all_videos()
    for v_rel in videos:
        # Use filename with underscores as thumb name to handle subdirs
        t_name = v_rel.replace('/', '_') + ".jpg"
        t_path = os.path.join(THUMB_DIR, t_name)
        
        if not os.path.exists(t_path):
            full_video_path = os.path.join(VIDEO_DIR, v_rel)
            # Scrape or FFmpeg
            subprocess.run(["ffmpeg", "-ss", "00:00:05", "-i", full_video_path, 
                            "-vf", "scale=300:-1", "-vframes", "1", t_path], stderr=subprocess.DEVNULL)

# --- ROUTES ---
@app.route('/')
def index():
    return render_template_string(INDEX_HTML, videos=get_all_videos())

@app.route('/stream/<path:f>')
def stream(f): return send_from_directory(VIDEO_DIR, f)

@app.route('/thumb/<f>')
def thumb(f): return send_from_directory(THUMB_DIR, f)

@app.route('/play/<path:f>')
def play(f):
    tmpl = "<body style='background:#000;color:red;text-align:center;'><video controls autoplay style='width:90%;border:1px solid red;'><source src='/stream/{{f}}'></video><br><a href='/' style='color:#00f3ff;font-family:monospace;'><< RETURN_TO_VOID</a></body>"
    return render_template_string(tmpl, f=f)

# --- [LCD MONITOR THREAD REMAINS SAME AS PREVIOUS] ---
# (Include the get_stats, get_ip, and lcd_monitor functions from the previous response here)

if __name__ == "__main__":
    if HAS_HW:
        GPIO.setmode(GPIO.BCM)
        for p in PINS.values(): GPIO.setup(p, GPIO.IN, GPIO.PUD_UP)
        # Import and run the lcd_monitor thread here
    
    threading.Thread(target=generate_thumbnails, daemon=True).start()
    app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)
