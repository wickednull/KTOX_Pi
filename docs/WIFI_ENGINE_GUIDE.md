# KTOx WiFi Handshake Engine Guide

## Overview

The new WiFi Handshake Engine provides comprehensive WiFi attack capabilities with proper 4-way handshake capture, deauthentication attacks, and PMKID capture. It uses Scapy for low-level packet control and validation.

## Features

### 1. Monitor Mode Management
- Automatic monitor mode activation using `airmon-ng`
- Fallback to `iw` if airmon-ng fails
- Proper cleanup and restoration to managed mode
- Interface detection and validation

### 2. Network Scanning
- Comprehensive WiFi network discovery using `airodump-ng`
- Extracts: BSSID, ESSID, Channel, Signal strength
- 15-second scan window
- Results displayed with signal strength sorting

### 3. 4-Way Handshake Capture
**How it works:**
1. Target a specific access point (AP)
2. Engine sets WiFi interface to target's channel
3. Starts packet capture thread listening for EAPOL frames
4. Sends deauthentication frames to force reconnection
5. Captures EAPOL frames (4-way handshake messages)
6. Saves valid handshakes to PCAP format

**What's captured:**
- Message 1: AP → Client (encryption info)
- Message 2: Client → AP (client nonce)
- Message 3: AP → Client (GTK, install bit set)
- Message 4: Client → AP (ACK)

**EAPOL Frame Validation:**
- Minimum 2 frames required for valid capture
- Frames must match target BSSID
- Prevents saving invalid/malformed packets

### 4. Deauthentication Attacks
- Sends 802.11 deauth frames with reason code 7
- Configurable packet rate (packets per second)
- Forces devices to reconnect or roam
- Triggers 4-way handshake for capture

### 5. PMKID Attack
- Captures PMKID without clients needed
- Uses shorter capture time (10 seconds typical)
- Works on many newer WPA2/WPA3 implementations
- Faster than 4-way handshake capture

## Usage

### From KTOx Menu
1. **Main Menu** → **WiFi Engine**
2. Choose from options:
   - **Enable Monitor**: Activates monitor mode
   - **WiFi Scan**: Quick network discovery
   - **Deauth AP**: Deauthenticate target network
   - **Handshake Cap**: Old method (airodump-ng based)
   - **HS Engine Pro**: New Scapy-based handshake capture
   - **PMKID Attack**: PMKID capture attack
   - **Select Adapter**: Choose WiFi interface

### Recommended Workflow

**Option A: Capture Handshake for Cracking**
```
1. Enable Monitor Mode (checks adapter support)
2. HS Engine Pro
   → Select network from scan results
   → Confirm target network
   → Engine captures handshake
   → Saved to: loot/handshakes/hs_NETWORK_BSSID_TIMESTAMP.pcap
3. Crack with aircrack-ng:
   aircrack-ng -w wordlist.txt handshake.pcap
```

**Option B: PMKID Attack (Faster)**
```
1. Enable Monitor Mode
2. PMKID Attack
   → Select network from scan results
   → Engine captures PMKID
   → Use hashcat for cracking:
   hashcat -m 22000 pmkid.txt wordlist.txt
```

**Option C: Deauth Network**
```
1. Enable Monitor Mode
2. Deauth AP
   → Select network to deauth
   → Choose duration
   → Kicks all clients offline
   → Causes reconnection (triggers handshake)
```

## Requirements

### Hardware
- WiFi adapter with monitor mode support
  - Recommended: Alfa AWUS036ACH
  - Also works: TP-Link TL-WN722N, various USB adapters
- Raspberry Pi or Linux computer

### Software
```bash
# Debian/Raspberry Pi OS
sudo apt update
sudo apt install -y aircrack-ng python3-scapy

# Verify installation
dpkg -l | grep aircrack
python3 -c "from scapy.all import *; print('OK')"
```

### Python Packages
- `scapy>=2.4.5` - Packet manipulation
- `iw` - Interface management (usually pre-installed)
- `airmon-ng` - Monitor mode management (from aircrack-ng)
- `airodump-ng` - Network scanning (from aircrack-ng)

## Architecture

### WiFiEngine Class
```python
from payloads.wifi.wifi_handshake_engine import get_wifi_engine

engine = get_wifi_engine()

# Methods
engine.enable_monitor_mode(iface)      # Enable monitor mode
engine.disable_monitor_mode()          # Restore managed mode
engine.set_channel(channel)            # Set WiFi channel
engine.scan_networks(timeout=15)       # Discover networks
engine.deauth_network(bssid, count)    # Send deauth frames
engine.capture_handshake(...)          # Capture 4-way handshake
engine.pmkid_attack(...)               # Capture PMKID
engine.get_networks_list()             # Get scan results
```

### Integration with ktox_device.py

New menu functions:
- `do_wifi_handshake_engine()` - Enhanced handshake capture
- `do_wifi_pmkid_attack()` - PMKID attack handler

## File Locations

### Loot Directory
```
/root/KTOx/loot/
├── handshakes/
│   ├── hs_NETWORK_BSSID_20240424_120530.pcap
│   └── hs_NETWORK_BSSID_20240424_120630.pcap
├── wifi_scan_20240424_120530/
└── pmkid_captures/
```

