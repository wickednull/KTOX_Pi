#!/usr/bin/env python3
"""
KTOx Payload – Tiny Web Browser v3
=====================================
Full-featured text browser for the 128x128 LCD.

Features: trafilatura + BeautifulSoup content extraction, retries,
page title display, link list with KEY2 cycling, back history,
WebUI URL injection via /dev/shm/ktox_browser_url.txt.

Controls (BROWSER):
  UP / DOWN   scroll
  LEFT        back
  KEY1        URL bar
  KEY2        cycle links
  OK          follow highlighted link
  KEY3        exit

Controls (URL INPUT):
  UP / DOWN   prev / next char
  OK          append char
  LEFT        delete last char
  RIGHT       append '.'
  KEY1        append '/'
  KEY2        confirm / go
  KEY3        cancel
"""

import os, sys, re, time, threading, textwrap
import urllib.request, urllib.parse, urllib.error
from urllib.request import Request
from html import unescape

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

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

# ── Constants ────────────────────────────────────────────────────────────────
W, H            = 128, 128
WEBUI_URL_FILE  = "/dev/shm/ktox_browser_url.txt"
MAX_HISTORY     = 15
MAX_CONTENT     = 512 * 1024
CHAR_SET        = "abcdefghijklmnopqrstuvwxyz0123456789./:_-?=&#@%+"
LINES_PER_PAGE  = 9

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}

# ── Hardware globals ──────────────────────────────────────────────────────────
LCD      = None
_image   = None
_draw    = None
_font_sm = None
_font_md = None
_font_hd = None

# ── Page state ────────────────────────────────────────────────────────────────
RUNNING      = True
_lock        = threading.Lock()
_page_lines  = ["Welcome to KTOx Browser","","KEY1 = Enter URL","WebUI ready"]
_page_links  = []   # [(display_text, href), ...]
_link_idx    = 0
_scroll      = 0
_current_url = ""
_history     = []
_status_msg  = "ready"
_fetching    = False
_page_title  = ""


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
    paths  = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ]
    def _load(sz):
        for p in paths:
            try: return ImageFont.truetype(p, sz)
            except Exception: pass
        return ImageFont.load_default()
    _font_sm = _load(9)
    _font_md = _load(11)
    _font_hd = _load(12)


# ── Fetch with retries ────────────────────────────────────────────────────────
def _robust_fetch(url, retries=3):
    if not re.match(r'^https?://', url, re.I):
        url = "https://" + url
    hdrs = {
        "User-Agent": "Mozilla/5.0 (compatible; KTOxBrowser/3.0; RaspberryPi)",
        "Accept":     "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for attempt in range(retries):
        try:
            req = Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(MAX_CONTENT)
                ct  = resp.headers.get("Content-Type","").lower()
                cs  = "utf-8"
                m   = re.search(r'charset=([^\s;"\']+)', ct)
                if m: cs = m.group(1)
                return raw.decode(cs, errors="replace"), ct
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < retries-1:
                time.sleep(1.5*(attempt+1)); continue
            raise
        except Exception:
            if attempt < retries-1:
                time.sleep(0.8*(attempt+1)); continue
            raise
    raise RuntimeError("Failed after retries")


# ── Content extraction ────────────────────────────────────────────────────────
def _extract_content(raw_html, base_url):
    global _page_title
    _page_title = ""

    if HAS_BS4:
        try:
            soup = BeautifulSoup(raw_html, "lxml")

            # Title
            t = soup.find("title")
            if t: _page_title = t.get_text(strip=True)[:32]

            # Links (before decomposing)
            links = []
            seen  = set()
            for a in soup.find_all("a", href=True):
                txt  = a.get_text(strip=True)
                href = a["href"].strip()
                if not txt or len(txt) < 2: continue
                if href.startswith(("javascript:","#","mailto:")): continue
                try:
                    href = urllib.parse.urljoin(base_url, href)
                    if href.startswith(("http://","https://")) and href not in seen:
                        seen.add(href)
                        links.append((txt[:22], href))
                except Exception:
                    pass

            # Text: trafilatura first, BS4 fallback
            text = None
            if HAS_TRAFILATURA:
                text = trafilatura.extract(raw_html, include_links=False,
                                           include_comments=False,
                                           include_tables=True, no_fallback=False)

            if not text or len(text.strip()) < 50:
                for tag in soup(["script","style","nav","header","footer","aside","noscript"]):
                    tag.decompose()
                text = soup.get_text(separator="\n")

            return _wrap_text(text) or ["(no content)"], links

        except Exception:
            pass

    # Pure-regex fallback
    links = []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         raw_html, re.I|re.DOTALL):
        href = m.group(1)
        txt  = re.sub(r'<[^>]+>',"",m.group(2)).strip()
        if txt and len(txt)>1:
            try:
                href = urllib.parse.urljoin(base_url, href)
                links.append((txt[:22], href))
            except Exception: pass
    text = unescape(re.sub(r'<[^>]+'," ", raw_html))
    return _wrap_text(text) or ["(no content)"], links


