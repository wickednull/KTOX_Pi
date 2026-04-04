#!/usr/bin/env python3
"""
KTOx Payload – Reliable Tiny Web Browser (Link Clicking Fixed)
==============================================================
- Better link extraction and highlighting
- Fixed KEY2 cycling + auto-scroll
- Improved OK to follow links
"""

import os
import sys
import re
import time
import threading
import textwrap
import urllib.request
import urllib.parse
import urllib.error
from urllib.request import Request

KTOX_ROOT = "/root/KTOx"
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("Warning: BeautifulSoup4 not available.")

# ── Constants ────────────────────────────────────────────────────────────────
W, H = 128, 128
WEBUI_URL_FILE = "/dev/shm/ktox_browser_url.txt"
MAX_HISTORY = 15
CHAR_SET = "abcdefghijklmnopqrstuvwxyz0123456789./:_-?=&#@%+"
MAX_CONTENT_SIZE = 512 * 1024

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

# ── Globals ──────────────────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font_sm = None
_font_md = None
_font_hd = None

RUNNING = True
_ui_lock = threading.Lock()

_page_lines   = ["Welcome to KTOx Browser", "", "KEY1 = Enter URL"]
_page_links   = []          # list of (display_text, full_href)
_link_idx     = 0
_scroll       = 0
_current_url  = ""
_history      = []
_status_msg   = "ready"
_fetching     = False
_page_title   = ""

_LINES_PER_PAGE = 9


# ── Hardware Init ────────────────────────────────────────────────────────────
def _init_hw():
    global LCD, _image, _draw, _font_sm, _font_md, _font_hd
    if not HAS_HW:
        return
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()

    _image = Image.new("RGB", (W, H), "black")
    _draw = ImageDraw.Draw(_image)

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ]
    def _load(size):
        for p in font_paths:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
        return ImageFont.load_default()

    _font_sm = _load(9)
    _font_md = _load(11)
    _font_hd = _load(12)


# ── Robust Fetch ─────────────────────────────────────────────────────────────
def _robust_fetch(url, retries=3):
    url = (url or "").strip()
    if not url:
        url = "https://example.com"

    if not re.match(r'^https?://', url, re.IGNORECASE):
        url = "https://" + url

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; KTOxBrowser/1.5; RaspberryPi)",
        "Accept": "text/html,application/xhtml+xml,*/*",
    }

    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(MAX_CONTENT_SIZE)
                charset = "utf-8"
                ct = resp.headers.get("Content-Type", "").lower()
                m = re.search(r'charset=([^\s;"]+)', ct)
                if m:
                    charset = m.group(1).strip('"\'')
                return raw.decode(charset, errors="replace")
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(1.2 * (attempt + 1))


# ── Improved Content + Link Extraction ───────────────────────────────────────
def _extract_content(raw_html, base_url):
    global _page_title
    if not raw_html:
        return ["(empty page)"], []

    try:
        soup = BeautifulSoup(raw_html, 'lxml') if HAS_BS4 else None

        if soup:
            title_tag = soup.find('title')
            _page_title = (title_tag.get_text(strip=True) if title_tag else "")[:32]

            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()

            text = soup.get_text(separator="\n")
        else:
            text = raw_html

        lines = _simple_wrap(text)

        # Extract links more reliably
        links = []
        if soup:
            for a in soup.find_all('a', href=True):
                txt = a.get_text(strip=True)
                if txt and len(txt) > 1 and not txt.startswith(('http', '#')):  # avoid some junk
                    href = urllib.parse.urljoin(base_url, a['href'])
                    if href.startswith(('http://', 'https://')):
                        links.append((txt[:22], href))
        else:
            # very basic fallback
            for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw_html, re.I | re.DOTALL):
                href = m.group(1)
                txt = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if txt and len(txt) > 1:
                    href = urllib.parse.urljoin(base_url, href)
                    links.append((txt[:22], href))

        return lines, links
    except Exception:
        return _simple_wrap(raw_html), []


def _simple_wrap(text, width=20):
    lines = []
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if line:
            lines.extend(textwrap.wrap(line, width=width) or [line])
        else:
            lines.append("")
    out = "\n".join(lines)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.splitlines()


# ── Fetch ────────────────────────────────────────────────────────────────────
def _fetch(url):
    global _page_lines, _page_links, _scroll, _link_idx, _status_msg, _fetching, _page_title, _current_url

    with _ui_lock:
        _fetching = True
        _status_msg = "loading..."
        _page_lines = ["Connecting...", (url or "")[:25]]
        _page_links = []
        _scroll = 0
        _link_idx = 0
        _page_title = ""

    try:
        raw = _robust_fetch(url)
        lines, links = _extract_content(raw, url)

        if not lines:
            lines = ["(no readable content)"]

        # Append links section cleanly
        if links:
            lines += ["", "── Links ──"]
            for i, (txt, _) in enumerate(links):
                lines.append(f"[{i+1}] {txt}")

        with _ui_lock:
            _page_lines = lines
            _page_links = links
            _scroll = 0
            _link_idx = 0
            _status_msg = f"OK {len(lines)}L {len(links)}lk"
            _current_url = url

    except Exception as e:
        err = str(e)[:28]
        with _ui_lock:
            _page_lines = ["Load failed", err]
            _status_msg = "Error"
    finally:
        with _ui_lock:
            _fetching = False


def navigate(url):
    global _history, _current_url
    url = (url or "").strip()
    if not url:
        return
    if _current_url and _current_url != url:
        _history.append(_current_url)
        if len(_history) > MAX_HISTORY:
            _history.pop(0)
    _current_url = url
    threading.Thread(target=_fetch, args=(url,), daemon=True).start()


def go_back():
    if _history:
        navigate(_history.pop())


