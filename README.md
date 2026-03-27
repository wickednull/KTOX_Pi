<div align="center">

```
 ██╗  ██╗████████╗ ██████╗ ██╗  ██╗       ██████╗ ██╗
 ██║ ██╔╝╚══██╔══╝██╔═══██╗╚██╗██╔╝       ██╔══██╗██║
 █████╔╝    ██║   ██║   ██║ ╚███╔╝        ██████╔╝██║
 ██╔═██╗    ██║   ██║   ██║ ██╔██╗        ██╔═══╝ ██║
 ██║  ██╗   ██║   ╚██████╔╝██╔╝ ██╗       ██║     ██║
 ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝       ╚═╝     ╚═╝
```

**Network penetration & purple team suite for Raspberry Pi Zero 2W**

[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red?style=flat-square&logo=raspberry-pi)](https://www.raspberrypi.com)
[![OS](https://img.shields.io/badge/OS-Kali%20Linux%20ARM64-557C94?style=flat-square&logo=kali-linux)](https://www.kali.org/get-kali/#kali-arm)
[![Python](https://img.shields.io/badge/python-3.11+-yellow?style=flat-square&logo=python)](https://www.python.org)
[![Payloads](https://img.shields.io/badge/payloads-155-darkred?style=flat-square)](#-payloads-155-scripts)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Usage](https://img.shields.io/badge/usage-authorized%20testing%20only-blue?style=flat-square)](#-disclaimer)
[![Author](https://img.shields.io/badge/author-wickednull-red?style=flat-square&logo=github)](https://github.com/wickednull)

</div>

---

## ▐ WHAT IS KTOx_Pi

KTOx_Pi turns a Raspberry Pi Zero 2W into a standalone handheld network penetration and purple team device. Plug it into a network via Ethernet, navigate the LCD attack menu with the joystick, and everything runs silently from boot — no laptop required.

The **Waveshare 1.44" LCD HAT** gives you a full joystick-controlled menu on the device. The **WebUI** at port 8080 mirrors the LCD live so you can control everything from any browser too. Every module from the full KTOx suite is bundled — ARP attacks, MITM, WiFi engine, Responder/NTLMv2, purple team defense, DNS spoofing with 30+ phishing sites, and 155 payload scripts across 12 categories.

> **This is not a custom OS image.** It installs cleanly on top of a fresh Kali Linux ARM64 image.

---

## ▐ HARDWARE

| Component | Part | ~Cost |
|-----------|------|-------|
| SBC | Raspberry Pi Zero 2WH *(pre-soldered headers)* | $15 |
| Display + controls | Waveshare 1.44" LCD HAT (ST7735S, 128×128) | $14 |
| WiFi adapter | Alfa AWUS036ACH or TP-Link AC1300 | $30 |
| Ethernet | USB-C OTG to Ethernet adapter | $10 |
| Power | PiSugar2 or USB power bank | $20 |
| Storage | 32GB+ microSD (Class 10 / A1) | $10 |
| **Total** | | **~$99** |

> The **Pi Zero 2WH** has pre-soldered headers — the LCD HAT plugs straight on, no soldering needed.

The onboard WiFi (`wlan0`) is reserved for WebUI access and internet. The external USB adapter (`wlan1+`) is used for monitor mode and WiFi attacks.

---

## ▐ COMPATIBLE HARDWARE

Works on any Raspberry Pi with a standard 40-pin GPIO header.

| Board | Status | Notes |
|-------|--------|-------|
| **Pi Zero 2W / 2WH** ⭐ | ✅ Full support | Built and tested on this. Perfect field size. |
| **Pi 3B / 3B+** | ✅ Full support | Same Kali ARM64 image, same 40-pin header. Drop-in. |
| **Pi 4B** | ✅ Full support | Fully compatible. More power than needed but works perfectly. |
| **Pi Zero W (v1)** | ⚠️ Partial | 32-bit only — use Kali ARMhf image instead of ARM64. |
| **Pi 5** | ⚠️ Needs tweak | Different GPIO chip (RP1). Swap `RPi.GPIO` for `lgpio` or `gpiozero`. |
| **Pi Pico / Pico W** | ❌ Not supported | Microcontroller — not Linux, completely different architecture. |

BCM pin numbers in `LCD_Config.py` (RST=27, DC=25, CS=8, BL=24) and all button pins (5, 6, 13, 16, 19, 20, 21, 26) are consistent across all compatible Pi models.

---

## ▐ BUTTON CONTROLS

```
Joystick UP      navigate up
Joystick DOWN    navigate down
Joystick LEFT    back / cancel
Joystick RIGHT   select / enter submenu
Joystick CTR     select / confirm

KEY1   back  (same as LEFT)
KEY2   home screen from anywhere
KEY3   stop running attack / exit payload

Stealth exit:    hold KEY1 + KEY3 for 3 seconds
```

---

## ▐ LCD MENU STRUCTURE

```
▐ KTOx_Pi ▌  (home)
│
├── Network
│   ├── Scan Network        nmap -sn ping sweep → host table
│   ├── Show Hosts          scroll discovered IP / MAC list
│   ├── Ping Gateway        4-packet ping test
│   ├── Network Info        IP, gateway, interface, loot count
│   └── ARP Watch           passive ARP conflict monitor
│
├── Offensive
│   ├── Kick ONE off        ARP denial → selected host
│   ├── Kick ALL off        ARP denial → gateway (drops everyone)
│   ├── ARP MITM            bidirectional ARP poison + IP forward
│   ├── ARP Flood           saturate target ARP cache
│   ├── Gateway DoS         flood router with fake ARP entries
│   ├── ARP Cage            isolate target — sees LAN, not internet
│   └── NTLMv2 Capture      redirect to Responder menu
│
├── WiFi Engine
│   ├── Enable Monitor      airmon-ng check kill → airmon-ng start
│   ├── Disable Monitor     airmon-ng stop → restart NetworkManager
│   ├── WiFi Scan           airodump-ng CSV log to loot
│   ├── Deauth (Payload)    launches payloads/wifi/deauth.py
│   ├── Handshake Cap       configure BSSID/channel via WebUI or SSH
│   ├── PMKID Attack        launches payloads/wifi/pmkid_capture.py
│   ├── Evil Twin AP        launches payloads/wifi/evil_twin.py
│   └── Select Adapter      pick from detected wlan interfaces
│
├── MITM & Spoof
│   ├── Start MITM Suite    full config via SSH + ktox_mitm.py
│   ├── DNS Spoofing ON     pick phishing site → php -S :80
│   ├── DNS Spoofing OFF    stop php + ettercap
│   ├── Rogue DHCP/WPAD     rogue_dhcp_wpad.py payload
│   ├── Silent Bridge       silent_bridge.py payload
│   └── Evil Portal         honeypot.py captive portal
│
├── Responder
│   ├── Responder ON        Responder.py -Q -I <iface>
│   ├── Responder OFF       kill Responder
│   └── Read Hashes         browse Responder/logs/ on LCD
│
├── Purple Team
│   ├── ARP Watch           live ARP conflict detection
│   ├── ARP Diff Live       baseline then alert on changes
│   ├── Rogue Detector      scan every 30s for new MACs
│   ├── LLMNR Detector      scapy sniffer on UDP 5355
│   ├── ARP Harden          static ARP entries for all known hosts
│   ├── Baseline Export     save host table to loot/baseline_DATE.json
│   ├── Verify Baseline     diff current hosts vs saved baseline
│   └── SMB Probe           smb_probe.py payload
│
├── Payloads                155 scripts across 12 categories
│
├── Loot                    browse /root/KTOx/loot/ on LCD
│
├── Stealth                 blank LCD — all attacks keep running silently
│
└── System
    ├── WebUI Status        http://[ip]:8080  /  ws://[ip]:8765
    ├── Refresh State       re-detect interface + gateway
    ├── System Info         kernel, uptime, temp, loot count
    ├── Discord Webhook     configure exfiltration webhook
    ├── Reboot
    └── Shutdown
```

---

## ▐ KTOx SUITE MODULES

The full KTOx suite installs to `/root/KTOx/`. Access over SSH or launch from the LCD menus.

| Module | Description |
|--------|-------------|
| `ktox.py` | Full blood-red TUI — 35+ modules, ARP attacks, MITM, recon, host scanning, NDJSON session logging |
| `ktox_mitm.py` | DNS/DHCP spoof, HTTP sniffer, credential harvester, SSL strip, 5-template captive portal, IP forwarding |
| `ktox_advanced.py` | JS/HTML injector into HTTP responses, multi-protocol sniffer (FTP/SMTP/POP3/IMAP/Telnet/IRC/Redis/SNMP), PCAP export, NTLMv2 relay, session hijack |
| `ktox_extended.py` | LLMNR/WPAD/NBT-NS poisoner, rogue SMB server, network topology mapper, report generator, hashcat/john interface |
| `ktox_defense.py` | Purple team — ARP hardening, LLMNR disable, SMB signing enforce, encrypted DNS, cleartext protocol audit, dry-run preview on every change |
| `ktox_stealth.py` | IoT device fingerprinter (5-layer), Ghost/Ninja/Normal stealth profiles, MAC rotation, rate limiting, traffic jitter |
| `ktox_netattack.py` | ICMP redirect (stealthy MITM alternative), IPv6 NDP spoof, DHCPv6 spoof, IPv6 RA flood |
| `ktox_wifi.py` | Monitor mode manager, airodump-ng AP/client scanner, deauth, WPA handshake, PMKID, evil twin |
| `ktox_dashboard.py` | Live Flask web dashboard at `:9999` — attack status, loot browser, real-time interface stats |
| `ktox_repl.py` | Interactive REPL — `set`/`get` session vars, `module.start`/`module.stop`, plugin system |
| `scan.py` | nmap scanner returning `[ip, mac, vendor, hostname]` |
| `spoof.py` | ARP packet crafting and injection engine |

```bash
# SSH in (default Kali creds — change these)
ssh root@[ip]

# Full TUI
python3 /root/KTOx/ktox.py

# Individual modules
python3 /root/KTOx/ktox_defense.py
python3 /root/KTOx/ktox_mitm.py
python3 /root/KTOx/ktox_wifi.py

# Interactive REPL
python3 /root/KTOx/ktox_repl.py

# KTOx live dashboard
python3 /root/KTOx/ktox_dashboard.py
# open http://[ip]:9999
```

---

## ▐ PAYLOADS (155 scripts)

Drop any `.py` file into a category folder and it appears in the Payloads menu automatically on next navigation. All payloads use `_input_helper.py` so WebUI virtual buttons work out of the box too.

| Category | Count | Highlights |
|----------|-------|-----------|
| `reconnaissance` | 25 | ARP scanner, traffic analyzer, log4shell scanner, ping sweep, TCP/UDP port scanners, DNS zone transfer, SMB shares, SNMP walk, OS fingerprint, cam finder, wardriving, Navarro OSINT |
| `interception` | 38 | KickThemOut, MITM code injector, silent bridge, DHCP starvation, VLAN hopper, EternalBlue, Kerberoasting, PetitPotam, PrintNightmare, SMB relay, Pass the Hash, ProxyLogon, ProxyShell, Follina, KRACK, SSH/FTP/Telnet bruteforce, hashcat |
| `wifi` | 18 | Deauth (multi-target), evil twin, PMKID capture, handshake capture, TinyWifite, Marauder, WPS Pixie, WiFi lab, beacon flood, probe sniffer, channel analyzer, rogue AP |
| `dos` | 6 | SYN flood, UDP flood, LAND attack, smurf, ping of death, ARP poison DoS |
| `bluetooth` | 9 | BLE spam, impersonator, flood, replay, char scanner, service explorer, BT scanner |
| `social_eng` | 5 | Evil twin captive portals — Facebook, Google, PayPal, router login, VPN login |
| `general` | 36 | MAC spoof, C2 controller, Bloodhound collector, pwnagotchi, process killer, file browser, fs encrypt/decrypt, webcam spy, self-destruct, auto-update, shell |
| `games` | 13 | Breakout, snake, Tetris, 2048, Conway's Life, Doom demake, clock, pomodoro, video player |
| `exfiltration` | 1 | Discord webhook loot exfiltration |
| `remote_access` | 2 | PTY shell over network, Tailscale control |
| `evil_portal` | 1 | Full captive portal with credential capture |
| `examples` | 2 | `_payload_template.py`, button demo |

**Shared helpers (in `payloads/` root):**
- `_input_helper.py` — unified GPIO + WebUI virtual button input
- `monitor_mode_helper.py` — shared monitor mode management
- `hid_helper.py` — USB HID keyboard/mouse emulation via zero-hid

---

## ▐ DNS SPOOF PHISHING SITES

30+ credential harvesting pages ready to go in `DNSSpoof/sites/`. Select one from `MITM & Spoof → DNS Spoofing ON`, PHP spins up on port 80, and DNS redirects victims to the chosen page. Captured credentials save to `DNSSpoof/captures/`.

**Sites included:** Adobe · Amazon · Badoo · Google · iCloud · Instagram · LinkedIn · Microsoft · Netflix · Origin · PayPal · Pinterest · PlayStation · ProtonMail · Shopify · Snapchat · Spotify · Steam · Twitter · WiFi Login · WordPress · Yahoo · Yandex — plus lightweight custom phish pages for **Facebook, Google, PayPal, router login**, and **VPN login**.

---

## ▐ WEBUI

Full remote control from any browser at `http://[ip]:8080`.

| Feature | Description |
|---------|-------------|
| 📺 **Live LCD mirror** | 10fps screen stream via WebSocket — see exactly what's on the device |
| 🎮 **Virtual gamepad** | Full button control from the browser — no physical access needed |
| 🛠️ **Payload IDE** | Browse, edit, create, and launch payloads remotely |
| 📁 **Loot browser** | View, preview, and download all captured files with nmap XML visualizer |
| 📊 **System monitor** | CPU, RAM, temp, disk, uptime, active payload status |
| 💻 **Shell** | Full interactive PTY terminal in the browser (xterm.js) |
| 🔔 **Discord webhook** | Configure loot exfiltration target |
| 🔐 **Auth** | Username/password login with session tokens and first-run bootstrap |

```
http://[ip]:8080    WebUI (HTTP)
ws://[ip]:8765      WebSocket device server (frame mirror + virtual buttons)
http://[ip]:9999    KTOx live dashboard (ktox_dashboard.py)
```

The LCD frame is always saved as a JPEG at `/dev/shm/ktox_last.jpg` for any external tool that needs it.

---

## ▐ INSTALL

### Step 1 — Flash Kali to SD

Download the official Kali Linux ARM64 image for Raspberry Pi Zero 2W from [kali.org/get-kali/#kali-arm](https://www.kali.org/get-kali/#kali-arm) and flash with **Raspberry Pi Imager** or **Balena Etcher**.

### Step 2 — SSH in

```bash
ssh root@[pi-ip]
# default password: kali
```

### Step 3 — Clone and install

```bash
git clone https://github.com/wickednull/KTOx_Pi /tmp/KTOx_Pi
cd /tmp/KTOx_Pi
chmod +x install.sh
sudo bash install.sh
```

Or copy manually:
```bash
scp -r KTOx_Pi/ root@[pi-ip]:/tmp/
ssh root@[pi-ip]
cd /tmp/KTOx_Pi && sudo bash install.sh
```

The installer is **fully unattended** and reboots when done. On the next boot the KTOx demon skull logo appears, followed by the main menu.

### What the installer does

| Step | Action |
|------|--------|
| 1 | Detects `/boot/firmware/config.txt` or `/boot/config.txt` (Bookworm-compatible) |
| 2 | Enables SPI and I2C |
| 3 | Sets GPIO pull-ups for all 8 joystick + button pins |
| 4 | Installs APT packages — nmap, aircrack-ng, hostapd, dnsmasq, hashcat, john, ettercap, php, and more |
| 5 | Installs Nexmon for onboard WiFi monitor mode support |
| 6 | Installs Python packages via pip |
| 7 | Downloads Font Awesome for LCD icon rendering |
| 8 | Copies all files to `/root/KTOx/` |
| 9 | Creates `/root/Raspyjack → /root/KTOx` symlink for payload compatibility |
| 10 | Generates WebUI auth token and session secret |
| 11 | Pins onboard WiFi MAC to `wlan0` via systemd `.link` + udev rule |
| 12 | Configures NetworkManager to leave monitor interfaces unmanaged |
| 13 | Creates and enables 3 systemd services |
| 14 | Configures auto-login on tty1 |
| 15 | Sets hostname to `ktox`, writes MOTD and SSH banner |
| 16 | Runs health checks (SPI, Python imports, tool availability) |
| 17 | Reboots |

---

## ▐ SERVICES

Three systemd services are created and enabled on boot.

| Service | What it runs | Port |
|---------|-------------|------|
| `ktox.service` | `ktox_device.py` — LCD firmware + menu controller | — |
| `ktox-device.service` | `device_server.py` — WebSocket server | 8765 |
| `ktox-webui.service` | `web_server.py` — HTTP WebUI | 8080 |

```bash
# Check all services
systemctl status ktox ktox-device ktox-webui

# Live logs
journalctl -fu ktox
journalctl -fu ktox-device
journalctl -fu ktox-webui

# Restart LCD firmware
systemctl restart ktox

# Run headless (disable LCD service, keep WebUI)
systemctl stop ktox && systemctl disable ktox
```

---

## ▐ LOOT

Everything is saved to `/root/KTOx/loot/`.

```
/root/KTOx/loot/
├── atk_arp_mitm_20250101_120000.log   attack runner logs
├── wifi_scan_20250101-01.csv          airodump-ng WiFi scans
├── baseline_20250101.json             ARP baseline exports
├── payload.log                        combined payload stdout
├── MITM/                              MITM session captures
├── Nmap/                              nmap XML results
└── payloads/                          per-payload loot subdirs
```

```bash
# On LCD:   Loot menu
# In WebUI: http://[ip]:8080 → Loot tab
# Via SSH:  ls -lh /root/KTOx/loot/

# Pull everything locally
scp -r root@[ip]:/root/KTOx/loot/ ./loot/
```

---

## ▐ STEALTH MODE

Select `Stealth` from the home menu. The LCD goes blank (or shows a configured decoy image). **All attacks and services keep running silently in the background.**

**Exit stealth:**
- Hold **KEY1 + KEY3** for 3 seconds
- Or write `{"stealth": false}` to `/dev/shm/ktox_stealth.json` from WebUI or SSH

---

## ▐ HEADLESS MODE

No LCD HAT? `ktox_device.py` detects missing hardware and falls back gracefully.

- Full control via WebUI at `http://[ip]:8080`
- Full TUI via SSH: `python3 /root/KTOx/ktox.py`
- WebUI virtual gamepad still injects button events to all running payloads

---

## ▐ ADDING PAYLOADS

Drop any `.py` file into a category folder under `/root/KTOx/payloads/` and it shows up in the menu automatically.

```
payloads/
├── reconnaissance/
├── interception/
├── wifi/
├── dos/
├── bluetooth/
├── social_eng/
├── exfiltration/
├── remote_access/
├── evil_portal/
├── games/
├── general/
└── examples/    ← start here: _payload_template.py
```

Every payload should import the shared input helper:
```python
from payloads._input_helper import get_button
```
This gives you unified GPIO + WebUI virtual button support automatically. See `payloads/examples/_payload_template.py` for a minimal working starting point.

---

## ▐ FILE STRUCTURE

```
KTOx_Pi/
│
├── install.sh                   run this on a fresh Kali ARM image
├── README.md
├── requirements.txt
├── gui_conf.json                KTOx blood-red colour scheme
├── discord_webhook.txt          paste your webhook URL here
│
├── ktox_pi/                     LCD firmware core
│   ├── ktox_device.py           main firmware controller + full menu tree
│   ├── LCD_1in44.py             Waveshare ST7735S driver
│   ├── LCD_Config.py            SPI + GPIO hardware config
│   └── rj_input.py              WebUI virtual button bridge (Unix socket)
│
├── ktox.py                      KTOx main TUI
├── ktox_mitm.py                 MITM + credential harvest engine
├── ktox_advanced.py             JS inject, multi-proto sniffer, PCAP
├── ktox_extended.py             LLMNR, rogue SMB, topology, hash crack
├── ktox_defense.py              purple team defense suite
├── ktox_stealth.py              stealth + IoT fingerprinter
├── ktox_netattack.py            ICMP redirect, IPv6 attacks
├── ktox_wifi.py                 WiFi attack engine
├── ktox_dashboard.py            Flask live dashboard (:9999)
├── ktox_repl.py                 interactive REPL + plugins
├── ktox_config.py               persistent config
├── scan.py                      nmap scanner helper
├── spoof.py                     ARP packet engine
│
├── device_server.py             WebSocket server (:8765)
├── web_server.py                HTTP WebUI (:8080)
├── nmap_parser.py               nmap XML parser for WebUI
│
├── web/                         WebUI frontend (HTML/JS/CSS)
├── payloads/                    155 payload scripts (12 categories)
├── Responder/                   LLMNR/NBT-NS/MDNS poisoner
├── DNSSpoof/                    30+ phishing site templates
├── wifi/                        WiFi manager integration modules
├── img/logo.bmp                 128×128 boot logo (KTOx demon skull)
└── assets/                      screenshots
```

---

## ▐ PYTHON REQUIREMENTS

```
rich>=13.0.0        terminal UI
scapy>=2.5.0        packet crafting + injection
python-nmap>=0.7.1  nmap wrapper
netifaces>=0.11.0   network interface enumeration
flask>=3.0.0        web dashboard
pillow>=10.0.0      LCD image rendering
spidev>=3.6         SPI bus driver
RPi.GPIO>=0.7.1     GPIO (buttons + LCD hardware)
requests            HTTP client
websockets          WebSocket server
customtkinter       desktop GUI (Pi 4/5 with display only)
```

**System tools** (installed automatically by `install.sh`):
`nmap` · `aircrack-ng` · `aireplay-ng` · `airodump-ng` · `airmon-ng` · `hostapd` · `dnsmasq` · `hashcat` · `john` · `ettercap` · `php` · `arpspoof` · `tcpdump` · `iw` · `hcxdumptool`

---

## ▐ DISCLAIMER

KTOx_Pi is intended exclusively for **authorized penetration testing, security research, and education** on networks and systems you own or have explicit written permission to test.

Unauthorized use against any network, device, or individual is illegal and unethical. The author accepts no responsibility for misuse.

```
authorized eyes only
```

---

## ▐ CREDITS

KTOx_Pi is built on top of **RaspyJack** — and we want to be upfront about that. The WebUI, WebSocket device server, LCD hardware driver, `rj_input` virtual button bridge, payload launcher architecture, DNSSpoof phishing sites, and Responder integration all originate from the RaspyJack project. We've layered the full KTOx attack and purple team suite, a custom firmware controller, extended LCD menus, and 155 additional payloads on top — but the foundation is theirs and it's a solid one.

A genuine thank you to **7h30th3r0n3** for building RaspyJack in the open and to every contributor who worked on it. If you use KTOx_Pi and haven't already, go give RaspyJack a star — it absolutely deserves it.

---

<div align="center">

### 🙏 Built on RaspyJack

**[github.com/7h30th3r0n3/Raspyjack](https://github.com/7h30th3r0n3/Raspyjack)**

| | |
|--|--|
| **Creator** | [@7h30th3r0n3](https://github.com/7h30th3r0n3) |
| **Contributor** | [@dagnazty](https://github.com/dagnazty) |
| **Contributor** | [@Hosseios](https://github.com/Hosseios) |
| **Contributor** | [@m0usem0use](https://github.com/m0usem0use) |

*RaspyJack — MIT License — Copyright © 2025 7h30th3r0n3*

---

### ⚡ KTOx_Pi

**[github.com/wickednull/KTOx_Pi](https://github.com/wickednull/KTOx_Pi)**

Built by [@wickednull](https://github.com/wickednull)

*authorized eyes only*

</div>