def _wrap_text(text, width=20):
    lines = []
    for line in text.splitlines():
        line = re.sub(r'\s+'," ",line).strip()
        if line:
            lines.extend(textwrap.wrap(line, width=width) or [line])
        else:
            lines.append("")
    out, prev_blank = [], False
    for ln in lines:
        blank = not ln.strip()
        if blank and prev_blank: continue
        out.append(ln)
        prev_blank = blank
    return out


# ── Fetch worker ──────────────────────────────────────────────────────────────
def _fetch(url):
    global _page_lines, _page_links, _scroll, _link_idx
    global _status_msg, _fetching, _page_title, _current_url

    with _lock:
        _fetching   = True
        _status_msg = "loading..."
        _page_lines = ["Connecting...", url[:25]]
        _page_links = []
        _scroll     = 0
        _link_idx   = 0
        _page_title = ""

    try:
        raw, ct = _robust_fetch(url)

        if "text/html" in ct or "text/plain" in ct:
            lines, links = _extract_content(raw, url)
        else:
            lines = [f"Content: {ct[:20]}", f"Size: {len(raw)//1024}KB","","(Binary)"]
            links = []

        if not lines: lines = ["(empty page)"]

        if links:
            lines += ["","── Links ──"]
            for i,(txt,_) in enumerate(links):
                lines.append(f"[{i+1}] {txt}")

        with _lock:
            _page_lines  = lines
            _page_links  = links
            _scroll      = 0
            _link_idx    = 0
            _status_msg  = f"OK {len(lines)}L {len(links)}lk"
            _current_url = url

    except urllib.error.HTTPError as e:
        with _lock:
            _page_lines = [f"HTTP {e.code}", str(e.reason)[:20]]
            _status_msg = f"HTTP{e.code}"
    except urllib.error.URLError as e:
        with _lock:
            _page_lines = ["Connection failed", str(e.reason)[:20]]
            _status_msg = "URLErr"
    except Exception as e:
        with _lock:
            _page_lines = ["Error:", str(e)[:25]]
            _status_msg = "Error"
    finally:
        with _lock:
            _fetching = False


def navigate(url):
    global _history, _current_url
    url = (url or "").strip()
    if not url: return
    if _current_url and _current_url != url:
        _history.append(_current_url)
        if len(_history) > MAX_HISTORY: _history.pop(0)
    _current_url = url
    threading.Thread(target=_fetch, args=(url,), daemon=True).start()


def go_back():
    global _current_url
    if _history:
        url = _history.pop()
        _current_url = url
        threading.Thread(target=_fetch, args=(url,), daemon=True).start()


# ── Draw: browser ─────────────────────────────────────────────────────────────
def _draw_browser():
    _draw.rectangle([(0,0),(W,H)], fill="black")

    # Header
    _draw.rectangle([(0,0),(W,17)], fill=(0,40,90))
    title = (_page_title or _current_url or "KTOx Browser")[-20:]
    _draw.text((2,2), title, font=_font_sm, fill="cyan")
    st = _status_msg[:10]
    _draw.text((W-len(st)*6-2, 2), st, font=_font_sm, fill=(180,180,180))

    # Content
    y = 20
    with _lock:
        lines       = _page_lines[:]
        scroll      = _scroll
        fetching    = _fetching
        active_link = _link_idx
        n_links     = len(_page_links)

    if fetching:
        dots = "." * (int(time.time()*2) % 4)
        _draw.text((10,52), f"Loading{dots}", font=_font_md, fill="yellow")
    else:
        for i in range(LINES_PER_PAGE):
            idx = scroll + i
            if idx >= len(lines): break
            txt   = lines[idx][:20]
            color = "white"

            if txt.startswith("[") and "]" in txt:
                try:
                    link_num = int(txt.split("]")[0][1:]) - 1
                except (ValueError, IndexError):
                    link_num = -1

                if link_num == active_link:
                    _draw.rectangle([(0,y-1),(123,y+9)], fill=(0,60,0))
                    color = (255,255,80)
                    txt   = (">" + txt)[:20]
                else:
                    color = (80,200,255)

            _draw.text((2,y), txt, font=_font_sm, fill=color)
            y += 11

    # Scrollbar
    total = max(1, len(lines))
    if total > LINES_PER_PAGE:
        sb_h  = H-20
        bar_h = max(3, int(sb_h * LINES_PER_PAGE / total))
        bar_y = 18 + int(sb_h * scroll / total)
        _draw.rectangle([(125,18),(127,H-1)], fill=(40,40,40))
        _draw.rectangle([(125,bar_y),(127,min(bar_y+bar_h,H-1))], fill=(0,160,255))

    # Footer
    _draw.rectangle([(0,H-11),(W,H)], fill=(25,25,25))
    _draw.text((2,H-10), "K1=URL K2=Lnk L=Bk K3=X", font=_font_sm, fill=(130,130,130))


