#!/usr/bin/env python3
"""
KTOx Payload – USB File Explorer (Enhanced)
============================================
- Full directory navigation on USB drives
- Select multiple files/folders (checkboxes)
- Copy selected items to any local KTOx directory
- Cyberpunk UI, real-time status

Controls (LCD):
  KEY3  Exit payload
  KEY1  Toggle server (auto-start)

Access: http://<IP>:8889
"""

import os
import sys
import time
import socket
import threading
import shutil
import subprocess
from flask import Flask, render_template_string, request, jsonify

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

try:
    import pyudev
    HAS_UDEV = True
except ImportError:
    HAS_UDEV = False
    print("Install pyudev for better USB detection: pip install pyudev")

PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    W, H = 128, 128
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    except:
        font_sm = font_bold = ImageFont.load_default()

# ----------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------
PORT = 8889
app = Flask(__name__)

# ----------------------------------------------------------------------
# USB detection (pyudev + fallback)
# ----------------------------------------------------------------------
def get_usb_drives():
    """Return list of dicts: {'mount': mount_point, 'device': dev_node}"""
    drives = []
    if HAS_UDEV:
        context = pyudev.Context()
        for device in context.list_devices(subsystem='block', DEVTYPE='partition'):
            if device.get('ID_BUS') == 'usb':
                dev_node = device.device_node
                if not dev_node:
                    continue
                # Find mount point
                try:
                    result = subprocess.run(
                        ['findmnt', '-no', 'TARGET', dev_node],
                        capture_output=True, text=True, check=False
                    )
                    mount_point = result.stdout.strip()
                except:
                    mount_point = None
                if mount_point and os.path.exists(mount_point):
                    drives.append({'mount': mount_point, 'device': dev_node})
    # Fallback: scan common mount points
    if not drives:
        base_dirs = ["/media/pi", "/media", "/mnt", "/run/media"]
        for base in base_dirs:
            if os.path.isdir(base):
                for entry in os.listdir(base):
                    full = os.path.join(base, entry)
                    if os.path.ismount(full):
                        drives.append({'mount': full, 'device': 'unknown'})
    return drives

# ----------------------------------------------------------------------
# File listing helpers
# ----------------------------------------------------------------------
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

def size_fmt(size):
    for unit in ['B','KB','MB','GB']:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"

