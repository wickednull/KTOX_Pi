#!/usr/bin/env python3
"""
KTOx Payload – Video Player (Waveshare LCD)
=============================================
Plays MP4/AVI/etc. directly on the 128x128 LCD using ffmpeg.
Audio plays through the system (headphone jack / HDMI).

Controls:
  UP/DOWN   – navigate file list
  LEFT      – parent directory
  OK        – play selected video
  KEY1      – stop playback (return to browser)
  KEY3      – exit payload

Dependencies: ffmpeg (sudo apt install ffmpeg)
"""

import os
import sys
import time
import subprocess
import threading
import queue
import select
from PIL import Image
from datetime import datetime

# ----------------------------------------------------------------------
# KTOx Hardware / LCD
# ----------------------------------------------------------------------
KTOX_ROOT = "/root/KTOx"
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not found")
    sys.exit(1)

PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26,
        "OK":13, "KEY1":21, "KEY2":20, "KEY3":16}

# Video extensions
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.m4v', '.flv'}

# Where to start browsing
START_DIRS = ["/media", "/home", "/root", "/tmp"]

# ----------------------------------------------------------------------
# LCD helpers
# ----------------------------------------------------------------------
LCD = None
image = None
draw = None
font_sm = None
font_md = None

def init_lcd():
    global LCD, image, draw, font_sm, font_md
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()
    image = Image.new("RGB", (128, 128), "black")
    draw = ImageDraw.Draw(image)

    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except:
        font_sm = font_md = ImageFont.load_default()

def draw_screen(lines, title="VIDEO PLAYER", title_color="#8B0000", text_color="#FFBBBB"):
    draw.rectangle((0,0,128,128), fill="#0A0000")
    draw.rectangle((0,0,128,17), fill=title_color)
    draw.text((4,3), title[:20], font=font_sm, fill="#FF3333")
    y = 20
    for line in lines[:7]:
        draw.text((4,y), line[:23], font=font_sm, fill=text_color)
        y += 12
    draw.rectangle((0,128-12,128,128), fill="#220000")
    draw.text((4,128-10), "UP/DN OK LEFT K3", font=font_sm, fill="#FF7777")
    LCD.LCD_ShowImage(image, 0, 0)

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
            elif f.name.lower().endswith(tuple(VIDEO_EXTS)):
                items.append(f)
        return items
    except:
        return []

def draw_browser(path, entries, sel):
    lines = []
    short = os.path.basename(path) or "/"
    lines.append(f"Dir: {short[:18]}")
    lines.append("")
    start = max(0, sel - 5)
    for i in range(start, min(start+6, len(entries))):
        e = entries[i]
        marker = ">" if i == sel else " "
        name = e.name[:18] + ("/" if e.is_dir() else "")
        lines.append(f"{marker} {name}")
    if not entries:
        lines.append("(empty)")
    draw_screen(lines, title="VIDEO PLAYER")

# ----------------------------------------------------------------------
# Video player using ffmpeg (frame extraction + LCD display)
# ----------------------------------------------------------------------
playing = False
stop_playback = threading.Event()

def play_video(video_path):
    global playing
    playing = True
    stop_playback.clear()

    # Show "loading"
    draw_screen(["Loading video...", os.path.basename(video_path)[:18]], title="PLAYING")
    time.sleep(0.5)

    # Build ffmpeg command: decode, scale to 128x128, output raw RGB24 frames
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", "scale=128:128,fps=10",   # limit to 10 fps for performance
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "-"
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as e:
        draw_screen([f"FFmpeg error", str(e)[:20]], title="ERROR")
        time.sleep(2)
        playing = False
        return

    # Frame size: 128*128*3 = 49152 bytes
    frame_size = 128 * 128 * 3

    # Show "Playing" screen (clear background)
    draw.rectangle((0,0,128,128), fill="black")
    draw.text((4, 60), "Playing...", font=font_sm, fill="#00FF00")
    LCD.LCD_ShowImage(image, 0, 0)

    while not stop_playback.is_set():
        raw_frame = proc.stdout.read(frame_size)
        if len(raw_frame) < frame_size:
            break   # end of video

        # Convert raw RGB bytes to PIL Image
        try:
            img = Image.frombytes("RGB", (128, 128), raw_frame)
            # Display on LCD
            LCD.LCD_ShowImage(img, 0, 0)
        except:
            pass

        # Check for stop button
        if wait_btn(0.01) in ("KEY1", "KEY3"):
            stop_playback.set()
            break

    proc.terminate()
    proc.wait()
    playing = False

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if not HAS_HW:
        print("No hardware")
        return
    init_lcd()

    # Check if ffmpeg is installed
    if not os.system("which ffmpeg > /dev/null 2>&1") == 0:
        draw_screen(["ffmpeg not installed", "sudo apt install ffmpeg", "KEY3 to exit"], title="ERROR")
        while wait_btn(0.5) != "KEY3":
            pass
        GPIO.cleanup()
        return

    # Find start directory
    start = "/"
    for d in START_DIRS:
        if os.path.isdir(d):
            start = d
            break

    path = start
    entries = list_media(path)
    sel = 0

    while True:
        draw_browser(path, entries, sel)
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "UP":
            sel = max(0, sel-1)
        elif btn == "DOWN":
            sel = min(len(entries)-1, sel+1) if entries else 0
        elif btn == "LEFT":
            parent = os.path.dirname(path)
            if parent and parent != path:
                path = parent
                entries = list_media(path)
                sel = 0
        elif btn == "OK" and entries:
            selected = entries[sel]
            if selected.is_dir():
                path = selected.path
                entries = list_media(path)
                sel = 0
            else:
                # Play video
                play_video(selected.path)
                # After playback, refresh the browser list (in case directory changed)
                entries = list_media(path)
        time.sleep(0.05)

    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
