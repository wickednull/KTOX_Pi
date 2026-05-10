# Spam-Jam BLE Toolkit Setup Guide

## Installation Issue

Spam-Jam requires `bluepy` which has compatibility issues with Python 3.11+. Here are solutions:

### Option 1: Using an older Python version (Recommended)
```bash
sudo apt-get install python3.9
pip3.9 install bluepy
# If needed, update payloads/bluetooth/spam_jam.py to call python3.9
```

### Option 2: Install via system package + compile workaround
```bash
sudo apt-get install -y bluez bluez-tools libglib2.0-dev
pip3 install gatt  # Alternative BLE library
```

### Option 3: Rewrite for compatible library (Bleak)
The Bleak library is actively maintained and works with Python 3.11:
```bash
pip3 install bleak
```

A Bleak-compatible version would need modifications to the external Spam-Jam toolkit; the KTOx wrapper in `payloads/bluetooth/spam_jam.py` will continue to provide LCD controls for whichever interpreter/script path you configure.

## Quick Install
Run the installer script:
```bash
cd /home/user/KTOX_Pi/vendor/spam-jam
chmod +x install_spam_jam.sh
./install_spam_jam.sh
```

## Testing
After installation, test with:
```bash
sudo python3 spam_jam.py
```

If you get a menu, installation was successful!

## Alternative: Use Jam_Fi instead
If Spam-Jam continues to have issues, Jam_Fi offers similar WiFi-layer attack capabilities.
