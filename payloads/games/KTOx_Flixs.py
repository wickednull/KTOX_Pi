import os, subprocess
from flask import Flask, render_template_string, send_from_directory

app = Flask(__name__)

VIDEO_DIR = "/root/Videos"
THUMB_DIR = "/root/Videos/thumbnails"
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov')

# Ensure thumbnail folder exists
if not os.path.exists(THUMB_DIR):
    os.makedirs(THUMB_DIR)

def generate_thumbnails():
    """Create a preview image for every video found."""
    for f in os.listdir(VIDEO_DIR):
        if f.lower().endswith(VIDEO_EXTS):
            thumb_path = os.path.join(THUMB_DIR, f + ".jpg")
            if not os.path.exists(thumb_path):
                video_path = os.path.join(VIDEO_DIR, f)
                # FFmpeg captures 1 frame at 2 seconds in
                subprocess.run([
                    "ffmpeg", "-i", video_path, "-ss", "00:00:02", 
                    "-vframes", "1", "-q:v", "2", thumb_path
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- HTML/CSS UI ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx Video Server</title>
    <style>
        body { background: #141414; color: white; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; margin: 0; padding: 20px; }
        h1 { color: #E50914; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }
        .card { background: #222; border-radius: 4px; overflow: hidden; transition: transform 0.3s; cursor: pointer; text-decoration: none; color: white; }
        .card:hover { transform: scale(1.05); }
        .card img { width: 100%; height: 120px; object-fit: cover; }
        .card-title { padding: 10px; font-size: 14px; text-align: center; }
        video { width: 100%; max-width: 1000px; display: block; margin: 20px auto; border: 2px solid #333; }
    </style>
</head>
<body>
    <h1>KTOx NETFLIX</h1>
    <div class="grid">
        {% for video in videos %}
        <a href="/play/{{ video }}" class="card">
            <img src="/thumb/{{ video }}.jpg">
            <div class="card-title">{{ video }}</div>
        </a>
        {% endfor %}
    </div>
</body>
</html>
"""

PLAYER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Playing {{ video }}</title>
    <style>
        body { background: black; color: white; text-align: center; font-family: sans-serif; }
        video { width: 80%; margin-top: 50px; outline: none; }
        .back { display: inline-block; margin-top: 20px; color: #E50914; text-decoration: none; font-size: 18px; }
    </style>
</head>
<body>
    <video controls autoplay>
        <source src="/stream/{{ video }}" type="video/mp4">
        Your browser does not support the video tag.
    </video>
    <br>
    <a href="/" class="back">← Back to Gallery</a>
</body>
</html>
"""

# --- ROUTES ---
@app.route('/')
def index():
    videos = [f for f in os.listdir(VIDEO_DIR) if f.lower().endswith(VIDEO_EXTS)]
    return render_template_string(HTML_TEMPLATE, videos=videos)

@app.route('/play/<filename>')
def play(filename):
    return render_template_string(PLAYER_TEMPLATE, video=filename)

@app.route('/stream/<filename>')
def stream(filename):
    return send_from_directory(VIDEO_DIR, filename)

@app.route('/thumb/<filename>')
def thumb(filename):
    return send_from_directory(THUMB_DIR, filename)

if __name__ == '__main__':
    print("Generating thumbnails...")
    generate_thumbnails()
    # Run on all interfaces so you can access from your laptop
    app.run(host='0.0.0.0', port=80, debug=False)
