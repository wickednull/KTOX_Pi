# RaspyJack Cardputer Integration with KTOx

## Overview

KTOx is already compatible with RaspyJack! Both systems use the same WebSocket architecture and Unix socket input protocol for device control. This document explains how to use RaspyJack Cardputer app to control KTOx remotely.

## Architecture

### Communication Flow

```
RaspyJack Cardputer App
    ↓ (WebSocket)
    ↓ JSON input events
    ↓
KTOx device_server.py (WebSocket server)
    ↓ (Unix socket)
    ↓ JSON to /dev/shm/ktox_input.sock
    ↓
ktox_input.py (Input bridge)
    ↓ (Button queue)
    ↓
ktox_device.py (Main UI)
    ↓ (Frame output)
    ↓
/dev/shm/ktox_last.jpg (Shared frame buffer)
    ↓ (Read by WebSocket server)
    ↓
device_server.py broadcasts to clients
    ↓ (WebSocket)
    ↓
RaspyJack displays on Cardputer screen
```

## Key Components

### 1. Input Socket Protocol

**Path**: `/dev/shm/ktox_input.sock`

**Format**: JSON datagram over Unix socket

**Button Names**:
- Navigation: `UP`, `DOWN`, `LEFT`, `RIGHT`
- Select: `OK`
- System: `KEY1`, `KEY2`, `KEY3`

**Example Message**:
```json
{"type":"input","button":"UP","state":"press"}
{"type":"input","button":"UP","state":"release"}
```

### 2. Frame Output

**Path**: `/dev/shm/ktox_last.jpg`

- KTOx writes frames here at ~10 FPS
- device_server.py reads and broadcasts to RaspyJack clients
- RaspyJack Cardputer displays in real-time

### 3. WebSocket Server

**File**: `device_server.py`

**Default Port**: 8765

**Supported Clients**:
- RaspyJack Cardputer (frame format: `legacy` or `cardputer`)
- KTOx WebUI
- Any WebSocket client supporting the input protocol

### 4. Input Bridge

**File**: `ktox_pi/ktox_input.py`

**Functions**:
- Maps frontend button names to GPIO pin names
- Maintains held-state file (`/dev/shm/ktox_held`)
- Queues button presses for main UI

## Button Mapping

| RaspyJack Button | KTOx Function |
|-----------------|--------------|
| UP | Navigate up |
| DOWN | Navigate down |
| LEFT | Back/Left |
| RIGHT | Select/Right |
| OK | Confirm selection |
| KEY1 | Back/Escape |
| KEY2 | Home |
| KEY3 | Stop/Exit |

## Setup Instructions

### 1. Start KTOx Device Server

```bash
cd /root/KTOx
python3 device_server.py
```

**Environment Variables**:
```bash
# Frame output location (RaspyJack reads from here)
RJ_FRAME_PATH=/dev/shm/ktox_last.jpg

# WebSocket server bind address
RJ_WS_HOST=0.0.0.0
RJ_WS_PORT=8765

# Input socket for RaspyJack to send button events
RJ_INPUT_SOCK=/dev/shm/ktox_input.sock

# Frame rate
RJ_FPS=10

# Authentication token (optional)
RJ_WS_TOKEN=your_token_here
```

### 2. Start KTOx Main Device

```bash
cd /root/KTOx
python3 ktox_device.py
```

This will:
- Initialize GPIO and LCD
- Start main UI loop
- Listen on `/dev/shm/ktox_input.sock` for WebUI input
- Write frames to `/dev/shm/ktox_last.jpg`

### 3. Configure RaspyJack Cardputer

In RaspyJack Cardputer app settings:

```
WebSocket Server: ws://<ktox-ip>:8765
Authentication: (token if configured)
Display Profile: legacy (default) or cardputer (240x135)
Stream Format: json
```

## Testing the Integration

### 1. Verify Socket Exists
```bash
ls -la /dev/shm/ktox_input.sock
```

### 2. Test Manual Input
```bash
python3 -c "
import json, socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.connect('/dev/shm/ktox_input.sock')
msg = json.dumps({'type':'input','button':'UP','state':'press'})
s.send(msg.encode())
s.close()
"
```

### 3. Check Frame Output
```bash
# Monitor frame updates
watch -n 0.5 'ls -lh /dev/shm/ktox_last.jpg'

# View frame size
file /dev/shm/ktox_last.jpg
```

