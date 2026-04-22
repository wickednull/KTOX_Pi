#!/usr/bin/env python3
"""
KTOx Media Player – Smooth Video with A/V Sync
================================================
- Non‑blocking button polling.
- ffmpeg with -re for real‑time playback, -async 1 for audio sync.
- USB audio via plughw:1,0 (your Onn headset).
- 15 fps video, hardware‑accelerated where possible.

Controls: UP/DOWN, OK, LEFT, KEY1=stop, KEY3=exit
"""

import os, sys, time, json, subprocess
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Paths & config
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/MediaPlayer"
os.makedirs(LOOT_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(LOOT_DIR, "config.json")
START_DIR = "/root/Videos"
os.makedirs(START_DIR, exist_ok=True)

VIDEO_EXTS = ('.mp4', '.avi', '.mkv', '.mov', '.webm')
AUDIO_EXTS = ('.mp3', '.wav', '.flac', '.ogg')
ALL_MEDIA_EXTS = VIDEO_EXTS + AUDIO_EXTS

# ----------------------------------------------------------------------
# Hardware
# ----------------------------------------------------------------------
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
FONT = font(9)
FONT_BOLD = font(10)

def wait_btn_nonblock():
    """Non‑blocking button check. Returns button name or None."""
    for name, pin in PINS.items():
        if GPIO.input(pin) == 0:
            time.sleep(0.05)  # debounce
            return name
    return None

def show_message(msg, sub=""):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((64, 50), msg, font=FONT_BOLD, fill=(30, 132, 73), anchor="mm")
    if sub:
        d.text((64, 65), sub[:22], font=FONT, fill=(113, 125, 126), anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1.5)

# ----------------------------------------------------------------------
# Audio device (hardcoded for your headset)
# ----------------------------------------------------------------------
AUDIO_DEV = "plughw:1,0"

# ----------------------------------------------------------------------
# Config persistence
# ----------------------------------------------------------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"last_dir": START_DIR}

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except:
        pass

# ----------------------------------------------------------------------
# File browser helpers
# ----------------------------------------------------------------------
def list_media(path):
    try:
        items = []
        for f in sorted(os.scandir(path), key=lambda x: (not x.is_dir(), x.name.lower())):
            if f.is_dir() or f.name.lower().endswith(ALL_MEDIA_EXTS):
                items.append(f)
        return items
    except:
        return []

def get_icon(entry):
    if entry.is_dir():
        return "📁"
    name = entry.name.lower()
    if name.endswith(VIDEO_EXTS):
        return "🎬"
    elif name.endswith(AUDIO_EXTS):
        return "🎵"
    return "❓"

def draw_browser(path, entries, cursor, scroll):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((4, 2), "MEDIA PLAYER", font=FONT_BOLD, fill=(231, 76, 60))
    # File count (right-aligned)
    count_text = f"{len(entries)}"
    tw = d.textlength(count_text, font=FONT)
    d.text((W - 4 - int(tw), 2), count_text, font=FONT, fill=(30, 132, 73))
    path_display = os.path.basename(path) if path != "/" else path
    d.text((4, 14), f"📂 {path_display[:20]}", font=FONT, fill=(171, 178, 185))
    y = 26
    visible = entries[scroll:scroll+5]
    for i, e in enumerate(visible):
        idx = scroll + i
        name = e.name[:16] + ("/" if e.is_dir() else "")
        icon = get_icon(e)
        if idx == cursor:
            d.rectangle((0, y-1, W, y+9), fill=(60, 0, 0))
            d.text((4, y), f"{icon} {name}", font=FONT, fill=(255, 255, 255))
        else:
            d.text((4, y), f"{icon} {name}", font=FONT, fill=(171, 178, 185))
        y += 12
    if len(entries) > 5:
        bar_h = max(4, int(5 / len(entries) * 70))
        bar_y = 26 + int((scroll / max(1, len(entries)-5)) * (70 - bar_h))
        d.rectangle((W-4, bar_y, W-2, bar_y+bar_h), fill=(192, 57, 43))
    d.rectangle((0, H-12, W, H), fill=(34, 0, 0))
    d.text((4, H-10), "UP/DN OK LEFT K1=Stop K3=Exit", font=FONT, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Playback (smooth, with A/V sync)
# ----------------------------------------------------------------------
current_process = None

def stop_playback():
    global current_process
    if current_process:
        current_process.terminate()
        try:
            current_process.wait(timeout=2)
        except:
            current_process.kill()
        current_process = None

def play_audio(filepath):
    """Use aplay for reliable audio playback."""
    global current_process
    stop_playback()
    cmd = ["aplay", "-D", AUDIO_DEV, filepath]
    current_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    while current_process.poll() is None:
        img = Image.new("RGB", (W, H), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
        d.text((4, 2), "NOW PLAYING", font=FONT_BOLD, fill=(231, 76, 60))
        d.text((4, 20), f"🎵 {os.path.basename(filepath)[:18]}", font=FONT, fill=(171, 178, 185))
        d.text((4, 40), "Press KEY1 to stop", font=FONT, fill=(113, 125, 126))
        d.text((4, H-12), "KEY1=stop", font=FONT, fill=(192, 57, 43))
        LCD.LCD_ShowImage(img, 0, 0)
        if wait_btn_nonblock() in ("KEY1", "KEY3"):
            stop_playback()
            break
        time.sleep(0.05)
    stop_playback()

def play_video(filepath):
    """Play video with ffmpeg using -re for real‑time and -async 1 for sync."""
    global current_process
    stop_playback()

    cmd = [
        "ffmpeg",
        "-re",                     # Read input at native frame rate
        "-i", filepath,
        "-vf", "fps=15,scale=128:128",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "-vsync", "cfr",           # Constant frame rate output
        "-",
        "-map", "0:a",
        "-f", "alsa", AUDIO_DEV,
        "-ac", "2", "-ar", "48000",
        "-async", "1"              # Audio sync resampling
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    current_process = proc
    frame_size = 128 * 128 * 3

    # Show now‑playing screen
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((4, 2), "NOW PLAYING", font=FONT_BOLD, fill=(231, 76, 60))
    d.text((4, 20), f"🎬 {os.path.basename(filepath)[:18]}", font=FONT, fill=(171, 178, 185))
    d.text((4, 35), "Press KEY1 to stop", font=FONT, fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1)

    while True:
        btn = wait_btn_nonblock()
        if btn == "KEY1" or btn == "KEY3":
            stop_playback()
            break

        raw = proc.stdout.read(frame_size)
        if len(raw) < frame_size:
            break

        try:
            frame = Image.frombytes("RGB", (128, 128), raw)
            LCD.LCD_ShowImage(frame, 0, 0)
        except:
            pass

    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    cfg = load_config()
    path = cfg.get("last_dir", START_DIR)
    if not os.path.exists(path):
        path = START_DIR
    entries = list_media(path)
    cursor = 0
    scroll = 0
    show_message("Media Player Ready", f"Audio: {AUDIO_DEV}")
    while True:
        draw_browser(path, entries, cursor, scroll)
        btn = wait_btn_nonblock()
        if btn == "KEY3":
            break
        elif btn == "UP" and cursor > 0:
            cursor -= 1
            if cursor < scroll:
                scroll = cursor
        elif btn == "DOWN" and entries and cursor < len(entries)-1:
            cursor += 1
            if cursor >= scroll + 5:
                scroll = cursor - 4
        elif btn == "LEFT":
            parent = os.path.dirname(path)
            if parent != path:
                path = parent
                entries = list_media(path)
                cursor = 0
                scroll = 0
                cfg["last_dir"] = path
                save_config(cfg)
        elif btn == "OK" and entries:
            e = entries[cursor]
            if e.is_dir():
                path = e.path
                entries = list_media(path)
                cursor = 0
                scroll = 0
                cfg["last_dir"] = path
                save_config(cfg)
            else:
                filepath = e.path
                if filepath.lower().endswith(VIDEO_EXTS):
                    play_video(filepath)
                elif filepath.lower().endswith(AUDIO_EXTS):
                    play_audio(filepath)
                entries = list_media(path)
        elif btn == "KEY1":
            stop_playback()
        time.sleep(0.05)  # small delay to prevent CPU hogging in menu

    stop_playback()
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    if os.system("which ffmpeg >/dev/null 2>&1") != 0 or os.system("which aplay >/dev/null 2>&1") != 0:
        show_message("Missing ffmpeg or aplay", "sudo apt install ffmpeg alsa-utils")
        sys.exit(1)
    main()
