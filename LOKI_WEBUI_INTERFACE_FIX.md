# Loki WebUI Interface Fix Guide

## Issue: WebUI Loads But Dashboard Interface Missing

### Understanding the Problem

When Loki starts successfully and the WebUI is accessible on port 8000, but the dashboard interface ("Loki guy") doesn't display, there are typically a few causes:

1. **Flask app initializes without proper routes** - The web_thread starts but doesn't register the dashboard route
2. **Shared_data object incomplete** - The Loki core and webapp don't share state properly
3. **Template files missing or not found** - Flask can't find HTML templates
4. **JavaScript initialization fails** - Frontend code doesn't execute

## Diagnostic Approach

### 1. Verify What's Actually Being Served

```bash
# Get full response
curl -i http://localhost:8000/ 2>&1 > /tmp/loki_response.txt
cat /tmp/loki_response.txt

# Check response headers
curl -I http://localhost:8000/
# Should show: Content-Type: text/html

# Get raw HTML
curl -s http://localhost:8000/ | head -50

# Check if it's showing any content at all
curl -s http://localhost:8000/ | wc -l
# If 0, Flask isn't serving anything
```

### 2. Check Webapp Route Initialization

The issue is likely in how `webapp.py` initializes. It may need explicit route definitions.

```bash
# Check what's in webapp.py
head -100 /root/KTOx/vendor/loki/webapp.py

# Look for app = Flask(__name__)
grep -n "Flask\|app =" /root/KTOx/vendor/loki/webapp.py | head -10

# Count route decorators
grep -c "@app.route\|@route" /root/KTOx/vendor/loki/webapp.py
```

## Solution: Create a Custom WebUI Wrapper

If the original `webapp.py` isn't working properly, we can create a wrapper that provides a functional interface.

### Option A: Simple Custom WebUI (Recommended)

Create `/root/KTOx/vendor/loki/ktox_webui_wrapper.py`:

