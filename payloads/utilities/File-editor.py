#!/usr/bin/env python3
"""
KTOx Payload – File Explorer & Editor
======================================
- Browse directories
- Rename, delete, edit text files
- Create new files/folders
- Cyberpunk web UI on port 8890
- LCD: IP, QR (KEY1), exit (KEY3)
"""

import os
import sys
import time
import socket
import threading
import shutil
from flask import Flask, render_template_string, request, send_from_directory, jsonify
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
f11 = font(11)

# ----------------------------------------------------------------------
# Flask web server (runs in background)
# ----------------------------------------------------------------------
PORT = 8890
app = Flask(__name__)

def size_fmt(size):
    for unit in ['B','KB','MB','GB']:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"

def list_directory(path):
    items = []
    try:
        for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
            items.append({
                'name': entry.name,
                'type': 'dir' if entry.is_dir() else 'file',
                'size': entry.stat().st_size if entry.is_file() else 0,
                'path': entry.path,
                'size_fmt': size_fmt(entry.stat().st_size) if entry.is_file() else ''
            })
    except PermissionError:
        pass
    return items

def is_text_file(filepath):
    text_exts = ('.txt', '.cfg', '.conf', '.py', '.sh', '.json', '.yml', '.yaml', '.md', '.html', '.css', '.js', '.csv')
    return filepath.lower().endswith(text_exts)