# ----------------------------------------------------------------------
# HTML Template – Cyberpunk with checkboxes
# ----------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx USB Explorer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: #0a0f0f;
            font-family: 'Share Tech Mono', 'Courier New', monospace;
            color: #0ff;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            font-size: 2rem;
            text-shadow: 0 0 5px #0ff;
            border-left: 4px solid #0ff;
            padding-left: 20px;
            margin-bottom: 20px;
        }
        .panel-row { display: flex; gap: 20px; flex-wrap: wrap; }
        .panel {
            flex: 1;
            background: #0f1212;
            border: 1px solid #0ff;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 0 10px rgba(0,255,255,0.2);
        }
        .panel h2 {
            color: #f0f;
            text-shadow: 0 0 3px #f0f;
            border-bottom: 1px solid #0ff;
            padding-bottom: 5px;
            margin-bottom: 15px;
        }
        .usb-selector select, .path-bar {
            background: #111;
            color: #0ff;
            border: 1px solid #0ff;
            padding: 8px;
            width: 100%;
            font-family: monospace;
            margin-bottom: 15px;
        }
        .path-bar {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .path-bar span { flex: 1; word-break: break-all; }
        .path-bar button {
            background: #0a2a2a;
            border: 1px solid #0ff;
            color: #0ff;
            padding: 4px 10px;
            cursor: pointer;
        }
        .file-list {
            max-height: 400px;
            overflow-y: auto;
            font-size: 0.85rem;
        }
        .file-item {
            padding: 5px 8px;
            border-bottom: 1px solid #1a2a2a;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .file-item:hover { background: #1a2a2a; }
        .file-item input { margin-right: 8px; cursor: pointer; }
        .file-name { flex: 1; cursor: pointer; word-break: break-word; }
        .file-name:hover { text-shadow: 0 0 2px #0ff; }
        .file-size { color: #8a8; font-size: 0.75rem; }
        .dir-icon { color: #0ff; margin-right: 4px; }
        .file-icon { color: #f0f; margin-right: 4px; }
        .action-bar { margin-top: 20px; text-align: center; }
        .copy-btn {
            background: #0ff;
            color: #000;
            border: none;
            padding: 12px 24px;
            font-size: 1.2rem;
            font-weight: bold;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 2px;
            transition: 0.2s;
            box-shadow: 0 0 10px #0ff;
            width: 100%;
        }
        .copy-btn:hover { background: #f0f; box-shadow: 0 0 15px #f0f; }
        .status {
            margin-top: 15px;
            padding: 8px;
            background: #0a1a1a;
            border-left: 4px solid #0ff;
            font-family: monospace;
        }
        footer { margin-top: 30px; text-align: center; color: #4a6; font-size: 0.7rem; }
        ::-webkit-scrollbar { width: 6px; background: #0a0f0f; }
        ::-webkit-scrollbar-thumb { background: #0ff; border-radius: 3px; }
    </style>
</head>
<body>
<div class="container">
    <h1>⎯ KTOx USB EXPLORER ⎯</h1>
    <div class="panel-row">
        <!-- USB Source Panel -->
        <div class="panel">
            <h2>⚡ USB DRIVE</h2>
            <select id="usbSelect" onchange="loadUsbRoot()">
                <option value="">-- Select USB --</option>
                {% for drive in drives %}
                <option value="{{ drive.mount }}">{{ drive.mount }}</option>
                {% endfor %}
            </select>
            <div class="path-bar">
                <span id="usbPath">/</span>
                <button onclick="navigateUsb('..')">Up</button>
            </div>
            <div id="usbFileList" class="file-list">Select a USB drive</div>
            <div class="action-bar">
                <button class="copy-btn" onclick="copySelected()">▶ COPY SELECTED TO DESTINATION ◀</button>
            </div>
        </div>

        <!-- Local Destination Panel -->
        <div class="panel">
            <h2>💾 KTOx DESTINATION</h2>
            <div class="path-bar">
                <span id="destPath">/root</span>
                <button onclick="browseLocal('/root')">Home</button>
                <button onclick="browseLocal('..')">Up</button>
            </div>
            <div id="localFileList" class="file-list">Loading...</div>
        </div>
    </div>
    <div id="status" class="status">Ready.</div>
    <footer>KTOx Cyberdeck – USB File Transfer</footer>
</div>

<script>
    let currentUsbPath = "";
    let currentLocalPath = "/root";
    let selectedPaths = new Set();

    function loadUsbRoot() {
        const usb = document.getElementById('usbSelect').value;
        if (!usb) {
            document.getElementById('usbFileList').innerHTML = '<div class="file-item">Select a USB drive</div>';
            return;
        }
        currentUsbPath = usb;
        refreshUsbList(usb);
    }

    function refreshUsbList(path) {
        fetch('/api/usb/list?path=' + encodeURIComponent(path))
            .then(r => r.json())
            .then(data => renderUsbFileList(data));
        document.getElementById('usbPath').innerText = path;
    }

    function navigateUsb(target) {
        if (target === '..') {
            let parent = currentUsbPath.split('/').slice(0, -1).join('/');
            if (!parent) parent = '/';
            currentUsbPath = parent;
        } else {
            currentUsbPath = target;
        }
        refreshUsbList(currentUsbPath);
    }

    function renderUsbFileList(items) {
        const container = document.getElementById('usbFileList');
        if (!items || items.length === 0) {
            container.innerHTML = '<div class="file-item">(empty)</div>';
            return;
        }
        let html = '';
        for (let item of items) {
            const icon = item.type === 'dir' ? '📁' : '📄';
            const iconClass = item.type === 'dir' ? 'dir-icon' : 'file-icon';
            const checked = selectedPaths.has(item.path) ? 'checked' : '';
            html += `
                <div class="file-item">
                    <input type="checkbox" value="${item.path}" ${checked} onchange="toggleSelect('${item.path}', this)">
                    <div class="${iconClass}">${icon}</div>
                    <div class="file-name" onclick="navigateInto('${item.path}')">${escapeHtml(item.name)}</div>
                    <div class="file-size">${item.size_fmt}</div>
                </div>
            `;
        }
        container.innerHTML = html;
        // Restore checkbox states
        document.querySelectorAll('#usbFileList input[type="checkbox"]').forEach(cb => {
            if (selectedPaths.has(cb.value)) cb.checked = true;
        });
    }

    function navigateInto(path) {
        fetch('/api/usb/isdir?path=' + encodeURIComponent(path))
            .then(r => r.json())
            .then(data => {
                if (data.is_dir) {
                    currentUsbPath = path;
                    refreshUsbList(path);
                }
            });
    }

    function toggleSelect(path, checkbox) {
        if (checkbox.checked) {
            selectedPaths.add(path);
        } else {
            selectedPaths.delete(path);
        }
    }

    function browseLocal(path) {
        if (path === '..') {
            let parent = currentLocalPath.split('/').slice(0, -1).join('/');
            if (!parent) parent = '/';
            path = parent;
        }
        fetch('/api/local/list?path=' + encodeURIComponent(path))
            .then(r => r.json())
            .then(data => {
                renderLocalFileList(data);
                currentLocalPath = path;
                document.getElementById('destPath').innerText = path;
            });
    }

    function renderLocalFileList(items) {
        const container = document.getElementById('localFileList');
        if (!items || items.length === 0) {
            container.innerHTML = '<div class="file-item">(empty)</div>';
            return;
        }
        let html = '';
        for (let item of items) {
            const icon = item.type === 'dir' ? '📁' : '📄';
            const iconClass = item.type === 'dir' ? 'dir-icon' : 'file-icon';
            html += `
                <div class="file-item">
                    <div class="${iconClass}">${icon}</div>
                    <div class="file-name" onclick="browseLocal('${item.path}')">${escapeHtml(item.name)}</div>
                    <div class="file-size">${item.size_fmt}</div>
                </div>
            `;
        }
        container.innerHTML = html;
    }

    function copySelected() {
        const sources = Array.from(selectedPaths);
        if (sources.length === 0) {
            document.getElementById('status').innerText = '❌ No items selected.';
            return;
        }
        document.getElementById('status').innerHTML = '⏳ Copying... please wait.';
        fetch('/api/copy', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ sources: sources, destination: currentLocalPath })
        })
        .then(r => r.json())
        .then(data => {
            document.getElementById('status').innerHTML = `✅ ${data.message}`;
            // Refresh local file list to show copied items
            browseLocal(currentLocalPath);
            // Clear selections
            selectedPaths.clear();
            refreshUsbList(currentUsbPath);
        })
        .catch(err => {
            document.getElementById('status').innerHTML = `❌ Error: ${err}`;
        });
    }

    function escapeHtml(str) {
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    // Initial load
    browseLocal('/root');
</script>
</body>
</html>
"""

# ----------------------------------------------------------------------
# Flask routes
# ----------------------------------------------------------------------
@app.route('/')
def index():
    drives = get_usb_drives()
    return render_template_string(HTML_TEMPLATE, drives=drives)

@app.route('/api/usb/list')
def api_usb_list():
    path = request.args.get('path', '')
    if not os.path.exists(path):
        return jsonify([])
    items = list_directory(path)
    return jsonify(items)

@app.route('/api/usb/isdir')
def api_usb_isdir():
    path = request.args.get('path', '')
    is_dir = os.path.isdir(path) if os.path.exists(path) else False
    return jsonify({'is_dir': is_dir})

@app.route('/api/local/list')
def api_local_list():
    path = request.args.get('path', '/root')
    if not os.path.exists(path):
        path = '/root'
    items = list_directory(path)
    return jsonify(items)

@app.route('/api/copy', methods=['POST'])
def api_copy():
    data = request.get_json()
    sources = data.get('sources', [])
    dest = data.get('destination', '')
    if not sources or not dest:
        return jsonify({'message': 'Invalid request'}), 400
    if not os.path.isdir(dest):
        return jsonify({'message': 'Destination is not a directory'}), 400
    copied = 0
    errors = []
    for src in sources:
        try:
            if os.path.isdir(src):
                dest_path = os.path.join(dest, os.path.basename(src))
                shutil.copytree(src, dest_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
            copied += 1
        except Exception as e:
            errors.append(f"{os.path.basename(src)}: {str(e)[:30]}")
    msg = f"Copied {copied} item(s)."
    if errors:
        msg += f" Errors: {', '.join(errors[:2])}"
    return jsonify({'message': msg})

# ----------------------------------------------------------------------
# LCD display
# ----------------------------------------------------------------------
def lcd_loop():
    if not HAS_HW:
        return
    ip = socket.gethostbyname(socket.gethostname())
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
        s.close()
    except:
        pass
    while True:
        drives = get_usb_drives()
        usb_status = drives[0]['mount'] if drives else "none"
        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        d.rectangle((0,0,W,17), fill="#8B0000")
        d.text((4,3), "USB EXPLORER", font=font_bold, fill="#FF3333")
        y = 20
        d.text((4,y), f"IP: {ip}:{PORT}", font=font_sm, fill="#FFBBBB"); y+=12
        d.text((4,y), f"USB: {usb_status[:15]}", font=font_sm, fill="#FFBBBB"); y+=12
        d.text((4,y), "Status: RUNNING", font=font_sm, fill="#00FF00"); y+=12
        d.text((4,y), "KEY3=Exit", font=font_sm, fill="#FF7777")
        d.rectangle((0,H-12,W,H), fill="#220000")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(2)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if not HAS_UDEV:
        print("\n⚠️  pyudev not installed. USB detection may be limited.")
        print("   Install: pip install pyudev\n")

    if HAS_HW:
        threading.Thread(target=lcd_loop, daemon=True).start()
        def run_flask():
            app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
        server_thread = threading.Thread(target=run_flask, daemon=True)
        server_thread.start()
        time.sleep(2)
        while True:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    time.sleep(0.05)
                    if name == "KEY3":
                        GPIO.cleanup()
                        LCD.LCD_Clear()
                        os._exit(0)
            time.sleep(0.1)
    else:
        app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == "__main__":
    main()
