# M5Cardputer Remote Control Integration

This document explains how to set up KTOX_Pi for remote control via the M5Cardputer device.

## Overview

The M5Cardputer connects to KTOX_Pi via WebSocket to:
- **Receive live video frames** from the LCD display
- **Send button/input commands** to control the KTOX device

## Architecture

```
KTOX_Pi Device
├── LCD Display (128x128 ST7735S)
│   ├── Frame Mirror → /dev/shm/ktox_last.jpg (standard 128x128 @6 FPS)
│   └── M5 Optimizer → /dev/shm/ktox_m5.jpg (240x135 scaled @6 FPS)
│
├── device_server.py (WebSocket @ :8765)
│   ├── Standard profile: 128x128 JPEG frames for web UI
│   └── M5Cardputer profile: 240x135 optimized JPEG for M5 display
│   └── Broadcasts both profiles to connected clients
│
└── web_server.py (HTTP @ :8080)
    └── Web UI (optional)

         ↓ WebSocket Connection
         
M5Cardputer (240x135 LCD)
├── Receives optimized frame stream (240x135 @6 FPS)
├── Displays on local screen  
└── Sends button input events back
```

## Setup Instructions

### 1. Enable Frame Capture (Automatic)

The frame capture is **already built into KTOX_Pi**. Just ensure environment variables are set:

```bash
# The configuration is in .env.frame_capture
source /root/KTOXM5_Pi/.env.frame_capture

# Key variables:
export RJ_FRAME_MIRROR=1          # Enable frame capture
export RJ_FRAME_PATH=/dev/shm/ktox_last.jpg  # Where frames are saved
export RJ_FRAME_FPS=6              # Update rate (6 FPS = ~167ms per frame)
```

### 2. Start KTOX_Pi with M5 Support

Use the provided startup script:

```bash
sudo /root/KTOX_Pi/scripts/run_with_m5_support.sh [FPS]
```

Examples:
```bash
# Default (6 FPS)
sudo /root/KTOX_Pi/scripts/run_with_m5_support.sh

# Higher responsiveness (10 FPS)
sudo /root/KTOX_Pi/scripts/run_with_m5_support.sh 10

# Lower bandwidth (3 FPS)
sudo /root/KTOX_Pi/scripts/run_with_m5_support.sh 3
```

### 3. Verify Frame Capture

Check if frames are being written:

```bash
# Watch frame updates in real-time
watch -n 0.5 ls -lh /dev/shm/ktox_last.jpg

# Or check timestamp updates
while true; do stat /dev/shm/ktox_last.jpg | grep Modify; sleep 1; done
```

If timestamps aren't changing, the frame capture isn't working. See "Troubleshooting" below.

### 4. Configure M5Cardputer

In your KTOXM5 firmware, set the device connection:

```cpp
// Example WebSocket connection in M5 firmware
const char* KTOX_HOST = "192.168.1.100";  // KTOX_Pi IP
const int KTOX_WS_PORT = 8765;
const char* WS_PATH = "/";  // device_server.py path
```

### 5. Configure M5 Frame Optimization (Optional)

The M5Cardputer has a 240x135 display, much smaller than KTOX's 128x128. KTOX_Pi automatically generates optimized frames for M5:

Edit `.env.frame_capture` to customize M5 frame settings:

```bash
# M5 frame optimization
export RJ_CARDPUTER_ENABLED=1              # Enable M5 optimization
export RJ_CARDPUTER_FRAME_WIDTH=240        # M5 display width
export RJ_CARDPUTER_FRAME_HEIGHT=135       # M5 display height
export RJ_CARDPUTER_FRAME_MODE=contain     # Scale mode: stretch|contain|fit
export RJ_CARDPUTER_FPS=6                  # M5 frame rate (can differ from LCD)
export RJ_CARDPUTER_FRAME_QUALITY=75       # JPEG quality (1-95, higher = better)
export RJ_CARDPUTER_FRAME_SUBSAMPLING=4:2:0  # JPEG subsampling for bandwidth
```

**Scale Modes:**
- **stretch**: Fill display (may distort aspect ratio) - fastest
- **contain**: Fit entire frame with letterboxing - preserves aspect - recommended
- **fit**: Crop to aspect ratio then scale - no letterbox - best for full display

## Performance Tuning

### Frame Rate (RJ_FRAME_FPS)

- **3 FPS**: Very low bandwidth, ~8 KB/s, slight lag
- **6 FPS** ✓ Recommended: Good balance, ~16 KB/s, responsive
- **10 FPS**: Higher responsiveness, ~27 KB/s
- **15+ FPS**: Overkill, LCD typically updates at 10 FPS anyway

### Network Requirements

For stable operation:
- **Local Network**: Use WiFi (wlan0) or Ethernet (eth0)
- **Bandwidth**: 3-10 FPS uses 8-30 KB/s on typical home networks
- **Latency**: Should be <100ms for responsive control

## Troubleshooting

### 1. No Frames Being Captured

**Symptoms**: `/dev/shm/ktox_last.jpg` doesn't update or doesn't exist

