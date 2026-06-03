#!/usr/bin/env python3
"""
KTOx DOOM Payload
=================
Runs chocolate-doom on Xvfb, captures via ffmpeg x11grab,
streams to KTOx WebUI via Flask + base64 frames.

Supports:
- CardputerZero TCA8418 keyboard via evdev
- Remote control via WebUI (arrow keys, attack, use, menu)
- Real-time frame streaming over HTTP
- Graceful cleanup on exit

Accessible at: http://localhost:8080/payloads/doom
"""

import os
import sys
import time
import signal
import subprocess
import threading
import json
import base64
from io import BytesIO
from dataclasses import dataclass
from typing import Optional
from queue import Queue

# KTOx imports
sys.path.insert(0, '/root/KTOx')
from flask import Blueprint, render_template, jsonify, request
from PIL import Image

# Constants
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    HAS_GPIO = True
except:
    HAS_GPIO = False
    print("[DOOM] WARNING: GPIO not available, hardware input disabled")

DOOM_BIN = "/usr/games/chocolate-doom"
WADS = [
    "/usr/share/games/doom/freedoom1.wad",
    "/usr/share/games/doom/freedoom2.wad",
    "/usr/share/games/doom/doom1.wad",
    "/usr/share/games/doom/doom.wad",
]

DOOM_W, DOOM_H = 320, 200
DISPLAY_NUM = ":99"

# Global state
_doom_state = {
    'running': False,
    'frame_queue': Queue(maxsize=5),
    'current_frame': None,
    'frame_count': 0,
    'process': None,
    'xvfb': None,
    'ffmpeg': None,
}

blueprint = Blueprint('doom', __name__, url_prefix='/payloads/doom', template_folder='../templates')


@dataclass
class DoomFrame:
    """Container for frame data"""
    data: bytes  # Raw RGB565 or JPEG
    timestamp: float
    frame_num: int
    format: str = 'jpeg'  # 'jpeg' for web, 'raw' for LCD


