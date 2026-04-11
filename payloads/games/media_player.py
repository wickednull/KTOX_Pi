#!/usr/bin/env python3
"""
KTOx Payload – Media Player
============================
Browse and play MP3/MP4/audio files from the device or USB drive.
Video plays directly on the LCD framebuffer. Audio shows a Now Playing screen.

Controls:
  UP / DOWN     Navigate file list
  LEFT          Parent directory
  OK (joystick) Open folder / Play file
  KEY1          Stop playback (returns to browser)
  KEY2          Toggle repeat mode
  KEY3          Exit payload
"""

import os, sys, time, subprocess, shutil, threading

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

PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

AUDIO_EXT = {'.mp3', '.flac', '.wav', '.ogg', '.aac', '.m4a', '.opus'}
VIDEO_EXT = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.m4v', '.flv'}
MEDIA_EXT = AUDIO_EXT | VIDEO_EXT

START_DIRS = ["/media", "/root/Music", "/home", "/root", "/tmp"]


# ── Utilities ─────────────────────────────────────────────────────────────────

def _find_start():
    for d in START_DIRS:
        if os.path.isdir(d):
            return d
    return "/"

def _load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def _get_player():
    for cmd in ["mplayer", "mpv", "cvlc"]:
        if shutil.which(cmd):
            return cmd
    return None


# ── LCD state (module-level so helpers can access) ────────────────────────────

_lcd       = None
_image     = None
_draw      = None
_font_bold = None
_font_sm   = None


def _init_lcd():
    global _lcd, _image, _draw, _font_bold, _font_sm
    _lcd = LCD_1in44.LCD()
    _lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    _lcd.LCD_Clear()
    _image = Image.new("RGB", (128, 128), "black")
    _draw  = ImageDraw.Draw(_image)
    _font_bold = _load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    _font_sm   = _load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)


def _show():
    if _lcd:
        _lcd.LCD_ShowImage(_image, 0, 0)


def _draw_header(title, bg=(0, 100, 180)):
    _draw.rectangle([(0, 0), (128, 16)], fill=bg)
    _draw.text((4, 3), title[:21], font=_font_sm, fill="black")


def _draw_footer(text, bg=(25, 25, 25)):
    _draw.rectangle([(0, 112), (128, 128)], fill=bg)
    _draw.text((4, 114), text, font=_font_sm, fill=(130, 130, 130))


# ── File browser ──────────────────────────────────────────────────────────────

def _list_dir(path):
    try:
        entries = []
        for e in sorted(os.scandir(path), key=lambda x: (not x.is_dir(), x.name.lower())):
            ext = os.path.splitext(e.name)[1].lower()
            if e.is_dir() or ext in MEDIA_EXT:
                entries.append(e)
        return entries
    except PermissionError:
        return []


def _draw_browser(path, entries, sel, repeat):
    _draw.rectangle([(0, 0), (128, 128)], fill=(8, 8, 20))
    _draw_header("MEDIA PLAYER" + (" [R]" if repeat else ""), (0, 100, 180))

    # Current directory name
    short = os.path.basename(path) or "/"
    _draw.text((4, 19), short[:21], font=_font_sm, fill=(90, 150, 255))

    max_items = 6
    start = max(0, sel - max_items + 1) if sel >= max_items else 0
    y = 31

    for i in range(max_items):
        idx = start + i
        if idx >= len(entries):
            break
        e = entries[idx]
        is_sel = (idx == sel)
        ext = os.path.splitext(e.name)[1].lower()

        if is_sel:
            _draw.rectangle([(0, y - 1), (128, y + 12)], fill=(0, 55, 100))

        if e.is_dir():
            icon = "\u25b6"
            col  = (220, 170, 50) if is_sel else (160, 120, 30)
            label = e.name[:16] + "/"
        elif ext in VIDEO_EXT:
            icon = "\u25a0"
            col  = (80, 200, 255) if is_sel else (50, 140, 190)
            label = e.name[:16]
        else:
            icon = "\u266a"
            col  = (80, 255, 140) if is_sel else (50, 190, 90)
            label = e.name[:16]

        _draw.text((4,  y), icon,  font=_font_sm, fill=col)
        _draw.text((17, y), label, font=_font_sm, fill=col)
        y += 13

    if not entries:
        _draw.text((4, 60), "(empty)", font=_font_sm, fill=(80, 80, 80))

    _draw_footer("OK=Play  KEY2=Rpt  K3=Exit")
    _show()


# ── Now Playing (audio) ───────────────────────────────────────────────────────

_stop_flag = threading.Event()


def _draw_now_playing(fname, elapsed=0.0, total=0.0, repeat=False):
    _draw.rectangle([(0, 0), (128, 128)], fill=(5, 5, 15))
    _draw_header("\u266b NOW PLAYING", (0, 100, 60))

    # Title (up to 3 wrapped lines)
    title = os.path.splitext(fname)[0]
    y = 22
    for chunk in [title[i:i+19] for i in range(0, min(len(title), 57), 19)]:
        _draw.text((4, y), chunk, font=_font_sm, fill=(190, 215, 255))
        y += 12

    # Progress bar at y=80
    bar_y = 78
    _draw.rectangle([(4, bar_y), (124, bar_y + 6)], fill=(25, 25, 35), outline=(50, 50, 70))
    if total > 0:
        w = int(120 * min(elapsed, total) / total)
        _draw.rectangle([(4, bar_y), (4 + w, bar_y + 6)], fill=(0, 180, 80))
    else:
        # Spinner when total unknown
        tick = int(elapsed) % 20
        _draw.rectangle([(4 + tick * 6, bar_y), (4 + tick * 6 + 10, bar_y + 6)], fill=(0, 150, 220))

    # Time stamps
    if total > 0:
        ts = f"{int(elapsed//60)}:{int(elapsed%60):02d} / {int(total//60)}:{int(total%60):02d}"
    else:
        ts = f"{int(elapsed//60)}:{int(elapsed%60):02d}"
    _draw.text((4, bar_y + 9), ts, font=_font_sm, fill=(120, 120, 120))

    if repeat:
        _draw.text((104, bar_y + 9), "\u21bb", font=_font_sm, fill=(80, 200, 80))

    _draw_footer("KEY1=Stop  KEY3=Exit", (20, 20, 20))
    _show()