# ── Draw: URL input ───────────────────────────────────────────────────────────
def _draw_url_input(input_text, char_idx):
    _draw.rectangle([(0,0),(W,H)], fill="black")
    _draw.rectangle([(0,0),(W,15)], fill=(0,70,0))
    _draw.text((3,2), "Enter URL", font=_font_sm, fill="lime")

    shown = (input_text or "")[-19:]
    _draw.rectangle([(0,17),(W,32)], fill=(30,30,30))
    _draw.text((2,19), "> "+shown, font=_font_sm, fill="white")

    cs     = CHAR_SET
    prev_c = cs[(char_idx-1) % len(cs)]
    curr_c = cs[char_idx]
    next_c = cs[(char_idx+1) % len(cs)]

    _draw.text((4,44),  f"< {prev_c} ", font=_font_md, fill=(100,100,100))
    _draw.rectangle([(50,38),(78,58)], fill=(0,90,160))
    _draw.text((56,40), curr_c, font=_font_hd, fill="yellow")
    _draw.text((82,44), f" {next_c} >", font=_font_md, fill=(100,100,100))

    for row, hint in enumerate(["U/D=char  OK=add","L=del  R=.  K1=/","K2=GO  K3=Cancel"]):
        _draw.text((2, 65+row*11), hint, font=_font_sm, fill=(160,160,160))


def _push():
    if LCD and _image:
        LCD.LCD_ShowImage(_image, 0, 0)


# ── URL input screen ──────────────────────────────────────────────────────────
def _url_input_screen(initial=""):
    input_text = initial or ""
    char_idx   = 0

    while RUNNING:
        _draw_url_input(input_text, char_idx)
        _push()

        btn, t0 = None, time.time()
        while not btn and RUNNING:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    btn = name; break
            if time.time()-t0 > 90: return ""
            time.sleep(0.04)

        if not RUNNING: break
        if btn == "KEY3": return ""
        elif btn == "KEY2": return input_text.strip()
        elif btn == "OK":    input_text += CHAR_SET[char_idx]
        elif btn == "LEFT":  input_text  = input_text[:-1]
        elif btn == "RIGHT": input_text += "."
        elif btn == "KEY1":  input_text += "/"
        elif btn == "UP":    char_idx = (char_idx-1+len(CHAR_SET)) % len(CHAR_SET)
        elif btn == "DOWN":  char_idx = (char_idx+1) % len(CHAR_SET)
        time.sleep(0.10)
    return ""


# ── WebUI watcher ─────────────────────────────────────────────────────────────
def _webui_watcher():
    last_url = ""
    while RUNNING:
        try:
            if os.path.exists(WEBUI_URL_FILE):
                url = open(WEBUI_URL_FILE).read().strip()
                if url and url != last_url:
                    last_url = url
                    navigate(url)
        except Exception: pass
        time.sleep(0.7)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    global RUNNING, _scroll, _link_idx

    _init_hw()
    if not HAS_HW:
        print("[web_browser] No hardware — exiting.", flush=True)
        return

    try: os.remove(WEBUI_URL_FILE)
    except OSError: pass

    threading.Thread(target=_webui_watcher, daemon=True).start()
    _draw_browser()
    _push()

    _held     = {}   # name -> time first pressed
    _consumed = set()

    try:
        while RUNNING:
            _draw_browser()
            _push()

            now     = time.time()
            pressed = {name: GPIO.input(pin)==0 for name,pin in PINS.items()}

            for name, is_down in pressed.items():
                if is_down:
                    if name not in _held: _held[name] = now
                else:
                    _held.pop(name, None)
                    _consumed.discard(name)

            def just_pressed(name):
                """True only on the first ~60 ms a button is down."""
                return pressed.get(name) and (now - _held.get(name, now)) <= 0.06

            if just_pressed("KEY3"): break

            if just_pressed("KEY1"):
                url = _url_input_screen(_current_url)
                if url: navigate(url)
                _held.clear(); _consumed.clear()
                time.sleep(0.2)
                continue

            if just_pressed("LEFT"):
                go_back()
                time.sleep(0.25)
                continue

            if just_pressed("UP"):
                with _lock: _scroll = max(0, _scroll-1)
                time.sleep(0.07)
                continue

            if just_pressed("DOWN"):
                with _lock:
                    ms = max(0, len(_page_lines)-LINES_PER_PAGE)
                    _scroll = min(ms, _scroll+1)
                time.sleep(0.07)
                continue

            if just_pressed("KEY2"):
                with _lock:
                    if _page_links:
                        _link_idx = (_link_idx+1) % len(_page_links)
                        sect  = max(0, len(_page_lines)-len(_page_links)-2)
                        target = sect + _link_idx + 2
                        _scroll = max(0, target - LINES_PER_PAGE//2)
                time.sleep(0.18)
                continue

            if just_pressed("OK"):
                with _lock:
                    links = _page_links[:]
                    idx   = _link_idx
                if links and idx < len(links):
                    _, href = links[idx]
                    navigate(href)
                time.sleep(0.25)
                continue

            time.sleep(0.04)

    except KeyboardInterrupt:
        pass
    finally:
        RUNNING = False
        try: os.remove(WEBUI_URL_FILE)
        except OSError: pass
        if LCD: LCD.LCD_Clear()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