class DoomManager:
    """Manage DOOM process and streaming"""
    
    def __init__(self):
        self.wad = self._find_wad()
        self.running = False
        self.frame_count = 0
        
    def _find_wad(self) -> Optional[str]:
        """Locate a DOOM WAD file"""
        for w in WADS:
            if os.path.isfile(w):
                return w
        return None
    
    def verify_deps(self) -> tuple[bool, str]:
        """Check if all dependencies are available"""
        missing = []
        
        if not os.path.isfile(DOOM_BIN):
            missing.append("chocolate-doom")
        
        if not self.wad:
            missing.append("freedoom/doom.wad")
        
        if not os.path.isfile("/usr/bin/Xvfb"):
            missing.append("xvfb")
        
        if not os.path.isfile("/usr/bin/ffmpeg"):
            missing.append("ffmpeg")
        
        if missing:
            return False, f"Missing: {', '.join(missing)}"
        
        return True, "All dependencies OK"
    
    def install_deps(self) -> bool:
        """Install missing dependencies"""
        missing = []
        if not os.path.isfile(DOOM_BIN):
            missing.append("chocolate-doom")
        if not self.wad:
            missing.append("freedoom")
        if not os.path.isfile("/usr/bin/Xvfb"):
            missing.append("xvfb")
        
        if not missing:
            return True
        
        print(f"[DOOM] Installing {missing}...")
        try:
            subprocess.run(
                ["apt-get", "install", "-y"] + missing,
                capture_output=True, timeout=180, check=False
            )
            return True
        except Exception as e:
            print(f"[DOOM] Install failed: {e}")
            return False
    
    def start(self) -> tuple[bool, str]:
        """Start DOOM and streaming"""
        if self.running:
            return False, "Already running"
        
        # Verify WAD
        if not self.wad:
            self.install_deps()
            self.wad = self._find_wad()
            if not self.wad:
                return False, "No DOOM WAD found"
        
        print(f"[DOOM] Starting with WAD={self.wad}")
        
        # Start Xvfb
        try:
            _doom_state['xvfb'] = subprocess.Popen(
                ["Xvfb", DISPLAY_NUM, "-screen", "0", f"{DOOM_W}x{DOOM_H}x24", "-ac", "-nocursor"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)
            if _doom_state['xvfb'].poll() is not None:
                return False, "Xvfb failed to start"
            print("[DOOM] Xvfb OK")
        except Exception as e:
            return False, f"Xvfb error: {e}"
        
        # Set up environment
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY_NUM
        env["SDL_VIDEODRIVER"] = "x11"
        env["SDL_VIDEO_WINDOW_POS"] = "0,0"
        
        # Start DOOM
        try:
            _doom_state['process'] = subprocess.Popen(
                [DOOM_BIN, "-iwad", self.wad, "-nomusic", "-nomouse",
                 "-1", "-window", "-geometry", f"{DOOM_W}x{DOOM_H}+0+0"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )
            time.sleep(2)
            if _doom_state['process'].poll() is not None:
                err = _doom_state['process'].stderr.read(100).decode(errors='replace')
                return False, f"DOOM crashed: {err}"
            print("[DOOM] chocolate-doom OK")
        except Exception as e:
            return False, f"DOOM error: {e}"
        
        # Start ffmpeg capture
        try:
            _doom_state['ffmpeg'] = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "quiet",
                 "-f", "x11grab", "-framerate", "15",
                 "-video_size", f"{DOOM_W}x{DOOM_H}",
                 "-i", DISPLAY_NUM,
                 "-vf", f"scale=320:200",
                 "-pix_fmt", "rgb24",
                 "-f", "rawvideo", "pipe:1"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0
            )
            print("[DOOM] ffmpeg OK")
        except Exception as e:
            return False, f"ffmpeg error: {e}"
        
        self.running = True
        _doom_state['running'] = True
        
        # Start capture thread
        capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        capture_thread.start()
        
        # Start input thread (hardware buttons)
        if HAS_GPIO:
            input_thread = threading.Thread(target=self._input_loop, args=(env,), daemon=True)
            input_thread.start()
        
        return True, "DOOM started"
    
    def _capture_loop(self):
        """Read frames from ffmpeg, convert to JPEG, queue for WebUI"""
        FRAME_SIZE = DOOM_W * DOOM_H * 3  # RGB24
        
        while self.running and _doom_state['process'].poll() is None:
            try:
                raw = _doom_state['ffmpeg'].stdout.read(FRAME_SIZE)
                if not raw or len(raw) != FRAME_SIZE:
                    break
                
                # Convert raw RGB to PIL Image, then to JPEG
                img = Image.frombytes('RGB', (DOOM_W, DOOM_H), raw)
                
                # Compress to JPEG
                buf = BytesIO()
                img.save(buf, format='JPEG', quality=70)
                jpeg_data = buf.getvalue()
                
                # Queue for WebUI
                frame = DoomFrame(
                    data=jpeg_data,
                    timestamp=time.time(),
                    frame_num=self.frame_count,
                    format='jpeg'
                )
                
                try:
                    _doom_state['frame_queue'].put_nowait(frame)
                except:
                    pass  # Queue full, drop frame
                
                _doom_state['current_frame'] = frame
                self.frame_count += 1
                
                if self.frame_count == 1:
                    print("[DOOM] First frame captured!")
            
            except Exception as e:
                print(f"[DOOM] Capture error: {e}")
                break
        
        self.stop()
    
    def _input_loop(self, env: dict):
        """Read hardware buttons, send to DOOM"""
        key_map = {
            "UP": "Up",
            "DOWN": "Down",
            "LEFT": "Left",
            "RIGHT": "Right",
            "OK": "Return",
            "KEY1": "ctrl",
        }
        
        pressed = set()
        k2_down_time = 0
        
        while self.running and _doom_state['process'].poll() is None:
            now = time.time()
            
            # KEY2: short = space (use/open), long = Escape (menu)
            if HAS_GPIO:
                k2_down = GPIO.input(PINS["KEY2"]) == 0
                if k2_down and "KEY2" not in pressed:
                    pressed.add("KEY2")
                    k2_down_time = now
                elif not k2_down and "KEY2" in pressed:
                    pressed.discard("KEY2")
                    held = now - k2_down_time
                    key = "Escape" if held > 0.5 else "space"
                    subprocess.run(
                        ["xdotool", "key", key],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1
                    )
                
                # KEY3: quit
                k3_down = GPIO.input(PINS["KEY3"]) == 0
                if k3_down:
                    print("[DOOM] KEY3 pressed, quitting")
                    self.stop()
                    break
                
                # Direction/action keys
                for name, pin in PINS.items():
                    if name in ("KEY2", "KEY3"):
                        continue
                    
                    is_down = GPIO.input(pin) == 0
                    xkey = key_map.get(name)
                    
                    if not xkey:
                        continue
                    
                    if is_down and name not in pressed:
                        pressed.add(name)
                        subprocess.run(
                            ["xdotool", "keydown", xkey],
                            env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1
                        )
                    elif not is_down and name in pressed:
                        pressed.discard(name)
                        subprocess.run(
                            ["xdotool", "keyup", xkey],
                            env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1
                        )
            
            time.sleep(0.02)
    
    def send_input(self, key: str, env: dict = None):
        """Remote input from WebUI"""
        if not env:
            env = os.environ.copy()
            env["DISPLAY"] = DISPLAY_NUM
        
        key_map = {
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
            "attack": "ctrl",
            "use": "space",
            "menu": "Escape",
        }
        
        xkey = key_map.get(key.lower())
        if xkey:
            try:
                subprocess.run(
                    ["xdotool", "key", xkey],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1
                )
            except:
                pass
    
    def stop(self):
        """Stop DOOM and clean up"""
        print("[DOOM] Stopping...")
        self.running = False
        _doom_state['running'] = False
        
        for proc in [_doom_state['ffmpeg'], _doom_state['process'], _doom_state['xvfb']]:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except:
                    try:
                        proc.kill()
                    except:
                        pass
        
        subprocess.run(["pkill", "-9", "chocolate"], capture_output=True)
        subprocess.run(["pkill", "-9", "Xvfb"], capture_output=True)
        subprocess.run(["pkill", "-9", "ffmpeg"], capture_output=True)
        
        if HAS_GPIO:
            try:
                GPIO.cleanup()
            except:
                pass


# Global manager
doom_mgr = DoomManager()


# Flask routes
@blueprint.route('/')
def index():
    """Main DOOM page"""
    ok, msg = doom_mgr.verify_deps()
    return render_template('doom.html', deps_ok=ok, deps_msg=msg)


@blueprint.route('/api/start', methods=['POST'])
def api_start():
    """Start DOOM"""
    ok, msg = doom_mgr.start()
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg})


