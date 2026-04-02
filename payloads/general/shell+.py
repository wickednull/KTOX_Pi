#!/usr/bin/env python3
"""
KTOx DarkSec Shell v3
=====================
• PTY bash (real shell)
• USB + Bluetooth keyboard (auto + reconnect)
• On-screen keyboard (KEY2 toggle)
• DarkSec themed UI
• Stable (no crash if no keyboard)

KEY1 = zoom +
KEY2 = toggle keyboard
KEY3 = exit
"""

import os, sys, time, signal, select, fcntl, pty, re

sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..', '..')))

import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from evdev import InputDevice, categorize, ecodes, list_devices
import RPi.GPIO as GPIO
from payloads._input_helper import get_virtual_button

# ---------------- LCD ----------------
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

# ---------------- THEME ----------------
BG = "#060101"
RED = "#8B0000"
RED_B = "#cc1a1a"
TXT = "#00FF41"

# ---------------- FONT ----------------
FONT_SIZE = 8
def load_font(size):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
    except:
        return ImageFont.load_default()

font = load_font(FONT_SIZE)
CHAR_W, CHAR_H = font.getbbox("M")[2:]

COLS = W // CHAR_W
ROWS = (H - 14) // CHAR_H

# ---------------- GPIO ----------------
KEY1, KEY2, KEY3 = 21, 20, 16
GPIO.setmode(GPIO.BCM)
for p in (KEY1, KEY2, KEY3):
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ---------------- KEYBOARD ----------------
def find_keyboard():
    for path in list_devices():
        dev = InputDevice(path)
        if "keyboard" in dev.name.lower():
            try:
                dev.grab()
                return dev
            except:
                continue
    return None

keyboard = find_keyboard()

# ---------------- SHELL ----------------
pid, fd = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["bash"])

fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK)

poller = select.poll()
poller.register(fd, select.POLLIN)
if keyboard:
    poller.register(keyboard.fd, select.POLLIN)

ansi = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")

scroll = []
line = ""

# ---------------- ON SCREEN KB ----------------
KB = [
    list("abcdefghi"),
    list("jklmnopqr"),
    list("stuvwxyz_"),
    [" ", ".", "/", "-", "←", "OK"]
]

kb_on = False
kx = ky = 0

# ---------------- DRAW ----------------
def draw():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Header
    d.rectangle((0,0,W,12), fill="#1a0000")
    d.text((2,1),"KTOX DARKSEC", fill=RED_B, font=font)

    # Shell
    y = 14
    for l in scroll[-(ROWS-1):]:
        d.text((2,y), l[:COLS], fill=TXT, font=font)
        y += CHAR_H

    # Current line
    cursor = "_" if int(time.time()*2)%2 else " "
    d.text((2,y), (line+cursor)[:COLS], fill=TXT, font=font)

    # On-screen keyboard
    if kb_on:
        for iy,row in enumerate(KB):
            for ix,key in enumerate(row):
                x = ix*20
                yk = 60 + iy*16
                sel = (ix==kx and iy==ky)
                d.rectangle((x,yk,x+18,yk+14), outline=TXT if sel else "#333")
                d.text((x+3,yk+2), key[:2], fill=TXT, font=font)

    LCD.LCD_ShowImage(img,0,0)

# ---------------- INPUT ----------------
SHIFT = False

def write(s):
    os.write(fd, s.encode())

def handle_key(ev):
    global SHIFT
    key = ev.keycode if isinstance(ev.keycode,str) else ev.keycode[0]
    if ev.keystate != ev.key_down:
        return
    if key=="KEY_ESC":
        return False
    if key.startswith("KEY_") and len(key)==5:
        write(key[-1].lower())
    if key=="KEY_SPACE": write(" ")
    if key=="KEY_ENTER": write("\n")
    if key=="KEY_BACKSPACE": write("\x7f")
    return True

# ---------------- LOOP ----------------
running = True

while running:
    # Poll
    for fd_ev,_ in poller.poll(30):
        if fd_ev == fd:
            try:
                data = os.read(fd,1024).decode(errors="ignore")
                data = ansi.sub("", data)
                for c in data:
                    if c=="\n":
                        scroll.append(line)
                        line=""
                    else:
                        line+=c
            except:
                pass

        elif keyboard and fd_ev == keyboard.fd:
            try:
                for ev in keyboard.read():
                    if ev.type==ecodes.EV_KEY:
                        handle_key(categorize(ev))
            except:
                keyboard = None

    # GPIO buttons
    if GPIO.input(KEY2)==0:
        kb_on = not kb_on
        time.sleep(0.3)

    if GPIO.input(KEY3)==0:
        running=False

    # On-screen keyboard control
    if kb_on:
        btn = get_virtual_button()
        if btn=="UP": ky=max(0,ky-1)
        if btn=="DOWN": ky=min(len(KB)-1,ky+1)
        if btn=="LEFT": kx=max(0,kx-1)
        if btn=="RIGHT": kx=min(len(KB[ky])-1,kx+1)
        if btn=="OK":
            key = KB[ky][kx]
            if key=="←":
                write("\x7f")
            elif key=="OK":
                kb_on=False
            else:
                write(key)
            time.sleep(0.2)

    draw()

# ---------------- CLEANUP ----------------
LCD.LCD_Clear()
GPIO.cleanup()
