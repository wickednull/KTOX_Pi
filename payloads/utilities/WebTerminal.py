#!/usr/bin/env python3
"""
KTOx Payload – Standalone Web Terminal (Pro Edition)
======================================================
Author: wickednull

Starts a standalone, high-performance web terminal on port 4242.
- Full xterm.js terminal with 256-color support.
- Real-time PTY bridging via SocketIO.
- Interactive bash shell with profile loading.
- Auto-scaling and window resize support.

LCD:
- Displays connection URL and QR code.
- K3 to exit and stop the server.
"""

import os
import sys
import time
import socket
import threading
import subprocess
import pty
import fcntl
import termios
import struct
import signal
import json
from flask import Flask, render_template_string
from flask_socketio import SocketIO

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
    print("KTOx hardware not found - LCD disabled")

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
PORT = 4242

if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    W, H = 128, 128
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except:
        font_sm = font_bold = ImageFont.load_default()

# ----------------------------------------------------------------------
# Flask & SocketIO setup
# ----------------------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
# Use eventlet or gevent if available for better performance
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Global PTY master
fd = None
child_pid = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx // WEB TERMINAL</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
    <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        body { 
            background: #000; 
            margin: 0; 
            padding: 10px; 
            overflow: hidden;
            font-family: 'Share Tech Mono', monospace;
        }
        #terminal { 
            height: calc(100vh - 20px); 
            width: 100%; 
            border: 1px solid #333;
        }
        .xterm-viewport::-webkit-scrollbar { width: 8px; }
        .xterm-viewport::-webkit-scrollbar-thumb { background: #444; }
        .header {
            color: #0f0;
            font-size: 12px;
            margin-bottom: 5px;
            display: flex;
            justify-content: space-between;
        }
    </style>
</head>
<body>
    <div class="header">
        <span>KTOx_Pi // STANDALONE TERMINAL</span>
        <span id="status" style="color:#f00;">CONNECTING...</span>
    </div>
    <div id="terminal"></div>
    <script>
        const term = new Terminal({
            cursorBlink: true,
            macOptionIsMeta: true,
            scrollback: 1000,
            theme: {
                background: '#000000',
                foreground: '#00ff00',
                cursor: '#ff0000',
                selectionBackground: '#333333'
            },
            fontFamily: 'monospace',
            fontSize: 14
        });
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        fitAddon.fit();

        const socket = io();

        socket.on('connect', () => {
            document.getElementById('status').innerText = 'CONNECTED';
            document.getElementById('status').style.color = '#0f0';
            socket.emit('resize', {'cols': term.cols, 'rows': term.rows});
        });

        socket.on('disconnect', () => {
            document.getElementById('status').innerText = 'DISCONNECTED';
            document.getElementById('status').style.color = '#f00';
        });

        socket.on('output', (data) => {
            term.write(data);
        });

        term.onData((data) => {
            socket.emit('input', data);
        });

        window.onresize = () => {
            fitAddon.fit();
            socket.emit('resize', {'cols': term.cols, 'rows': term.rows});
        };
        
        // Focus terminal on load
        term.focus();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('input')
def handle_input(data):
    if fd:
        os.write(fd, data.encode())

@socketio.on('resize')
def handle_resize(data):
    if fd:
        set_winsize(fd, data['rows'], data['cols'])

def set_winsize(fd, row, col, xpix=0, ypix=0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

def read_and_forward_output():
    global fd
    while True:
        if fd:
            try:
                # Use a larger buffer for high-throughput output (like 'top' or 'cat')
                data = os.read(fd, 8192)
                if data:
                    socketio.emit('output', data.decode(errors='replace'))
            except Exception:
                break
        socketio.sleep(0.01)

def start_bash():
    global fd, child_pid
    child_pid, fd = pty.fork()
    if child_pid == 0:
        # Child process
        os.environ["TERM"] = "xterm-256color"
        os.environ["SHELL"] = "/bin/bash"
        os.execv("/bin/bash", ["bash", "--login"])
    else:
        # Parent process
        socketio.start_background_task(read_and_forward_output)

# ----------------------------------------------------------------------
# LCD & Main loop
# ----------------------------------------------------------------------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def generate_qr(data):
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=3, border=2)
        qr.add_data(data)
        return qr.make_image(fill_color="white", back_color="black").get_image()
    except:
        return None

def lcd_loop():
    if not HAS_HW: return
    ip = get_local_ip()
    show_qr = False
    held = {}
    while True:
        now = time.time()
        img = Image.new("RGB", (W, H), "black")
        d = ImageDraw.Draw(img)
        
        if show_qr:
            qr_img = generate_qr(f"http://{ip}:{PORT}")
            if qr_img:
                qr_img = qr_img.resize((W, H))
                img.paste(qr_img, (0,0))
            else:
                d.text((10, 50), "QR Error", font=font_sm, fill="red")
        else:
            d.rectangle([(0,0),(128,18)], fill="#1a1a1a")
            d.text((4,3), "WEB TERMINAL", font=font_bold, fill="#00FF00")
            y = 25
            d.text((4,y), f"Status: ACTIVE", font=font_sm, fill="#888888"); y+=15
            d.text((4,y), f"URL:", font=font_sm, fill="#00AA00"); y+=12
            d.text((4,y), f"http://{ip}", font=font_sm, fill="white"); y+=12
            d.text((4,y), f"Port: {PORT}", font=font_sm, fill="white"); y+=25
            d.text((4,y), "K1=QR  K3=EXIT", font=font_sm, fill="#FF7777")
        
        LCD.LCD_ShowImage(img, 0, 0)
        
        pressed = {n: GPIO.input(p)==0 for n,p in PINS.items()}
        for n, down in pressed.items():
            if down:
                if n not in held: held[n] = now
            else:
                held.pop(n, None)
        
        def just_pressed(name, delay=0.2):
            return pressed.get(name) and (now - held.get(name, now)) <= delay

        if just_pressed("KEY3"):
            os.kill(os.getpid(), signal.SIGINT)
            break
        if just_pressed("KEY1"):
            show_qr = not show_qr
            time.sleep(0.3)
            
        time.sleep(0.1)

def main():
    start_bash()
    if HAS_HW:
        threading.Thread(target=lcd_loop, daemon=True).start()
    
    print(f"Web Terminal running at http://{get_local_ip()}:{PORT}")
    try:
        # Use eventlet as it's better for SocketIO performance
        socketio.run(app, host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        if child_pid:
            try: os.kill(child_pid, signal.SIGTERM)
            except: pass
        if HAS_HW:
            try:
                LCD.LCD_Clear()
                GPIO.cleanup()
            except: pass

if __name__ == "__main__":
    main()
