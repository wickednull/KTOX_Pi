#!/usr/bin/env python3
"""
KTOx WebSocket device server
Compatible websockets v11+ / v12+ /
"""

import asyncio
import base64
import hmac
import hashlib
import json
import logging
import os
import socket
import subprocess
import time
import termios
import fcntl
import struct
import pty
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Set, Optional
from urllib.parse import urlparse, parse_qs

import websockets

try:
	from PIL import Image
	HAS_PIL = True
except ImportError:
	HAS_PIL = False


# ------------------------------ Config ---------------------------------------
# Support both KTOX and RaspyJack naming conventions
FRAME_PATH = Path(os.environ.get("KTOX_FRAME_PATH") or os.environ.get("RJ_FRAME_PATH", "/dev/shm/ktox_last.jpg"))
HOST = os.environ.get("KTOX_WS_HOST") or os.environ.get("RJ_WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("KTOX_WS_PORT") or os.environ.get("RJ_WS_PORT", "8765"))
FPS = float(os.environ.get("KTOX_FRAME_FPS") or os.environ.get("RJ_FRAME_FPS", "6"))
ROOT_DIR = Path(__file__).resolve().parent
TOKEN_FILE = Path(os.environ.get("KTOX_WS_TOKEN_FILE") or os.environ.get("RJ_WS_TOKEN_FILE", str(ROOT_DIR / ".webui_token")))
AUTH_FILE = Path(os.environ.get("KTOX_WEB_AUTH_FILE") or os.environ.get("RJ_WEB_AUTH_FILE", "/root/KTOx/.webui_auth.json"))
AUTH_SECRET_FILE = Path(os.environ.get("KTOX_WEB_AUTH_SECRET_FILE") or os.environ.get("RJ_WEB_AUTH_SECRET_FILE", "/root/KTOx/.webui_session_secret"))
SESSION_COOKIE_NAME = os.environ.get("KTOX_WEB_SESSION_COOKIE") or os.environ.get("RJ_WEB_SESSION_COOKIE", "ktox_session")
INPUT_SOCK = os.environ.get("KTOX_INPUT_SOCK") or os.environ.get("RJ_INPUT_SOCK", "/dev/shm/ktox_input.sock")
SHELL_CMD = os.environ.get("KTOX_SHELL_CMD") or os.environ.get("RJ_SHELL_CMD", "/bin/bash")
SHELL_CWD = os.environ.get("KTOX_SHELL_CWD") or os.environ.get("RJ_SHELL_CWD", "/")

# M5Cardputer-specific frame configuration
# Support both KTOX and RaspyJack naming conventions
CARDPUTER_ENABLED = (os.environ.get("KTOX_CARDPUTER_ENABLED") or os.environ.get("RJ_CARDPUTER_ENABLED", "1")) != "0"
CARDPUTER_FRAME_PATH = Path(os.environ.get("KTOX_CARDPUTER_FRAME_PATH") or os.environ.get("RJ_CARDPUTER_FRAME_PATH", "/dev/shm/ktox_m5.jpg"))
CARDPUTER_FRAME_WIDTH = int(os.environ.get("KTOX_CARDPUTER_FRAME_WIDTH") or os.environ.get("RJ_CARDPUTER_FRAME_WIDTH", "240"))
CARDPUTER_FRAME_HEIGHT = int(os.environ.get("KTOX_CARDPUTER_FRAME_HEIGHT") or os.environ.get("RJ_CARDPUTER_FRAME_HEIGHT", "135"))
CARDPUTER_FPS = float(os.environ.get("KTOX_CARDPUTER_FPS") or os.environ.get("RJ_CARDPUTER_FPS", "6"))
CARDPUTER_FRAME_MODE = os.environ.get("KTOX_CARDPUTER_FRAME_MODE") or os.environ.get("RJ_CARDPUTER_FRAME_MODE", "contain")
CARDPUTER_FRAME_QUALITY = int(os.environ.get("KTOX_CARDPUTER_FRAME_QUALITY") or os.environ.get("RJ_CARDPUTER_FRAME_QUALITY", "75"))
CARDPUTER_FRAME_SUBSAMPLING = os.environ.get("KTOX_CARDPUTER_FRAME_SUBSAMPLING") or os.environ.get("RJ_CARDPUTER_FRAME_SUBSAMPLING", "4:2:0")

SEND_TIMEOUT = 0.5
PING_INTERVAL = 15

# WebSocket server only listens on these interfaces — wlan1+ are for attacks
WEBUI_INTERFACES = ["eth0", "wlan0", "tailscale0"]


def _load_shared_token():
    """Load auth token from env first, then token file."""
    env_token = str(os.environ.get("RJ_WS_TOKEN", "")).strip()
    if env_token:
        return env_token
    try:
        if TOKEN_FILE.exists():
            for line in TOKEN_FILE.read_text(encoding="utf-8").splitlines():
                value = line.strip()
                if value and not value.startswith("#"):
                    return value
    except Exception:
        pass
    return None


TOKEN = _load_shared_token()


def _load_line_secret(path: Path):
    try:
        if not path.exists():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                return value
    except Exception:
        pass
    return None


def _auth_initialized() -> bool:
    try:
        if not AUTH_FILE.exists():
            return False
        raw = AUTH_FILE.read_text(encoding="utf-8")
        data = json.loads(raw) if raw else {}
        return bool(data.get("username") and data.get("password_hash"))
    except Exception:
        return False


AUTH_SECRET = _load_line_secret(AUTH_SECRET_FILE)


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _hmac_sign(payload: str) -> str:
    if not AUTH_SECRET:
        return ""
    mac = hmac.new(AUTH_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(mac)


def _read_signed_token(token: str):
    if not AUTH_SECRET:
        return None
    try:
        payload, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_hmac_sign(payload), sig):
        return None
    try:
        raw = _b64url_decode(payload)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _get_interface_ip(interface: str):
    """Get the IPv4 address of a network interface."""
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", interface],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "inet " in line:
                    return line.split("inet ")[1].split("/")[0]
    except Exception:
        pass
    return None


def _get_webui_bind_addrs():
    """Return (ip, iface_label) pairs the WS server should bind to."""
    addrs = []
    for iface in WEBUI_INTERFACES:
        ip = _get_interface_ip(iface)
        if ip:
            addrs.append((ip, iface))
    addrs.append(("127.0.0.1", "lo"))
    return addrs


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("rj-ws")
if TOKEN:
    log.info("WebSocket token auth enabled")
else:
    log.warning("WebSocket token auth disabled (set RJ_WS_TOKEN or token file)")
if AUTH_SECRET:
    log.info("WebSocket session-ticket auth enabled")
else:
    log.warning("WebSocket session-ticket auth disabled (missing auth secret)")


# --------------------------- Client Registry ---------------------------------
clients: Set = set()
clients_lock = asyncio.Lock()


def _pty_setup(slave_fd: int):
    """Run in child process: become session leader and set controlling terminal.
    This allows Ctrl+C (\\x03) to deliver SIGINT via the PTY signal mechanism."""
    os.setsid()
    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)


