# KTOX Cyberpunk WebUI Theming Guide

This guide explains how to apply the yt-ripper cyberpunk theme and DarkSec Micro Shell keyboard to all web servers in KTOX_Pi.

## Overview

Three reusable components are now available:

1. **_cyberpunk_theme.css** - Shared CSS theme with dark red aesthetic
2. **_darksec_keyboard.py** - Virtual keyboard module with command history
3. **Theme color palette** - Consistent colors across all UIs

## Cyberpunk Color Palette

```python
COLORS = {
    "BG":       (10, 0, 0),        # Deep dark red - #0a0000
    "PANEL":    (34, 0, 0),        # Dark red - #220000
    "HEADER":   (139, 0, 0),       # Medium red - #8b0000
    "FG":       (171, 178, 185),   # Light gray - #abb2b9
    "ACCENT":   (231, 76, 60),     # Bright red-orange - #e74c3c
    "WARN":     (212, 172, 13),    # Gold/yellow - #d4ac0d
    "DIM":      (113, 125, 126),   # Dark gray - #717d7e
    "WHITE":    (255, 255, 255),   # White
}
```

Or use CSS variables:
```css
--bg-0:     #0a0000;  /* Primary background */
--header:   #8b0000;  /* Headers */
--accent:   #e74c3c;  /* Highlights/glow */
--warn:     #d4ac0d;  /* Warnings */
--fg:       #abb2b9;  /* Main text */
```

## Theme Flask Web Servers

### Step 1: Import CSS in your HTML template

```html
<!DOCTYPE html>
<html>
<head>
    <title>Your Tool Name</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='../../../_cyberpunk_theme.css') }}">
    <style>
        /* Tool-specific overrides go here */
    </style>
</head>
<body>
    <header>
        <h1>TOOL NAME</h1>
        <div class="status">
            <div class="status-dot"></div>
            <span>RUNNING</span>
        </div>
    </header>

    <main>
        <!-- Your content here -->
    </main>

    <footer>
        <span>Status: Active</span>
        <span class="uptime">Uptime: 1:23:45</span>
    </footer>

    <div class="scanlines"></div>
</body>
</html>
```

### Step 2: Organize static files

```
payloads/your_tool/
├── your_tool.py (Flask app)
└── static/
    ├── style.css (tool-specific styles)
    ├── script.js
    └── templates/
        └── index.html
```

### Step 3: Flask app setup

```python
from flask import Flask, render_template

app = Flask(__name__, static_folder='static')

@app.route('/')
def index():
    return render_template('index.html')

# Serve shared CSS
import os
from pathlib import Path

@app.route('/static/<path:filename>')
def serve_static(filename):
    if filename.startswith('../../../'):
        # Serve from payloads root
        path = os.path.join(Path(__file__).parent.parent, filename[9:])
        return app.send_static_file(path)
    return app.send_static_file(filename)
```

## Example: Flask WebUI with Cyberpunk Theme

```python
#!/usr/bin/env python3
from flask import Flask, render_template, jsonify, request
import os
from datetime import datetime

app = Flask(__name__, static_folder='static')

# Tool state
state = {
    "running": True,
    "started_at": datetime.now(),
}

@app.route('/')
def index():
    uptime_sec = (datetime.now() - state["started_at"]).total_seconds()
    hours = int(uptime_sec // 3600)
    minutes = int((uptime_sec % 3600) // 60)
    seconds = int(uptime_sec % 60)
    uptime = f"{hours}:{minutes:02d}:{seconds:02d}"
    
    return render_template('index.html', uptime=uptime)

@app.route('/api/status')
def get_status():
    return jsonify({
        "status": "RUNNING" if state["running"] else "STOPPED",
        "uptime": str(state["started_at"])
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

Template (templates/index.html):
```html
<!DOCTYPE html>
<html>
<head>
    <title>My Tool</title>
    <link rel="stylesheet" href="static/theme.css">
</head>
<body>
    <header>
        <h1>MY TOOL</h1>
        <div class="status">
            <div class="status-dot"></div>
            <span>RUNNING</span>
        </div>
    </header>

    <main>
        <div class="tabs">
            <button class="tab-btn active" data-tab="overview">Overview</button>
            <button class="tab-btn" data-tab="logs">Logs</button>
            <button class="tab-btn" data-tab="settings">Settings</button>
        </div>

        <div id="overview" class="tab-content active">
            <div class="panel">
                <div class="panel-header">System Status</div>
                <div class="panel-content">
                    <p>Status: <span class="status-badge status-active">ONLINE</span></p>
                    <p>Uptime: {{ uptime }}</p>
                </div>
            </div>
        </div>
    </main>

    <footer>
        <span>Status: Running</span>
        <span class="uptime">Uptime: {{ uptime }}</span>
    </footer>

    <div class="scanlines"></div>

    <script src="static/script.js"></script>