# ── Drawing ──────────────────────────────────────────────────────────────────
def _draw_browser():
    _draw.rectangle([(0, 0), (W, H)], fill="black")
    _draw.rectangle([(0, 0), (W, 17)], fill=(0, 40, 90))

    title = (_page_title or _current_url or "KTOx Browser")[-20:]
    _draw.text((2, 2), title, font=_font_sm, fill="cyan")

    st = _status_msg[:12]
    _draw.text((W - len(st)*6 - 3, 2), st, font=_font_sm, fill=(180, 180, 180))

    y = 20
    with _ui_lock:
        lines = _page_lines[:]
        scroll = _scroll
        fetching = _fetching
        current_link_idx = _link_idx

    if fetching:
        _draw.text((10, 45), "Fetching...", font=_font_md, fill="yellow")
    else:
        for i in range(_LINES_PER_PAGE):
            idx = scroll + i
            if idx >= len(lines):
                break
            txt = lines[idx][:20]
            color = "white"

            # Highlight selected link
            if txt.startswith("[") and "]" in txt:
                color = (100, 255, 255)
                # Add arrow for currently selected link
                link_num = int(txt.split(']')[0][1:]) - 1 if ']' in txt else -1
                if link_num == current_link_idx:
                    color = (255, 255, 100)
                    txt = "→ " + txt

            _draw.text((2, y), txt, font=_font_sm, fill=color)
            y += 11

    # Scrollbar
    total = max(1, len(lines))
    if total > _LINES_PER_PAGE:
        sb_h = H - 20
        bar_h = max(3, int(sb_h * _LINES_PER_PAGE / total))
        bar_y = 18 + int(sb_h * scroll / total)
        _draw.rectangle([(125, 18), (127, H-1)], fill=(40, 40, 40))
        _draw.rectangle([(125, bar_y), (127, min(bar_y + bar_h, H-1))], fill=(0, 160, 255))

    _draw.rectangle([(0, H-11), (W, H)], fill=(25, 25, 25))
    _draw.text((2, H-10), "K1=URL  K2=Next  OK=Go", font=_font_sm, fill=(140, 140, 140))


# ( _draw_url_input and _push remain the same as previous version - omitted for brevity but copy them from the last script you have )


def _draw_url_input(input_text, char_idx):
    # ... same as in the previous full script you received ...
    # (keep the exact same function from the last working version)
    pass  # placeholder - paste the full _draw_url_input from before


def _push():
    if LCD and _image:
        LCD.LCD_ShowImage(_image, 0, 0)


# ── URL Input (same as before) ───────────────────────────────────────────────
# Paste your existing _url_input_screen function here (unchanged)


# ── WebUI Watcher (same) ─────────────────────────────────────────────────────
def _webui_watcher():
    last_url = ""
    while RUNNING:
        try:
            if os.path.exists(WEBUI_URL_FILE):
                with open(WEBUI_URL_FILE) as f:
                    url = f.read().strip()
                if url and url != last_url:
                    last_url = url
                    navigate(url)
        except Exception:
            pass
        time.sleep(0.7)


# ── Main Loop with Improved Link Handling ────────────────────────────────────
def main():
    global RUNNING, _scroll, _link_idx

    _init_hw()
    if not HAS_HW:
        print("No hardware — exiting.")
        return

    try:
        os.remove(WEBUI_URL_FILE)
    except OSError:
        pass

    watcher = threading.Thread(target=_webui_watcher, daemon=True)
    watcher.start()

    if not _current_url:
        navigate("https://example.com")

    _draw_browser()
    _push()

    held = {}

    try:
        while RUNNING:
            _draw_browser()
            _push()

            pressed = {name: GPIO.input(pin) == 0 for name, pin in PINS.items()}
            now = time.time()

            for name, is_down in pressed.items():
                if is_down and name not in held:
                    held[name] = now
                elif not is_down:
                    held.pop(name, None)

            def just_pressed(name):
                return pressed.get(name) and (now - held.get(name, 0)) < 0.15

            if just_pressed("KEY3"):
                break

            if just_pressed("KEY1"):
                url = _url_input_screen(_current_url)
                if url:
                    navigate(url)
                time.sleep(0.2)
                continue

            if just_pressed("LEFT"):
                go_back()
                time.sleep(0.25)
                continue

            if just_pressed("UP"):
                with _ui_lock:
                    _scroll = max(0, _scroll - 1)
                time.sleep(0.07)
                continue

            if just_pressed("DOWN"):
                with _ui_lock:
                    max_s = max(0, len(_page_lines) - _LINES_PER_PAGE)
                    _scroll = min(max_s, _scroll + 1)
                time.sleep(0.07)
                continue

            # Improved KEY2: cycle links + auto-scroll
            if just_pressed("KEY2"):
                with _ui_lock:
                    if _page_links:
                        _link_idx = (_link_idx + 1) % len(_page_links)
                        # Calculate approximate line number for the link
                        link_section_start = len(_page_lines) - len(_page_links) - 2
                        target_line = link_section_start + _link_idx + 2
                        _scroll = max(0, target_line - (_LINES_PER_PAGE // 2))
                time.sleep(0.18)
                continue

            # Improved OK: follow highlighted link
            if just_pressed("OK"):
                with _ui_lock:
                    links = _page_links
                    idx = _link_idx
                if links and idx < len(links):
                    _, href = links[idx]
                    if href:
                        navigate(href)
                time.sleep(0.25)
                continue

            time.sleep(0.04)

    except KeyboardInterrupt:
        pass
    finally:
        RUNNING = False
        try:
            os.remove(WEBUI_URL_FILE)
        except OSError:
            pass
        if LCD:
            LCD.LCD_Clear()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