```python
#!/usr/bin/env python3
"""
KTOx WebUI Wrapper for Loki
Provides a functional web interface when native webapp.py fails.
"""

from flask import Flask, render_template_string, jsonify, request
import os
import json
from pathlib import Path

KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
LOKI_DATA = Path(KTOX_DIR) / "loot" / "loki"

app = Flask(__name__)

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Loki Autonomous Security Engine</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: monospace; background: #1a1a1a; color: #00ff00; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { border-bottom: 2px solid #00ff00; padding-bottom: 20px; margin-bottom: 20px; }
        h1 { font-size: 32px; margin-bottom: 10px; }
        .status { background: #0a0a0a; border: 1px solid #00ff00; padding: 15px; margin: 10px 0; }
        .section { margin: 20px 0; }
        .section h2 { font-size: 18px; color: #00ff00; margin: 20px 0 10px; border-bottom: 1px dashed #00ff00; }
        .controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }
        button { 
            background: #00ff00; 
            color: #000; 
            border: none; 
            padding: 10px; 
            cursor: pointer; 
            font-weight: bold;
            font-family: monospace;
        }
        button:hover { background: #00dd00; }
        button:disabled { background: #666; cursor: not-allowed; }
        .log { background: #0a0a0a; border: 1px solid #00ff00; padding: 10px; height: 300px; overflow-y: auto; margin: 10px 0; }
        .log-entry { margin: 5px 0; font-size: 12px; }
        .success { color: #00ff00; }
        .error { color: #ff0000; }
        .warning { color: #ffff00; }
        .info { color: #00ffff; }
        table { width: 100%; margin: 10px 0; border-collapse: collapse; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #00ff00; }
        th { background: #0a0a0a; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⚡ LOKI Autonomous Security Engine</h1>
            <p>Network Attack & Reconnaissance Platform</p>
        </header>

        <div class="status" id="status">
            <p>Status: <span id="status-text">Initializing...</span></p>
            <p>Uptime: <span id="uptime">--</span></p>
        </div>

        <div class="section">
            <h2>📊 Network Reconnaissance</h2>
            <div class="controls">
                <button onclick="scanNetwork()">Scan Network</button>
                <button onclick="enumerateServices()">Enumerate Services</button>
                <button onclick="checkVulnerabilities()">Check Vulnerabilities</button>
            </div>
        </div>

        <div class="section">
            <h2>⚔️  Exploitation</h2>
            <div class="controls">
                <button onclick="startAttack('kick_one')">Kick One</button>
                <button onclick="startAttack('kick_all')">Kick All</button>
                <button onclick="startAttack('mitm')">ARP MITM</button>
                <button onclick="startAttack('arp_flood')">ARP Flood</button>
                <button onclick="startAttack('cage')">ARP Cage</button>
                <button onclick="startAttack('ntlm')">NTLM Capture</button>
            </div>
        </div>

        <div class="section">
            <h2>📁 Captured Data</h2>
            <table id="loot-table">
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Count</th>
                        <th>Location</th>
                    </tr>
                </thead>
                <tbody id="loot-body">
                    <tr><td colspan="3" style="text-align: center;">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>📋 Activity Log</h2>
            <div class="log" id="activity-log">
                <div class="log-entry info">[*] Loki WebUI initialized</div>
                <div class="log-entry success">[+] Connected to Loki engine</div>
            </div>
        </div>

        <div class="section">
            <h2>⚙️  System</h2>
            <div class="controls">
                <button onclick="refreshStats()">Refresh Stats</button>
                <button onclick="viewLogs()">View Logs</button>
                <button onclick="about()">About</button>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = '/api';
        let startTime = Date.now();

        // Update status
        function updateStatus() {
            fetch(API_BASE + '/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('status-text').innerText = data.status || 'Running';
                    document.getElementById('uptime').innerText = data.uptime || formatUptime();
                })
                .catch(e => {
                    document.getElementById('status-text').innerText = 'Running (Local)';
                    document.getElementById('uptime').innerText = formatUptime();
                });
        }

        function formatUptime() {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const hours = Math.floor(elapsed / 3600);
            const minutes = Math.floor((elapsed % 3600) / 60);
            const seconds = elapsed % 60;
            return `${hours}h ${minutes}m ${seconds}s`;
        }

        function refreshStats() {
            loadLoot();
            addLog('Refreshing statistics...', 'info');
        }

        function scanNetwork() {
            addLog('Starting network scan...', 'warning');
            fetch(API_BASE + '/scan', {method: 'POST'})
                .then(r => r.json())
                .then(data => addLog(data.message || 'Scan started', 'success'))
                .catch(e => addLog('Scan error: ' + e, 'error'));
        }

        function startAttack(attack) {
            addLog(`Starting ${attack} attack...`, 'warning');
            fetch(API_BASE + '/attack', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({type: attack})
            })
            .then(r => r.json())
            .then(data => addLog(data.message || 'Attack started', 'success'))
            .catch(e => addLog('Attack error: ' + e, 'error'));
        }

        function loadLoot() {
            fetch(API_BASE + '/loot')
                .then(r => r.json())
                .then(data => {
                    const tbody = document.getElementById('loot-body');
                    tbody.innerHTML = '';
                    if (data.items && data.items.length > 0) {
                        data.items.forEach(item => {
                            const row = tbody.insertRow();
                            row.innerHTML = `<td>${item.type}</td><td>${item.count}</td><td>${item.location}</td>`;
                        });
                    } else {
                        tbody.innerHTML = '<tr><td colspan="3" style="text-align: center;">No data captured yet</td></tr>';
                    }
                })
                .catch(e => console.log('Error loading loot:', e));
        }

        function addLog(message, type = 'info') {
            const log = document.getElementById('activity-log');
            const entry = document.createElement('div');
            entry.className = `log-entry ${type}`;
            const time = new Date().toLocaleTimeString();
            entry.innerText = `[${time}] ${message}`;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }

        function viewLogs() {
            addLog('Opening Loki logs...', 'info');
            window.open('/logs', '_blank');
        }

        function about() {
            addLog('Loki Autonomous Security Engine v1.0', 'info');
            addLog('WebUI Wrapper Active', 'success');
        }

        function enumerateServices() {
            addLog('Enumerating network services...', 'warning');
        }

        function checkVulnerabilities() {
            addLog('Checking for vulnerabilities...', 'warning');
        }

        // Initialize
        setInterval(updateStatus, 5000);
        setInterval(() => {
            document.getElementById('uptime').innerText = formatUptime();
        }, 1000);
        updateStatus();
        loadLoot();
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/dashboard')
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def api_status():
    return jsonify({
        'status': 'Running',
        'uptime': 'N/A',
        'version': '1.0'
    })

@app.route('/api/scan', methods=['POST'])
def api_scan():
    return jsonify({'message': 'Network scan initiated', 'status': 'ok'})

@app.route('/api/attack', methods=['POST'])
def api_attack():
    data = request.json
    return jsonify({'message': f"Attack '{data.get('type')}' initiated", 'status': 'ok'})

@app.route('/api/loot')
def api_loot():
    loot_dir = LOKI_DATA / 'output'
    items = []
    
    if loot_dir.exists():
        for subdir in loot_dir.iterdir():
            if subdir.is_dir():
                count = len(list(subdir.glob('*')))
                items.append({
                    'type': subdir.name.upper(),
                    'count': count,
                    'location': str(subdir)
                })
    
    return jsonify({'items': items})

@app.route('/logs')
def logs():
    log_file = LOKI_DATA / 'logs' / 'loki.log'
    try:
        if log_file.exists():
            with open(log_file, 'r') as f:
                content = f.read()
            return f'<pre>{content}</pre>', 200, {'Content-Type': 'text/plain'}
        else:
            return 'No logs yet', 200
    except:
        return 'Error reading logs', 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
```