def play_audio(path, repeat=False):
    player = _get_player()
    if not player:
        _draw.rectangle([(0, 0), (128, 128)], fill="black")
        _draw.text((4, 48), "No player found!", font=_font_sm, fill=(255, 80, 80))
        _draw.text((4, 62), "sudo apt install", font=_font_sm, fill=(150, 150, 150))
        _draw.text((4, 75), "mplayer", font=_font_sm, fill=(150, 150, 150))
        _show()
        time.sleep(3)
        return

    fname = os.path.basename(path)
    _stop_flag.clear()

    while True:
        if player == "mplayer":
            cmd = ["mplayer", "-quiet", "-vo", "null", path]
        elif player == "mpv":
            cmd = ["mpv", "--no-video", "--really-quiet", path]
        else:
            cmd = [player, "--intf", "dummy", "--no-video", path]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            _draw.rectangle([(0, 0), (128, 128)], fill="black")
            _draw.text((4, 55), f"Launch error:", font=_font_sm, fill=(255, 80, 80))
            _draw.text((4, 70), str(e)[:20], font=_font_sm, fill=(180, 180, 180))
            _show()
            time.sleep(3)
            return

        start_t = time.time()
        _held   = {}

        while proc.poll() is None:
            now = time.time()
            pressed = {n: GPIO.input(p) == 0 for n, p in PINS.items()}
            for n, down in pressed.items():
                if down:
                    _held.setdefault(n, now)
                else:
                    _held.pop(n, None)

            def jp(name):
                return pressed.get(name) and (now - _held.get(name, now)) <= 0.06

            if jp("KEY1") or jp("KEY3"):
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                _stop_flag.set()
                break

            elapsed = now - start_t
            _draw_now_playing(fname, elapsed=elapsed, repeat=repeat)
            time.sleep(0.15)

        proc.wait()

        if _stop_flag.is_set() or not repeat:
            break
        time.sleep(0.3)


# ── Video playback ────────────────────────────────────────────────────────────

def play_video(path):
    player = _get_player()
    if not player:
        return

    fname = os.path.basename(path)
    _draw.rectangle([(0, 0), (128, 128)], fill="black")
    _draw.text((4, 52), "Loading video...", font=_font_sm, fill=(80, 200, 80))
    _draw.text((4, 66), fname[:21], font=_font_sm, fill=(130, 130, 130))
    _show()
    time.sleep(0.4)

    # mplayer writes directly to /dev/fb1 framebuffer (Waveshare fbtft)
    if player == "mplayer":
        cmd = ["mplayer", "-vo", "fbdev2:/dev/fb1",
               "-vf", "scale=128:128", "-framedrop", "-quiet", path]
    elif player == "mpv":
        cmd = ["mpv", "--vo=drm", "--drm-connector=1",
               "--vf=scale=128:128", "--really-quiet", path]
    else:
        # vlc fallback: audio only on tiny screen
        cmd = ["cvlc", "--no-video", "--quiet", path]

    try:
        proc = subprocess.Popen(cmd)
        _held = {}

        while proc.poll() is None:
            now = time.time()
            pressed = {n: GPIO.input(p) == 0 for n, p in PINS.items()}
            for n, down in pressed.items():
                if down:
                    _held.setdefault(n, now)
                else:
                    _held.pop(n, None)

            def jp(name):
                return pressed.get(name) and (now - _held.get(name, now)) <= 0.06

            if jp("KEY1") or jp("KEY3"):
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(0.05)

        proc.wait()
    except Exception:
        pass
    finally:
        # Reinit LCD SPI after mplayer owned the framebuffer
        try:
            _lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not HAS_HW:
        print("[media_player] No hardware — cannot run.")
        return

    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    _init_lcd()

    cur_path = _find_start()
    entries  = _list_dir(cur_path)
    sel      = 0
    repeat   = False
    _held    = {}

    try:
        while True:
            _draw_browser(cur_path, entries, sel, repeat)

            now     = time.time()
            pressed = {n: GPIO.input(p) == 0 for n, p in PINS.items()}
            for n, down in pressed.items():
                if down:
                    _held.setdefault(n, now)
                else:
                    _held.pop(n, None)

            def jp(name):
                return pressed.get(name) and (now - _held.get(name, now)) <= 0.06

            if jp("KEY3"):
                break
            elif jp("UP"):
                sel = max(0, sel - 1)
            elif jp("DOWN"):
                sel = min(len(entries) - 1, sel + 1) if entries else 0
            elif jp("LEFT"):
                parent = os.path.dirname(cur_path)
                if parent != cur_path:
                    cur_path = parent
                    entries  = _list_dir(cur_path)
                    sel      = 0
            elif jp("KEY2"):
                repeat = not repeat
            elif jp("OK") and entries:
                e = entries[sel]
                if e.is_dir():
                    cur_path = e.path
                    entries  = _list_dir(cur_path)
                    sel      = 0
                else:
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in VIDEO_EXT:
                        play_video(e.path)
                    else:
                        play_audio(e.path, repeat=repeat)
                    # Refresh listing after playback
                    entries = _list_dir(cur_path)

            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        if _lcd:
            _lcd.LCD_Clear()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
