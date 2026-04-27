# Loki WebUI Dashboard Troubleshooting Guide

## Problem Summary

Loki is installed and running on port 8000, but the WebUI dashboard ("Loki guy") is not displaying properly. The service is accessible, but the interface isn't showing the expected attack/reconnaissance interface.

## Quick Diagnostic Steps

### 1. Verify Loki is Actually Running

```bash
# Check process
ps aux | grep loki

# Check port
netstat -tlnp | grep 8000
# or
lsof -i :8000
```

**Expected output:** Should show Python process running and port 8000 in LISTEN state.

### 2. Test WebUI Connectivity

```bash
# Quick test with curl
curl -I http://localhost:8000/

# Get response headers
curl -v http://localhost:8000/ 2>&1 | head -20

# Try dashboard endpoint
curl http://localhost:8000/dashboard
```

**Expected:** HTTP 200 response with HTML content.

### 3. Run Diagnostic Tools

I've created several diagnostic tools to help troubleshoot:

```bash
# Check installation structure
python3 /home/user/KTOX_Pi/payloads/offensive/verify_loki_structure.py

# Run full diagnostics
python3 /home/user/KTOX_Pi/payloads/offensive/loki_diagnostic.py

# Test WebUI endpoints
python3 /home/user/KTOX_Pi/payloads/offensive/test_loki_webui.py
```

### 4. Check Logs

```bash
# View recent logs
tail -50 /root/KTOx/loot/loki/logs/loki.log

# Follow logs in real-time
tail -f /root/KTOx/loot/loki/logs/loki.log

# Check for errors
grep -i error /root/KTOx/loot/loki/logs/loki.log

# Check debug log (if it exists)
tail -50 /root/KTOx/loot/loki/logs/loki_debug.log
```

## Common Issues and Solutions

### Issue 1: Port 8000 Not Responding

**Symptoms:** `curl http://localhost:8000` times out or refuses connection

**Diagnosis:**
```bash
# Verify process is running
pgrep -f ktox_headless_loki

# Check if another service is using port 8000
sudo lsof -i :8000
```

**Solutions:**

1. **Process not running:** Restart Loki
   ```bash
   pkill -f ktox_headless_loki
   # Wait 2 seconds
   python3 /home/user/KTOX_Pi/payloads/offensive/loki_engine.py
   # Select option 2 (Start Loki)
   ```

2. **Port in use:** Find and kill the other service
   ```bash
   sudo lsof -i :8000
   # Note the PID, then:
   sudo kill -9 <PID>
   ```

3. **Firewall blocking:** Allow port 8000
   ```bash
   sudo ufw allow 8000
   # or
   sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
   ```

### Issue 2: HTTP 500 or Flask Errors

**Symptoms:** `curl http://localhost:8000` returns error or blank response

**Diagnosis:**
```bash
# Get detailed error
curl -v http://localhost:8000/

# Check logs for Flask errors
grep -i "exception\|error\|traceback" /root/KTOx/loot/loki/logs/loki.log
```

**Common causes:**

1. **Missing dependencies:** Flask, paramiko, cryptography
   ```bash
   cd /root/KTOx/vendor/loki
   pip3 install flask paramiko cryptography pillow requests
   ```

2. **Missing init_shared.py:** Required module not found
   ```bash
   ls -la /root/KTOx/vendor/loki/init_shared.py
   # If missing, reinstall Loki
   ```

3. **Configuration load failure:** shared_data.load_config() failing
   ```bash
   # Check if config exists
   ls -la /root/KTOx/vendor/loki/config/
   ls -la /root/KTOx/loot/loki/
   ```

**Solution:** Use enhanced launcher with better error reporting
```bash
# Install enhanced launcher
cp /home/user/KTOX_Pi/payloads/offensive/loki_enhanced_launcher.py /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py

# Run with enhanced logging
LOKI_DATA_DIR=/root/KTOx/loot/loki \
BJORN_IP=$(hostname -I | awk '{print $1}') \
python3 /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py 2>&1 | tee /root/KTOx/loot/loki/logs/enhanced.log

# Watch logs
tail -f /root/KTOx/loot/loki/logs/enhanced.log
```

### Issue 3: Dashboard Route Not Found (404)