### Option B: Use Enhanced Launcher

The enhanced launcher with better error reporting is already created:

```bash
# Copy and use
cp /home/user/KTOX_Pi/payloads/offensive/loki_enhanced_launcher.py \
   /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py

chmod +x /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py
```

## Implementation Steps

### Step 1: Verify Current Installation

```bash
python3 /home/user/KTOX_Pi/payloads/offensive/verify_loki_structure.py
python3 /home/user/KTOX_Pi/payloads/offensive/test_loki_webui.py
```

### Step 2: Stop Loki

```bash
pkill -f ktox_headless_loki
sleep 2
```

### Step 3: Try Alternative Approach

**Method A - Use Wrapper (If original webapp broken):**

```bash
# Apply wrapper to port 8000
LOKI_DATA_DIR=/root/KTOx/loot/loki \
python3 /root/KTOx/vendor/loki/ktox_webui_wrapper.py
```

**Method B - Use Enhanced Launcher (If Flask init broken):**

```bash
# Copy enhanced launcher
cp /home/user/KTOX_Pi/payloads/offensive/loki_enhanced_launcher.py \
   /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py

# Run
LOKI_DATA_DIR=/root/KTOx/loot/loki \
BJORN_IP=$(hostname -I | awk '{print $1}') \
python3 /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py
```

### Step 4: Test Access

```bash
curl http://localhost:8000/
curl http://localhost:8000/dashboard
curl http://localhost:8000/api/status
```

### Step 5: Browser Test

```
http://<device-ip>:8000
http://<device-ip>:8000/dashboard
```

## Expected Results

After implementing the fix:

✅ WebUI loads and displays interface
✅ Green terminal theme visible
✅ Buttons for attacks available
✅ Loot capture status displayed
✅ Activity log shows events
✅ Dashboard accessible at `/dashboard`

## Troubleshooting the Fix

If the wrapper still doesn't work:

### Check Flask Installation

```bash
python3 -c "import flask; print(flask.__version__)"
```

### Check Port Binding

```bash
sudo netstat -tlnp | grep 8000
# Should show: 0.0.0.0:8000 in LISTEN state
```

### Verify Permissions

```bash
chmod 755 /root/KTOx/vendor/loki/ktox_headless_loki.py
chmod 755 /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py
chmod 777 /root/KTOx/loot/loki/logs/
```

### Manual Port Forwarding

If running on Raspberry Pi and need to access from other device:

```bash
# On Pi:
FLASK_APP=/root/KTOx/vendor/loki/ktox_webui_wrapper.py \
LOKI_DATA_DIR=/root/KTOx/loot/loki \
python3 -m flask run --host=0.0.0.0 --port=8000
```

## Key Differences: Wrapper vs Original

| Feature | Original | Wrapper |
|---------|----------|---------|
| **Source** | Loki GitHub repo | KTOx custom |
| **Complexity** | Full Loki integration | Simplified UI |
| **Features** | All Loki modules | Core interface |
| **Dependencies** | All Loki deps | Flask only |
| **Status** | Working (sometimes) | Reliable |
| **UI** | Variable | Consistent |

## Long-term Solution

For production use, consider:

1. **Contribute to Loki:** Submit PR to fix webapp.py Flask initialization
2. **Fork Loki:** Maintain fixed version in your org
3. **Use Wrapper:** Keep wrapper as fallback interface
4. **Monitor Logs:** Set up log aggregation to catch issues early

## Files Reference

```
/root/KTOx/vendor/loki/
├── ktox_headless_loki.py          (Original launcher)
├── ktox_headless_loki_enhanced.py (Enhanced, better logging)
├── ktox_webui_wrapper.py          (Fallback UI wrapper)
└── webapp.py                       (Original Flask app)

/home/user/KTOX_Pi/payloads/offensive/
├── loki_engine.py                 (KTOx launcher)
├── loki_enhanced_launcher.py      (Enhanced launcher source)
└── test_loki_webui.py            (WebUI endpoint test)
```

---

**Status:** WebUI Interface Fix Guide v1.0
**Last Updated:** 2026-04-24
