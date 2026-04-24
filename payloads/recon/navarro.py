#!/usr/bin/env python3
"""
KTOx payload – Navarro username checker
=============================================================================
This payload prompts for a username, runs Navarro, saves JSON results under
loot/OSINT/, and shows found profile URLs on the 128×128 LCD.
-Credits: https://github.com/noobosaurus-r3x/Navarro
-Device Port Author: @hosseios https://github.com/Hosseios

requirements
-----------
  • python3
  • Navarro present at /home/ktox/Navarro/navarro.py
  • qrcode sudo apt install -y python3-qrcode python3-pil

Controls
--------
  • UP/DOWN: navigate fields/lists
  • LEFT/RIGHT: page results
  • OK: edit username (on-screen keyboard)
  • KEY1: Start/Rescan
  • KEY3: Back/Exit
"""

import os, sys, time, signal, subprocess, json, fcntl, re
from urllib.parse import urlparse
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from payloads._input_helper import get_button
from payloads._darksec_keyboard import DarkSecKeyboard
try:
    import qrcode 
except Exception:
    qrcode = None


# ----------------------------- Config -----------------------------
PINS = {
    "UP": 6,
    "DOWN": 19,
    "LEFT": 5,
    "RIGHT": 26,
    "OK": 13,
    "KEY1": 21,
    "KEY2": 20,
    "KEY3": 16,
}

WIDTH, HEIGHT = 128, 128
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_SMALL_SIZE = 9
FONT_BIG_SIZE = 11

NAVARRO_PATHS = [
    "/root/KTOx/Navarro/navarro.py",
    "/home/ktox/Navarro/navarro.py",
    "/root/Navarro/navarro.py",
]
NAVARRO_PATH = next((p for p in NAVARRO_PATHS if os.path.exists(p)), None)
LOOT_BASE = "/root/KTOx/loot/OSINT"
os.makedirs(LOOT_BASE, exist_ok=True)
APP_RUNNING = True


# --------------------------- LCD / Fonts ---------------------------
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

def load_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()

font_small = load_font(FONT_SMALL_SIZE)
font_big = load_font(FONT_BIG_SIZE)


# ----------------------------- GPIO -------------------------------
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


# ------------------------- Drawing helpers ------------------------
def new_canvas():
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    return img, ImageDraw.Draw(img)


