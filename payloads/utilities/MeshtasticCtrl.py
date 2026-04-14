#!/usr/bin/env python3
"""
KTOx Payload – Meshtastic T-Deck Plus Web Controller
======================================================
Author: wickednull

A full web UI for Meshtastic devices (T-Deck, T-Beam, etc.) connected via USB.
- Detects serial port automatically
- Provides nodes list, message history, send message, device info
- Runs on port 8888

Usage: python3 meshtastic_webui.py
Then open http://<KTOx-IP>:8888 in any browser.
"""

import os
import sys
import time
import threading
import subprocess
import json
from flask import Flask, render_template_string, request, jsonify

# ----------------------------------------------------------------------
# Meshtastic library check
# ----------------------------------------------------------------------
try:
    import meshtastic
    import meshtastic.serial_interface
    HAS_MESHTASTIC = True
except ImportError:
    HAS_MESHTASTIC = False
    print("ERROR: meshtastic library not installed. Run: pip install meshtastic")
    sys.exit(1)

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
WEB_PORT = 8888
interface = None
message_cache = []          # list of {'from': 'NodeName', 'text': '...', 'time': timestamp}
message_cache_max = 100
lock = threading.Lock()
app = Flask(__name__)

# ----------------------------------------------------------------------
# Auto‑detect serial port for T-Deck Plus
# ----------------------------------------------------------------------
def find_meshtastic_port():
    """Return the first serial port that looks like a Meshtastic device."""
    # Common patterns for T-Deck / CP210x / CH340
    candidates = []
    # List all tty devices
    try:
        for f in os.listdir('/dev'):
            if f.startswith('ttyACM') or f.startswith('ttyUSB'):
                candidates.append(f'/dev/{f}')
    except:
        pass
    # Try each candidate
    for port in candidates:
        try:
            # Quick test: try to open a serial interface
            test_iface = meshtastic.serial_interface.SerialInterface(port)
            test_iface.close()
            return port
        except:
            continue
    return None

# ----------------------------------------------------------------------
# Meshtastic event listener (runs in background)
# ----------------------------------------------------------------------
def on_message(packet, interface):
    """Callback when a message is received."""
    global message_cache
    try:
        decoded = packet.get('decoded', {})
        text = decoded.get('text', '')
        from_id = packet.get('fromId', 'unknown')
        if text:
            with lock:
                message_cache.append({
                    'from': from_id,
                    'text': text,
                    'time': time.time()
                })
                if len(message_cache) > message_cache_max:
                    message_cache.pop(0)
    except Exception as e:
        print(f"Message callback error: {e}")

def on_node(node, interface):
    """Callback when node information is updated."""
    # We'll just update the global node info; the API will fetch fresh data each request.
    pass

def start_meshtastic_listener():
    """Start the Meshtastic interface and register callbacks."""
    global interface
    port = find_meshtastic_port()
    if not port:
        print("No Meshtastic device found. Please connect your T-Deck Plus.")
        return False
    try:
        interface = meshtastic.serial_interface.SerialInterface(port)
        interface.onReceive = on_message
        interface.onNode = on_node
        print(f"Connected to Meshtastic device on {port}")
        return True
    except Exception as e:
        print(f"Failed to connect: {e}")
        return False

