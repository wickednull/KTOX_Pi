# Scripts

Utility scripts for KTOX_Pi setup and management.

## M5Cardputer Integration

### `run_with_m5_support.sh`
Starts KTOX_Pi with M5Cardputer remote control support enabled.

**Usage:**
```bash
sudo ./run_with_m5_support.sh [FPS]
```

**Examples:**
```bash
# Default (6 FPS)
sudo ./run_with_m5_support.sh

# Higher responsiveness
sudo ./run_with_m5_support.sh 10

# Lower bandwidth
sudo ./run_with_m5_support.sh 3
```

### `test_m5_setup.py`
Verifies M5Cardputer integration is configured correctly.

**Usage:**
```bash
python3 test_m5_setup.py
```

Checks:
- Environment variables configured
- /dev/shm is writable
- Frame files being captured
- WebSocket port accessible
- Required dependencies installed

### `install_m5_service.sh`
Installs KTOX_Pi M5Cardputer support as a systemd service for automatic startup.

**Usage:**
```bash
sudo ./install_m5_service.sh
```

Then:
```bash
sudo systemctl enable ktox-with-m5    # Enable on boot
sudo systemctl start ktox-with-m5     # Start service
sudo journalctl -u ktox-with-m5 -f    # View logs
```

## Other Scripts

- `check_webui_js.sh` — Verify web UI JavaScript files
- `install_pyboy.sh` — Install PyBoy emulator support
- `pin_wifi_names.sh` — Configure WiFi network pinning
- `pboy.sh` — PyBoy launcher
- `optimize_gifs.py` — GIF optimization utility

See main [README.md](../README.md) for full documentation.