# ----------------------------------------------------------------------
# Web UI template (same as original)
# ----------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx File Editor</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: #0a0a0a;
            font-family: 'Share Tech Mono', 'Courier New', monospace;
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
            padding: 8px;
            margin-bottom: 15px;
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
        .file-list {
            background: #050505;
            border: 1px solid #300;
            border-radius: 8px;
            max-height: 400px;
            overflow-y: auto;
        }
        .file-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            border-bottom: 1px solid #1a1a1a;
        }
        .file-item:hover { background: #1a1a1a; }
        .file-info {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
        }
        .file-name { cursor: pointer; color: #0ff; }
        .file-name:hover { text-shadow: 0 0 3px #0ff; }
        .file-actions button {
            background: none;
            border: 1px solid #f00;
            color: #f00;
            padding: 2px 8px;
            margin-left: 5px;
            cursor: pointer;
            font-size: 0.7rem;
        }
        .file-actions button:hover { background: #f00; color: #000; }
        .dir-icon { color: #f0f; }
        .file-icon { color: #0ff; }
        .action-bar {
            margin-top: 20px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .action-bar button {
            background: #2a0a0a;
            border: 1px solid #f00;
            color: #f00;
            padding: 6px 12px;
            cursor: pointer;
        }
        .action-bar button:hover { background: #f00; color: #000; }
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        .modal-content {
            background: #111;
            border: 2px solid #0f0;
            border-radius: 12px;
            padding: 20px;
            width: 90%;
            max-width: 600px;
        }
        .modal-content h3 { color: #f00; margin-bottom: 15px; }
        .modal-content input, .modal-content textarea {
            background: #222;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 8px;
            width: 100%;
            margin-bottom: 10px;
            font-family: monospace;
        }
        .modal-content textarea { height: 300px; }
        .modal-content button {
            background: #2a0a0a;
            border: 1px solid #f00;
            color: #f00;
            padding: 6px 12px;
            margin-right: 10px;
            cursor: pointer;
        }
        .close { float: right; cursor: pointer; font-size: 24px; color: #f00; }
        .status {
            margin-top: 10px;
            color: #ff0;
        }
        footer {
            margin-top: 30px;
            text-align: center;
            color: #444;
            font-size: 0.7rem;
        }
    </style>
</head>
<body>
<div class="container">
    <h1>⎯ KTOx FILE EDITOR ⎯</h1>
    <div class="path-bar">
        <span id="currentPath">{{ current_path }}</span>
        <button onclick="reload()">⟳</button>
        <button onclick="parentDir()">⬆ Up</button>
    </div>
    <div class="file-list" id="fileList">
        Loading...
    </div>
    <div class="action-bar">
        <button onclick="newFile()">📄 New File</button>
        <button onclick="newFolder()">📁 New Folder</button>
    </div>
    <div id="status" class="status"></div>
    <footer>KTOx Cyberpunk File Editor – click filename to edit/rename</footer>
</div>

<div id="modal" class="modal">
    <div class="modal-content">
        <span class="close" onclick="closeModal()">&times;</span>
        <h3 id="modalTitle">Edit File</h3>
        <input type="text" id="modalInput" placeholder="New name">
        <textarea id="modalTextarea" style="display:none;"></textarea>
        <div>
            <button id="modalConfirm">Confirm</button>
            <button onclick="closeModal()">Cancel</button>
        </div>
    </div>
</div>

<script>
    let currentPath = "{{ current_path }}";
    let currentAction = null;
    let currentTarget = null;

    function reload() {
        fetch('/api/list?path=' + encodeURIComponent(currentPath))
            .then(r => r.json())
            .then(data => renderFileList(data));
    }

    function parentDir() {
        let parent = currentPath.split('/').slice(0, -1).join('/');
        if (!parent) parent = '/';
        navigateTo(parent);
    }

    function navigateTo(path) {
        currentPath = path;
        document.getElementById('currentPath').innerText = path;
        reload();
    }

    function renderFileList(items) {
        const container = document.getElementById('fileList');
        if (!items || items.length === 0) {
            container.innerHTML = '<div style="padding:20px;text-align:center;">(empty)</div>';
            return;
        }
        let html = '';
        for (let item of items) {
            const icon = item.type === 'dir' ? '📁' : '📄';
            const iconClass = item.type === 'dir' ? 'dir-icon' : 'file-icon';
            html += `
                <div class="file-item">
                    <div class="file-info">
                        <div class="${iconClass}">${icon}</div>
                        <div class="file-name" onclick="openItem('${item.path}')">${escapeHtml(item.name)}</div>
                        <div style="color:#666; font-size:0.7rem;">${item.size_fmt}</div>
                    </div>
                    <div class="file-actions">
                        <button onclick="renameItem('${item.path}', '${item.name}')">✎</button>
                        <button onclick="deleteItem('${item.path}')">🗑</button>
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    }

    function openItem(path) {
        fetch('/api/isdir?path=' + encodeURIComponent(path))
            .then(r => r.json())
            .then(data => {
                if (data.is_dir) {
                    navigateTo(path);
                } else {
                    editFile(path);
                }
            });
    }

    function editFile(path) {
        currentTarget = path;
        currentAction = 'edit';
        fetch('/api/read?path=' + encodeURIComponent(path))
            .then(r => r.json())
            .then(data => {
                document.getElementById('modalTitle').innerText = 'Edit: ' + path.split('/').pop();
                document.getElementById('modalInput').style.display = 'none';
                document.getElementById('modalTextarea').style.display = 'block';
                document.getElementById('modalTextarea').value = data.content;
                document.getElementById('modalConfirm').onclick = () => saveFile();
                openModal();
            });
    }

    function saveFile() {
        const content = document.getElementById('modalTextarea').value;
        fetch('/api/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: currentTarget, content: content })
        })
        .then(r => r.json())
        .then(data => {
            showStatus(data.message);
            closeModal();
            reload();
        });
    }

    function renameItem(path, oldName) {
        currentTarget = path;
        currentAction = 'rename';
        document.getElementById('modalTitle').innerText = 'Rename: ' + oldName;
        document.getElementById('modalInput').style.display = 'block';
        document.getElementById('modalTextarea').style.display = 'none';
        document.getElementById('modalInput').value = oldName;
        document.getElementById('modalConfirm').onclick = () => confirmRename();
        openModal();
    }

    function confirmRename() {
        const newName = document.getElementById('modalInput').value;
        if (!newName) return;
        fetch('/api/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: currentTarget, new_name: newName })
        })
        .then(r => r.json())
        .then(data => {
            showStatus(data.message);
            closeModal();
            reload();
        });
    }

    function deleteItem(path) {
        if (!confirm('Delete permanently?')) return;
        fetch('/api/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path })
        })
        .then(r => r.json())
        .then(data => {
            showStatus(data.message);
            reload();
        });
    }

    function newFile() {
        const name = prompt('New file name:');
        if (!name) return;
        fetch('/api/new_file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dir: currentPath, name: name })
        })
        .then(r => r.json())
        .then(data => {
            showStatus(data.message);
            reload();
        });
    }

    function newFolder() {
        const name = prompt('New folder name:');
        if (!name) return;
        fetch('/api/new_folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dir: currentPath, name: name })
        })
        .then(r => r.json())
        .then(data => {
            showStatus(data.message);
            reload();
        });
    }

    function showStatus(msg) {
        const statusDiv = document.getElementById('status');
        statusDiv.innerText = msg;
        setTimeout(() => statusDiv.innerText = '', 3000);
    }

    function openModal() { document.getElementById('modal').style.display = 'flex'; }
    function closeModal() { document.getElementById('modal').style.display = 'none'; }

    function escapeHtml(str) {
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    reload();
</script>
</body>
</html>
"""

# ----------------------------------------------------------------------
# Flask routes
# ----------------------------------------------------------------------
@app.route('/')
def index():
    start = "/root"
    return render_template_string(HTML_TEMPLATE, current_path=start)

@app.route('/api/list')
def api_list():
    path = request.args.get('path', '/root')
    if not os.path.exists(path):
        return jsonify([])
    items = list_directory(path)
    return jsonify(items)

@app.route('/api/isdir')
def api_isdir():
    path = request.args.get('path', '')
    is_dir = os.path.isdir(path) if os.path.exists(path) else False
    return jsonify({'is_dir': is_dir})

@app.route('/api/read')
def api_read():
    path = request.args.get('path', '')
    if not os.path.isfile(path):
        return jsonify({'content': 'Error: not a file'})
    if not is_text_file(path):
        return jsonify({'content': 'Binary file cannot be edited'})
    try:
        with open(path, 'r') as f:
            content = f.read()
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'content': f'Error: {str(e)}'})

@app.route('/api/write', methods=['POST'])
def api_write():
    data = request.json
    path = data.get('path')
    content = data.get('content', '')
    if not path:
        return jsonify({'message': 'No path'})
    try:
        with open(path, 'w') as f:
            f.write(content)
        return jsonify({'message': 'Saved'})
    except Exception as e:
        return jsonify({'message': f'Error: {str(e)}'})

@app.route('/api/rename', methods=['POST'])
def api_rename():
    data = request.json
    old_path = data.get('path')
    new_name = data.get('new_name')
    if not old_path or not new_name:
        return jsonify({'message': 'Missing parameters'})
    dirname = os.path.dirname(old_path)
    new_path = os.path.join(dirname, secure_filename(new_name))
    try:
        os.rename(old_path, new_path)
        return jsonify({'message': f'Renamed to {new_name}'})
    except Exception as e:
        return jsonify({'message': f'Error: {str(e)}'})

@app.route('/api/delete', methods=['POST'])
def api_delete():
    data = request.json
    path = data.get('path')
    if not path:
        return jsonify({'message': 'No path'})
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return jsonify({'message': 'Deleted'})
    except Exception as e:
        return jsonify({'message': f'Error: {str(e)}'})

@app.route('/api/new_file', methods=['POST'])
def api_new_file():
    data = request.json
    dir_path = data.get('dir')
    name = data.get('name')
    if not dir_path or not name:
        return jsonify({'message': 'Missing parameters'})
    name = secure_filename(name)
    full = os.path.join(dir_path, name)
    if os.path.exists(full):
        return jsonify({'message': 'Already exists'})
    try:
        with open(full, 'w') as f:
            f.write('')
        return jsonify({'message': f'Created {name}'})
    except Exception as e:
        return jsonify({'message': f'Error: {str(e)}'})

@app.route('/api/new_folder', methods=['POST'])
def api_new_folder():
    data = request.json
    dir_path = data.get('dir')
    name = data.get('name')
    if not dir_path or not name:
        return jsonify({'message': 'Missing parameters'})
    name = secure_filename(name)
    full = os.path.join(dir_path, name)
    if os.path.exists(full):
        return jsonify({'message': 'Already exists'})
    try:
        os.mkdir(full)
        return jsonify({'message': f'Created folder {name}'})
    except Exception as e:
        return jsonify({'message': f'Error: {str(e)}'})

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ----------------------------------------------------------------------
# LCD drawing (exactly like working example)
# ----------------------------------------------------------------------
def draw(lines, title="FILE EDITOR", title_color="#8B0000", text_color="#FFBBBB"):
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
# Main (LCD loop in main thread, Flask in daemon)
# ----------------------------------------------------------------------
def main():
    # Start Flask in a daemon thread
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(1)  # give Flask time to start

    ip = get_ip()
    draw([f"Server: {ip}:{PORT}", "", "K1=QR  K3=EXIT"], title="FILE EDITOR")

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
                draw(["QR error"], title="FILE EDITOR")
        else:
            draw([f"IP: {ip}:{PORT}", "", "Web editor running", "", "K1=QR  K3=EXIT"], title="FILE EDITOR")

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
