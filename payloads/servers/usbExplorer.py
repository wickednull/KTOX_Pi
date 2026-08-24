#!/usr/bin/env python3
"""
KTOx Payload – USB File Explorer (Stable)
===========================================
- Persistent USB mounts, stable file listing
- Auto-refresh dropdown without resetting view
- Copy files/folders from USB to KTOx
"""

import os, sys, time, socket, threading, shutil, subprocess, json
from flask import Flask, render_template_string, request, jsonify

# Hardware
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
PORT = 8889

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

app = Flask(__name__)

# Global mount registry
MOUNT_REGISTRY = {}

def unmount_all():
    for dev, mp in list(MOUNT_REGISTRY.items()):
        if mp.startswith('/mnt/ktox_usb_'):
            subprocess.run(['umount', mp], capture_output=True)
    MOUNT_REGISTRY.clear()

def get_usb_drives():
    drives = []
    try:
        result = subprocess.run(['lsblk', '-o', 'NAME,MOUNTPOINT,MODEL,TRAN,SIZE', '-J'], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        for device in data.get('blockdevices', []):
            is_usb = device.get('tran') == 'usb' or 'USB' in device.get('model', '')
            if not is_usb:
                continue
            candidates = [device] + device.get('children', [])
            for cand in candidates:
                name = cand['name']
                dev_path = f"/dev/{name}"
                mount = cand.get('mountpoint')
                if mount:
                    MOUNT_REGISTRY[dev_path] = mount
                    drives.append({'mount': mount, 'device': dev_path})
                else:
                    if dev_path in MOUNT_REGISTRY:
                        drives.append({'mount': MOUNT_REGISTRY[dev_path], 'device': dev_path})
                        continue
                    mount_point = f"/mnt/ktox_usb_{name}"
                    os.makedirs(mount_point, exist_ok=True)
                    ret = subprocess.run(['mount', dev_path, mount_point], capture_output=True)
                    if ret.returncode == 0:
                        MOUNT_REGISTRY[dev_path] = mount_point
                        drives.append({'mount': mount_point, 'device': dev_path})
    except Exception as e:
        print(f"USB error: {e}")
    return drives

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

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx USB Explorer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root { --bg-0:#0a0000; --bg-1:#220000; --header:#8b0000; --accent:#e74c3c; --warn:#d4ac0d;
                --fg:#abb2b9; --fg-muted:#717d7e; --white:#f5f5f5; --glow:0 0 10px rgba(231,76,60,0.3); }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: linear-gradient(135deg,var(--bg-0),var(--bg-1)); font-family: 'Courier New', monospace;
               color: var(--fg); padding: 16px; margin: 0; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { font-size: 1.8rem; text-shadow: 0 0 6px var(--accent); border-left: 4px solid var(--accent);
             padding-left: 16px; margin-bottom: 16px; color: var(--white); letter-spacing: 1px; }
        .panel-row { display: flex; gap: 16px; flex-wrap: wrap; }
        .panel { flex: 1; background: var(--bg-1); border: 1px solid rgba(231,76,60,0.3); border-radius: 4px;
                 padding: 12px; box-shadow: var(--glow); }
        .panel h2 { color: var(--accent); text-shadow: 0 0 4px var(--accent); border-bottom: 1px solid rgba(231,76,60,0.2);
                    padding-bottom: 6px; margin-bottom: 12px; }
        .usb-selector select, .path-bar { background: var(--bg-0); color: var(--fg); border: 1px solid rgba(231,76,60,0.3);
                                           padding: 6px; width: 100%; font-family: monospace; margin-bottom: 12px; border-radius: 3px; }
        select:focus { outline: none; border-color: var(--accent); box-shadow: var(--glow); }
        .path-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .path-bar span { flex: 1; word-break: break-all; color: var(--fg-muted); font-size: 0.85rem; }
        .path-bar button { background: linear-gradient(135deg,var(--header),var(--bg-1)); border: 1px solid var(--accent);
                          color: var(--white); padding: 4px 10px; cursor: pointer; border-radius: 3px; box-shadow: var(--glow); }
        .path-bar button:hover { background: linear-gradient(135deg,var(--accent),#c0392b); box-shadow: 0 0 20px rgba(231,76,60,0.5); }
        .file-list { max-height: 400px; overflow-y: auto; font-size: 0.85rem; }
        .file-item { padding: 6px 8px; border-bottom: 1px solid rgba(231,76,60,0.15); display: flex; align-items: center; gap: 8px; }
        .file-item:hover { background: var(--bg-0); box-shadow: inset 0 0 4px var(--accent); }
        .file-item input { margin-right: 6px; cursor: pointer; accent-color: var(--accent); }
        .file-name { flex: 1; cursor: pointer; word-break: break-word; color: var(--fg); }
        .file-name:hover { text-shadow: 0 0 4px var(--accent); }
        .file-size { color: var(--fg-muted); font-size: 0.75rem; font-family: monospace; }
        .dir-icon { color: var(--warn); margin-right: 4px; }
        .file-icon { color: var(--accent); margin-right: 4px; }
        .action-bar { margin-top: 16px; text-align: center; }
        .copy-btn { background: linear-gradient(135deg,var(--accent),#c0392b); color: var(--white); border: 1px solid var(--accent);
                    padding: 10px 20px; font-size: 1rem; font-weight: bold; cursor: pointer; text-transform: uppercase;
                    letter-spacing: 1px; transition: 0.3s; box-shadow: var(--glow); width: 100%; border-radius: 4px; }
        .copy-btn:hover { box-shadow: 0 0 20px rgba(231,76,60,0.5); transform: translateY(-1px); }
        .status { margin-top: 12px; padding: 8px; background: var(--bg-0); border-left: 4px solid var(--accent);
                  font-family: monospace; color: var(--fg); font-size: 0.85rem; }
        footer { margin-top: 20px; text-align: center; color: var(--fg-muted); font-size: 0.7rem;
                 padding-top: 12px; border-top: 1px solid rgba(231,76,60,0.2); }
        ::-webkit-scrollbar { width: 6px; background: var(--bg-0); }
        ::-webkit-scrollbar-thumb { background: var(--header); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--accent); }
        .refresh-btn { background: linear-gradient(135deg,var(--header),var(--bg-1)); border: 1px solid var(--accent);
                      color: var(--white); padding: 4px 10px; cursor: pointer; margin-left: 8px; border-radius: 3px;
                      box-shadow: var(--glow); }
        .refresh-btn:hover { background: linear-gradient(135deg,var(--accent),#c0392b); box-shadow: 0 0 20px rgba(231,76,60,0.5); }
        .scanlines { position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;
                    background: repeating-linear-gradient(0deg,rgba(0,0,0,0.1),rgba(0,0,0,0.1) 1px,transparent 1px,transparent 2px);
                    z-index: 9999; }
    </style>
</head>
<body>
<div class="container">
    <h1>⎯ KTOx USB EXPLORER ⎯</h1>
    <div class="panel-row">
        <div class="panel">
            <h2>⚡ USB DRIVE <button class="refresh-btn" onclick="refreshUsbList()">⟳</button></h2>
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

    function refreshUsbList() {
        fetch('/api/usb/drives')
            .then(r => r.json())
            .then(data => {
                const select = document.getElementById('usbSelect');
                const currentVal = select.value;
                select.innerHTML = '<option value="">-- Select USB --</option>';
                for (let drive of data) {
                    select.innerHTML += `<option value="${drive.mount}">${drive.mount}</option>`;
                }
                if (currentVal && data.some(d => d.mount === currentVal)) {
                    select.value = currentVal;
                } else if (currentVal) {
                    document.getElementById('usbFileList').innerHTML = '<div class="file-item">Select a USB drive</div>';
                    currentUsbPath = "";
                    selectedPaths.clear();
                }
            });
    }

    function loadUsbRoot() {
        const usb = document.getElementById('usbSelect').value;
        if (!usb) {
            document.getElementById('usbFileList').innerHTML = '<div class="file-item">Select a USB drive</div>';
            return;
        }
        currentUsbPath = usb;
        refreshUsbListAtPath(usb);
    }

    function refreshUsbListAtPath(path) {
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
        refreshUsbListAtPath(currentUsbPath);
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
                    refreshUsbListAtPath(path);
                }
            });
    }

    function toggleSelect(path, checkbox) {
        if (checkbox.checked) selectedPaths.add(path);
        else selectedPaths.delete(path);
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
            html += `<div class="file-item"><div class="${iconClass}">${icon}</div><div class="file-name" onclick="browseLocal('${item.path}')">${escapeHtml(item.name)}</div><div class="file-size">${item.size_fmt}</div></div>`;
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
            browseLocal(currentLocalPath);
            selectedPaths.clear();
            refreshUsbListAtPath(currentUsbPath);
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

    browseLocal('/root');
    setInterval(refreshUsbList, 5000);
</script>
<div class="scanlines"></div>
</body>
</html>
"""

# Flask routes (unchanged)
@app.route('/')
def index():
    drives = get_usb_drives()
    return render_template_string(HTML_TEMPLATE, drives=drives)

@app.route('/api/usb/drives')
def api_usb_drives():
    return jsonify(get_usb_drives())

@app.route('/api/usb/list')
def api_usb_list():
    path = request.args.get('path', '')
    if not os.path.exists(path):
        return jsonify([])
    return jsonify(list_directory(path))

@app.route('/api/usb/isdir')
def api_usb_isdir():
    path = request.args.get('path', '')
    return jsonify({'is_dir': os.path.isdir(path) if os.path.exists(path) else False})

@app.route('/api/local/list')
def api_local_list():
    path = request.args.get('path', '/root')
    if not os.path.exists(path):
        path = '/root'
    return jsonify(list_directory(path))

@app.route('/api/copy', methods=['POST'])
def api_copy():
    data = request.get_json()
    sources = data.get('sources', [])
    dest = data.get('destination', '')
    if not sources or not dest:
        return jsonify({'message': 'Invalid request'}), 400
    if not os.path.isdir(dest):
        return jsonify({'message': f'Destination {dest} not a directory'}), 400
    copied = 0
    errors = []
    for src in sources:
        try:
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dest, os.path.basename(src)), dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
            copied += 1
        except Exception as e:
            errors.append(f"{os.path.basename(src)}: {str(e)[:30]}")
    msg = f"Copied {copied} item(s)."
    if errors:
        msg += f" Errors: {', '.join(errors[:2])}"
    return jsonify({'message': msg})

# LCD loop and main (same as before, with unmount on exit)
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
        d.text((4,3), "USB EXPLORER", font=font_bold, fill=(231, 76, 60))
        y = 20
        d.text((4,y), f"IP: {ip}:{PORT}", font=font_sm, fill=(171, 178, 185)); y+=12
        d.text((4,y), f"USB: {usb_status[:15]}", font=font_sm, fill=(171, 178, 185)); y+=12
        d.text((4,y), "Status: RUNNING", font=font_sm, fill=(30, 132, 73)); y+=12
        d.text((4,y), "K2=Refresh  K3=Exit", font=font_sm, fill="#FF7777")
        d.rectangle((0,H-12,W,H), fill="#220000")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(2)

def main():
    if HAS_HW:
        threading.Thread(target=lcd_loop, daemon=True).start()
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False), daemon=True).start()
        time.sleep(2)
        held = {}
        while True:
            now = time.time()
            pressed = {n: GPIO.input(p)==0 for n,p in PINS.items()}
            for n, down in pressed.items():
                if down:
                    if n not in held: held[n] = now
                else:
                    held.pop(n, None)
            if pressed.get("KEY3") and (now - held.get("KEY3", now)) <= 0.05:
                unmount_all()
                GPIO.cleanup()
                LCD.LCD_Clear()
                os._exit(0)
            if pressed.get("KEY2") and (now - held.get("KEY2", now)) <= 0.05:
                time.sleep(0.3)
            time.sleep(0.1)
    else:
        app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("⚠️  Requires root for mounting. Run with: sudo")
        sys.exit(1)
    main()
