#!/usr/bin/env python3
"""
KTOx-Loki Professional WebUI
============================
Canvas-based LCD display + real-time controls
Similar to RaspyJack's integration of Ragnar
"""

import os
import sys
import json
import threading
import time
import base64
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Configuration
KTOX_ROOT = "/root/KTOx"
LOOT_DIR = Path(KTOX_ROOT) / "loot"
LOKI_DATA = LOOT_DIR / "loki"
LOKI_PORT = 8000
LOKI_DIR = Path(KTOX_ROOT) / "vendor" / "loki" / "payloads" / "user" / "reconnaissance" / "loki"

# Create Flask app with CORS
app = Flask(__name__)
CORS(app)

# LCD Display State (shared between processes)
lcd_state = {
    'screen': None,  # PIL Image or bytes
    'last_update': 0,
    'running': False,
    'current_screen': 'welcome',
    'log_lines': [],
}

# Ensure data directories exist
for subdir in ["logs", "output/crackedpwd", "output/datastolen", "output/zombies", "output/vulnerabilities", "input"]:
    (LOKI_DATA / subdir).mkdir(parents=True, exist_ok=True)

# HTML/CSS/JS for Professional WebUI
WEBUI_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LOKI - KTOx Integration</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --loki-bg-0: #05060a;
            --loki-bg-1: #07090f;
            --loki-bg-2: #0f1b2d;
            --loki-accent: #10b981;
            --loki-accent-soft: rgba(16, 185, 129, 0.16);
            --loki-border: rgba(148, 163, 184, 0.2);
            --loki-text: #e2e8f0;
            --loki-text-muted: #94a3b8;
            --loki-shadow: 0 12px 30px rgba(2, 6, 23, 0.35);
        }

        body {
            background: radial-gradient(1200px 800px at 50% -10%, var(--loki-bg-2) 0%, var(--loki-bg-1) 55%, var(--loki-bg-0) 100%);
            color: var(--loki-text);
            font-family: 'Inter', sans-serif;
        }

        .device-shell {
            background: linear-gradient(145deg, rgba(15,23,42,.65), rgba(15,23,42,.35));
            border: 1px solid rgba(16,185,129,.2);
            box-shadow: 0 0 0 1px rgba(116,255,180,.2), 0 0 25px rgba(18,255,120,.15) inset, 0 0 40px rgba(18,255,120,.15);
            backdrop-filter: blur(8px);
            border-radius: 24px;
        }

        .screen-frame {
            border: 1px solid rgba(16,185,129,.3);
            background: rgba(0,0,0,.8);
            box-shadow: 0 0 40px rgba(18,255,120,0.18);
            border-radius: 8px;
        }

        canvas {
            display: block;
            background: #000;
            border-radius: 4px;
            image-rendering: pixelated;
            image-rendering: -moz-crisp-edges;
            image-rendering: crisp-edges;
        }

        .rj-btn {
            transition: all 0.15s ease;
            background: rgba(30,41,59,0.8) !important;
            border: 1px solid rgba(148,163,184,0.25) !important;
            box-shadow: 0 0 0 1px rgba(160,160,255,.25), 0 0 18px rgba(120,120,255,.18) inset !important;
        }

        .rj-btn:hover {
            background: rgba(51,65,85,0.95) !important;
            box-shadow: 0 0 0 1px rgba(160,160,255,.4), 0 0 24px rgba(120,120,255,.25) inset !important;
        }

        .rj-btn:active, .rj-btn.active {
            filter: brightness(1.2);
            transform: scale(0.98);
        }

        .ok-btn {
            background: rgba(16, 185, 129, 0.3) !important;
            box-shadow: 0 0 0 1px rgba(16,185,129,.4), 0 0 18px rgba(16,185,129,.25) inset !important;
        }

        .ok-btn:hover {
            background: rgba(16, 185, 129, 0.4) !important;
            box-shadow: 0 0 0 1px rgba(16,185,129,.6), 0 0 24px rgba(16,185,129,.35) inset !important;
        }

        .key-btn {
            background: rgba(168, 85, 247, 0.3) !important;
            box-shadow: 0 0 0 1px rgba(168,85,247,.4), 0 0 18px rgba(168,85,247,.2) inset !important;
        }

        .key-btn:hover {
            background: rgba(168, 85, 247, 0.4) !important;
            box-shadow: 0 0 0 1px rgba(168,85,247,.6), 0 0 24px rgba(168,85,247,.3) inset !important;
        }

        .nav-active {
            background: rgba(16, 185, 129, 0.1) !important;
            border-color: rgba(16, 185, 129, 0.3) !important;
            box-shadow: 0 0 12px rgba(16,185,129,.25) !important;
        }

        .status-tone-ok { color: #34d399 !important; text-shadow: 0 0 10px rgba(16,185,129,.28); }
        .status-tone-warn { color: #fbbf24 !important; }
        .status-tone-bad { color: #fb7185 !important; }

        .terminal-wrap {
            background: transparent;
            border-radius: 12px;
            overflow: hidden;
        }

        .log-container {
            background: rgba(0,0,0,.8);
            border: 1px solid rgba(16,185,129,.2);
            border-radius: 8px;
            height: 300px;
            overflow-y: auto;
            padding: 12px;
            font-size: 12px;
            font-family: 'Courier New', monospace;
        }

        .log-line { margin: 2px 0; }
        .log-success { color: #34d399; }
        .log-error { color: #fb7185; }
        .log-warning { color: #fbbf24; }
        .log-info { color: #00ffff; }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .status-running { animation: pulse 1.5s ease-in-out infinite; }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .button-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px;
            margin-top: 12px;
        }

        @media (max-width: 768px) {
            .device-shell { transform: scale(0.9); transform-origin: top center; }
        }
    </style>
</head>
<body class="min-h-screen">
    <div class="min-h-screen lg:flex">
        <!-- Sidebar -->
        <aside class="w-64 bg-slate-950/60 border-r border-slate-800/70 backdrop-blur p-4 space-y-4">
            <div class="flex items-center gap-3 mb-6">
                <div class="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                    <i class="fas fa-bolt text-emerald-400"></i>
                </div>
                <div>
                    <div class="font-bold text-emerald-400">LOKI</div>
                    <div class="text-xs text-slate-400">Security Engine</div>
                </div>
            </div>

            <nav class="space-y-2">
                <button onclick="switchTab('device')" class="w-full px-3 py-2 rounded-lg text-left text-sm font-semibold border border-slate-700/20 bg-slate-800/40 text-slate-300 hover:text-white hover:bg-slate-700/50 nav-btn nav-active" data-tab="device">
                    <i class="fas fa-gamepad mr-2"></i>Device
                </button>
                <button onclick="switchTab('reconnaissance')" class="w-full px-3 py-2 rounded-lg text-left text-sm font-semibold border border-slate-700/20 bg-slate-800/40 text-slate-300 hover:text-white hover:bg-slate-700/50 nav-btn" data-tab="reconnaissance">
                    <i class="fas fa-radar mr-2"></i>Reconnaissance
                </button>
                <button onclick="switchTab('exploitation')" class="w-full px-3 py-2 rounded-lg text-left text-sm font-semibold border border-slate-700/20 bg-slate-800/40 text-slate-300 hover:text-white hover:bg-slate-700/50 nav-btn" data-tab="exploitation">
                    <i class="fas fa-crosshairs mr-2"></i>Exploitation
                </button>
                <button onclick="switchTab('loot')" class="w-full px-3 py-2 rounded-lg text-left text-sm font-semibold border border-slate-700/20 bg-slate-800/40 text-slate-300 hover:text-white hover:bg-slate-700/50 nav-btn" data-tab="loot">
                    <i class="fas fa-vault mr-2"></i>Loot
                </button>
                <button onclick="switchTab('logs')" class="w-full px-3 py-2 rounded-lg text-left text-sm font-semibold border border-slate-700/20 bg-slate-800/40 text-slate-300 hover:text-white hover:bg-slate-700/50 nav-btn" data-tab="logs">
                    <i class="fas fa-book mr-2"></i>Logs
                </button>
            </nav>

            <div class="pt-4 border-t border-slate-700/50">
                <div class="text-xs font-semibold text-emerald-300 mb-2">Status</div>
                <div class="text-[11px] space-y-1 text-slate-400">
                    <div>
                        <span id="status-indicator" class="inline-block w-2 h-2 rounded-full bg-yellow-500 mr-2"></span>
                        <span id="status-text">Initializing...</span>
                    </div>
                    <div>Port: <span id="status-port" class="text-slate-300">8000</span></div>
                    <div>Uptime: <span id="status-uptime" class="text-slate-300">--:--:--</span></div>
                </div>
            </div>
        </aside>

        <!-- Main Content -->
        <main class="flex-1 p-6 space-y-6">
            <!-- Device Tab -->
            <div id="device" class="tab-content active">
                <div class="grid lg:grid-cols-2 gap-6">
                    <!-- LCD Display -->
                    <div>
                        <div class="mb-4">
                            <div class="text-sm font-semibold text-emerald-300 mb-2">
                                <i class="fas fa-screen-users mr-2"></i>LCD Display (128x128)
                            </div>
                        </div>

                        <div class="device-shell p-6">
                            <div class="screen-frame p-2">
                                <canvas id="lcdCanvas" width="128" height="128" class="w-full max-w-xs mx-auto"></canvas>
                            </div>

                            <!-- D-Pad and Buttons -->
                            <div class="mt-6 grid grid-cols-[auto_auto_auto] gap-3 justify-center">
                                <div></div>
                                <button class="rj-btn w-12 h-12 rounded-lg flex items-center justify-center" onclick="sendButton('UP')" title="UP">
                                    <i class="fas fa-arrow-up"></i>
                                </button>
                                <div></div>

                                <button class="rj-btn w-12 h-12 rounded-lg flex items-center justify-center" onclick="sendButton('LEFT')" title="LEFT">
                                    <i class="fas fa-arrow-left"></i>
                                </button>
                                <button class="ok-btn w-12 h-12 rounded-lg flex items-center justify-center text-lg font-bold" onclick="sendButton('OK')" title="OK">
                                    OK
                                </button>
                                <button class="rj-btn w-12 h-12 rounded-lg flex items-center justify-center" onclick="sendButton('RIGHT')" title="RIGHT">
                                    <i class="fas fa-arrow-right"></i>
                                </button>

                                <div></div>
                                <button class="rj-btn w-12 h-12 rounded-lg flex items-center justify-center" onclick="sendButton('DOWN')" title="DOWN">
                                    <i class="fas fa-arrow-down"></i>
                                </button>
                                <div></div>
                            </div>

                            <!-- Side Buttons -->
                            <div class="mt-4 space-y-2">
                                <button class="key-btn w-full py-2 rounded-lg text-sm font-semibold" onclick="sendButton('KEY1')">KEY1</button>
                                <button class="key-btn w-full py-2 rounded-lg text-sm font-semibold" onclick="sendButton('KEY2')">KEY2</button>
                                <button class="key-btn w-full py-2 rounded-lg text-sm font-semibold" onclick="sendButton('KEY3')">KEY3</button>
                            </div>
                        </div>
                    </div>

                    <!-- Info Panel -->
                    <div class="space-y-4">
                        <div class="rounded-lg border border-slate-700/60 bg-slate-950/40 p-4">
                            <div class="text-sm font-semibold text-emerald-300 mb-3">
                                <i class="fas fa-info-circle mr-2"></i>Device Status
                            </div>
                            <div class="text-sm space-y-2 text-slate-300">
                                <div class="flex justify-between">
                                    <span class="text-slate-400">Status:</span>
                                    <span id="info-status" class="status-tone-ok">RUNNING</span>
                                </div>
                                <div class="flex justify-between">
                                    <span class="text-slate-400">Interface:</span>
                                    <span id="info-interface" class="text-slate-200">eth0</span>
                                </div>
                                <div class="flex justify-between">
                                    <span class="text-slate-400">IP Address:</span>
                                    <span id="info-ip" class="text-slate-200">--</span>
                                </div>
                                <div class="flex justify-between">
                                    <span class="text-slate-400">WebUI:</span>
                                    <span class="text-slate-200">:8000</span>
                                </div>
                            </div>
                        </div>

                        <div class="rounded-lg border border-slate-700/60 bg-slate-950/40 p-4">
                            <div class="text-sm font-semibold text-emerald-300 mb-3">
                                <i class="fas fa-zap mr-2"></i>Quick Actions
                            </div>
                            <div class="space-y-2">
                                <button onclick="quickAction('scan')" class="w-full px-3 py-2 rounded-lg bg-emerald-600/80 hover:bg-emerald-500/80 text-white text-sm font-semibold transition">
                                    <i class="fas fa-magnifying-glass mr-2"></i>Network Scan
                                </button>
                                <button onclick="quickAction('stop')" class="w-full px-3 py-2 rounded-lg bg-rose-600/80 hover:bg-rose-500/80 text-white text-sm font-semibold transition">
                                    <i class="fas fa-stop mr-2"></i>Stop All
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Reconnaissance Tab -->
            <div id="reconnaissance" class="tab-content">
                <div class="rounded-lg border border-slate-700/60 bg-slate-950/40 p-4">
                    <div class="text-sm font-semibold text-emerald-300 mb-4">
                        <i class="fas fa-radar mr-2"></i>Network Reconnaissance
                    </div>
                    <div class="grid md:grid-cols-2 gap-3">
                        <button onclick="action('scan')" class="px-4 py-2 rounded-lg bg-slate-800/70 hover:bg-slate-700/70 text-slate-200 text-sm font-semibold border border-slate-600/40 transition">
                            <i class="fas fa-wifi mr-2"></i>Network Scan
                        </button>
                        <button onclick="action('enumerate')" class="px-4 py-2 rounded-lg bg-slate-800/70 hover:bg-slate-700/70 text-slate-200 text-sm font-semibold border border-slate-600/40 transition">
                            <i class="fas fa-list mr-2"></i>Enumerate Services
                        </button>
                        <button onclick="action('discover')" class="px-4 py-2 rounded-lg bg-slate-800/70 hover:bg-slate-700/70 text-slate-200 text-sm font-semibold border border-slate-600/40 transition">
                            <i class="fas fa-network-wired mr-2"></i>Host Discovery
                        </button>
                        <button onclick="action('fingerprint')" class="px-4 py-2 rounded-lg bg-slate-800/70 hover:bg-slate-700/70 text-slate-200 text-sm font-semibold border border-slate-600/40 transition">
                            <i class="fas fa-fingerprint mr-2"></i>Fingerprint
                        </button>
                    </div>
                </div>
            </div>

            <!-- Exploitation Tab -->
            <div id="exploitation" class="tab-content">
                <div class="rounded-lg border border-slate-700/60 bg-slate-950/40 p-4">
                    <div class="text-sm font-semibold text-emerald-300 mb-4">
                        <i class="fas fa-crosshairs mr-2"></i>Exploitation Tools
                    </div>
                    <div class="grid md:grid-cols-3 gap-3">
                        <button onclick="attack('kick_one')" class="px-4 py-2 rounded-lg bg-amber-600/70 hover:bg-amber-500/70 text-white text-sm font-semibold border border-amber-500/30 transition">
                            <i class="fas fa-bolt mr-2"></i>Kick ONE
                        </button>
                        <button onclick="attack('kick_all')" class="px-4 py-2 rounded-lg bg-amber-600/70 hover:bg-amber-500/70 text-white text-sm font-semibold border border-amber-500/30 transition">
                            <i class="fas fa-cloud-bolt mr-2"></i>Kick ALL
                        </button>
                        <button onclick="attack('mitm')" class="px-4 py-2 rounded-lg bg-amber-600/70 hover:bg-amber-500/70 text-white text-sm font-semibold border border-amber-500/30 transition">
                            <i class="fas fa-exchange mr-2"></i>ARP MITM
                        </button>
                        <button onclick="attack('flood')" class="px-4 py-2 rounded-lg bg-amber-600/70 hover:bg-amber-500/70 text-white text-sm font-semibold border border-amber-500/30 transition">
                            <i class="fas fa-water mr-2"></i>ARP Flood
                        </button>
                        <button onclick="attack('cage')" class="px-4 py-2 rounded-lg bg-amber-600/70 hover:bg-amber-500/70 text-white text-sm font-semibold border border-amber-500/30 transition">
                            <i class="fas fa-ban mr-2"></i>ARP Cage
                        </button>
                        <button onclick="attack('ntlm')" class="px-4 py-2 rounded-lg bg-amber-600/70 hover:bg-amber-500/70 text-white text-sm font-semibold border border-amber-500/30 transition">
                            <i class="fas fa-key mr-2"></i>NTLM Capture
                        </button>
                    </div>
                </div>
            </div>

            <!-- Loot Tab -->
            <div id="loot" class="tab-content">
                <div class="rounded-lg border border-slate-700/60 bg-slate-950/40 p-4">
                    <div class="text-sm font-semibold text-emerald-300 mb-4">
                        <i class="fas fa-vault mr-2"></i>Captured Loot
                    </div>
                    <div class="space-y-2" id="loot-list">
                        <div class="text-slate-400 text-sm">Loading...</div>
                    </div>
                </div>
            </div>

            <!-- Logs Tab -->
            <div id="logs" class="tab-content">
                <div class="rounded-lg border border-slate-700/60 bg-slate-950/40 p-4">
                    <div class="text-sm font-semibold text-emerald-300 mb-4">
                        <i class="fas fa-book mr-2"></i>Activity Log
                    </div>
                    <div class="log-container" id="log-container">
                        <div class="log-line log-info">[*] Loki WebUI initialized</div>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        const API_BASE = '/api';
        let canvas = document.getElementById('lcdCanvas');
        let ctx = canvas ? canvas.getContext('2d') : null;
        let startTime = Date.now();

        function switchTab(tabName) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('nav-active'));

            // Show selected tab
            const tab = document.getElementById(tabName);
            if (tab) {
                tab.classList.add('active');
            }

            // Highlight nav button
            document.querySelector(`[data-tab="${tabName}"]`)?.classList.add('nav-active');
        }

        function log(message, level = 'info') {
            const container = document.getElementById('log-container');
            const line = document.createElement('div');
            line.className = `log-line log-${level}`;
            const time = new Date().toLocaleTimeString();
            line.textContent = `[${time}] ${message}`;
            container.appendChild(line);
            container.scrollTop = container.scrollHeight;
        }

        function sendButton(btn) {
            console.log('Button pressed:', btn);
            fetch(API_BASE + '/input', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ button: btn })
            }).catch(e => console.error('Error:', e));
        }

        function action(type) {
            log(`Started: ${type}`, 'warning');
            fetch(API_BASE + '/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ type: type })
            }).then(r => r.json())
            .then(data => log(data.message || 'Action started', 'success'))
            .catch(e => log(`Error: ${e}`, 'error'));
        }

        function attack(type) {
            log(`Attack: ${type}`, 'warning');
            fetch(API_BASE + '/attack', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ type: type })
            }).then(r => r.json())
            .then(data => log(data.message || 'Attack started', 'success'))
            .catch(e => log(`Error: ${e}`, 'error'));
        }

        function quickAction(type) {
            if (type === 'scan') action('scan');
            if (type === 'stop') log('Stopping all operations...', 'warning');
        }

        function updateStatus() {
            fetch(API_BASE + '/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('status-text').textContent = data.status || 'RUNNING';
                    document.getElementById('status-indicator').className =
                        'inline-block w-2 h-2 rounded-full mr-2 ' +
                        (data.status === 'RUNNING' ? 'bg-green-500 status-running' : 'bg-yellow-500');
                    document.getElementById('info-status').textContent = data.status || 'RUNNING';
                    document.getElementById('info-ip').textContent = data.ip || '--';
                })
                .catch(e => console.error('Status error:', e));
        }

        function updateLoot() {
            fetch(API_BASE + '/loot')
                .then(r => r.json())
                .then(data => {
                    const container = document.getElementById('loot-list');
                    container.innerHTML = '';
                    if (data.items && data.items.length > 0) {
                        data.items.forEach(item => {
                            const div = document.createElement('div');
                            div.className = 'flex items-center justify-between px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/30';
                            div.innerHTML = `
                                <span class="text-slate-300 text-sm"><i class="fas fa-folder mr-2"></i>${item.type}</span>
                                <span class="text-emerald-400 text-sm font-semibold">${item.count}</span>
                            `;
                            container.appendChild(div);
                        });
                    } else {
                        container.innerHTML = '<div class="text-slate-400 text-sm">No data captured yet</div>';
                    }
                })
                .catch(e => console.error('Loot error:', e));
        }

        function updateCanvas() {
            if (!ctx) return;
            fetch(API_BASE + '/screen')
                .then(r => r.json())
                .then(data => {
                    if (data.image) {
                        const img = new Image();
                        img.onload = function() {
                            ctx.drawImage(img, 0, 0);
                        };
                        img.src = 'data:image/png;base64,' + data.image;
                    }
                })
                .catch(e => {
                    // Draw placeholder
                    ctx.fillStyle = '#000';
                    ctx.fillRect(0, 0, 128, 128);
                    ctx.fillStyle = '#0f0';
                    ctx.font = '10px monospace';
                    ctx.fillText('Loki Ready', 35, 60);
                });
        }

        function updateUptime() {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const h = Math.floor(elapsed / 3600);
            const m = Math.floor((elapsed % 3600) / 60);
            const s = elapsed % 60;
            document.getElementById('status-uptime').textContent =
                `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }

        // Initialize
        updateStatus();
        updateLoot();
        updateCanvas();
        setInterval(updateStatus, 10000);
        setInterval(updateLoot, 5000);
        setInterval(updateCanvas, 1000);
        setInterval(updateUptime, 1000);

        log('WebUI initialized', 'success');
    </script>
</body>
</html>
'''

# API Routes
@app.route('/')
def index():
    return render_template_string(WEBUI_HTML)

@app.route('/api/status')
def api_status():
    return jsonify({
        'status': 'RUNNING',
        'port': LOKI_PORT,
        'ip': '192.168.1.x',  # Would get actual IP
        'uptime': 'N/A',
    })

@app.route('/api/screen')
def api_screen():
    """Return current LCD screen as base64 image"""
    if HAS_PIL:
        img = Image.new('RGB', (128, 128), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 118, 118], outline=(0, 255, 0))
        draw.text((20, 50), 'LOKI', fill=(0, 255, 0))

        # Convert to base64
        import io
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        return jsonify({'image': img_base64})
    return jsonify({'image': None})

@app.route('/api/input', methods=['POST'])
def api_input():
    """Handle button input"""
    data = request.json or {}
    button = data.get('button', 'UNKNOWN')
    print(f"[Loki] Button pressed: {button}")
    return jsonify({'status': 'ok', 'button': button})

@app.route('/api/action', methods=['POST'])
def api_action():
    """Handle reconnaissance actions"""
    data = request.json or {}
    action_type = data.get('type', 'unknown')
    return jsonify({
        'status': 'ok',
        'message': f'{action_type.upper()} action started',
        'type': action_type
    })

@app.route('/api/attack', methods=['POST'])
def api_attack():
    """Handle exploitation attacks"""
    data = request.json or {}
    attack_type = data.get('type', 'unknown')
    return jsonify({
        'status': 'ok',
        'message': f'{attack_type.upper()} attack initiated',
        'type': attack_type
    })

@app.route('/api/loot')
def api_loot():
    """List captured loot"""
    items = []
    loot_dir = LOKI_DATA / 'output'

    if loot_dir.exists():
        for subdir in loot_dir.iterdir():
            if subdir.is_dir():
                count = len(list(subdir.glob('*')))
                if count > 0:
                    items.append({
                        'type': subdir.name.replace('_', ' ').title(),
                        'count': count
                    })

    return jsonify({'items': items})

if __name__ == '__main__':
    print("[Loki] Professional WebUI starting on http://0.0.0.0:8000")
    print("[Loki] Features:")
    print("  - Canvas-based LCD display (128x128)")
    print("  - D-Pad + OK + KEY1/2/3 controls")
    print("  - Reconnaissance & Exploitation tabs")
    print("  - Real-time loot and log display")
    print("[Loki] Data directory: " + str(LOKI_DATA))

    app.run(
        host='0.0.0.0',
        port=LOKI_PORT,
        debug=False,
        threaded=True
    )
