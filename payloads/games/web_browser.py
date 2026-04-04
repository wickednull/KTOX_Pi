#!/usr/bin/env python3
"""
KTOx Payload – Tiny Web Browser
=================================
Fetches pages with urllib, strips HTML, renders on 128×128 LCD.

Controls (BROWSER view):
  UP / DOWN     Scroll content
  LEFT          Back (history)
  OK            Follow highlighted link
  KEY1          Open URL keyboard
  KEY2          Cycle to next link
  KEY3          Exit

Controls (URL INPUT):
  UP / DOWN     Prev / next char in charset
  OK            Append char
  LEFT          Delete last char
  RIGHT         Add '.' (quick domain char)
  KEY1          Add '/' separator
  KEY2          Confirm / Go
  KEY3          Cancel

WebUI:
  Write a URL to /dev/shm/ktox_browser_url.txt and the browser
  will navigate there automatically within 1 second.
"""

import os
import sys
import re
import time
import html
import threading
import textwrap
import urllib.request
import urllib.parse
import urllib.error

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

# ── Constants ────────────────────────────────────────────────────────────────
W, H = 128, 128
WEBUI_URL_FILE = "/dev/shm/ktox_browser_url.txt"
MAX_HISTORY = 20
CHAR_SET = "abcdefghijklmnopqrstuvwxyz0123456789./:_-?=&#@%+"

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

# ── Module-level hardware ────────────────────────────────────────────────────
LCD = None
_image = None
_draw = None
_font_sm = None
_font_md = None
_font_hd = None

# ── Shared state ─────────────────────────────────────────────────────────────
RUNNING = True
_ui_lock = threading.Lock()

_page_lines   = ["Welcome!", "", "Press KEY1 to", "enter a URL,", "or send one via", "the WebUI."]
_page_links   = []          # list of (display_text, href) extracted from page
_link_idx     = 0           # currently highlighted link index
_scroll       = 0           # line scroll offset
_current_url  = ""
_history      = []          # list of URLs for back navigation
_status_msg   = ""          # one-line status shown in header
_fetching     = False


# ── Hardware init ─────────────────────────────────────────────────────────────
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
    _draw  = ImageDraw.Draw(_image)

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


# ── HTML → text ───────────────────────────────────────────────────────────────
_BLOCK_TAGS = re.compile(
    r'<(br|p|div|h[1-6]|li|tr|blockquote|pre|hr)[^>]*>',
    re.IGNORECASE
)
_STRIP_TAGS = re.compile(r'<[^>]+>')
_MULTI_BLANK = re.compile(r'\n{3,}')
_LINK_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def _extract_links(raw_html, base_url):
    """Return list of (text, absolute_url) from <a href=...> tags."""
    links = []
    for href, text in _LINK_RE.findall(raw_html):
        text = _STRIP_TAGS.sub("", text).strip()
        text = html.unescape(text)
        if not text:
            continue
        try:
            href = urllib.parse.urljoin(base_url, href)
        except Exception:
            pass
        links.append((text[:22], href))
    return links


def _html_to_text(raw_html, width=20):
    """Strip HTML, decode entities, wrap to `width` chars."""
    # Replace block tags with newlines
    text = _BLOCK_TAGS.sub("\n", raw_html)
    text = _STRIP_TAGS.sub("", text)
    text = html.unescape(text)
    # Collapse whitespace within lines, keep real newlines
    lines = []
    for line in text.splitlines():
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if line:
            lines.extend(textwrap.wrap(line, width) or [line])
        else:
            lines.append("")
    # Collapse triple+ blank lines
    out = "\n".join(lines)
    out = _MULTI_BLANK.sub("\n\n", out)
    return out.splitlines()


