# M5Stack Cardputer Remote Control for KTOX_Pi

Full-featured remote control application for KTOX_Pi running on M5Stack Cardputer with ESP32-S3.

## Features

- **Live Video Streaming**: View KTOX_Pi LCD display on M5Cardputer (240x135 optimized frames)
- **Simple Control Interface**: Keyboard-based input for KTOX device control
- **Settings Persistence**: WiFi credentials and KTOX connection settings saved to SPIFFS
- **Setup Wizard**: First-time WiFi and KTOX host configuration via on-screen prompts
- **Auto-Reconnect**: Automatic reconnection with exponential backoff if connection drops
- **Status Display**: Connection indicator (● connected, ○ disconnected), frame count, uptime
- **Optional Authentication**: Support for auth token if KTOX_Pi requires it

## Hardware Requirements

- M5Stack M5Cardputer with 240x135 display
- ESP32-S3 microcontroller (integrated)
- WiFi capability (WiFi 802.11 b/g/n)
- USB-C connection for programming

## Software Requirements

- PlatformIO (VS Code extension or CLI)
- ESP32 Arduino framework
- M5Cardputer library
- WebSocket client library
- ArduinoJson library
- TJpg_Decoder library

## Building and Deploying

### 1. Prerequisites

Install PlatformIO:
```bash
# Via Python
pip install platformio

# Or via VS Code: Install PlatformIO IDE extension
```

### 2. Build the Firmware

```bash
cd /home/user/KTOX_Pi/m5cardputer

# Compile for M5Stack Cardputer
platformio run -e m5stack-cardputer

# Or to build and upload directly
platformio run -e m5stack-cardputer --target upload
```

### 3. Upload to M5Cardputer

Connect M5Cardputer via USB-C cable and:

```bash
cd /home/user/KTOX_Pi/m5cardputer

# Upload firmware
platformio run -e m5stack-cardputer --target upload

# Monitor serial output for debugging
platformio run -e m5stack-cardputer --target upload --target monitor
```

### 4. First-Time Setup

1. Power on M5Cardputer after upload
2. Follow the on-screen setup wizard:
   - Enter WiFi SSID
   - Enter WiFi password
   - Enter KTOX_Pi IP address (e.g., 192.168.0.50)
   - Enter KTOX WebSocket port (default 8765)
   - (Optional) Enter authentication token
3. Device connects to WiFi and KTOX_Pi WebSocket
4. Frame streaming begins automatically

## Keyboard Controls

**Keyboard input is sent directly to KTOX_Pi. The M5Cardputer just relays button presses.**

- **Arrow Keys / WASD / IJKL**: Send UP/DOWN/LEFT/RIGHT button presses (navigation)
- **Space / Enter**: Send OK button press (confirm/select)
- **H**: Open settings menu (reconfigure WiFi, save settings, exit)

All other key presses are ignored. Control mapping depends on what payloads are running on KTOX_Pi.

## Configuration

Settings are stored in `/settings.json` on device's SPIFFS:

```json
{
  "wifi_ssid": "YourWiFiNetwork",
  "wifi_password": "YourPassword",
  "ktox_host": "192.168.0.50",
  "ktox_port": 8765,
  "auth_token": "optional_token"
}
```

Change settings via the in-device configuration menu (press 'H' on stream view).

## Connection Flow

```
1. WiFi Setup
   └─ WiFi SSID + password stored in SPIFFS (/settings.json)

2. WebSocket Connect
   └─ ws://<ktox_host>:8765

3. Authentication (optional)
   └─ If auth_token configured, send: {"type": "auth", "token": "<token>"}
   └─ Wait for: {"type": "auth_ok"} or connection drop

4. Frame Reception (starts immediately after auth or connection)
   └─ Receive: {"type": "frame_m5", "data": "<base64-jpeg>"}
   └─ Decode base64 → JPEG binary
   └─ Use TJpg_Decoder to render 240x135 image to M5 display

5. Input Events (user presses keyboard)
   └─ Send: {"type": "input", "button": "UP|DOWN|LEFT|RIGHT|OK", "state": "press|release"}
   └─ KTOX_Pi queues input for running payload
```

## Frame Format

Frames are received as JSON messages from device_server.py:

```json
{
  "type": "frame_m5",
  "data": "<base64-encoded JPEG>"
}
```

