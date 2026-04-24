# Loki Integration - Correct Approach

## Overview

Loki is a comprehensive autonomous network reconnaissance tool with sophisticated capabilities. Rather than fabricating UI features, the proper integration approach follows the RaspyJack pattern:

1. **Keep Loki's actual webapp unchanged** - It already provides complete functionality
2. **Launcher provides device control** - LCD display and button interface
3. **Web interface for operations** - Full Loki webapp at http://<ip>:8000

## Architecture

```
┌────────────────────────────────────────┐
│     KTOx_Pi Menu                       │
│  (Main Dashboard)                      │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│  loki_engine.py (Launcher)             │
│  - Device LCD display                  │
│  - Button controls (UP/DOWN/LEFT/OK)   │
│  - KEY1/KEY2/KEY3 shortcuts            │
│  - Installation management             │
│  - Process lifecycle                   │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────┐
│  Loki Actual WebApp                    │
│  (Port 8000)                           │
│                                        │
│  - Dashboard                           │
│  - Hosts (discovered targets)          │
│  - Attacks (manual execution)          │
│  - Loot (captured data)                │
│  - Credentials (harvested)             │
│  - Config (settings)                   │
│  - Terminal (remote shell)             │
│  - Display (pager output)              │
└────────────────────────────────────────┘
```

## Loki's Actual Capabilities

### Network Reconnaissance
- **Host Discovery** - Discover active devices on network
- **Port Scanning** - Identify open ports via Nmap
- **Service Enumeration** - Detect running services
- **Vulnerability Discovery** - Identify known CVEs

### Attack Capabilities
- **Brute Force** - SSH, FTP, SMB, Telnet, RDP, SQL
- **Credential Harvesting** - NTLM capture, file stealing
- **Network Attacks** - Placeholder for network-based attacks
- **Manual Attacks** - Execute custom attacks from UI

### Data Management
- **Loot Storage** - Organize captured files by type
- **Credentials** - Manage harvested credentials
- **Backup/Restore** - Full system backup capability
- **Export** - Generate host reports

### Orchestration
- **Automation** - Auto-execute configured attacks
- **Manual Control** - Execute specific attacks on demand
- **Scheduling** - Plan attacks for specific times
- **Logging** - Comprehensive action logging

### System Features
- **Terminal Access** - Remote shell execution
- **Configuration** - Customize attack parameters
- **Theme Support** - Multiple visual themes
- **Multi-language** - Internationalization support

## Device Launcher (loki_engine.py)

The launcher provides device-specific functionality:

### LCD Display (128x128)
```
┌─────────────────────┐
│ LOKI                │  <- Red title
│ ─────────────────── │
│ ● RUNNING           │  <- Status dot (green/orange)
│ http://192.168.1.50 │  <- Access URL
│ :8000               │  <- Port
│                     │
│ [0:12:34]           │  <- Uptime
│ ─────────────────── │
│ KEY1: stop          │  <- Button instructions
│ KEY3: exit (keep)   │
└─────────────────────┘
```

### Button Controls
- **UP/DOWN/LEFT/RIGHT** - Navigate menu (for future expansion)
- **OK** - Confirm selections
- **KEY1** - Quick action (stop Loki when running)
- **KEY2** - Secondary action (reinstall when stopped)
- **KEY3** - Exit/cancel

### States
1. **Not Installed** - Show installation prompt
2. **Installing** - Progress bar with step indicator
3. **Starting** - Loading message while waiting for web server
4. **Running** - Show URL, status dot, uptime, and controls
5. **Stopped** - Show quick actions (start, exit, reinstall)
6. **Error** - Display error message with recovery options

## Web Interface Access

### From Browser
```
http://<device-ip>:8000
```

### Actual Features Available
Users access the full Loki webapp with tabs for:
- **Dashboard** - Overview of scans and activity
- **Hosts** - List of discovered targets with details
- **Attacks** - Execute reconnaissance and brute force
- **Loot** - Browse captured files and data
- **Credentials** - Manage harvested credentials
- **Config** - Customize Loki settings and attack parameters
- **Terminal** - Execute commands on target systems
- **Display** - View pager output if device connected

## Installation

### First-Time Setup
```bash
# From KTOx menu or direct execution
python3 /home/user/KTOX_Pi/payloads/offensive/loki_engine.py

# Device LCD shows:
# LOKI
# ─────────
# Not installed
# 
# KEY3: install
# KEY1: exit
```

Press KEY3 to install. Installation includes:
1. Clone Loki repository
2. Create data directories
3. Generate pagerctl shim for LCD compatibility
4. Install dependencies
5. Create headless launcher script

## Deployment Pattern

Unlike fabricated UIs, the real pattern is:

```
Device Interface (LCD + Buttons)
        ↓
      loki_engine.py (launcher + status)
        ↓
    Actual Loki Webapp (all real operations)
        ↓
    Web Browser (full feature access)
```

The device LCD/buttons provide:
- Quick status checks
- Start/stop operations
- Installation management
- Device-native interface

The web interface provides:
- Real network reconnaissance
- Actual vulnerability detection
- Legitimate loot management
- Genuine attack execution

## Why No Cyberpunk "Reconnaissance" UI

The mistake was fabricating UI elements that don't correspond to actual Loki operations:

❌ **Wrong**: Create fake "reconnaissance" tab with invented features
✅ **Correct**: Access actual Loki webapp at port 8000 which has real reconnaissance

❌ **Wrong**: Add fake "exploitation" buttons for non-existent operations
✅ **Correct**: Use Loki's actual attack interface with real implementations

❌ **Wrong**: Design custom UI with made-up concepts
✅ **Correct**: Wrapper/launcher for actual tool, browser for real operations

## Future Enhancement

If cyberpunk theming is desired, proper approaches:

1. **Web Server Wrapper** - Proxy Loki's webapp with cyberpunk CSS/styling
2. **Status Dashboard** - Lightweight device-local statistics page
3. **API Wrapper** - Bridge device controls to Loki's real API endpoints

But these should **enhance** actual functionality, not **replace** it with fabrication.

## References

- **Loki Repository**: https://github.com/pineapple-pager-projects/pineapple_pager_loki
- **RaspyJack Pattern**: https://github.com/7h30th3r0n3/Raspyjack
- **Actual Implementation**: `/tmp/pineapple_pager_loki/payloads/user/reconnaissance/loki/webapp.py`

---

**Key Principle**: Always examine the tool's actual capabilities before building interfaces. Integration should expose real features clearly, not create fictional ones.