# ----------------------------------------------------------------------
# Flask Routes – Full Web UI
# ----------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=yes">
    <title>KTOx Mesh Control</title>
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            background: #0a0f0a;
            font-family: 'Segoe UI', 'Courier New', monospace;
            color: #cfc;
            margin: 0;
            padding: 16px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 {
            color: #0f0;
            border-left: 4px solid #0f0;
            padding-left: 16px;
            margin-top: 0;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: #111a11;
            border: 1px solid #2a3a2a;
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        .card h2 {
            margin-top: 0;
            font-size: 1.3rem;
            color: #8f8;
            border-bottom: 1px solid #2a4a2a;
            padding-bottom: 6px;
        }
        .node-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 16px;
            max-height: 200px;
            overflow-y: auto;
        }
        .node-item {
            background: #1a2a1a;
            padding: 6px 12px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: 0.1s;
            border: 1px solid #2a4a2a;
        }
        .node-item.selected {
            background: #2a6a2a;
            color: #fff;
            border-color: #0f0;
        }
        .message-area {
            background: #0a0f0a;
            border: 1px solid #2a3a2a;
            border-radius: 8px;
            padding: 8px;
            height: 250px;
            overflow-y: auto;
            font-size: 0.85rem;
        }
        .message {
            border-bottom: 1px solid #2a3a2a;
            padding: 6px 4px;
            font-family: monospace;
        }
        .message-time {
            color: #6a6;
            font-size: 0.7rem;
            margin-right: 10px;
        }
        .message-from {
            font-weight: bold;
            color: #8f8;
        }
        .message-text {
            word-break: break-word;
        }
        input, button {
            background: #1a2a1a;
            border: 1px solid #2a6a2a;
            color: #cfc;
            padding: 10px;
            border-radius: 6px;
            font-size: 1rem;
        }
        input {
            width: calc(100% - 100px);
        }
        button {
            cursor: pointer;
            width: 90px;
            margin-left: 8px;
        }
        button:hover {
            background: #2a6a2a;
            color: #000;
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 10px;
        }
        .status-badge {
            background: #1a2a1a;
            padding: 4px 10px;
            border-radius: 16px;
            font-size: 0.8rem;
        }
        pre {
            background: #0a0f0a;
            padding: 8px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 0.8rem;
            margin: 0;
        }
        footer {
            text-align: center;
            margin-top: 24px;
            color: #6a6;
            font-size: 0.7rem;
        }
        @media (max-width: 600px) {
            body { padding: 8px; }
            .card { padding: 12px; }
            input { width: calc(100% - 80px); }
            button { width: 70px; }
        }
    </style>
</head>
<body>
<div class="container">
    <h1>📡 KTOx Mesh Control</h1>
    <div class="grid">
        <!-- Left column: nodes + send -->
        <div>
            <div class="card">
                <h2>🌐 Nodes</h2>
                <div id="nodesList" class="node-list">Loading...</div>
                <div style="margin-top: 12px;">
                    <input type="text" id="messageInput" placeholder="Type your message...">
                    <button onclick="sendMessage()">Send</button>
                </div>
                <div id="sendStatus" style="font-size:0.8rem; margin-top:6px;"></div>
            </div>
            <div class="card">
                <h2>📟 Device Info</h2>
                <pre id="deviceInfo">Loading...</pre>
            </div>
        </div>
        <!-- Right column: messages -->
        <div class="card">
            <h2>💬 Messages</h2>
            <div id="messagesArea" class="message-area">Waiting for messages...</div>
        </div>
    </div>
    <footer>
        KTOx Meshtastic Controller | T-Deck Plus | Port 8888
    </footer>
</div>