@blueprint.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop DOOM"""
    doom_mgr.stop()
    return jsonify({'status': 'ok'})


@blueprint.route('/api/frame')
def api_frame():
    """Get current frame as base64 JPEG"""
    if not _doom_state['current_frame']:
        return jsonify({'error': 'No frame yet'}), 404
    
    frame = _doom_state['current_frame']
    b64 = base64.b64encode(frame.data).decode('ascii')
    
    return jsonify({
        'data': f"data:image/jpeg;base64,{b64}",
        'frame_num': frame.frame_num,
        'timestamp': frame.timestamp
    })


@blueprint.route('/api/input', methods=['POST'])
def api_input():
    """Send input to DOOM"""
    data = request.json
    key = data.get('key')
    
    if key and doom_mgr.running:
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY_NUM
        doom_mgr.send_input(key, env)
        return jsonify({'status': 'ok'})
    
    return jsonify({'status': 'error', 'message': 'Not running or invalid key'}), 400


@blueprint.route('/api/status')
def api_status():
    """Get DOOM status"""
    return jsonify({
        'running': doom_mgr.running,
        'frame_count': doom_mgr.frame_count,
        'wad': doom_mgr.wad,
    })


# Template (save as /root/KTOx/templates/doom.html)
DOOM_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>🎮 DOOM</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            background: #000;
            color: #0f0;
            font-family: monospace;
            overflow: hidden;
        }
        
        .container {
            display: flex;
            flex-direction: column;
            height: 100vh;
            justify-content: center;
            align-items: center;
            gap: 20px;
        }
        
        #canvas {
            max-width: 90vw;
            max-height: 70vh;
            border: 2px solid #0f0;
            box-shadow: 0 0 20px rgba(0, 255, 0, 0.3);
            background: #000;
        }
        
        .controls {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: center;
        }
        
        button {
            padding: 10px 20px;
            background: #0a0;
            color: #000;
            border: 1px solid #0f0;
            font-family: monospace;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        button:hover {
            background: #0f0;
            box-shadow: 0 0 10px rgba(0, 255, 0, 0.5);
        }
        
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .status {
            text-align: center;
            font-size: 12px;
            color: #888;
        }
        
        .gamepad {
            display: grid;
            grid-template-columns: repeat(3, 60px);
            gap: 5px;
            margin-top: 20px;
        }
        
        .gamepad button {
            width: 60px;
            height: 60px;
            padding: 0;
            font-size: 12px;
        }
        
        .gamepad-spacer {
            grid-column: 2;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎮 DOOM 🎮</h1>
        
        <canvas id="canvas" width="320" height="200"></canvas>
        
        <div class="controls">
            <button id="btnStart" onclick="startDoom()">START</button>
            <button id="btnStop" onclick="stopDoom()" disabled>STOP</button>
        </div>
        
        <div class="gamepad">
            <button id="btnUp" onclick="sendInput('up')">↑</button>
            <div></div>
            <button id="btnMenu" onclick="sendInput('menu')">MENU</button>
            
            <button id="btnLeft" onclick="sendInput('left')">←</button>
            <button id="btnUse" onclick="sendInput('use')">USE</button>
            <button id="btnRight" onclick="sendInput('right')">→</button>
            
            <button id="btnDown" onclick="sendInput('down')">↓</button>
            <div></div>
            <button id="btnAttack" onclick="sendInput('attack')">FIRE</button>
        </div>
        
        <div class="status">
            <p id="status">Ready</p>
            <p id="frameCount">Frames: 0</p>
        </div>
    </div>
    
    <script>
        const canvas = document.getElementById('canvas');
        const ctx = canvas.getContext('2d');
        let running = false;
        let frameCount = 0;
        
        async function checkStatus() {
            try {
                const res = await fetch('/payloads/doom/api/status');
                const data = await res.json();
                running = data.running;
                frameCount = data.frame_count;
                
                document.getElementById('btnStart').disabled = running;
                document.getElementById('btnStop').disabled = !running;
                document.getElementById('frameCount').textContent = `Frames: ${frameCount}`;
                
                if (running) {
                    document.getElementById('status').textContent = 'Running...';
                    streamFrame();
                }
            } catch (e) {
                document.getElementById('status').textContent = `Error: ${e.message}`;
            }
        }
        
        async function startDoom() {
            try {
                const res = await fetch('/payloads/doom/api/start', { method: 'POST' });
                const data = await res.json();
                document.getElementById('status').textContent = data.message;
                
                if (data.status === 'ok') {
                    setTimeout(() => streamFrame(), 1000);
                }
            } catch (e) {
                document.getElementById('status').textContent = `Error: ${e.message}`;
            }
        }
        
        async function stopDoom() {
            try {
                await fetch('/payloads/doom/api/stop', { method: 'POST' });
                running = false;
                document.getElementById('status').textContent = 'Stopped';
                document.getElementById('btnStart').disabled = false;
                document.getElementById('btnStop').disabled = true;
            } catch (e) {
                document.getElementById('status').textContent = `Error: ${e.message}`;
            }
        }
        
        async function streamFrame() {
            if (!running) return;
            
            try {
                const res = await fetch('/payloads/doom/api/frame');
                const data = await res.json();
                
                const img = new Image();
                img.onload = () => {
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                };
                img.src = data.data;
            } catch (e) {
                console.error('Frame error:', e);
            }
            
            setTimeout(streamFrame, 66);  // ~15 FPS
        }
        
        async function sendInput(key) {
            try {
                await fetch('/payloads/doom/api/input', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key })
                });
            } catch (e) {
                console.error('Input error:', e);
            }
        }
        
        // Check status every second
        setInterval(checkStatus, 1000);
        checkStatus();
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    # For testing locally
    doom_mgr.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        doom_mgr.stop()
