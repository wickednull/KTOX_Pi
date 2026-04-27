# M5Cardputer WebSocket Protocol Testing

This guide helps verify that M5Cardputer firmware and KTOX_Pi device_server are communicating correctly.

## Prerequisites

You have:
- KTOX_Pi running with device_server.py
- M5Cardputer device flashed with corrected firmware
- Both on same WiFi network

## Quick Verification Checklist

### 1. KTOX_Pi Server Check

```bash
# Verify device_server.py is running
ps aux | grep device_server.py

# Should show:
# /usr/bin/python3 device_server.py

# Verify WebSocket is listening
netstat -tlnp | grep 8765

# Should show:
# tcp 0 0 0.0.0.0:8765 0.0.0.0:* LISTEN
```

### 2. Frame File Check

```bash
# Verify M5 frame file exists and is updating
ls -lh /dev/shm/ktox_m5.jpg

# Monitor frame updates (should change every ~166ms for 6 FPS)
watch -n 0.5 'ls -lh /dev/shm/ktox_m5.jpg && stat /dev/shm/ktox_m5.jpg | grep Modify'

# If times don't change, frame capture isn't running
# Check: export RJ_FRAME_MIRROR=1
# And: export RJ_CARDPUTER_ENABLED=1
```

### 3. Frame Validity Check

```bash
# Verify JPEG is valid
file /dev/shm/ktox_m5.jpg
# Should output: "JPEG image data, 240 x 135 ..."

# Check JPEG size (should be 4-12 KB typically)
ls -lh /dev/shm/ktox_m5.jpg
# Example: -rw-r--r-- 1 root root 6.2K Apr 27 12:34 /dev/shm/ktox_m5.jpg

# Test JPEG can be decoded
python3 -c "from PIL import Image; i=Image.open('/dev/shm/ktox_m5.jpg'); print(f'Size: {i.size}')"
# Should output: "Size: (240, 135)"
```

### 4. M5Cardputer Firmware Check

**Serial Monitor Output:**

Connect M5Cardputer via USB and monitor:

```bash
cd /home/user/KTOX_Pi/m5cardputer
platformio run -e m5stack-cardputer --target monitor
```

Expected output sequence:

```
[... startup messages ...]
================================
KTOx Remote Control
M5Cardputer Edition
================================
[... SPIFFS and settings ...]
Connecting to WiFi: YourSSID
[WiFi connection attempts...]
WiFi connected!
IP: 192.168.1.X
Connecting to WebSocket: 192.168.0.50:8765
[WS] Connected!
[WS] Sent auth token
[FRAME] Decoded 5432 bytes from base64
[FRAME] Frame displayed (#1)
[FRAME] Decoded 5245 bytes from base64
[FRAME] Frame displayed (#2)
```

### 5. WebSocket Verification with Python

Test WebSocket communication directly (run on KTOX_Pi):

```bash
python3 << 'EOF'
import asyncio
import websockets
import json
import base64
import time

async def test_m5_frames():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as ws:
        print(f"Connected to {uri}")
        
        # Receive a few frames
        for i in range(3):
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)
            
            msg_type = data.get("type")
            if msg_type == "frame_m5":
                # Validate frame message
                frame_data = data.get("data", "")
                print(f"Frame {i+1}: type='{msg_type}', data_len={len(frame_data)} chars")
                
                # Try to decode base64
                try:
                    jpeg_bytes = base64.b64decode(frame_data)
                    print(f"  → Decoded to {len(jpeg_bytes)} bytes JPEG")
                    
                    # Check JPEG magic bytes
                    if jpeg_bytes[:2] == b'\xff\xd8':
                        print(f"  ✓ Valid JPEG header")
                    else:
                        print(f"  ✗ Invalid JPEG header: {jpeg_bytes[:2].hex()}")
                except Exception as e:
                    print(f"  ✗ Base64 decode failed: {e}")
            else:
                print(f"Frame {i+1}: type='{msg_type}' (not frame_m5)")

asyncio.run(test_m5_frames())
EOF
```

Expected output:

```
Connected to ws://localhost:8765
Frame 1: type='frame_m5', data_len=7328 chars
  → Decoded to 5496 bytes JPEG
  ✓ Valid JPEG header
Frame 2: type='frame_m5', data_len=7200 chars
  → Decoded to 5400 bytes JPEG
  ✓ Valid JPEG header
Frame 3: type='frame_m5', data_len=7456 chars
  → Decoded to 5592 bytes JPEG
  ✓ Valid JPEG header
```

### 6. Authentication Test

If auth token is configured:

```bash
# Send auth message
python3 << 'EOF'
import asyncio
import websockets
import json

async def test_auth():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as ws:
        # Try to receive frame without auth
        print("Testing auth flow...")
        
        # Get auth token from env
        import os
        token = os.environ.get("RJ_WS_TOKEN", "")
        
        if token:
            # Send auth message
            auth_msg = {"type": "auth", "token": token}
            ws.send(json.dumps(auth_msg))
            print(f"Sent auth: {json.dumps(auth_msg)}")
            
            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"Response: {response}")
        else:
            print("No auth token configured, connection allowed")
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"Received: {msg[:100]}...")

asyncio.run(test_auth())
EOF
```

## Protocol Debugging

### Enable Debug Logging in device_server.py

Edit device_server.py to increase logging:

```python
# Around line 17-20
import logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)  # Change to DEBUG for more verbose output
```

Restart device_server and look for:

```
[COOKIE_AUTH] Header value: <header>
[COOKIE_AUTH] Parsed cookie value: <token>
[COOKIE_AUTH] Token validation result: True
Client connected - authenticated (1 online)
```

### Monitor WebSocket Messages

Use tcpdump to see raw WebSocket traffic:

```bash
# Capture WebSocket traffic on port 8765
sudo tcpdump -i eth0 -A 'tcp port 8765' -n | head -100

# For more readable output, filter for JSON:
sudo tcpdump -i eth0 -A 'tcp port 8765' -n | grep -E '(frame_m5|auth|input)' | head -20
```

## Common Issues and Fixes

### Issue: "No frames received" on M5

**Symptoms:**
- M5 shows "Connected!" but display stays black
- Serial monitor shows no "[FRAME]" messages

**Debugging:**
```bash
# 1. Check if device_server is sending frame_m5
python3 << 'EOF'
import asyncio, websockets, json, time
async def test():
    async with websockets.connect("ws://localhost:8765") as ws:
        for i in range(5):
            msg = json.loads(await asyncio.wait_for(ws.recv(), 3.0))
            print(f"{i}: type={msg.get('type')}")
            time.sleep(1)
asyncio.run(test())
EOF

# 2. Verify frame file is being updated
watch -n 0.2 stat /dev/shm/ktox_m5.jpg | grep Modify

# 3. Check if PIL is available (needed for frame scaling)
python3 -c "from PIL import Image; print('PIL available')"
```

### Issue: "Connection refused" on M5

**Symptoms:**
- M5 shows "Connecting..." then disconnects
- Serial shows "[WS] Disconnected"

**Debugging:**
```bash
# 1. Verify device_server is running
ps aux | grep device_server

# 2. Verify port is open
sudo ufw allow 8765
netstat -tlnp | grep 8765

# 3. Test local connection
python3 -c "import socket; s=socket.socket(); s.connect(('localhost', 8765)); print('Connected')"

# 4. Test from M5's IP
python3 -c "import socket; s=socket.socket(); s.connect(('192.168.1.50', 8765)); print('Connected')"
# (Replace IP with M5's actual IP)
```

### Issue: "Auth failed" on M5

**Symptoms:**
- M5 shows "Authenticating..." then disconnects
- Serial shows "[WS] Authentication failed"

**Debugging:**
```bash
# 1. Verify token is set
echo $RJ_WS_TOKEN

# 2. Test auth directly
python3 << 'EOF'
import asyncio, websockets, json, os
async def test():
    token = os.environ["RJ_WS_TOKEN"]
    async with websockets.connect("ws://localhost:8765") as ws:
        ws.send(json.dumps({"type": "auth", "token": token}))
        response = await asyncio.wait_for(ws.recv(), 2.0)
        print(f"Response: {response}")
asyncio.run(test())
EOF

# 3. Check token file exists
cat /root/KTOx/.webui_token
```

## Performance Metrics

When working correctly, expect:

| Metric | Expected | Indicator |
|--------|----------|-----------|
| Frames/second | 5-6 FPS | Status bar shows consistent frame count increase |
| Frame size | 4-8 KB | Depends on image complexity and quality setting |
| Latency | <200 ms | Video appears smooth with minimal lag |
| Connection stability | 24+ hours | No disconnects under normal operation |
| Memory usage (M5) | <50 MB | Device doesn't crash or reboot |
| CPU usage (Pi) | <5% additional | No impact on KTOX payload execution |

## Next Steps

If all checks pass:
1. **Build and upload** the corrected M5Cardputer firmware
2. **Run setup wizard** on M5 to configure WiFi
3. **Monitor serial output** to verify frame reception
4. **Test input** by pressing arrow keys

If issues persist:
1. Check device_server.py environment variables: `env | grep -i cardputer`
2. Verify PIL is installed: `python3 -c "from PIL import Image"`
3. Check M5 serial output for decoding errors
4. Enable DEBUG logging in device_server.py for detailed diagnostics