</body>
</html>
```

## Integrate DarkSec Keyboard

### For LCD CLI tools (using GPIO buttons)

```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/../..')

from payloads._darksec_keyboard import DarkSecKeyboard
import RPi.GPIO as GPIO
import LCD_1in44

# Initialize LCD
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

# GPIO pins
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Create keyboard
keyboard = DarkSecKeyboard(
    width=128,
    height=128,
    lcd=LCD,
    gpio_pins=PINS,
    gpio_module=GPIO
)

# Use keyboard
user_input = keyboard.run()
if user_input:
    print(f"User entered: {user_input}")
else:
    print("User cancelled")
```

### For web-based tools (using forms)

Use standard HTML forms with the cyberpunk theme - no special integration needed.

## Existing Web Servers to Theme

### Priority 1: Utilities
- [ ] **yt-ripper.py** (port 5000) - Already has cyberpunk colors, just needs HTML/CSS
- [ ] **file-browser.py** - File/directory navigation
- [ ] **docXplorer.py** - Document viewing
- [ ] **DarkSec-Chat.py** - Chat interface
- [ ] **usbExplorer.py** - USB device browser

### Priority 2: Games
- [ ] **KTOx_Flixs.py** - Video streaming UI
- [ ] **browser.py** - Web browser UI

### Priority 3: Network Tools
- [ ] **captive_portal.py** - Capture page
- [ ] **karma_ap.py** - AP dashboard
- [ ] **rogue_dhcp_wpad.py** - DHCP/WPAD UI
- [ ] **ssdp_spoof.py** - SSDP spoofing UI

### Priority 4: Offensive Tools
- [ ] **MSFweb.py** - Metasploit web UI
- [ ] **honeypot.py** - Honeypot dashboard

### Priority 5: WiFi/Evil
- [ ] Various evil payloads with web interfaces

## Testing Checklist

For each themed web server:

- [ ] Theme CSS loads correctly
- [ ] Colors match cyberpunk palette
- [ ] Text is readable (sufficient contrast)
- [ ] Responsive layout works on different sizes
- [ ] Buttons/inputs are functional
- [ ] Scanlines effect is subtle (not distracting)
- [ ] Glow effects work as intended
- [ ] Mobile display is usable
- [ ] Performance is acceptable

## Best Practices

### 1. Use Semantic HTML
```html
<!-- Good -->
<header>
    <h1>Tool Name</h1>
</header>

<main>
    <section class="panel">
        <h2>Content</h2>
    </section>
</main>

<!-- Bad -->
<div id="header">
    <div id="title">Tool Name</div>
</div>
```

### 2. Leverage Existing Classes
```html
<!-- Use predefined classes -->
<button class="btn primary">Submit</button>
<div class="alert warning">Warning message</div>
<span class="status-badge status-active">Online</span>

<!-- Not: custom inline styles -->
```

### 3. Override Theme Selectively
```css
/* theme.css has defaults, override only what you need */
.my-tool-specific {
    --accent: #ff6b6b;  /* Custom accent if needed */
}
```

### 4. Maintain Readability
- Ensure text contrast ≥ 4.5:1
- Use monospace for logs/code
- Provide clear visual hierarchy
- Don't overcomplicate with effects

## JavaScript Integration

Most interactive features should use vanilla JS or minimal dependencies:

```javascript
// Toggle tabs
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        // Hide all tabs
        document.querySelectorAll('.tab-content').forEach(tc => {
            tc.classList.remove('active');
        });
        
        // Show selected tab
        const tabName = btn.dataset.tab;
        document.getElementById(tabName).classList.add('active');
        
        // Update button state
        document.querySelectorAll('.tab-btn').forEach(b => {
            b.classList.remove('active');
        });
        btn.classList.add('active');
    });
});
```

## Troubleshooting

### CSS not loading
- Check file paths (use relative URLs from template)
- Verify Flask static folder configuration
- Clear browser cache (Ctrl+Shift+R)

### Colors look different
- Ensure browser isn't applying color filter
- Check monitor color profile
- Try in dark mode if available

### Text hard to read
- Increase font size in theme.css
- Use higher contrast overlay
- Reduce background blur/effects

### Performance issues
- Reduce number of gradients
- Disable scanlines effect for slower devices
- Minimize JS file size
- Use CSS animations instead of JS

## References

- **yt-ripper** - Original cyberpunk implementation
- **DarkSec Micro Shell** - Keyboard implementation
- **KTOx_Pi** - Main project repository
- **Cyberpunk Aesthetic** - High-tech, dark, neon style

---

**Status**: ✅ Theme and keyboard components ready for integration
**Last Updated**: 2026-04-24
