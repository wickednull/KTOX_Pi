#!/usr/bin/env python3
"""
KTOx payload — Wordlist Manager
================================
Download and manage wordlists and hashcat rule files for
password cracking tools (hashcat, aircrack-ng, john, etc.).

Automatically checks for an existing rockyou.txt.gz and offers
to decompress it before falling back to a network download.

Controls
--------
  UP / DOWN   navigate list
  OK          download / decompress selected entry
  KEY1        download all missing entries
  KEY2        refresh installed status
  KEY3        exit

Author: wickednull
"""

import os, sys, time, threading, urllib.request, gzip, shutil
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))
if "/root/KTOx" not in sys.path:
    sys.path.insert(0, "/root/KTOx")

try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

from _input_helper import get_button, flush_input

# ── constants ─────────────────────────────────────────────────────────────────
PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}

W, H = 128, 128
WORDLIST_DIR   = Path("/usr/share/wordlists")
HASHCAT_DIR    = Path("/usr/share/hashcat/rules")

# ── Game Boy DMG colour palette ───────────────────────────────────────────────
GB_BG    = "#0f380f"   # darkest  — background
GB_DARK  = "#306230"   # dark     — title bars, borders, selected rows
GB_MID   = "#8bac0f"   # medium   — dim text, footer hints
GB_LIGHT = "#9bbc0f"   # light    — active / installed items
GB_WHITE = "#e0f8d0"   # lightest — bright / important text
GB_ERR   = "#7a1a1a"   # error title bar
GB_ERRT  = "#c04040"   # error body text

# ── catalog ───────────────────────────────────────────────────────────────────
# Each entry:
#   name       short display name (≤14 chars)
#   desc       one-line description
#   size       human size for display
#   url        download URL
#   dest       destination path (Path)
#   gz_source  if set, try to decompress this .gz first before downloading
CATALOG = [
    {
        "name":      "rockyou.txt",
        "desc":      "Classic 14M passwords",
        "size":      "134 MB",
        "url":       "https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt",
        "dest":      WORDLIST_DIR / "rockyou.txt",
        "gz_source": WORDLIST_DIR / "rockyou.txt.gz",
    },
    {
        "name":      "Top-10K",
        "desc":      "10K most common passwords",
        "size":      "85 KB",
        "url":       "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/10-million-password-list-top-10000.txt",
        "dest":      WORDLIST_DIR / "top10k.txt",
        "gz_source": None,
    },
    {
        "name":      "Top-100K",
        "desc":      "100K common passwords",
        "size":      "870 KB",
        "url":       "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/10-million-password-list-top-100000.txt",
        "dest":      WORDLIST_DIR / "top100k.txt",
        "gz_source": None,
    },
    {
        "name":      "Top-1M",
        "desc":      "1M common passwords",
        "size":      "8.5 MB",
        "url":       "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/10-million-password-list-top-1000000.txt",
        "dest":      WORDLIST_DIR / "top1m.txt",
        "gz_source": None,
    },
    {
        "name":      "WiFi-WPA",
        "desc":      "WPA-specific 4.8K list",
        "size":      "35 KB",
        "url":       "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/WiFi-WPA/probable-v2-wpa-top4800.txt",
        "dest":      WORDLIST_DIR / "wifi-wpa.txt",
        "gz_source": None,
    },
    {
        "name":      "DarkWeb2017",
        "desc":      "Top 10K darkweb leaks",
        "size":      "75 KB",
        "url":       "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/darkweb2017-top10000.txt",
        "dest":      WORDLIST_DIR / "darkweb2017.txt",
        "gz_source": None,
    },
    {
        "name":      "Probable-WPA",
        "desc":      "Probable WPA top 12K",
        "size":      "100 KB",
        "url":       "https://raw.githubusercontent.com/berzerk0/Probable-Wordlists/master/Real-Passwords/WPA-Probable/Top12Thousand-WPA-probable-v2.txt",
        "dest":      WORDLIST_DIR / "probable-wpa.txt",
        "gz_source": None,
    },
    {
        "name":      "Best64 (rules)",
        "desc":      "Hashcat Best64 rule",
        "size":      "3 KB",
        "url":       "https://raw.githubusercontent.com/hashcat/hashcat/master/rules/best64.rule",
        "dest":      HASHCAT_DIR / "best64.rule",
        "gz_source": None,
    },
    {
        "name":      "OneRule (rules)",
        "desc":      "Mega hashcat rule file",
        "size":      "1.1 MB",
        "url":       "https://raw.githubusercontent.com/NotSoSecure/password_cracking_rules/master/OneRuleToRuleThemAll.rule",
        "dest":      HASHCAT_DIR / "OneRuleToRuleThemAll.rule",
        "gz_source": None,
    },
]