### Engine Code
```
/home/user/KTOX_Pi/payloads/wifi/
├── wifi_handshake_engine.py (main engine)
├── deauth.py (legacy implementation)
├── handshake_hunter.py (alternate version)
└── monitor_mode_helper.py (helper functions)
```

## Troubleshooting

### Monitor Mode Won't Enable
```bash
# Check adapter support
sudo airmon-ng check

# Kill interfering processes
sudo airmon-ng check kill

# Check if interface exists
iw dev

# Manual activation
sudo ip link set wlan1 down
sudo iw dev wlan1 set type monitor
sudo ip link set wlan1 up
```

### No Networks Found
- Ensure monitor mode is active: `iw dev` (shows `type monitor`)
- Check if WiFi is broadcasting: `sudo airodump-ng <mon_iface>`
- Verify antenna connection
- Try different channel: `sudo iw dev <iface> set channel 6`

### Handshake Not Captured
- **Ensure clients connected**: Deauth works better with active devices
- **Try more deauth frames**: Increase `deauth_count` parameter
- **Increase timeout**: Longer capture window increases success
- **Check signal strength**: Weak signals miss frames
- **Verify target channel**: Engine auto-sets, but manual check: `iw dev <iface> link`

### Scapy Import Error
```bash
# Install Scapy
sudo pip3 install scapy

# Or system package
sudo apt install python3-scapy

# Verify
python3 -c "from scapy.all import *; print('OK')"
```

## Security Notes

### Responsible Use
- **Only attack networks you own or have explicit permission to test**
- WiFi attacks violate laws in many jurisdictions if unauthorized
- Deauth attacks disrupt legitimate network use
- PMKID/handshake capture for dictionary attacks requires wordlists

### Privacy
- Captured handshakes contain network identifiers
- PCAP files capture metadata (SSIDs, MAC addresses)
- Store loot securely or delete after testing
- Consider encryption for sensitive network data

### Detection Prevention
- Deauth attacks are easily detectable via packet analysis
- Monitoring systems flag unusual deauth patterns
- Consider timing and frequency to avoid detection
- Use randomized MAC addresses if available

## Comparison: Old vs New Implementation

| Feature | Old (airodump-ng) | New (Scapy Engine) |
|---------|-------------------|-------------------|
| **Control** | Limited | Fine-grained |
| **Validation** | Basic | EAPOL frame verification |
| **Timing** | Fixed | Configurable |
| **Deauth Rate** | Fixed 4 packets | Configurable PPS |
| **Error Handling** | Minimal | Comprehensive |
| **Logging** | None | Detailed debug logs |
| **Framework** | Tool-based | Pure Python |
| **Dependencies** | aircrack-ng only | aircrack-ng + Scapy |

## Advanced Usage

### Custom Deauth Rate
```python
from payloads.wifi.wifi_handshake_engine import get_wifi_engine

engine = get_wifi_engine()
engine.enable_monitor_mode("wlan1")
# Deauth with 20 packets per second
engine.deauth_network("AA:BB:CC:DD:EE:FF", count=50, pps=20)
engine.disable_monitor_mode()
```

### Extended Handshake Capture
```python
# 60-second capture with 10 deauth frames
engine.capture_handshake(
    bssid="AA:BB:CC:DD:EE:FF",
    essid="TestNetwork",
    channel=6,
    timeout=60,          # 60 seconds
    deauth_count=10      # 10 deauth frames
)
```

### Manual Network Scanning
```python
from payloads.wifi.wifi_handshake_engine import get_wifi_engine

engine = get_wifi_engine()
engine.enable_monitor_mode("wlan1")

# Perform scan
engine.scan_networks(timeout=20)

# Get results
networks = engine.get_networks_list()
for bssid, essid, channel, signal in networks:
    print(f"{essid:30} | {bssid} | Ch{channel} | {signal}dBm")

engine.disable_monitor_mode()
```

## Performance Metrics

### Typical Handshake Capture Time
- **With active clients**: 10-20 seconds
- **Without clients**: 30-45 seconds (deauth required)
- **Weak signal**: Up to 60+ seconds

### PMKID Capture Time
- **Average**: 5-15 seconds
- **Modern routers**: 2-5 seconds
- **Older routers**: May not support PMKID

### Network Scan Time
- **Default**: 15 seconds
- **Small networks** (< 10 APs): 5-10 seconds
- **Crowded areas** (50+ APs): 20-30 seconds recommended

## Debugging

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)

from payloads.wifi.wifi_handshake_engine import get_wifi_engine
engine = get_wifi_engine()
# All operations now log detailed debug info
```

### Check PCAP File Validity
```bash
# Check captured frames
tcpdump -r handshake.pcap -e | grep -i eapol

# Verify with wireshark
wireshark handshake.pcap

# Check with aircrack-ng
aircrack-ng -q handshake.pcap
```

## Future Enhancements

- [ ] WiFi 6 (802.11ax) support
- [ ] WPA3 specific capture improvements
- [ ] Automatic wordlist integration
- [ ] Real-time cracking feedback
- [ ] Multi-target simultaneous capture
- [ ] Packet replay capability
- [ ] Custom beacon frame generation

## References

- **4-Way Handshake**: IEEE 802.11i / WPA2 standard
- **PMKID**: Pairwise Master Key Identifier
- **Scapy**: https://scapy.readthedocs.io/
- **Aircrack-ng**: https://www.aircrack-ng.org/
- **WiFi Security**: NIST SP 800-153 / 802.11 specs