# ----------------------------- Shell Session ----------------------------------
class ShellSession:
    def __init__(self, loop: asyncio.AbstractEventLoop, ws):
        self.loop = loop
        self.ws = ws
        self.master_fd, self.slave_fd = pty.openpty()
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        slave_fd = self.slave_fd
        self.proc = subprocess.Popen(
            [SHELL_CMD],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=SHELL_CWD,
            env=env,
            close_fds=True,
            preexec_fn=lambda: _pty_setup(slave_fd),
        )
        os.close(self.slave_fd)
        os.set_blocking(self.master_fd, False)
        self.loop.add_reader(self.master_fd, self._on_output)
        self._closed = False
        self._exit_sent = False
        self._wait_task = self.loop.create_task(self._wait_exit())

    async def _wait_exit(self):
        try:
            await asyncio.to_thread(self.proc.wait)
        except Exception:
            return
        await self._send_exit()

    def _on_output(self):
        if self._closed:
            return
        try:
            data = os.read(self.master_fd, 4096)
            if not data:
                self.loop.create_task(self._send_exit())
                return
            msg = json.dumps({"type": "shell_out", "data": data.decode("utf-8", "ignore")})
            self.loop.create_task(self._safe_send(msg))
        except Exception:
            self.loop.create_task(self._send_exit())

    async def _safe_send(self, msg: str):
        try:
            await self.ws.send(msg)
        except Exception:
            self.close()

    async def _send_exit(self):
        if self._exit_sent:
            return
        self._exit_sent = True
        code = None
        try:
            code = self.proc.poll()
        except Exception:
            pass
        try:
            await self.ws.send(json.dumps({"type": "shell_exit", "code": code}))
        except Exception:
            pass
        self.close()

    def write(self, data: str):
        if self._closed:
            return
        try:
            os.write(self.master_fd, data.encode())
        except Exception:
            self.loop.create_task(self._send_exit())

    def resize(self, cols: int, rows: int):
        if self._closed:
            return
        try:
            size = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, size)
        except Exception:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.loop.remove_reader(self.master_fd)
        except Exception:
            pass
        try:
            os.close(self.master_fd)
        except Exception:
            pass
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass
        try:
            if self._wait_task:
                self._wait_task.cancel()
        except Exception:
            pass