**Symptoms:** Root URL works (http://localhost:8000) but `/dashboard` returns 404

**Diagnosis:**
```bash
# Check what routes are defined
grep -n "@app.route\|@route" /root/KTOx/vendor/loki/webapp.py | head -20

# Test specific endpoints
curl http://localhost:8000/
curl http://localhost:8000/dashboard
curl http://localhost:8000/api
curl http://localhost:8000/index.html
```

**Possible causes:**

1. **Routes not registered in webapp.py:** The Flask app wasn't initialized properly
2. **Template files missing:** HTML templates for dashboard not found
3. **Wrong URL patterns:** Dashboard might be at different path

**Solution:** Check webapp.py for route definitions
```bash
# View route definitions
grep -A 5 "@app.route" /root/KTOx/vendor/loki/webapp.py

# List all available routes
python3 << 'EOF'
import sys
sys.path.insert(0, '/root/KTOx/vendor/loki')
try:
    from webapp import app
    print("Routes defined:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.rule} -> {rule.endpoint}")
except Exception as e:
    print(f"Error loading webapp: {e}")
EOF
```

### Issue 4: HTML Content Downloaded Instead of Displayed

**Symptoms:** Browser downloads HTML file instead of displaying it

**Diagnosis:** Check Content-Type header
```bash
curl -I http://localhost:8000/
# Should show: Content-Type: text/html; charset=utf-8
```

**Solution:** Verify Flask is configured correctly
```bash
# Check if render_template is used
grep "render_template" /root/KTOx/vendor/loki/webapp.py
```

### Issue 5: WebUI Works but Dashboard Empty/Broken

**Symptoms:** Page loads but shows blank, loading spinner, or JavaScript errors

**Diagnosis:**

1. **Check browser console for JavaScript errors:**
   - Open: http://localhost:8000 in browser
   - Press F12 to open Developer Tools
   - Check Console tab for error messages

2. **Check Flask logging:**
   ```bash
   grep -i "error\|exception" /root/KTOx/loot/loki/logs/loki.log | head -20
   ```

3. **Test API endpoints:**
   ```bash
   curl http://localhost:8000/api/status
   curl http://localhost:8000/api/hosts
   curl http://localhost:8000/api/scan
   ```

**Possible causes:**

1. **API endpoints failing:** Backend not responding to frontend requests
2. **Static files not served:** CSS/JS loading fails
3. **Missing frontend code:** Templates not compiled

**Solution:**

1. Check if API is working:
   ```bash
   curl -s http://localhost:8000/api/status | python3 -m json.tool
   ```

2. Restart Loki with fresh state:
   ```bash
   pkill -f ktox_headless_loki
   sleep 2
   python3 /home/user/KTOX_Pi/payloads/offensive/loki_engine.py
   # Select option 2
   ```

## Advanced Troubleshooting

### Enable Debug Logging

Use the enhanced launcher with full debug output:

```bash
# Copy enhanced launcher
cp /home/user/KTOX_Pi/payloads/offensive/loki_enhanced_launcher.py \
   /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py

# Set executable
chmod +x /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py

# Run directly with logging
LOKI_DATA_DIR=/root/KTOx/loot/loki \
BJORN_IP=localhost \
python3 /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py
```

This will output detailed logs showing:
- Module import status
- Configuration loading
- Flask initialization
- Thread startup
- Signal handling

### Test Flask App Directly

```bash
# Test if Flask app can be imported
python3 << 'EOF'
import sys
sys.path.insert(0, '/root/KTOx/vendor/loki')

try:
    print("[*] Importing modules...")
    from init_shared import shared_data
    print("[✓] init_shared imported")

    from Loki import Loki, handle_exit
    print("[✓] Loki imported")

    from webapp import web_thread
    print("[✓] webapp imported")

    print("\n[*] Loading config...")
    shared_data.load_config()
    print("[✓] Config loaded")

    print("\n[*] Checking shared_data attributes...")
    print(f"  webapp_should_exit: {hasattr(shared_data, 'webapp_should_exit')}")
    print(f"  display_should_exit: {hasattr(shared_data, 'display_should_exit')}")
    print(f"  should_exit: {hasattr(shared_data, 'should_exit')}")

    print("\n[✓] All imports successful")

except Exception as e:
    print(f"\n[✗] Error: {e}")
    import traceback
    traceback.print_exc()
EOF
```

### Check Network Connectivity

```bash
# If accessing from another machine
ping <device-ip>
curl http://<device-ip>:8000/

# Check device IP
hostname -I

# Allow connections (if firewall is strict)
sudo ufw allow from any to any port 8000
```

## Recovery Steps

If Loki is broken, try these recovery steps:

### Step 1: Full Restart

```bash
# Stop any running instances
pkill -9 -f ktox_headless_loki

# Remove old logs
rm -f /root/KTOx/loot/loki/logs/*

# Start fresh
python3 /home/user/KTOX_Pi/payloads/offensive/loki_engine.py
# Select 2 to start
```

### Step 2: Reinstall Loki

```bash
# Backup data (if needed)
cp -r /root/KTOx/loot/loki/output /tmp/loki_backup/

# Remove installation
rm -rf /root/KTOx/vendor/loki

# Reinstall
python3 /home/user/KTOX_Pi/payloads/offensive/loki_engine.py
# Select 1 to install
# Select y to start after install
```

### Step 3: Manual Reinstall (if menu system broken)

```bash
# Clean slate
pkill -9 -f loki
rm -rf /root/KTOx/vendor/loki
rm -rf /root/KTOx/loot/loki

# Manual install
mkdir -p /root/KTOx/vendor /root/KTOx/loot/loki/{logs,output,input}
cd /root/KTOx/vendor

# Clone Loki
git clone --depth=1 https://github.com/pineapple-pager-projects/pineapple_pager_loki loki
cd loki

# Install dependencies
pip3 install -r requirements.txt

# Copy pagerctl shim
mkdir -p lib
cp /home/user/KTOX_Pi/payloads/offensive/loki_engine.py lib/pagerctl.py

# Start
LOKI_DATA_DIR=/root/KTOx/loot/loki python3 ktox_headless_loki.py
```

## WebUI Access

Once running, access the WebUI:

**From same device:**
```
http://localhost:8000
http://127.0.0.1:8000
```

**From another device on network:**
```
http://<device-ip>:8000
# Example: http://192.168.1.100:8000
```

**Find device IP:**
```bash
hostname -I
# or
ip addr | grep "inet "
```

## Expected WebUI Features

Once working, Loki should show:

- **Network Scanning**
  - Host discovery
  - Port scanning
  - Service enumeration

- **Exploitation Dashboard**
  - Attack modules
  - Configuration options
  - Execution status

- **Results/Loot**
  - Credentials captured
  - Data exfiltrated
  - Vulnerability findings

- **Logs**
  - Operation history
  - Error messages
  - System status

## Still Not Working?

If you've tried all steps above:

1. **Collect diagnostics:**
   ```bash
   python3 /home/user/KTOX_Pi/payloads/offensive/loki_diagnostic.py > /tmp/loki_diag.txt
   python3 /home/user/KTOX_Pi/payloads/offensive/test_loki_webui.py >> /tmp/loki_diag.txt
   python3 /home/user/KTOX_Pi/payloads/offensive/verify_loki_structure.py >> /tmp/loki_diag.txt
   cat /tmp/loki_diag.txt
   ```

2. **Include in bug report:**
   - Contents of `/tmp/loki_diag.txt`
   - Last 50 lines of `/root/KTOx/loot/loki/logs/loki.log`
   - Output of `curl -v http://localhost:8000/`
   - Python version: `python3 --version`
   - System info: `uname -a`

3. **Check Loki GitHub:**
   - https://github.com/pineapple-pager-projects/pineapple_pager_loki
   - Check issues and discussions

## Key Files

| File | Purpose |
|------|---------|
| `/root/KTOx/vendor/loki/` | Loki installation |
| `/root/KTOx/vendor/loki/webapp.py` | Flask WebUI application |
| `/root/KTOx/vendor/loki/Loki.py` | Core engine |
| `/root/KTOx/loot/loki/logs/loki.log` | Main log file |
| `/root/KTOx/payloads/offensive/loki_engine.py` | KTOx launcher |

## References

- **Loki Repository:** https://github.com/pineapple-pager-projects/pineapple_pager_loki
- **Flask Documentation:** https://flask.palletsprojects.com/
- **Python Debugging:** https://docs.python.org/3/library/pdb.html
- **Networking Tools:** curl, netstat, lsof, tcpdump

---

**Last Updated:** 2026-04-24
**Status:** Troubleshooting Guide v1.0