The M5Cardputer firmware:
1. Parses JSON message
2. Extracts base64 data field
3. Decodes base64 to binary JPEG
4. Passes JPEG binary to TJpg_Decoder.drawJpg()
5. JPEG decoder renders directly to M5 display

**Frame Properties:**
- Size: 240×135 pixels (M5Cardputer native resolution)
- Format: JPEG (base64-encoded for JSON transport)
- Rate: ~6 FPS (configurable on KTOX_Pi via RJ_CARDPUTER_FPS env var)
- Pre-scaled on KTOX_Pi server, no scaling needed on client

## Troubleshooting

### Can't Connect to WiFi
- Check SSID spelling (case-sensitive)
- Verify password is correct
- Ensure WiFi 2.4GHz is available (M5Cardputer doesn't support 5GHz)
- Check WiFi signal strength

### WebSocket Connection Fails
- Verify KTOX_Pi IP address is correct
- Ensure KTOX_Pi device_server is running (`ps aux | grep device_server`)
- Check firewall allows port 8765: `sudo ufw allow 8765`
- Test locally: `netstat -tlnp | grep 8765`

### Frames Not Displaying
- Check KTOX_Pi frame capture is enabled: `env | grep RJ_CARDPUTER`
- Verify M5 frames are being generated: `ls -lh /dev/shm/ktox_m5.jpg`
- Monitor frame file updates: `watch -n 0.5 stat /dev/shm/ktox_m5.jpg | grep Modify`
- Verify JPEG validity: `file /dev/shm/ktox_m5.jpg` (should show "JPEG image data")
- Check device_server.py is running: `ps aux | grep device_server.py`
- Monitor server frame output: Search for "M5Cardputer frame broadcaster" in logs

### Display Shows "Connected!" but No Frames
- Frame broadcaster might not be enabled on device_server.py
- Check: `env | grep CARDPUTER_ENABLED`
- Verify PIL/Pillow is installed on KTOX_Pi (needed for frame scaling)
- Test KTOX_Pi frame capture directly: `python3 -c "from PIL import Image; Image.open('/dev/shm/ktox_m5.jpg')"`

### M5 Display Hangs or Crashes
- Press reset button on M5Cardputer (back of device)
- Check serial monitor for exceptions: `platformio run -e m5stack-cardputer --target monitor`
- Look for out-of-memory (OOM) errors - may need to increase buffer sizes
- Check JPEG quality isn't too high (causing large frames): `env | grep FRAME_QUALITY`

### Compilation Errors
- Update PlatformIO: `platformio update`
- Clean build: `platformio run -e m5stack-cardputer --target clean`
- Delete `.pio` directory and rebuild

## Serial Debugging

Monitor M5Cardputer output during runtime:

```bash
cd /home/user/KTOX_Pi/m5cardputer
platformio device monitor -b 115200

# Or after upload
platformio run -e m5stack-cardputer --target monitor
```

Look for connection status, frame statistics, and error messages.

## Power Consumption

- Idle (WiFi connected, no frame streaming): ~100mA
- Active (streaming frames): ~300-400mA
- Max (streaming + menu interaction): ~500mA

Use a quality USB-C power supply (5V/2A minimum) for reliable operation.

## Known Limitations

- Display aspect ratio differs from KTOX LCD (4:3 vs square)
- Frame scaling may distort certain UI elements
- Latency depends on WiFi signal quality (typically 100-300ms)
- Menu operations limited to available button combinations on M5Cardputer

## Future Improvements

- Hardware button mappings for common attacks
- Recorded frame playback when offline
- Signal strength indicator
- Battery level monitoring
- Screen rotation options

## Integration with KTOX_Pi

This application is designed to work with KTOX_Pi frame streaming infrastructure:

- **device_server.py**: Handles WebSocket connections and frame broadcasting
- **web_server.py**: Provides authentication and configuration
- **.env.frame_capture**: Environment variables controlling frame capture

See `/home/user/KTOX_Pi/docs/M5_CARDPUTER_SETUP.md` for server-side configuration.

## Support

For issues, enable serial debugging and check:
1. KTOX_Pi server logs: `sudo journalctl -u ktox_pi -f` (if using systemd)
2. M5Cardputer serial output via `platformio device monitor`
3. Network connectivity: `ping KTOX_Pi_IP_ADDRESS`