# ----------------------- Frame Profile and Scaling -----------------------------
def _scale_frame(frame_path: Path, target_width: int, target_height: int, mode: str = "contain") -> Optional[bytes]:
    """Scale frame to target dimensions using specified mode. Returns JPEG bytes or None."""
    if not HAS_PIL or not frame_path.exists():
        return None
    try:
        img = Image.open(frame_path)
        orig_w, orig_h = img.size

        if mode == "stretch":
            scaled = img.resize((target_width, target_height), Image.LANCZOS)
        elif mode == "contain":
            img.thumbnail((target_width, target_height), Image.LANCZOS)
            new_img = Image.new('RGB', (target_width, target_height), (0, 0, 0))
            offset_x = (target_width - img.width) // 2
            offset_y = (target_height - img.height) // 2
            new_img.paste(img, (offset_x, offset_y))
            scaled = new_img
        elif mode == "fit":
            ratio_orig = orig_w / orig_h
            ratio_target = target_width / target_height
            if ratio_orig > ratio_target:
                new_w = int(orig_h * ratio_target)
                crop_img = img.crop(((orig_w - new_w) // 2, 0, (orig_w + new_w) // 2, orig_h))
            else:
                new_h = int(orig_w / ratio_target)
                crop_img = img.crop((0, (orig_h - new_h) // 2, orig_w, (orig_h + new_h) // 2))
            scaled = crop_img.resize((target_width, target_height), Image.LANCZOS)
        else:
            scaled = img.resize((target_width, target_height), Image.LANCZOS)

        buf = __import__('io').BytesIO()
        scaled.save(buf, format='JPEG', quality=CARDPUTER_FRAME_QUALITY, subsampling=CARDPUTER_FRAME_SUBSAMPLING)
        return buf.getvalue()
    except Exception:
        return None


# -------------------------- Frame Broadcasting --------------------------------
class FrameCache:
    def __init__(self, path: Path):
        self.path = path
        self._last_mtime = 0.0
        self._last_size = 0
        self._last_payload = None

    def has_changed(self) -> bool:
        try:
            st = self.path.stat()
            return st.st_mtime != self._last_mtime or st.st_size != self._last_size
        except FileNotFoundError:
            return False

    def load_b64(self):
        try:
            st = self.path.stat()
            with self.path.open("rb") as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode()
            self._last_mtime = st.st_mtime
            self._last_size = st.st_size
            self._last_payload = b64
            return b64
        except Exception:
            return None

    @property
    def last_payload(self):
        return self._last_payload


class CardputerFrameCache:
    """Optimized frame cache for M5Cardputer display (240x135)."""
    def __init__(self, source_path: Path):
        self.source_path = source_path
        self._last_mtime = 0.0
        self._last_size = 0
        self._last_payload = None

    def has_changed(self) -> bool:
        try:
            st = self.source_path.stat()
            return st.st_mtime != self._last_mtime or st.st_size != self._last_size
        except FileNotFoundError:
            return False

    def load_b64(self) -> Optional[str]:
        try:
            scaled_bytes = _scale_frame(self.source_path, CARDPUTER_FRAME_WIDTH, CARDPUTER_FRAME_HEIGHT, CARDPUTER_FRAME_MODE)
            if not scaled_bytes:
                return None
            b64 = base64.b64encode(scaled_bytes).decode()
            st = self.source_path.stat()
            self._last_mtime = st.st_mtime
            self._last_size = st.st_size
            self._last_payload = b64
            return b64
        except Exception:
            return None

    @property
    def last_payload(self) -> Optional[str]:
        return self._last_payload


async def broadcast_frames(cache: FrameCache, cardputer_cache: Optional[CardputerFrameCache] = None):
    delay = max(0.001, 1.0 / max(1.0, FPS))
    cardputer_delay = max(0.001, 1.0 / max(1.0, CARDPUTER_FPS)) if cardputer_cache else None
    log.info("Frame broadcaster started at ~%.1f FPS", 1.0 / delay)
    if cardputer_cache:
        log.info("M5Cardputer frame broadcaster enabled at ~%.1f FPS", 1.0 / cardputer_delay)

    cardputer_next = 0.0
    while True:
        try:
            payload = cache.load_b64() if cache.has_changed() else cache.last_payload
            if payload:
                msg = json.dumps({"type": "frame", "data": payload})
                async with clients_lock:
                    await asyncio.gather(
                        *[asyncio.wait_for(c.send(msg), SEND_TIMEOUT) for c in list(clients)],
                        return_exceptions=True,
                    )

            if cardputer_cache and CARDPUTER_ENABLED:
                import time as time_module
                now = time_module.time()
                if now >= cardputer_next:
                    m5_payload = cardputer_cache.load_b64() if cardputer_cache.has_changed() else cardputer_cache.last_payload
                    if m5_payload:
                        msg = json.dumps({"type": "frame_m5", "data": m5_payload})
                        async with clients_lock:
                            await asyncio.gather(
                                *[asyncio.wait_for(c.send(msg), SEND_TIMEOUT) for c in list(clients)],
                                return_exceptions=True,
                            )
                    cardputer_next = now + cardputer_delay

            await asyncio.sleep(delay)
        except Exception as e:
            log.warning("Broadcaster error: %s", e)


# ----------------------------- Input Bridge -----------------------------------
def send_input_event(button, state):
    try:
        payload = json.dumps({
            "type": "input",
            "button": button,
            "state": state
        }).encode()

        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(INPUT_SOCK)
            s.send(payload)
    except Exception:
        pass


# ----------------------------- Auth -------------------------------------------
def authorize(path: str) -> bool:
    if not TOKEN:
        return True
    try:
        q = parse_qs(urlparse(path).query)
        return q.get("token", [None])[0] == TOKEN
    except Exception:
        return False


def _token_ok(value: str) -> bool:
    if not TOKEN:
        return True
    return str(value or "").strip() == TOKEN


def _ws_ticket_ok(value: str) -> bool:
    claims = _read_signed_token(str(value or "").strip())
    if not claims:
        return False
    if claims.get("typ") != "ws_ticket":
        return False
    try:
        return int(claims.get("exp", 0)) >= int(time.time())
    except Exception:
        return False


def _session_token_ok(token: str) -> bool:
    claims = _read_signed_token(str(token or "").strip())
    if not claims:
        return False
    if claims.get("typ") != "session":
        return False
    try:
        return int(claims.get("exp", 0)) >= int(time.time())
    except Exception:
        return False


def _cookie_session_ok(ws) -> bool:
    header_val = ""
    try:
        req_headers = getattr(ws, "request_headers", None)
        if req_headers:
            header_val = str(req_headers.get("Cookie", "") or "")
    except Exception:
        header_val = ""
    if not header_val:
        try:
            req = getattr(ws, "request", None)
            hdrs = getattr(req, "headers", None) if req else None
            if hdrs:
                header_val = str(hdrs.get("Cookie", "") or "")
        except Exception:
            header_val = ""
    if not header_val:
        return False
    c = SimpleCookie()
    try:
        c.load(header_val)
    except Exception as e:
        log.debug("Cookie parse error (expected for non-cookie clients): %s", e)
        return False
    morsel = c.get(SESSION_COOKIE_NAME)
    if not morsel:
        return False
    return _session_token_ok(morsel.value)


# ----------------------------- WS Handler -------------------------------------
async def handle_client(ws):
    # websockets v12+ : path is in ws.request.path
    path = getattr(getattr(ws, "request", None), "path", "/")
    if not _auth_initialized():
        # No auth configured - allow all connections
        authenticated = True
    elif TOKEN:
        # Token configured - require either token or session cookie
        authenticated = _cookie_session_ok(ws) or authorize(path)
    else:
        # Auth initialized but no TOKEN - allow frame-only clients (M5Cardputer)
        # that may not have cookies. Full access requires valid session.
        authenticated = True

    if authenticated:
        async with clients_lock:
            clients.add(ws)
        log.info("Client connected (%d online)", len(clients))
    else:
        try:
            await ws.send(json.dumps({"type": "auth_required"}))
        except Exception:
            await ws.close(code=4401, reason="Unauthorized")
            return
    loop = asyncio.get_running_loop()
    shell = None

    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue

            if not authenticated:
                msg_type = data.get("type")
                if msg_type not in ("auth", "auth_session"):
                    continue
                token_ok = msg_type == "auth" and (
                    _token_ok(data.get("token", "")) or _session_token_ok(data.get("token", ""))
                )
                sess_ok = msg_type == "auth_session" and _ws_ticket_ok(data.get("ticket", ""))
                if token_ok or sess_ok:
                    authenticated = True
                    async with clients_lock:
                        clients.add(ws)
                    log.info("Client authenticated (%d online)", len(clients))
                    try:
                        await ws.send(json.dumps({"type": "auth_ok"}))
                    except Exception:
                        pass
                else:
                    log.warning("Client auth failed (type=%s)", msg_type)
                    try:
                        await ws.send(json.dumps({"type": "auth_error"}))
                    except Exception:
                        pass
                    await ws.close(code=4401, reason="Unauthorized")
                    break
                continue

            if data.get("type") == "input":
                btn = data.get("button")
                state = data.get("state")
                if btn and state in ("press", "release"):
                    send_input_event(btn, state)
                continue

            if data.get("type") == "stealth_exit":
                try:
                    Path("/dev/shm/ktox_stealth.json").write_text(
                        json.dumps({"stealth": False})
                    )
                except Exception:
                    pass
                continue

            if data.get("type") == "shell_open":
                if shell:
                    shell.close()
                shell = ShellSession(loop, ws)
                try:
                    await ws.send(json.dumps({"type": "shell_ready"}))
                except Exception:
                    shell.close()
                continue

            if data.get("type") == "shell_in":
                if shell:
                    payload = data.get("data", "")
                    if payload:
                        shell.write(payload)
                continue

            if data.get("type") == "shell_resize":
                if shell:
                    cols = int(data.get("cols") or 0)
                    rows = int(data.get("rows") or 0)
                    if cols > 0 and rows > 0:
                        shell.resize(cols, rows)
                continue

            if data.get("type") == "shell_close":
                if shell:
                    shell.close()
                    shell = None
                continue

    except Exception:
        pass
    finally:
        if shell:
            shell.close()
        async with clients_lock:
            clients.discard(ws)
        log.info("Client disconnected (%d online)", len(clients))


# ----------------------------- Main -------------------------------------------
async def main():
    cache = FrameCache(FRAME_PATH)
    cardputer_cache = CardputerFrameCache(FRAME_PATH) if (CARDPUTER_ENABLED and HAS_PIL) else None

    # If a specific host was set via env var, honour it (single bind)
    if HOST != "0.0.0.0":
        async with websockets.serve(
            handle_client, HOST, PORT,
            ping_interval=PING_INTERVAL, max_size=2 * 1024 * 1024,
        ):
            log.info("WebSocket server listening on %s:%d", HOST, PORT)
            await broadcast_frames(cache, cardputer_cache)
        return

    # Default: bind only to eth0 + wlan0 (+ localhost).  wlan1+ stay untouched.
    bind_addrs = _get_webui_bind_addrs()
    servers = []

    for addr, iface in bind_addrs:
        try:
            srv = await websockets.serve(
                handle_client, addr, PORT,
                ping_interval=PING_INTERVAL, max_size=2 * 1024 * 1024,
            )
            servers.append(srv)
            log.info("WebSocket server listening on %s:%d (%s)", addr, PORT, iface)
        except Exception as exc:
            log.warning("Could not bind WS to %s:%d (%s): %s", addr, PORT, iface, exc)

    if not servers:
        # Last resort — fall back so the WS server is not dead
        log.warning("No WebUI interfaces available, falling back to 0.0.0.0")
        async with websockets.serve(
            handle_client, "0.0.0.0", PORT,
            ping_interval=PING_INTERVAL, max_size=2 * 1024 * 1024,
        ):
            log.info("WebSocket server listening on 0.0.0.0:%d", PORT)
            await broadcast_frames(cache, cardputer_cache)
        return

    try:
        await broadcast_frames(cache, cardputer_cache)
    finally:
        for srv in servers:
            srv.close()
            await srv.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