# ── LCD helpers ───────────────────────────────────────────────────────────────

def _font(size=8):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except Exception:
        return ImageFont.load_default()


FONT_SM  = _font(8)
FONT_MD  = _font(9)

lcd_hw = None

if HAS_HW:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for _p in PINS.values():
            GPIO.setup(_p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        lcd_hw = LCD_1in44.LCD()
        lcd_hw.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        lcd_hw.LCD_Clear()
    except Exception as _e:
        print(f"LCD init error: {_e}")
        lcd_hw = None


def lcd_show(title, lines, title_col=None, text_col=None):
    title_col = title_col or GB_DARK
    text_col  = text_col  or GB_WHITE
    img  = Image.new("RGB", (W, H), GB_BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, 14), fill=title_col)
    draw.text((3, 2), title[:20], fill=GB_WHITE, font=FONT_MD)
    y = 18
    for ln in (lines or []):
        draw.text((3, y), str(ln)[:21], fill=text_col, font=FONT_SM)
        y += 11
        if y > H - 10:
            break
    if lcd_hw:
        try:
            lcd_hw.LCD_ShowImage(img, 0, 0)
        except Exception:
            pass
    else:
        print(f"[{title}]", " | ".join(str(l) for l in (lines or [])))


# ── install status ────────────────────────────────────────────────────────────

def is_installed(entry):
    return entry["dest"].exists()


def has_gz(entry):
    return entry.get("gz_source") and entry["gz_source"].exists()


def refresh_status():
    for e in CATALOG:
        e["installed"] = is_installed(e)
        e["can_decomp"] = has_gz(e) and not e["installed"]


# ── download / decompress ─────────────────────────────────────────────────────

_dl = {
    "active":  False,
    "name":    "",
    "pct":     0,
    "msg":     "",
    "error":   "",
    "done":    False,
}
_dl_lock = threading.Lock()


def _set_dl(**kw):
    with _dl_lock:
        _dl.update(kw)


def _decompress_gz(entry):
    gz = entry["gz_source"]
    dst = entry["dest"]
    _set_dl(name=entry["name"], msg="Decompressing...", pct=0, error="", done=False)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        total = gz.stat().st_size
        written = 0
        with gzip.open(gz, "rb") as fin, open(dst, "wb") as fout:
            while True:
                chunk = fin.read(65536)
                if not chunk:
                    break
                fout.write(chunk)
                written += len(chunk)
                pct = min(99, int(written / max(total, 1) * 100))
                _set_dl(pct=pct, msg=f"Decomp {pct}%")
        _set_dl(pct=100, msg="Done!", done=True)
    except Exception as exc:
        _set_dl(error=str(exc)[:40], done=True)


