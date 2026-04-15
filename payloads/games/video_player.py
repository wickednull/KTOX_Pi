#!/usr/bin/env python3
import os, sys, time, subprocess
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY3":16}
VIDEO_EXTS = ('.mp4','.avi','.mkv','.mov')
GPIO.setmode(GPIO.BCM)
for p in PINS.values(): GPIO.setup(p, GPIO.IN, GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W,H=128,128
try: f=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",9)
except: f=ImageFont.load_default()

def draw(lines):
    img=Image.new("RGB",(W,H),"black")
    d=ImageDraw.Draw(img)
    d.rectangle((0,0,W,17),fill="#8B0000")
    d.text((4,3),"VIDEO",font=f,fill="#FF3333")
    y=20
    for l in lines[:6]:
        d.text((4,y),l[:23],font=f,fill="#FFBBBB")
        y+=12
    d.rectangle((0,H-12,W,H),fill="#220000")
    d.text((4,H-10),"UP/DN OK LEFT KEY3",font=f,fill="#FF7777")
    LCD.LCD_ShowImage(img,0,0)

def wait():
    for _ in range(50):
        for n,p in PINS.items():
            if GPIO.input(p)==0:
                time.sleep(0.05)
                return n
        time.sleep(0.01)
    return None

def list_dir(p):
    try:
        items=[]
        for f in sorted(os.scandir(p),key=lambda x:(not x.is_dir(),x.name)):
            if f.is_dir() or f.name.lower().endswith(VIDEO_EXTS):
                items.append(f)
        return items
    except: return []

def play_video(path):
    # Your working Bluetooth sink name – verify with 'pactl list sinks'
    sink = "bluez_output.65_EA_C4_2F_05_0B.1"
    # Force A2DP profile
    card = subprocess.run("pactl list cards short | grep bluez | cut -f1", shell=True, capture_output=True, text=True).stdout.strip()
    if card:
        subprocess.run(f"pactl set-card-profile {card} a2dp-sink", shell=True)
        time.sleep(1)  # Give time to switch
    cmd = ["ffmpeg","-i",path,"-vf","scale=128:128,fps=10","-pix_fmt","rgb24","-f","rawvideo","-","-f","pulse","-device",sink]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame=128*128*3
    draw(["Playing...", os.path.basename(path)[:18]])
    while True:
        if wait()=="KEY3":
            proc.terminate()
            break
        raw=proc.stdout.read(frame)
        if len(raw)<frame: break
        img=Image.frombytes("RGB",(128,128),raw)
        LCD.LCD_ShowImage(img,0,0)
    proc.wait()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

path="/root/Videos"
entries=list_dir(path)
sel=0; scroll=0
while True:
    lines=[f"Dir: {os.path.basename(path)[:18]}",""]
    visible=entries[scroll:scroll+5]
    for i,e in enumerate(visible):
        idx=scroll+i
        m=">" if idx==sel else " "
        name=e.name[:18]+("/" if e.is_dir() else "")
        lines.append(f"{m} {name}")
    if not entries: lines.append("(empty)")
    draw(lines)
    btn=wait()
    if btn=="KEY3": break
    if btn=="UP" and sel>0: sel-=1; scroll=sel if sel<scroll else scroll
    if btn=="DOWN" and entries and sel<len(entries)-1: sel+=1; scroll=sel-4 if sel>=scroll+5 else scroll
    if btn=="LEFT":
        parent=os.path.dirname(path)
        if parent!=path: path=parent; entries=list_dir(path); sel=0; scroll=0
    if btn=="OK" and entries:
        e=entries[sel]
        if e.is_dir():
            path=e.path; entries=list_dir(path); sel=0; scroll=0
        else:
            play_video(e.path)
            entries=list_dir(path)
LCD.LCD_Clear()
GPIO.cleanup()