# ── Fetch ─────────────────────────────────────────────────────────────────────
def _fetch(url):
    global _page_lines, _page_links, _scroll, _link_idx, _status_msg, _fetching

    # Normalise URL
    if not re.match(r'^https?://', url, re.IGNORECASE):
        url = "http://" + url

    with _ui_lock:
        _page_lines = [f"Loading…", url[:20]]
        _page_links = []
        _scroll     = 0
        _link_idx   = 0
        _status_msg = "fetching…"
        _fetching   = True

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "KTOxBrowser/1.0 (tiny LCD browser)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(256 * 1024)          # cap at 256 KB
            charset = "utf-8"
            m = re.search(r'charset=([^\s;]+)', content_type)
            if m:
                charset = m.group(1).strip().strip('"')
            raw_str = raw.decode(charset, errors="replace")

        links = _extract_links(raw_str, url)
        lines = _html_to_text(raw_str, width=20)
        if not lines:
            lines = ["(empty page)"]

        # Inject link markers into text
        if links:
            lines += ["", "── Links ──"]
            for i, (txt, _) in enumerate(links):
                lines.append(f"[{i+1}] {txt}")

        with _ui_lock:
            _page_lines = lines
            _page_links = links
            _scroll     = 0
            _link_idx   = 0
            _status_msg = f"OK  {len(lines)}L {len(links)}lk"

    except urllib.error.HTTPError as e:
        with _ui_lock:
            _page_lines = [f"HTTP {e.code}", str(e.reason)[:20]]
            _status_msg = f"HTTP {e.code}"
    except urllib.error.URLError as e:
        reason = str(e.reason)[:18]
        with _ui_lock:
            _page_lines = ["URL Error:", reason]
            _status_msg = "URL Error"
    except Exception as e:
        with _ui_lock:
            _page_lines = ["Error:", str(e)[:20]]
            _status_msg = "Error"
    finally:
        with _ui_lock:
            _fetching = False


def navigate(url):
    global _current_url, _history
    if _current_url:
        _history.append(_current_url)
        if len(_history) > MAX_HISTORY:
            _history.pop(0)
    _current_url = url
    t = threading.Thread(target=_fetch, args=(url,), daemon=True)
    t.start()


def go_back():
    global _current_url
    if _history:
        url = _history.pop()
        _current_url = url
        t = threading.Thread(target=_fetch, args=(url,), daemon=True)
        t.start()


# ── Draw ──────────────────────────────────────────────────────────────────────
_LINES_PER_PAGE = 9   # content lines visible (below 18px header)

def _draw_browser():
    """Render browser view into global _image."""
    _draw.rectangle([(0, 0), (W, H)], fill="black")

    # Header bar
    _draw.rectangle([(0, 0), (W, 16)], fill=(0, 40, 80))
    url_disp = (_current_url or "no url")[-20:]
    _draw.text((2, 2), url_disp, font=_font_sm, fill="cyan")

    # Status right-aligned in header
    st = _status_msg[:10]
    _draw.text((W - len(st)*5 - 2, 2), st, font=_font_sm, fill=(150, 150, 150))

    # Content
    y = 19
    with _ui_lock:
        lines = _page_lines
        scroll = _scroll
        fetching = _fetching

    if fetching:
        _draw.text((4, 40), "Loading…", font=_font_md, fill="yellow")
    else:
        for i in range(_LINES_PER_PAGE):
            idx = scroll + i
            if idx >= len(lines):
                break
            txt = lines[idx][:20]
            color = "white"
            # Highlight link lines
            if txt.startswith("[") and "]" in txt:
                color = (100, 220, 255)
            _draw.text((2, y), txt, font=_font_sm, fill=color)
            y += 10

    # Scrollbar
    total = max(1, len(lines))
    if total > _LINES_PER_PAGE:
        sb_h = H - 18
        bar_h = max(4, int(sb_h * _LINES_PER_PAGE / total))
        bar_y = 18 + int(sb_h * scroll / total)
        _draw.rectangle([(125, 18), (127, H - 1)], fill=(30, 30, 30))
        _draw.rectangle([(125, bar_y), (127, min(bar_y + bar_h, H - 1))], fill=(0, 150, 255))

    # Footer hint
    _draw.rectangle([(0, H - 10), (W, H)], fill=(20, 20, 20))
    _draw.text((2, H - 9), "K1=URL K2=lnk K3=exit", font=_font_sm, fill=(120, 120, 120))


def _draw_url_input(input_text, char_idx):
    """Render URL keyboard screen into global _image."""
    _draw.rectangle([(0, 0), (W, H)], fill="black")
    _draw.rectangle([(0, 0), (W, 14)], fill=(0, 60, 0))
    _draw.text((3, 2), "Enter URL", font=_font_sm, fill="lime")

    # Current input (last 19 chars)
    shown = (input_text or "")[-19:]
    _draw.rectangle([(0, 16), (W, 30)], fill=(20, 20, 20))
    _draw.text((2, 18), "> " + shown, font=_font_sm, fill="white")

    # Character selector
    cs = CHAR_SET
    ci = char_idx
    prev_c = cs[(ci - 1) % len(cs)]
    curr_c = cs[ci]
    next_c = cs[(ci + 1) % len(cs)]

    _draw.text((10, 40), f"< {prev_c}  ", font=_font_md, fill=(100, 100, 100))
    _draw.rectangle([(48, 36), (80, 54)], fill=(0, 80, 140))
    _draw.text((54, 38), curr_c, font=_font_hd, fill="yellow")
    _draw.text((84, 40), f"  {next_c} >", font=_font_md, fill=(100, 100, 100))

    # Key hints
    hints = [
        "U/D=char  OK=add",
        "L=del  R=dot(.)  ",
        "K1=/  K2=GO  K3=X",
    ]
    y = 62
    for h in hints:
        _draw.text((2, y), h, font=_font_sm, fill=(160, 160, 160))
        y += 11