def draw_center(lines, *, small: bool = False, footer: str | None = None):
    img, d = new_canvas()
    f = font_small if small else font_big
    if isinstance(lines, str):
        lines = [lines]
    heights = [d.textbbox((0, 0), s, font=f)[3] for s in lines]
    total_h = sum(heights) + max(0, len(lines) - 1) * 2
    y = (HEIGHT - total_h) // 2
    for s, h in zip(lines, heights):
        w = d.textbbox((0, 0), s, font=f)[2]
        d.text(((WIDTH - w) // 2, y), s, font=f, fill=(231, 76, 60))
        y += h + 2
    if footer:
        d.text((2, HEIGHT - 10), footer[:20], font=font_small, fill="#999999")
    LCD.LCD_ShowImage(img, 0, 0)


def draw_home(username: str, cursor: int):
    img, d = new_canvas()
    d.text((2, 2), "Navarro", font=font_big, fill=(231, 76, 60))
    d.line([(0, 14), (WIDTH, 14)], fill="#202020")
    rows = [
        ("Username", username or "<enter>"),
        ("Start", "Run ▶" if username else "Disabled"),
    ]
    y = 24
    for i, (k, v) in enumerate(rows):
        prefix = ">" if i == cursor else " "
        d.text((4, y), f"{prefix} {k}: ", font=font_small, fill=(242, 243, 244))
        d.text((70, y), v[:14], font=font_small, fill=("#e74c3c" if i == cursor else "#CCCCCC"))
        y += 16
    d.line([(0, HEIGHT - 12), (WIDTH, HEIGHT - 12)], fill="#202020")
    d.text((2, HEIGHT - 10), "OK=Edit  K1 Start  K3 Back", font=font_small, fill="#999999")
    LCD.LCD_ShowImage(img, 0, 0)


def draw_running(user: str, bounce_pos: int):
    img, d = new_canvas()
    d.text((2, 2), f"{user}", font=font_small, fill=(231, 76, 60))
    d.line([(0, 14), (WIDTH, 14)], fill="#202020")

    # Status line (single): "Checking <user>…"
    d.text((2, 18), f"Checking {user}…", font=font_small, fill=(242, 243, 244))

    # Bouncing bar
    bar_y1, bar_y2 = 36, 42
    d.rectangle((2, bar_y1, WIDTH - 2, bar_y2), outline="#404040")
    seg_w = 24
    pos = max(2, min(WIDTH - 2 - seg_w, 2 + bounce_pos))
    d.rectangle((pos, bar_y1 + 1, pos + seg_w, bar_y2 - 1), fill="#e74c3c")

    # No duplicate bottom status line

    d.text((2, HEIGHT - 10), "K3 Stop", font=font_small, fill="#999999")
    LCD.LCD_ShowImage(img, 0, 0)


def _shorten_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    keep = max_chars - 3
    left = keep // 2
    right = keep - left
    return text[:left] + "…" + text[-right:]


def draw_results(user: str, items: list[tuple[str, str]], page: int, selected_idx: int, per_page: int = 6):
    img, d = new_canvas()
    d.text((2, 2), f"Results: {user}", font=font_small, fill=(231, 76, 60))
    d.line([(0, 14), (WIDTH, 14)], fill="#202020")
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    for i, (platform, url) in enumerate(items[start:start + per_page]):
        y = 18 + i * 16
        gi = start + i
        render = platform[:20]
        fill = (231, 76, 60) if gi == selected_idx else "#FFFFFF"
        d.text((2, y), f"• {render}", font=font_small, fill=fill)
    d.text((WIDTH - 34, HEIGHT - 10), f"{page}/{total_pages}", font=font_small, fill="#999999")
    d.line([(0, HEIGHT - 12), (WIDTH, HEIGHT - 12)], fill="#202020")
    d.text((2, HEIGHT - 10), "OK=Detail  LR=Pages  K3 Back", font=font_small, fill="#999999")
    LCD.LCD_ShowImage(img, 0, 0)


def draw_result_detail(user: str, platform: str, url: str, idx: int, total: int):
    img, d = new_canvas()
    d.text((2, 2), f"{platform}  {idx+1}/{total}", font=font_small, fill=(231, 76, 60))
    d.line([(0, 14), (WIDTH, 14)], fill="#202020")

    # Try to render a QR code on the right (64x64). If unavailable, use full width for text
    text_right = WIDTH - 4
    if qrcode is not None:
        try:
            qr = qrcode.QRCode(version=None, box_size=2, border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            qr_img = qr_img.resize((64, 64))
            img.paste(qr_img, (WIDTH - 64 - 2, 20))
            text_right = WIDTH - 64 - 6  # leave gap before QR
        except Exception:
            text_right = WIDTH - 4

    # wrap url text within the available area
    max_w = max(20, text_right - 2)
    words = [url]
    lines: list[str] = []
    while words:
        w = words.pop(0)
        acc = ""
        for ch in w:
            test = acc + ch
            tw = d.textbbox((0, 0), test, font=font_small)[2]
            if tw <= max_w:
                acc = test
            else:
                lines.append(acc)
                acc = ch
        if acc:
            lines.append(acc)
        if len(lines) > 8:
            lines = lines[:8]
            break
    y = 20
    for line in lines:
        d.text((2, y), line, font=font_small, fill=(242, 243, 244))
        y += 12
    d.line([(0, HEIGHT - 12), (WIDTH, HEIGHT - 12)], fill="#202020")
    d.text((2, HEIGHT - 10), "LR=Prev/Next  K3 Back", font=font_small, fill="#999999")
    LCD.LCD_ShowImage(img, 0, 0)


# ------------------------- Buttons/helpers ------------------------
def first_pressed() -> str | None:
    return get_button(PINS, GPIO)


def wait_release(name: str):
    while APP_RUNNING and GPIO.input(PINS[name]) == 0:
        time.sleep(0.03)


# ------------------------------ Runner ----------------------------
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_HOST_RE = re.compile(r"([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?:/|\b)")
_CHECK_RE = re.compile(r"^\s*[^A-Za-z0-9]*\s*Checking\s+\S+\.\.\.\s+([^\s]+)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"Username:\s*\S+\s*\|\s*Found:\s*(\d+)/(\d+)", re.IGNORECASE)
_PCT_RE = re.compile(r"(\d{1,3})%")


def _extract_platform_from_line(line: str) -> str | None:
    line = line.strip()
    if not line:
        return None
    # If a URL is present, extract hostname
    for token in _URL_RE.findall(line):
        try:
            host = urlparse(token).netloc or token.split("//", 1)[1].split("/", 1)[0]
            return host
        except Exception:
            continue
    # Otherwise, try explicit activity keywords (word-bound)
    for key in ("Checking", "Site", "Testing", "Scanning"):
        if re.search(rf"\b{key}\b", line, re.IGNORECASE):
            m = _HOST_RE.search(line)
            if m:
                return m.group(1)
            return None
    # As a last resort, any hostname-looking token
    m = _HOST_RE.search(line)
    if m:
        return m.group(1)
    return None


def _detect_export_flag(navarro_path: str) -> str:
    """Ask Navarro for --help and pick the right export flag."""
    try:
        out = subprocess.run(
            ["python3", navarro_path, "--help"],
            capture_output=True, text=True, timeout=8
        ).stdout + subprocess.run(
            ["python3", navarro_path, "--help"],
            capture_output=True, text=True, timeout=8
        ).stderr
        for flag in ("--output", "--export", "-o"):
            if flag in out:
                return flag
    except Exception:
        pass
    return "--output"   # best guess if --help fails


def _parse_json_results(json_path: str) -> list:
    """Try several known Navarro JSON shapes and return [(platform, url), ...]."""
    try:
        with open(json_path, "r", encoding="utf-8") as jf:
            data = json.load(jf)
    except Exception:
        return []

    items = []

    # Shape 1: {"username": {"found_profiles": {"Site": "url", ...}}}
    if isinstance(data, dict):
        for root_val in data.values():
            if isinstance(root_val, dict):
                for key in ("found_profiles", "found", "results"):
                    bucket = root_val.get(key)
                    if isinstance(bucket, dict):
                        for k, v in bucket.items():
                            if isinstance(v, str) and v.startswith("http"):
                                items.append((k, v))
                    elif isinstance(bucket, list):
                        for entry in bucket:
                            if isinstance(entry, dict):
                                url = entry.get("url") or entry.get("link") or ""
                                plat = entry.get("site") or entry.get("platform") or entry.get("name") or url
                                if url.startswith("http"):
                                    items.append((str(plat), str(url)))
                if items:
                    return items
        # Shape 2: flat dict {"Site": "url", ...} at root
        for k, v in data.items():
            if isinstance(v, str) and v.startswith("http"):
                items.append((k, v))
        if items:
            return items

    # Shape 3: list of dicts [{"site":..., "url":...}, ...]
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                url = entry.get("url") or entry.get("link") or ""
                plat = entry.get("site") or entry.get("platform") or entry.get("name") or url
                if url.startswith("http"):
                    items.append((str(plat), str(url)))

    return items


def _parse_stdout_results(log_path: str) -> list:
    """Fallback: extract any http URLs from the captured log."""
    items = []
    seen = set()
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                for url in _URL_RE.findall(line):
                    url = url.rstrip(".,;)")
                    if url not in seen:
                        seen.add(url)
                        try:
                            host = urlparse(url).netloc or url
                        except Exception:
                            host = url
                        items.append((host, url))
    except Exception:
        pass
    return items


def run_navarro(username: str) -> tuple:
    if NAVARRO_PATH is None:
        draw_center(["Navarro not found!", "Install at:", "/root/KTOx/Navarro/", "K3 Back"], small=True)
        time.sleep(4)
        return [], ""

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join(LOOT_BASE, f"navarro_{username}_{ts}")
    os.makedirs(run_dir, exist_ok=True)
    json_path = os.path.join(run_dir, "results.json")
    log_path  = os.path.join(run_dir, "log.txt")

    export_flag = _detect_export_flag(NAVARRO_PATH)
    cmd = ["python3", "-u", NAVARRO_PATH, username, export_flag, json_path]

    bounce_pos = 2
    bounce_dir = 4

    with open(log_path, "w", encoding="utf-8") as logf:
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env
            )
        except Exception as exc:
            logf.write(f"Failed to spawn navarro: {exc}\n")
            return [], run_dir

        try:
            # Make fd non-blocking
            if proc.stdout is not None:
                fd = proc.stdout.fileno()
                fcntl.fcntl(fd, fcntl.F_SETFL,
                            fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
            buf = ""

            def _drain():
                """Read all currently available bytes from the non-blocking fd."""
                nonlocal buf
                try:
                    if proc.stdout is not None:
                        # read(n) with size is safe on non-blocking fd
                        chunk = proc.stdout.read(4096) or ""
                        if chunk:
                            buf += chunk
                except Exception:
                    pass
                # Flush complete lines to log
                while True:
                    nl = buf.find('\n')
                    if nl == -1:
                        break
                    logf.write(buf[:nl + 1])
                    buf = buf[nl + 1:]

            while True:
                if not APP_RUNNING:
                    proc.terminate()
                    break

                _drain()

                if proc.poll() is not None:
                    # Process finished — drain any remaining buffered output
                    _drain()
                    _drain()   # second pass catches anything left in OS buffer
                    break

                # Animate bouncing bar
                bounce_pos += bounce_dir
                if bounce_pos >= (WIDTH - 26) or bounce_pos <= 2:
                    bounce_dir *= -1
                draw_running(username, bounce_pos)

                if get_button(PINS, GPIO) == "KEY3":
                    try:
                        proc.terminate()
                        time.sleep(0.3)
                        proc.kill()
                    except Exception:
                        pass
                    break

                time.sleep(0.05)
        finally:
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
        # Flush any remaining partial line
        if buf:
            logf.write(buf)

    # Try JSON first, fall back to stdout URL scraping
    items = _parse_json_results(json_path)
    if not items:
        items = _parse_stdout_results(log_path)

    return items, run_dir


# ------------------------------ Main UI ---------------------------
def _handle_exit_signal(_signum, _frame):
    global APP_RUNNING
    APP_RUNNING = False


def _safe_shutdown():
    try:
        LCD.LCD_Clear()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass


def main():
    username = ""
    cursor = 0  # 0 Username, 1 Start
    page = 1
    results: list[tuple[str, str]] = []
    selected_idx = 0
    in_detail = False

    signal.signal(signal.SIGINT, _handle_exit_signal)
    signal.signal(signal.SIGTERM, _handle_exit_signal)

    draw_home(username, cursor)

    while APP_RUNNING:
        btn = first_pressed()
        if not btn:
            time.sleep(0.05)
            continue
        if btn == "KEY3":
            if in_detail:
                in_detail = False
            elif results and cursor == 1:
                # Back to search (home screen) without exiting payload
                results = []
                page = 1
                selected_idx = 0
                cursor = 0
            else:
                break
        # In detail view, ignore UP/DOWN entirely
        if btn == "UP":
            if results and cursor == 1 and not in_detail:
                page_start = (page - 1) * 6
                selected_idx = max(page_start, selected_idx - 1)
            elif not in_detail:
                cursor = (cursor - 1) % 2
        elif btn == "DOWN":
            if results and cursor == 1 and not in_detail:
                page_start = (page - 1) * 6
                page_end = min(len(results), page_start + 6)
                selected_idx = min(page_end - 1, selected_idx + 1)
            elif not in_detail:
                cursor = (cursor + 1) % 2
        elif btn == "LEFT" and results and cursor == 1:
            if in_detail:
                selected_idx = max(0, selected_idx - 1)
            else:
                if page > 1:
                    page -= 1
                    page_start = (page - 1) * 6
                    page_end = min(len(results), page_start + 6)
                    selected_idx = page_end - 1  # wrap to last item of previous page
        elif btn == "RIGHT" and results and cursor == 1:
            if in_detail:
                selected_idx = min(len(results) - 1, selected_idx + 1)
            else:
                total_pages = max(1, (len(results) + 5) // 6)
                if page < total_pages:
                    page += 1
                    selected_idx = (page - 1) * 6  # wrap to first item of next page
        elif btn == "OK" and cursor == 0:
            username = keyboard_input(username)
        elif btn == "KEY1" and username and not in_detail and not results:
            if NAVARRO_PATH is None:
                draw_center(["Navarro not found!", "Install at:", "/root/KTOx/Navarro/", "K3 Back"], small=True)
                wait_release(btn)
                continue
            draw_center(["Starting…"], small=True)
            results, run_dir = run_navarro(username.strip())
            page = 1
            if not results:
                draw_center(["No results found", "(log saved)", "K3 Back"], small=True)
                wait_release(btn)
            else:
                cursor = 1
                selected_idx = 0
                in_detail = False
        elif btn == "OK" and results and cursor == 1:
            # open detail view for current selected item in current page
            start = (page - 1) * 6
            end = min(len(results), start + 6)
            # ensure selected_idx is within current page bounds
            if selected_idx < start or selected_idx >= end:
                selected_idx = start
            in_detail = True

        wait_release(btn)

        if cursor == 1 and results:
            if in_detail:
                platform, url = results[selected_idx]
                draw_result_detail(username, platform, url, selected_idx, len(results))
            else:
                draw_results(username, results, page, selected_idx)
        else:
            draw_home(username, cursor)

    _safe_shutdown()


def keyboard_input(initial: str) -> str:
    kb = DarkSecKeyboard(width=WIDTH, height=HEIGHT, lcd=LCD, gpio_pins=PINS, gpio_module=GPIO)
    typed = kb.run()
    if typed is None:
        return initial
    return typed


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _safe_shutdown()
        raise
