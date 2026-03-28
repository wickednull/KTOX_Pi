![image](https://github.com/user-attachments/assets/f4f1f4b4-364d-4c60-a5c1-d06cfd0e0aea)

# KTOx_Pi
### Raspberry Pi Zero 2W · Kali Linux ARM64 · Waveshare 1.44" LCD HAT

```
 ██╗  ██╗████████╗ ██████╗ ██╗  ██╗
 ██║ ██╔╝╚══██╔══╝██╔═══██╗╚██╗██╔╝
 █████╔╝    ██║   ██║   ██║ ╚███╔╝
 ██╔═██╗    ██║   ██║   ██║ ██╔██╗
 ██║  ██╗   ██║   ╚██████╔╝██╔╝ ██╗
 ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
   Network Control Suite
   authorized eyes only · wickednull
```

---

## ▐ WHAT IS THIS

KTOx_Pi turns a Raspberry Pi Zero 2W into a standalone network penetration and purple team device. The Waveshare 1.44" LCD HAT gives you a full joystick-controlled attack menu that runs on boot. Every module from the full KTOx suite is bundled — ARP attacks, MITM, WiFi engine, Responder/NTLMv2, purple team defense, DNS spoofing with 30+ phishing sites, and 156 payload scripts across 12 categories.

The WebUI (port 8080) mirrors the LCD screen live so you can control the device from any browser on the same network. The WebSocket server (port 8765) handles real-time frame streaming and virtual button injection. The full KTOx TUI is always accessible over SSH for anything that needs a terminal.

**This is not a custom OS image.** It installs on top of a fresh Kali Linux ARM64 image for the Pi Zero 2W.

---

## ▐ HARDWARE

| Component | Part | ~Cost |
|-----------|------|-------|
| SBC | Raspberry Pi Zero 2W (or 2WH) | $15 |
| Display + controls | Waveshare 1.44" LCD HAT (ST7735S, 128×128) | $14 |
| WiFi adapter | Alfa AWUS036ACH or TP-Link AC1300 (for attacks) | $30 |
| Ethernet | USB-C OTG to Ethernet adapter | $10 |
| Power | PiSugar2 or USB power bank | $20 |
| Storage | 32GB+ microSD (Class 10 / A1) | $10 |
| **Total** | | **~$99** |

> **Pi Zero 2WH** (pre-soldered headers) means the HAT plugs straight on — no soldering.

The onboard Pi WiFi (`wlan0`) is reserved for the WebUI and internet access. The external USB adapter (`wlan1+`) is used for WiFi attacks and monitor mode.

---

## ▐ BUTTON CONTROLS

```
Joystick UP     navigate up
Joystick DOWN   navigate down
Joystick LEFT   back / cancel
Joystick RIGHT  select / enter submenu
Joystick CTR    select / confirm

KEY1   back (same as LEFT)
KEY2   home screen (any depth)
KEY3   stop running attack / exit payload

Stealth exit:   hold KEY1 + KEY3 for 3 seconds
```

---

## ▐ LCD MENU STRUCTURE

```
▐ KTOx ▌  (home)
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
│   ├── Handshake Cap       enter BSSID/channel via WebUI or SSH
│   ├── PMKID Attack        launches payloads/wifi/pmkid_capture.py
│   ├── Evil Twin AP        launches payloads/wifi/evil_twin.py
│   └── Select Adapter      pick from detected wlan interfaces
│
├── MITM & Spoof
│   ├── Start MITM Suite    → SSH + ktox_mitm.py for full config
│   ├── DNS Spoofing ON     select phishing site → php -S :80
│   ├── DNS Spoofing OFF    kill php + ettercap
│   ├── Rogue DHCP/WPAD     launches payloads/interception/rogue_dhcp_wpad.py
│   ├── Silent Bridge       launches payloads/interception/silent_bridge.py
│   └── Evil Portal         launches payloads/evil_portal/honeypot.py
│
├── Responder
│   ├── Responder ON        Responder.py -Q -I <iface>
│   ├── Responder OFF       kill Responder processes
│   └── Read Hashes         browse Responder/logs/ on LCD
│
├── Purple Team
│   ├── ARP Watch           flag ARP conflicts live with scapy
│   ├── ARP Diff Live       baseline ARP table, alert on changes
│   ├── Rogue Detector      scan every 30s, alert on new MACs
│   ├── LLMNR Detector      scapy sniffer on UDP 5355
│   ├── ARP Harden          arp -s static entries for known hosts
│   ├── Baseline Export     save host table to loot/baseline_DATE.json
│   ├── Verify Baseline     diff current hosts against saved baseline
│   └── SMB Probe           launches payloads/reconnaissance/smb_probe.py
│
├── Payloads                156 scripts, 12 categories — see below
│
├── Loot                    browse /root/KTOx/loot/ on LCD
│
├── Stealth                 blank LCD, all attacks keep running silently
│
└── System
    ├── WebUI Status        http://[ip]:8080 / ws://[ip]:8765
    ├── Refresh State       re-detect interface + gateway
    ├── System Info         kernel, uptime, temp, loot count, IP
    ├── Discord Webhook     show/configure exfiltration webhook
    ├── Reboot              confirm → reboot
    └── Shutdown            confirm → poweroff
```

---

## ▐ KTOX SUITE MODULES

The full KTOx suite installs to `/root/KTOx/`. Access via SSH or launch from the MITM/WiFi menus on the LCD.

| Module | What it does |
|--------|-------------|
| `ktox.py` | Full blood-red TUI — 35+ modules, ARP attacks, MITM, recon, host scanning, NDJSON session logging |
| `ktox_mitm.py` | DNS spoof, DHCP spoof, HTTP sniffer, credential harvester, SSL strip, 5-template captive portal, IP forwarding |
| `ktox_advanced.py` | JS/HTML injector into HTTP responses, multi-protocol sniffer (FTP/SMTP/POP3/IMAP/Telnet/IRC/Redis/SNMP), Wireshark PCAP export, NTLMv2 relay, session hijack |
| `ktox_extended.py` | LLMNR/WPAD/NBT-NS poisoner, rogue SMB server, network topology mapper, report generator, hashcat/john interface |
| `ktox_defense.py` | Purple team suite — ARP hardening, LLMNR disable, SMB signing enforce, encrypted DNS, cleartext protocol audit, all changes backed up with dry-run preview |
| `ktox_stealth.py` | IoT device fingerprinter (5-layer), stealth profiles (Ghost/Ninja/Normal), MAC rotation, rate limiting, jitter |
| `ktox_netattack.py` | ICMP redirect attack (stealthy MITM), IPv6 NDP spoof, DHCPv6 spoof, IPv6 RA flood |
| `ktox_wifi.py` | Monitor mode manager, airodump-ng AP/client scanner, deauth, WPA handshake capture, PMKID, evil twin |
| `ktox_dashboard.py` | Live Flask web dashboard at `:9999` — attack status, loot browser, real-time interface stats |
| `ktox_repl.py` | Interactive REPL — `set`/`get` session vars, `module.start`/`module.stop`, plugin system |
| `ktox_config.py` | Persistent configuration for all modules |
| `scan.py` | nmap scanner — returns `[ip, mac, vendor, hostname]` |
| `spoof.py` | ARP packet crafting and injection engine |

```bash
# SSH in
ssh root@[ip]   # password: kali (change this)

# Full TUI
python3 /root/KTOx/ktox.py

# Individual modules
python3 /root/KTOx/ktox_defense.py
python3 /root/KTOx/ktox_mitm.py
python3 /root/KTOx/ktox_wifi.py

# REPL
python3 /root/KTOx/ktox_repl.py

# KTOx dashboard (separate from WebUI)
python3 /root/KTOx/ktox_dashboard.py
# then open http://[ip]:9999
```

---

## ▐ PAYLOADS (156 scripts)

All payloads are KTOx-compatible. They use `_input_helper.py` for unified button input (WebUI virtual buttons work too) and write loot to `/root/KTOx/loot/`. Drop any `.py` file into a category folder and it appears in the menu automatically.

| Category | Count | Highlights |
|----------|-------|-----------|
| `reconnaissance` | 25 | arp_scanner, traffic_analyzer, log4shell_scanner, ping sweep, TCP/UDP port scanners, DNS zone transfer, SMB shares, SNMP walk, HTTP headers, OS fingerprint, cam finder, wardriving, navarro OSINT |
| `interception` | 38 | kickthemout, mitm_code_injector, silent_bridge, dhcp_starvation, vlan_hopper, EternalBlue, Kerberoasting, PetitPotam, PrintNightmare, SMB relay, Pass the Hash, ProxyLogon, ProxyShell, Follina, KRACK, SSH/FTP/Telnet bruteforce, hashcat crack, IMSI catcher, JTAG |
| `wifi` | 18 | deauth (multi-target), evil_twin, pmkid_capture, wifi_handshake_capture, tiny_wifite, marauder, wps_pixie, wifi_lab, beacon flood, probe sniffer, channel analyzer, client mapper, rogue AP, known networks deauth |
| `dos` | 6 | SYN flood, UDP flood, LAND attack, smurf, ping of death, ARP poison DoS |
| `bluetooth` | 9 | BLE spam, impersonator, flood, replay, char scanner, service explorer, BT scanner, BT manager |
| `social_eng` | 5 | Evil twin portals — Facebook, Google, PayPal, router login, VPN login |
| `general` | 36 | MAC spoof (eth0/wlan0), C2 controller, Bloodhound collector, pwnagotchi, process killer, file browser, log viewer, service manager, fs encrypt/decrypt, webcam spy, system info, self-destruct, shell, auto-update |
| `games` | 13 | Breakout, snake, Tetris, 2048, Conway's Game of Life, Doom demake, clock, pomodoro, video player, web browser |
| `exfiltration` | 1 | exfiltrate_discord — send loot files to Discord webhook |
| `remote_access` | 2 | shell (PTY over network), tailscale_control |
| `evil_portal` | 1 | honeypot — full captive portal credential capture |
| `examples` | 2 | `_payload_template.py`, `example_show_buttons.py` |

**Shared helpers in `payloads/`:**
- `_input_helper.py` — unified GPIO + WebUI virtual button input
- `monitor_mode_helper.py` — shared monitor mode enable/disable
- `hid_helper.py` — USB HID keyboard/mouse via zero-hid

---

## ▐ DNS SPOOF PHISHING SITES

30+ credential harvesting sites in `DNSSpoof/sites/`. Select from `MITM & Spoof → DNS Spoofing ON` — PHP launches on port 80 and DNS redirects victims to the selected page. Captured credentials save to `DNSSpoof/captures/`.

**Available sites:** Adobe, Amazon, Badoo, Google, iCloud, Instagram, Instafollowers, LDLC, LinkedIn, Microsoft, Netflix, Origin, PayPal, Pinterest, PlayStation, ProtonMail, Shopify, Snapchat, Spotify, Steam, Twitter, WiFi login, WordPress, Yahoo, Yandex — plus custom lightweight phish pages for Facebook, Google, PayPal, router login, and VPN login.

---

## ▐ WEBUI

Real-time browser control at `http://[ip]:8080` (the actual KTOx WebUI).

- **Live LCD mirror** — screen streamed at 10fps via WebSocket
- **Virtual gamepad** — full button control from browser
- **Payload IDE** — browse, edit, and launch payloads remotely
- **Loot browser** — view and download captured files, nmap XML visualizer
- **System monitor** — CPU, RAM, temp, disk, uptime, active payload status
- **Shell** — full interactive PTY terminal in browser (xterm.js)
- **Discord webhook** — configure exfiltration target
- **Auth system** — username/password login with session tokens, first-run bootstrap

```
http://[ip]:8080    WebUI (HTTP server)
ws://[ip]:8765      WebSocket device server (frame mirror + virtual buttons)
http://[ip]:9999    KTOx live dashboard (ktox_dashboard.py)
```

Frame mirror JPEG is always at `/dev/shm/ktox_last.jpg` for any tool that wants it.

---

## ▐ INSTALL

### Step 1 — Flash Kali to SD

Get the Kali Linux ARM64 image for Raspberry Pi Zero 2W from [kali.org/get-kali/#kali-arm](https://www.kali.org/get-kali/#kali-arm) and flash with Raspberry Pi Imager or Balena Etcher.

### Step 2 — First boot

```bash
# Default credentials
ssh root@[pi-ip]
# password: kali
```

### Step 3 — Copy firmware and run installer

```bash
scp -r ktox_pi/ root@[pi-ip]:/tmp/
ssh root@[pi-ip]
cd /tmp/ktox_pi
chmod +x install.sh
sudo bash install.sh
```

Fully unattended. Reboots when done. On next boot the KTOx demon skull logo appears, then the main menu.

### What the installer does

1. Detects `/boot/firmware/config.txt` or `/boot/config.txt` (Bookworm-compatible)
2. Enables SPI and I2C
3. Adds `gpio=6,19,5,26,13,21,20,16=pu` for button pull-ups
4. Loads `spi_bcm2835`, `spidev`, `i2c-bcm2835`, `i2c-dev` kernel modules
5. Installs APT packages — nmap, aircrack-ng, hostapd, dnsmasq, hashcat, john, ettercap, php, net-tools, iw, git, and more
6. Installs Nexmon for onboard WiFi monitor mode
7. Installs Python packages via pip
8. Downloads Font Awesome for LCD icon rendering
9. Copies all files to `/root/KTOx/`
10. Creates `/root/KTOx` → `/root/KTOx` symlink for payload compatibility
11. Generates WebUI auth token and session secret in `/root/KTOx/.webui_token`
12. Pins onboard WiFi MAC to `wlan0` via systemd `.link` file and udev rule
13. Configures NetworkManager to leave monitor interfaces unmanaged
14. Creates and enables 3 systemd services
15. Configures auto-login on tty1
16. Sets hostname to `ktox`, writes `/etc/motd` and SSH banner
17. Health checks — SPI device, Python imports, tool availability
18. Reboots

---

## ▐ SYSTEMD SERVICES

| Service | Runs | Port |
|---------|------|------|
| `ktox.service` | `ktox_device.py` — LCD firmware, menu controller | — |
| `ktox-device.service` | `device_server.py` — WebSocket server | 8765 |
| `ktox-webui.service` | `web_server.py` — HTTP WebUI | 8080 |

```bash
# Status
systemctl status ktox ktox-device ktox-webui

# Logs
journalctl -fu ktox
journalctl -fu ktox-device
journalctl -fu ktox-webui

# Restart LCD firmware
systemctl restart ktox

# Manual launch (debugging)
python3 /root/KTOx/ktox_device.py
```

---

## ▐ LOOT

Everything goes to `/root/KTOx/loot/`:

```
/root/KTOx/loot/
├── atk_arp_mitm_20250101_120000.log    attack runner logs
├── wifi_scan_20250101-01.csv           airodump-ng WiFi scans
├── baseline_20250101.json              ARP baseline exports
├── payload.log                         combined payload stdout
├── MITM/                               MITM session captures
├── Nmap/                               nmap XML results
└── payloads/                           per-payload loot subdirs
```

Payloads that hardcode `/root/KTOx/loot/` still work — the installer symlinks `/root/KTOx` → `/root/KTOx`.

```bash
# Browse on device
# LCD: Loot menu
# WebUI: http://[ip]:8080 → Loot tab
ls -lh /root/KTOx/loot/

# Pull everything
scp -r root@[ip]:/root/KTOx/loot/ ./loot/
```

---

## ▐ STEALTH MODE

Select `Stealth` from the home menu. LCD goes blank (or shows a decoy image). All attacks and services keep running.

**Exit:** hold KEY1 + KEY3 for 3 seconds, or from WebUI write `{"stealth": false}` to `/dev/shm/ktox_stealth.json`.

---

## ▐ HEADLESS MODE (NO LCD HAT)

`ktox_device.py` detects missing hardware and falls back silently. You get full access via:

- WebUI at `http://[ip]:8080`
- SSH + `python3 /root/KTOx/ktox.py` for the full TUI
- WebUI virtual gamepad still injects button events to payloads

---

## ▐ FILE STRUCTURE

```
ktox_pi/                       copy this to the Pi → run install.sh
│
├── install.sh                       one-shot installer
├── README.md                        this file
│
├── ktox_pi/                   LCD firmware
│   ├── ktox_device.py               main controller + menu tree
│   ├── LCD_1in44.py                 Waveshare ST7735S driver (real)
│   ├── LCD_Config.py                SPI + GPIO hardware config (real)
│   └── rj_input.py                  WebUI virtual button bridge (Unix socket)
│
├── ktox.py                          KTOx main suite TUI
├── ktox_mitm.py                     MITM + credential harvest engine
├── ktox_advanced.py                 JS inject, multi-proto sniffer, PCAP
├── ktox_extended.py                 LLMNR, rogue SMB, topology, hash crack
├── ktox_defense.py                  purple team defense suite
├── ktox_stealth.py                  stealth + IoT fingerprinter
├── ktox_netattack.py                ICMP redirect, IPv6 attacks
├── ktox_wifi.py                     WiFi attack engine
├── ktox_dashboard.py                live Flask dashboard (:9999)
├── ktox_repl.py                     interactive REPL + plugins
├── ktox_config.py                   persistent config
├── scan.py                          nmap scanner helper
├── spoof.py                         ARP packet engine
├── requirements.txt                 Python dependencies
│
├── device_server.py                 WebSocket server (:8765)
├── web_server.py                    HTTP WebUI (:8080)
├── nmap_parser.py                   nmap XML parser for WebUI
├── web/                             WebUI frontend (HTML/JS/CSS)
├── gui_conf.json                    blood-red colour scheme
├── discord_webhook.txt              webhook URL placeholder
│
├── payloads/                        156 payload scripts
│   ├── _input_helper.py
│   ├── monitor_mode_helper.py
│   ├── hid_helper.py
│   ├── bluetooth/
│   ├── dos/
│   ├── evil_portal/
│   ├── examples/
│   ├── exfiltration/
│   ├── games/
│   ├── general/
│   ├── interception/
│   ├── reconnaissance/
│   ├── remote_access/
│   ├── social_eng/
│   └── wifi/
│
├── Responder/                       LLMNR/NBT-NS/MDNS poisoner
├── DNSSpoof/                        30+ phishing site templates
├── wifi/                            WiFi manager integration
├── img/logo.bmp                     128×128 boot logo
└── assets/                          screenshots
```

---

## ▐ PYTHON REQUIREMENTS

```
rich>=13.0.0          terminal UI
scapy>=2.5.0          packet crafting + injection
python-nmap>=0.7.1    nmap scanner wrapper
netifaces>=0.11.0     network interface enumeration
flask>=3.0.0          web dashboard
pillow>=10.0.0        LCD image rendering
spidev>=3.6           SPI bus (LCD hardware)
RPi.GPIO>=0.7.1       GPIO (buttons + LCD)
requests              HTTP client
websockets            WebSocket server
customtkinter>=5.2.0  desktop GUI (Pi 5 / desktop only)
```

---

## ▐ DISCLAIMER

For authorized security testing and research only, on networks and systems you own or have explicit written permission to test. Unauthorized use is illegal.

`authorized eyes only`

---

## ▐ COMPATIBLE HARDWARE

KTOx_Pi is built and tested on the Pi Zero 2W but works on any Pi with a 40-pin GPIO header.

| Board | Status | Notes |
|-------|--------|-------|
| **Pi Zero 2W** *(recommended)* | ✅ Full support | Built and tested on this. Perfect size for field use. |
| **Pi Zero 2WH** | ✅ Full support | Same as above with pre-soldered headers — no soldering needed. |
| **Pi 3B / 3B+** | ✅ Full support | Same ARM64 Kali image, same 40-pin header. Works out of the box. |
| **Pi 4B** | ✅ Full support | Overkill on RAM/CPU but fully compatible. Same pinout. |
| **Pi Zero W (v1)** | ⚠️ Partial | 32-bit only — ARM64 Kali won't run. Use Kali ARMhf image instead. |
| **Pi 5** | ⚠️ Needs tweak | Different GPIO chip (RP1). Swap `RPi.GPIO` for `lgpio` or `gpiozero`. SPI also differs. |
| **Pi Pico / Pico W** | ❌ Not supported | Microcontroller, not Linux. Completely different architecture. |

The Waveshare 1.44" HAT mounts on any board with a standard 40-pin header. BCM pin numbers used by `LCD_Config.py` (RST=27, DC=25, CS=8, BL=24) and button pins (5, 6, 13, 16, 19, 20, 21, 26) are consistent across all compatible Pi models.

---

## ▐ CREDITS

KTOx_Pi is built on top of the **RaspyJack** project. The WebUI, WebSocket device server, LCD driver, payload architecture, `rj_input` virtual button system, and DNSSpoof phishing sites all originate from RaspyJack. Without their work this project wouldn't exist.

**RaspyJack** — [github.com/7h30th3r0n3/Raspyjack](https://github.com/7h30th3r0n3/Raspyjack)

| Role | Handle |
|------|--------|
| Creator & lead developer | [@7h30th3r0n3](https://github.com/7h30th3r0n3) |
| Contributor | [@dagnazty](https://github.com/dagnazty) |
| Contributor | [@Hosseios](https://github.com/Hosseios) |
| Contributor | [@m0usem0use](https://github.com/m0usem0use) |

RaspyJack is licensed under the MIT License. Copyright (c) 2025 7h30th3r0n3.

**KTOx_Pi** adds the full KTOx attack and purple team suite, 155 custom payloads, KTOx_Pi firmware controller, blood-red theming, and extended menu system on top of the RaspyJack foundation.

**KTOx_Pi** — [github.com/wickednull/KTOx_Pi](https://github.com/wickednull/KTOx_Pi) · [@wickednull](https://github.com/wickednull)
