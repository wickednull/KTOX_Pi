#!/usr/bin/env python3
import os, time, subprocess, threading
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
W,H = 128,128
LCD = None
image = draw = None
font_sm = font_md = None

RAINBOW_TABLE_DIR = "/root/rainbow_tables/md5/"  #  Pre‑generated tables
HASH_FILE = "/dev/shm/ktox_hash.txt"
cracking = False
current_hash = ""
hash_type = "md5"
status = "Ready"
progress = ""

def init_hw():
    global LCD, image, draw, font_sm, font_md
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values(): GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()
    image = Image.new("RGB", (W, H), "black")
    draw = ImageDraw.Draw(image)
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",9)
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",11)
    except:
        font_sm = font_md = ImageFont.load_default()

def push(): LCD.LCD_ShowImage(image,0,0) if LCD and image else None

def draw_ui():
    draw.rectangle((0,0,W,H), fill="#0A0000")
    draw.rectangle((0,0,W,17), fill="#8B0000")
    draw.text((4,3), "RAINBOW CRACKER", font=font_sm, fill="#FF3333")
    draw.text((4,20), f"Hash: {current_hash[:16]}" if current_hash else "No hash", font=font_sm, fill="#FFBBBB")
    draw.text((4,32), f"Type: {hash_type}", font=font_sm, fill="#FFBBBB")
    draw.text((4,44), f"Status: {status}", font=font_sm, fill="#FFBBBB")
    draw.text((4,56), f"Table: {os.path.basename(RAINBOW_TABLE_DIR)}", font=font_sm, fill="#FFBBBB")
    draw.text((4,68), f"Progress: {progress[:16]}", font=font_sm, fill="#FFBBBB")
    draw.rectangle((0,H-12,W,H), fill="#220000")
    draw.text((4,H-11), "K1=Load  K2=Crack  K3=Exit", font=font_sm, fill="#FF7777")
    push()

def load_hash():
    global current_hash, hash_type, status
    #  On‑screen keyboard omitted – same as ReconDrone
    current_hash = "5d41402abc4b2a76b9719d911017c592"
    hash_type = "md5"
    status = "Hash loaded"

def run_rainbow():
    global status, progress, cracking
    if not current_hash:
        status = "No hash loaded"
        return
    if not os.path.isdir(RAINBOW_TABLE_DIR):
        status = "Table missing"
        return
    cracking = True
    status = "Looking up..."
    progress = "Searching"
    draw_ui()
    with open(HASH_FILE,"w") as f:
        f.write(current_hash)
    #  Use rcracki_mt with 2 threads (Pi Zero 2 W)
    cmd = f"rcracki_mt -h {current_hash} -t 2 {RAINBOW_TABLE_DIR}"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    #  Parse output for plaintext
    for line in output.splitlines():
        if "plaintext:" in line.lower():
            plain = line.split(":",1)[1].strip()
            status = f"Found: {plain}"
            progress = "Done"
            cracking = False
            draw_ui()
            return
    status = "Not found"
    progress = "Failed"
    cracking = False

def main():
    global cracking
    init_hw()
    draw_ui()
    held = {}
    while True:
        now = time.time()
        pressed = {n: GPIO.input(p)==0 for n,p in PINS.items()}
        for n,down in pressed.items():
            if down and n not in held: held[n] = now
            elif not down: held.pop(n, None)
        def just_pressed(n, d=0.2): return pressed.get(n) and (now-held.get(n,0)) < d
        if just_pressed("KEY3"): break
        if just_pressed("KEY1"):
            if cracking: continue
            load_hash()
            draw_ui()
        if just_pressed("KEY2"):
            if cracking: continue
            threading.Thread(target=run_rainbow, daemon=True).start()
        draw_ui()
        time.sleep(0.05)
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