<script>
    let selectedNode = null;

    async function fetchNodes() {
        try {
            const resp = await fetch('/api/nodes');
            const data = await resp.json();
            const container = document.getElementById('nodesList');
            if (!data.nodes || data.nodes.length === 0) {
                container.innerHTML = '<span style="color:#888;">No nodes found</span>';
                return;
            }
            let html = '';
            for (let node of data.nodes) {
                const name = node.short_name || node.long_name || node.id.slice(-6);
                const cls = (selectedNode === node.id) ? 'node-item selected' : 'node-item';
                html += `<div class="${cls}" onclick="selectNode('${node.id}')">${escapeHtml(name)}</div>`;
            }
            container.innerHTML = html;
        } catch(e) { console.error(e); }
    }

    function selectNode(id) {
        selectedNode = id;
        fetchNodes(); // refresh highlight
    }

    async function sendMessage() {
        const input = document.getElementById('messageInput');
        const text = input.value.trim();
        if (!text) return;
        const payload = { message: text };
        if (selectedNode) payload.node_id = selectedNode;
        try {
            const resp = await fetch('/api/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await resp.json();
            const statusDiv = document.getElementById('sendStatus');
            if (data.status === 'ok') {
                statusDiv.innerHTML = '✓ Sent';
                input.value = '';
                setTimeout(() => statusDiv.innerHTML = '', 2000);
            } else {
                statusDiv.innerHTML = '✗ ' + (data.error || 'Failed');
            }
        } catch(e) {
            document.getElementById('sendStatus').innerHTML = '✗ Network error';
        }
    }

    async function fetchMessages() {
        try {
            const resp = await fetch('/api/messages');
            const data = await resp.json();
            const container = document.getElementById('messagesArea');
            if (!data.messages || data.messages.length === 0) {
                container.innerHTML = '<div style="color:#888;">No messages yet</div>';
                return;
            }
            let html = '';
            for (let msg of data.messages.reverse()) {
                const timeStr = msg.time ? new Date(msg.time*1000).toLocaleTimeString() : '';
                html += `<div class="message">
                            <span class="message-time">[${timeStr}]</span>
                            <span class="message-from">${escapeHtml(msg.from)}:</span>
                            <span class="message-text">${escapeHtml(msg.text)}</span>
                         </div>`;
            }
            container.innerHTML = html;
            container.scrollTop = container.scrollHeight;
        } catch(e) { console.error(e); }
    }

    async function fetchDeviceInfo() {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            const pre = document.getElementById('deviceInfo');
            pre.textContent = JSON.stringify(data, null, 2);
        } catch(e) { console.error(e); }
    }

    function escapeHtml(str) {
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    setInterval(fetchNodes, 10000);
    setInterval(fetchMessages, 3000);
    setInterval(fetchDeviceInfo, 15000);
    fetchNodes();
    fetchMessages();
    fetchDeviceInfo();
</script>
</body>
</html>
"""

# ----------------------------------------------------------------------
# API endpoints
# ----------------------------------------------------------------------
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/nodes')
def api_nodes():
    """Return list of known nodes."""
    global interface
    if not interface:
        return jsonify({'nodes': [], 'error': 'Not connected'}), 500
    with lock:
        nodes = []
        for node_id, node in interface.nodes.items():
            nodes.append({
                'id': node_id,
                'long_name': getattr(node, 'long_name', ''),
                'short_name': getattr(node, 'short_name', ''),
                'battery': getattr(node, 'battery_level', -1),
                'snr': getattr(node, 'snr', 0)
            })
        return jsonify({'nodes': nodes})

@app.route('/api/messages')
def api_messages():
    """Return cached messages."""
    with lock:
        # Return copy of message_cache
        return jsonify({'messages': message_cache[-50:]})

@app.route('/api/status')
def api_status():
    """Return device status."""
    global interface
    if not interface:
        return jsonify({'connected': False}), 500
    try:
        my_info = interface.getMyNodeInfo()
        return jsonify({
            'connected': True,
            'my_node_id': my_info.get('my_node_num', 'unknown'),
            'firmware_version': my_info.get('firmware_version', 'unknown'),
            'has_gps': my_info.get('has_gps', False),
            'battery_level': my_info.get('battery_level', -1),
            'channel': interface.getChannel()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/send', methods=['POST'])
def api_send():
    """Send a text message."""
    global interface
    if not interface:
        return jsonify({'status': 'error', 'error': 'No device'}), 500
    data = request.get_json()
    text = data.get('message', '').strip()
    node_id = data.get('node_id')
    if not text:
        return jsonify({'status': 'error', 'error': 'Empty message'}), 400
    try:
        if node_id:
            interface.sendText(text, nodeId=node_id)
        else:
            interface.sendText(text)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

# ----------------------------------------------------------------------
# Background thread to keep interface alive (optional)
# ----------------------------------------------------------------------
def keep_alive():
    while True:
        time.sleep(30)
        if interface:
            try:
                # Ping to keep connection alive
                interface.getMyNodeInfo()
            except:
                pass

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    print("KTOx Meshtastic Web Controller starting...")
    if not HAS_MESHTASTIC:
        print("Meshtastic library not installed. Exiting.")
        return 1

    # Connect to device
    if not start_meshtastic_listener():
        print("Could not connect to any Meshtastic device. Make sure your T-Deck is plugged in.")
        return 1

    # Start background keep-alive
    threading.Thread(target=keep_alive, daemon=True).start()

    # Start Flask server
    print(f"\n✅ Web UI running at http://0.0.0.0:{WEB_PORT}")
    print("Open your browser and go to http://<KTOx-IP>:" + str(WEB_PORT))
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)

if __name__ == '__main__':
    main()
