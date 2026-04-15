#!/usr/bin/env python3
"""
KTOx Payload – Video Player
=========================================
- Full file browser with scroll and selection highlight
- Video playback on 128x128 LCD with Bluetooth audio
- Clean exit – no freezing

Controls:
  UP / DOWN   – navigate files
  LEFT        – parent directory
  OK          – play selected video
  KEY3        – exit
"""

import os
import sys
import time
import subprocess
from datetime import datetime

# ----------------------------------------------------------------------
# Hardware
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not found")
    sys.exit(1)

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16
}
VIDEO_EXTS = ('.mp4', '.avi', '.mkv', '.mov', '.webm', '.m4v')
START_DIR = "/root"

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

try:
    font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
except:
    font_sm = ImageFont.load_default()
    font_bold = font_sm

# ----------------------------------------------------------------------
# LCD drawing helpers
# ----------------------------------------------------------------------
def draw_screen(lines, title="VIDEO PLAYER", title_color="#8B0000"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=title_color)
    d.text((4, 3), title[:20], font=font_bold, fill="#FF3333")
    y = 20
    for line in lines[:6]:
        d.text((4, y), line[:23], font=font_sm, fill="#FFBBBB")
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DOWN  OK  LEFT  K3=exit", font=font_sm, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

# ----------------------------------------------------------------------
# File browser
# ----------------------------------------------------------------------
def list_media(path):
    try:
        items = []
        for f in sorted(os.scandir(path), key=lambda x: (not x.is_dir(), x.name.lower())):
            if f.is_dir():
                items.append(f)
            elif f.name.lower().endswith(VIDEO_EXTS):
                items.append(f)
        return items
    except PermissionError:
        return []

def draw_browser(path, entries, sel, scroll):
    # Build visible lines
    lines = []
    short = os.path.basename(path) or "/"
    lines.append(f"[ {short[:18]} ]")
    lines.append("")
    # Show 5 entries at a time
    visible = entries[scroll:scroll+5]
    for i, e in enumerate(visible):
        idx = scroll + i
        prefix = "> " if idx == sel else "  "
        name = e.name[:18] + ("/" if e.is_dir() else "")
        lines.append(f"{prefix}{name}")
    if not entries:
        lines.append("(empty)")
    draw_screen(lines, title="FILE BROWSER", title_color="#004466")

def main():
    path = START_DIR
    entries = list_media(path)
    sel = 0
    scroll = 0
    running = True

    while running:
        draw_browser(path, entries, sel, scroll)
        btn = wait_btn(0.2)
        if btn == "KEY3":
            running = False
        elif btn == "UP":
            if sel > 0:
                sel -= 1
                if sel < scroll:
                    scroll = sel
        elif btn == "DOWN":
            if entries and sel < len(entries)-1:
                sel += 1
                if sel >= scroll + 5:
                    scroll = sel - 4
        elif btn == "LEFT":
            parent = os.path.dirname(path)
            if parent != path:
                path = parent
                entries = list_media(path)
                sel = 0
                scroll = 0
        elif btn == "OK" and entries:
            selected = entries[sel]
            if selected.is_dir():
                path = selected.path
                entries = list_media(path)
                sel = 0
                scroll = 0
            else:
                # Play video
                video_path = selected.path
                # Show loading message
                draw_screen(["Loading video...", selected.name[:18]], title="PLAYING")
                time.sleep(0.5)
                # ffmpeg command: video to LCD, audio to default sink (PipeWire/PulseAudio)
                cmd = [
                    "ffmpeg", "-i", video_path,
                    "-vf", "scale=128:128,fps=10",
                    "-pix_fmt", "rgb24",
                    "-f", "rawvideo",
                    "-",
                    "-f", "pulse", "-device", "default"
                ]
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                frame_size = 128 * 128 * 3
                # Playback loop
                while True:
                    # Check for exit button
                    if wait_btn(0.01) in ("KEY1", "KEY3"):
                        proc.terminate()
                        break
                    raw = proc.stdout.read(frame_size)
                    if len(raw) < frame_size:
                        break
                    try:
                        img = Image.frombytes("RGB", (128, 128), raw)
                        LCD.LCD_ShowImage(img, 0, 0)
                    except:
                        pass
                proc.wait()
                # Reinit LCD after playback
                LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
                # Refresh file list (in case directory changed)
                entries = list_media(path)

    GPIO.cleanup()
    LCD.LCD_Clear()
    sys.exit(0)

if __name__ == "__main__":
    main()
