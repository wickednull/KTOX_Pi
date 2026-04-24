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

HASH_FILE = "/dev/shm/ktox_hash.txt"
CRACKED_FILE = "/dev/shm/ktox_cracked.txt"
WORDLIST = "/usr/share/wordlists/rockyou.txt"
RULES = ["best64","Single","Toggle","ShiftToggle","AppendSpecial"]

#  Global state
cracking = False
cracked = []
current_hash = ""
hash_type = "raw-md5"
status = "Ready"
progress = ""
thread = None

def init_hw():
    global LCD, image, draw, font_sm, font_md
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values(): GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()
    image = Image.new("RGB", (W, H), (10, 0, 0))
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
    draw.text((4,3), "HYBRID CRACKER", font=font_sm, fill=(231, 76, 60))
    draw.text((4,20), f"Hash: {current_hash[:16]}" if current_hash else "No hash loaded", font=font_sm, fill=(171, 178, 185))
    draw.text((4,32), f"Type: {hash_type}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,44), f"Status: {status}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,56), f"Progress: {progress[:16]}", font=font_sm, fill=(171, 178, 185))
    y = 72
    for line in cracked[-4:]:
        draw.text((4,y), line[:20], font=font_sm, fill="#88FF88")
        y += 11
    draw.rectangle((0,H-12,W,H), fill="#220000")
    draw.text((4,H-11), "K1=Load  K2=Crack  K3=Exit", font=font_sm, fill="#FF7777")
    push()

def load_hash():
    global current_hash, hash_type, cracked, cracking, status
    draw.rectangle((0,0,W,H), fill=(10, 0, 0))
    draw.text((4,20), "Enter MD5/NTLM hash:", font=font_sm, fill=(242, 243, 244))
    draw.text((4,40), "Or paste from file", font=font_sm, fill=(242, 243, 244))
    push()
    time.sleep(2)
    #  On‑screen keyboard logic (omitted for brevity – use same as ReconDrone)
    #  For this demo we simulate loading
    current_hash = "5d41402abc4b2a76b9719d911017c592"  # "hello" MD5
    hash_type = "raw-md5"
    status = "Hash loaded"
    cracked = []
    cracking = False

def run_hybrid():
    global status, progress, cracked, cracking
    if not current_hash:
        status = "No hash loaded"
        return
    if not os.path.exists(WORDLIST):
        status = "Wordlist missing"
        return
    cracking = True
    status = "Cracking..."
    progress = "Starting"
    draw_ui()
    with open(HASH_FILE,"w") as f:
        f.write(current_hash)
    for rule in RULES:
        if not cracking: break
        progress = f"Rule: {rule}"
        draw_ui()
        cmd = f"john --format={hash_type} --wordlist={WORDLIST} --rules={rule} {HASH_FILE} --pot={CRACKED_FILE}"
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        #  Parse john.pot for cracked passwords
        if os.path.exists(CRACKED_FILE):
            with open(CRACKED_FILE) as f:
                for line in f:
                    if ":" in line:
                        pwd = line.split(":",1)[1].strip()
                        if pwd and pwd not in cracked:
                            cracked.append(pwd)
                            status = f"Cracked: {pwd}"
                            progress = "Done"
                            draw_ui()
                            cracking = False
                            return
    status = "Not cracked"
    progress = "Exhausted"
    cracking = False

def main():
    global cracking, thread
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
            thread = threading.Thread(target=run_hybrid, daemon=True)
            thread.start()
        draw_ui()
        time.sleep(0.05)
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