def _download(entry):
    dst = entry["dest"]
    url = entry["url"]
    _set_dl(name=entry["name"], msg="Connecting...", pct=0, error="", done=False)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")

        req = urllib.request.Request(url, headers={"User-Agent": "KTOx/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            written = 0
            with open(tmp, "wb") as fout:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fout.write(chunk)
                    written += len(chunk)
                    if total:
                        pct = min(99, int(written / total * 100))
                        mb = written / 1_048_576
                        _set_dl(pct=pct, msg=f"{mb:.1f}MB {pct}%")
                    else:
                        mb = written / 1_048_576
                        _set_dl(msg=f"{mb:.1f}MB...")

        shutil.move(str(tmp), str(dst))
        _set_dl(pct=100, msg="Done!", done=True)

    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        _set_dl(error=str(exc)[:40], done=True)


def _start_worker(entry):
    """Start download/decompress in background thread."""
    if entry.get("can_decomp"):
        target = _decompress_gz
    else:
        target = _download
    _set_dl(active=True, done=False, error="", pct=0, msg="Starting...")
    t = threading.Thread(target=target, args=(entry,), daemon=True)
    t.start()
    return t


def _wait_for_worker(t):
    """Block main loop until worker finishes, updating LCD each frame."""
    while t.is_alive() or not _dl["done"]:
        with _dl_lock:
            name = _dl["name"]
            pct  = _dl["pct"]
            msg  = _dl["msg"]
            err  = _dl["error"]

        bar_w  = W - 6
        filled = int(bar_w * pct / 100)

        img  = Image.new("RGB", (W, H), GB_BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, W, 14), fill=GB_DARK)
        draw.text((3, 2),  "DOWNLOADING",  fill=GB_WHITE, font=FONT_MD)
        draw.text((3, 20), name[:21],       fill=GB_LIGHT, font=FONT_SM)
        draw.text((3, 34), msg[:21],        fill=GB_WHITE, font=FONT_SM)
        draw.rectangle((3, 50, W - 3, 62), outline=GB_DARK, fill=GB_BG)
        if filled:
            draw.rectangle((3, 50, 3 + filled, 62), fill=GB_LIGHT)
        draw.text((3, 66), f"{pct}%", fill=GB_LIGHT, font=FONT_SM)
        if err:
            draw.text((3, 80), "ERR:",      fill=GB_ERR,  font=FONT_SM)
            draw.text((3, 91), err[:21],    fill=GB_ERRT, font=FONT_SM)

        if lcd_hw:
            try:
                lcd_hw.LCD_ShowImage(img, 0, 0)
            except Exception:
                pass
        else:
            print(f"  [{pct:3d}%] {msg}")

        time.sleep(0.25)
        if _dl["done"] and not t.is_alive():
            break

    _set_dl(active=False)
    time.sleep(0.5)


# ── menu rendering ────────────────────────────────────────────────────────────

VISIBLE = 5


def _render_menu(cursor, scroll):
    """Draw the scrollable catalog list."""
    img  = Image.new("RGB", (W, H), GB_BG)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle((0, 0, W, 14), fill=GB_DARK)
    draw.text((3, 2), "WORDLISTS", fill=GB_WHITE, font=FONT_MD)

    # Count installed
    n_inst = sum(1 for e in CATALOG if e.get("installed"))
    draw.text((78, 3), f"{n_inst}/{len(CATALOG)}", fill=GB_LIGHT, font=FONT_SM)

    # List items
    y = 18
    for i in range(scroll, min(scroll + VISIBLE, len(CATALOG))):
        entry = CATALOG[i]
        sel   = (i == cursor)
        inst  = entry.get("installed", False)
        cdec  = entry.get("can_decomp", False)

        prefix = ">" if sel else " "
        status = "*" if inst else ("~" if cdec else " ")
        name14 = entry["name"][:13]
        line   = f"{prefix}{status}{name14}"

        if sel:
            draw.rectangle((0, y, W, y + 10), fill=GB_DARK)
            draw.text((3, y), line, fill=GB_WHITE, font=FONT_SM)
        elif inst:
            draw.text((3, y), line, fill=GB_LIGHT, font=FONT_SM)
        elif cdec:
            draw.text((3, y), line, fill=GB_MID,   font=FONT_SM)
        else:
            draw.text((3, y), line, fill=GB_MID,   font=FONT_SM)

        y += 11

    # Footer
    draw.line((0, H - 22, W, H - 22), fill=GB_DARK)
    draw.text((3, H - 20), "OK=DL  K1=ALL  K3=quit", fill=GB_MID, font=FONT_SM)
    draw.text((3, H - 10), "*=inst  ~=gz avail",      fill=GB_MID, font=FONT_SM)

    if lcd_hw:
        try:
            lcd_hw.LCD_ShowImage(img, 0, 0)
        except Exception:
            pass
    else:
        for i, e in enumerate(CATALOG):
            sel  = ">" if i == cursor else " "
            inst = "*" if e.get("installed") else ("~" if e.get("can_decomp") else " ")
            print(f"  {sel}{inst} {e['name']:14s} [{e['size']}]")


def _show_result(entry, error):
    if error:
        lcd_show("ERROR", [entry["name"], "", error],
                 title_col=GB_ERR, text_col=GB_ERRT)
    else:
        lcd_show("DONE", [entry["name"], "", "Installed OK!", f"-> {entry['dest']}"],
                 text_col=GB_LIGHT)
    time.sleep(2)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    flush_input()
    refresh_status()

    cursor = 0
    scroll = 0
    last_btn_time = 0

    _render_menu(cursor, scroll)

    while True:
        now = time.monotonic()
        btn = get_button(PINS, GPIO) if HAS_HW else None

        if btn and (now - last_btn_time) > 0.25:
            last_btn_time = now

            if btn == "UP":
                if cursor > 0:
                    cursor -= 1
                    if cursor < scroll:
                        scroll = cursor
                    _render_menu(cursor, scroll)

            elif btn == "DOWN":
                if cursor < len(CATALOG) - 1:
                    cursor += 1
                    if cursor >= scroll + VISIBLE:
                        scroll = cursor - VISIBLE + 1
                    _render_menu(cursor, scroll)

            elif btn == "OK":
                entry = CATALOG[cursor]
                if entry.get("installed"):
                    lcd_show("SKIP", [entry["name"], "", "Already installed."],
                             text_col=GB_MID)
                    time.sleep(1.5)
                    _render_menu(cursor, scroll)
                else:
                    t = _start_worker(entry)
                    _wait_for_worker(t)
                    err = _dl.get("error", "")
                    refresh_status()
                    _show_result(entry, err)
                    _render_menu(cursor, scroll)

            elif btn == "KEY1":
                missing = [e for e in CATALOG if not e.get("installed")]
                if not missing:
                    lcd_show("ALL DONE", ["All entries", "already installed."],
                             text_col=GB_LIGHT)
                    time.sleep(2)
                    _render_menu(cursor, scroll)
                else:
                    for i, entry in enumerate(missing):
                        lcd_show("BATCH DL",
                                 [f"{i+1}/{len(missing)}", entry["name"]])
                        time.sleep(0.3)
                        t = _start_worker(entry)
                        _wait_for_worker(t)
                    refresh_status()
                    ok = sum(1 for e in CATALOG if e.get("installed"))
                    lcd_show("BATCH DONE",
                             [f"{ok}/{len(CATALOG)} installed",
                              f"{len(missing)} attempted"],
                             text_col=GB_LIGHT)
                    time.sleep(2.5)
                    _render_menu(cursor, scroll)

            elif btn == "KEY2":
                lcd_show("REFRESH", ["Checking status..."])
                refresh_status()
                time.sleep(0.5)
                _render_menu(cursor, scroll)

            elif btn == "KEY3":
                lcd_show("EXIT", ["Wordlist Manager", "closed."],
                         text_col=GB_MID)
                time.sleep(1)
                break

        time.sleep(0.05)

    if HAS_HW:
        try:
            GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