def _push():
    if LCD and _image:
        LCD.LCD_ShowImage(_image, 0, 0)


# ── URL input screen ──────────────────────────────────────────────────────────
def _url_input_screen(initial=""):
    """Blocking on-screen URL keyboard. Returns URL string or '' if cancelled."""
    global RUNNING
    input_text = initial
    char_idx   = 0

    while RUNNING:
        _draw_url_input(input_text, char_idx)
        _push()

        # Wait for button
        btn = None
        t0 = time.time()
        while not btn and RUNNING:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    btn = name
                    break
            if time.time() - t0 > 60:
                return ""          # timeout → cancel
            time.sleep(0.04)

        if not RUNNING:
            break

        if btn == "KEY3":
            return ""
        elif btn == "KEY2":
            return input_text.strip()
        elif btn == "OK":
            input_text += CHAR_SET[char_idx]
        elif btn == "LEFT":
            input_text = input_text[:-1]
        elif btn == "RIGHT":
            input_text += "."
        elif btn == "KEY1":
            input_text += "/"
        elif btn == "UP":
            char_idx = (char_idx - 1 + len(CHAR_SET)) % len(CHAR_SET)
        elif btn == "DOWN":
            char_idx = (char_idx + 1) % len(CHAR_SET)

        time.sleep(0.12)   # debounce
    return ""


# ── WebUI URL watcher ─────────────────────────────────────────────────────────
def _webui_watcher():
    """Background thread: poll WEBUI_URL_FILE and navigate if updated."""
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
        time.sleep(0.8)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global RUNNING, _scroll, _link_idx

    _init_hw()
    if not HAS_HW:
        print("[web_browser] No hardware — exiting.", flush=True)
        return

    # Clean up any stale webui file
    try:
        os.remove(WEBUI_URL_FILE)
    except OSError:
        pass

    # Start WebUI watcher
    watcher = threading.Thread(target=_webui_watcher, daemon=True)
    watcher.start()

    # Initial render
    _draw_browser()
    _push()

    held = {}   # button → time first held

    try:
        while RUNNING:
            # ── Render ──
            _draw_browser()
            _push()

            # ── Input ──
            pressed = {}
            for name, pin in PINS.items():
                pressed[name] = GPIO.input(pin) == 0

            now = time.time()
            for name, is_down in pressed.items():
                if is_down:
                    if name not in held:
                        held[name] = now
                else:
                    held.pop(name, None)

            def just_pressed(name):
                return pressed.get(name) and held.get(name, now) >= now - 0.08

            if just_pressed("KEY3"):
                break

            if just_pressed("KEY1"):
                url = _url_input_screen(_current_url or "")
                if url:
                    navigate(url)
                time.sleep(0.2)
                continue

            if just_pressed("LEFT"):
                go_back()
                time.sleep(0.3)
                continue

            if just_pressed("UP"):
                with _ui_lock:
                    _scroll = max(0, _scroll - 1)
                time.sleep(0.08)
                continue

            if just_pressed("DOWN"):
                with _ui_lock:
                    max_s = max(0, len(_page_lines) - _LINES_PER_PAGE)
                    _scroll = min(max_s, _scroll + 1)
                time.sleep(0.08)
                continue

            if just_pressed("KEY2"):
                # Cycle to next link
                with _ui_lock:
                    links = _page_links
                if links:
                    _link_idx = (_link_idx + 1) % len(links)
                    # Scroll so link is visible — it's in the "Links" section
                    base = len(_page_lines) - len(links) - 2  # "── Links ──" + blank
                    target_line = base + _link_idx + 2
                    _scroll = max(0, target_line - _LINES_PER_PAGE // 2)
                time.sleep(0.2)
                continue

            if just_pressed("OK"):
                with _ui_lock:
                    links = _page_links
                    idx   = _link_idx
                if links and idx < len(links):
                    _, href = links[idx]
                    navigate(href)
                time.sleep(0.3)
                continue

            time.sleep(0.05)

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