**Solution**:
```bash
# Check if RJ_FRAME_MIRROR is enabled
env | grep RJ_FRAME

# Check if device_server.py is running
ps aux | grep device_server.py

# Check permissions on /dev/shm
ls -ld /dev/shm
chmod 777 /dev/shm

# Check for errors in KTOX_Pi
sudo journalctl -u ktox_pi -f  # if using systemd
```

### 2. WebSocket Connection Refused

**Symptoms**: M5 can't connect to `192.168.x.x:8765`

**Solution**:
```bash
# Verify device_server.py is running
ps aux | grep device_server.py

# Check port is listening
netstat -tlnp | grep 8765

# Verify firewall isn't blocking
sudo ufw allow 8765

# Try connecting locally first
python3 -c "import socket; s = socket.create_connection(('localhost', 8765), timeout=5); print('Connected!')"
```

### 3. High Latency / Lag

**Symptoms**: M5 display lags behind physical KTOX device

**Solution**:
```bash
# Reduce frame rate if on slower network
sudo /root/KTOX_Pi/scripts/run_with_m5_support.sh 3

# Check network
ping 192.168.x.x  # Should be <50ms

# Monitor frame timing
tcpdump -i wlan0 'tcp port 8765' -l | head -20
```

### 4. M5 Screen Freezes or Corrupted Frames

**Symptoms**: M5 display freezes or shows corrupted JPEG

**Solution**:
```bash
# Verify JPEG validity
file /dev/shm/ktox_last.jpg

# Test JPEG rendering
identify /dev/shm/ktox_last.jpg

# Reduce FPS if frames are corrupted
export RJ_FRAME_FPS=3
python3 device_server.py &
```

## Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `RJ_FRAME_MIRROR` | `1` | Enable/disable frame capture (0=off, 1=on) |
| `RJ_FRAME_PATH` | `/dev/shm/ktox_last.jpg` | Where to save frame JPEGs |
| `RJ_FRAME_FPS` | `10` | Frame capture rate (frames per second) |
| `RJ_WS_HOST` | `0.0.0.0` | WebSocket server bind address |
| `RJ_WS_PORT` | `8765` | WebSocket server port |
| `RJ_WS_TOKEN` | (empty) | Optional authentication token |

## Implementation Details

### Frame Capture Flow

1. **KTOX_Pi LCD Loop** (ktox_device_root.py)
   - Renders UI to PIL Image
   - Calls `LCD.LCD_ShowImage(image, 0, 0)`

2. **Frame Mirror** (LCD_1in44.py)
   - Inside `LCD_ShowImage()` method
   - Checks if `_FRAME_MIRROR_ENABLED` (from RJ_FRAME_MIRROR env var)
   - Saves frame as JPEG to `_FRAME_MIRROR_PATH` every `_FRAME_MIRROR_INTERVAL` seconds
   - Non-blocking: doesn't affect LCD refresh speed

3. **Device Server** (device_server.py)
   - Uses `FrameCache` to watch `/dev/shm/ktox_last.jpg`
   - On file change: reads JPEG, base64-encodes, broadcasts to WebSocket clients
   - Sends frame message type: `{"type": "frame", "data": "<base64_jpeg>"}`

4. **M5Cardputer** (KTOXM5 firmware)
   - Connects to WebSocket at `KTOX_IP:8765`
   - Receives frame messages
   - Decodes base64 JPEG
   - Renders to M5 screen (240x135 native, scales from 128x128)
   - Sends input events back on button press

### Why No Separate Daemon?

The original frame_capture daemon script was unnecessary because:
- KTOX already captures frames automatically
- Frame mirroring is built into LCD_1in44.py's `LCD_ShowImage()` method
- No external daemon needed—just environment variables
- This approach is simpler and more reliable

## Testing

### Local Frame Capture Test

```bash
# Start KTOX_Pi with frame capture
export RJ_FRAME_MIRROR=1
export RJ_FRAME_FPS=6
python3 ktox_device_root.py &

# Monitor frame updates
watch -n 0.5 'ls -lh /dev/shm/ktox_last.jpg && file /dev/shm/ktox_last.jpg'

# Stop
kill %1
```

### WebSocket Connection Test

```bash
# Start device_server directly
python3 device_server.py &

# Connect with Python WebSocket client
python3 -c "
import asyncio, websockets, json
async def test():
    async with websockets.connect('ws://localhost:8765') as ws:
        msg = await ws.recv()
        data = json.loads(msg)
        print(f'Received frame: {len(data.get(\"data\", \"\"))} bytes')
asyncio.run(test())
"

# Stop
kill %1
```

## Performance Metrics

On Raspberry Pi Zero 2W with 6 FPS:
- **CPU Usage**: 2-3% additional (frame encoding)
- **Memory**: ~5 MB for frame buffer
- **Network**: 16-30 KB/s depending on scene complexity
- **Latency**: <200ms typical

## See Also

- [KTOXM5 Firmware Repository](https://github.com/wickednull/KTOXM5)
- [device_server.py Documentation](./device_server.py)
- [LCD_1in44.py Frame Mirror Code](./LCD_1in44.py#L328-L334)