### 4. WebSocket Connection
```bash
# Test WebSocket server
wscat -c ws://localhost:8765

# Should receive text_session message
```

## Features Supported

✅ **Real-time remote control** via RaspyJack Cardputer  
✅ **Live screen streaming** to Cardputer display  
✅ **Button input** - All 8 buttons mapped  
✅ **Authentication** - Token-based (optional)  
✅ **Multi-client** - Multiple RaspyJack devices can connect  
✅ **Shell sessions** - Terminal access (if needed)  
✅ **Text input** - For interactive prompts  

## Advanced Configuration

### High FPS Mode
```bash
RJ_FPS=20 python3 device_server.py
```

### Custom Authentication Token
```bash
echo "your_secret_token_12345" > /root/KTOx/.webui_token
RJ_WS_TOKEN=your_secret_token_12345 python3 device_server.py
```

### Bind to Specific Interface
```bash
RJ_WS_HOST=192.168.1.100 RJ_WS_PORT=8765 python3 device_server.py
```

### Network-Only Mode (for security)
```bash
# Only allow specific IPs
# Edit device_server.py WEBUI_INTERFACES and restart
```

## Troubleshooting

### No Frame Updates
- Verify KTOx is running: `ps aux | grep ktox_device`
- Check frame path: `ls -lh /dev/shm/ktox_last.jpg`
- Ensure LCD is initialized (check KTOx logs)

### Input Not Working
- Verify socket exists: `ls -la /dev/shm/ktox_input.sock`
- Check socket permissions: `stat /dev/shm/ktox_input.sock`
- Test manually: See "Testing the Integration" section
- Check KTOx logs for input errors

### WebSocket Connection Issues
- Verify server running: `netstat -tlnp | grep 8765`
- Check firewall: `sudo ufw allow 8765`
- Test locally first: `ws://127.0.0.1:8765`

### Authentication Failures
- Verify token file: `cat /root/KTOx/.webui_token`
- Check RJ_WS_TOKEN env var
- Ensure token matches in RaspyJack app

## Performance Tips

1. **Reduce FPS for low bandwidth**: `RJ_FPS=5`
2. **Use binary frame format** for Cardputer (more efficient)
3. **Enable compression** in WebSocket server
4. **Use wired Ethernet** instead of WiFi for reliability
5. **Monitor frame queue**: Check `stream_stats` in logs

## Security Considerations

- **Always use TOKEN** in production
- **Restrict WebUI_INTERFACES** to trusted networks
- **Use HTTPS/WSS** with reverse proxy in production
- **Firewall port 8765** to allowed IPs only
- **Disable remote access** when not in use

## Integration with Existing KTOx Features

- **Menu Navigation**: All buttons work seamlessly
- **Payloads**: Can be launched and controlled remotely
- **Loot**: View captured files on remote display
- **Settings**: Adjust KTOx config from Cardputer
- **Stealth Mode**: Activate/deactivate from remote

## Files Modified/Created

- ✅ `device_server.py` - Already configured for RaspyJack
- ✅ `ktox_pi/ktox_input.py` - Input bridge (already in place)
- ✅ `/dev/shm/ktox_input.sock` - Created at runtime
- ✅ `/dev/shm/ktox_last.jpg` - Created by ktox_device.py
- ✅ `/root/KTOx/.webui_token` - Optional auth token

## Example Systemd Service

Create `/etc/systemd/system/ktox-device.service`:

```ini
[Unit]
Description=KTOx Device Server
After=network.target
Wants=ktox-ui.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/KTOx
Environment="RJ_WS_HOST=0.0.0.0"
Environment="RJ_WS_PORT=8765"
Environment="RJ_FRAME_PATH=/dev/shm/ktox_last.jpg"
ExecStart=/usr/bin/python3 device_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable ktox-device
sudo systemctl start ktox-device
```

## Next Steps

1. Start KTOx device server
2. Download RaspyJack Cardputer app
3. Configure WebSocket connection: `ws://<ktox-ip>:8765`
4. Launch KTOx main device
5. Control KTOx from Cardputer!

## Support

For issues or questions:
- Check KTOx logs: `/root/KTOx/loot/device.log`
- Monitor system logs: `journalctl -u ktox-device -f`
- Test components individually (see Troubleshooting)
