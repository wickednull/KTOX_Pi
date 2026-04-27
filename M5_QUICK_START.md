# M5Cardputer Quick Start

## TL;DR - Get it working in 30 seconds

### On KTOX_Pi:

```bash
cd /root/KTOX_Pi
sudo ./run_with_m5_support.sh
```

That's it. Frame capture and WebSocket server start automatically.

### On M5Cardputer:

Use KTOXM5 firmware and set:
```cpp
const char* KTOX_HOST = "YOUR_KTOX_IP";  // e.g. "192.168.1.100"
const int KTOX_WS_PORT = 8765;
```

Flash and connect. Done.

---

## Verify It's Working

```bash
# On KTOX_Pi, check frames are being captured:
watch -n 0.5 ls -lh /dev/shm/ktox_last.jpg
```

Timestamps should update every ~160ms (for 6 FPS). If they don't, see troubleshooting below.

---

## Adjusting Frame Rate

```bash
# Higher responsiveness (but more bandwidth)
sudo /root/KTOX_Pi/run_with_m5_support.sh 10

# Lower bandwidth (but more laggy)
sudo /root/KTOX_Pi/run_with_m5_support.sh 3

# Default
sudo /root/KTOX_Pi/run_with_m5_support.sh
```

---

## Troubleshooting

### "Frame file exists but not updating"

```bash
# Check if LCD is actually being used
ps aux | grep ktox

# Check file permissions
ls -l /dev/shm/ktox_last.jpg
chmod 666 /dev/shm/ktox_last.jpg
```

### "M5 can't connect to device_server"

```bash
# Verify WebSocket is running
netstat -tlnp | grep 8765

# Check firewall
sudo ufw allow 8765
```

### "High latency / lag"

```bash
# Use lower FPS
sudo /root/KTOX_Pi/run_with_m5_support.sh 3

# Check network ping time
ping YOUR_KTOX_IP
```

---

## How It Works

```
LCD Display → Saved as JPEG every 160ms → device_server reads → sends to M5 via WebSocket
```

**Key files:**
- `LCD_1in44.py` — Does the frame capture (lines 328-334)
- `device_server.py` — Streams frames to M5
- `run_with_m5_support.sh` — Startup with proper config
- `.env.frame_capture` — Environment variables
- `test_m5_setup.py` — Verify everything works

---

## Full Documentation

See `M5_CARDPUTER_SETUP.md` for complete details.
