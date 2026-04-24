#!/usr/bin/env python3
import os, time, subprocess, threading, socket, json, hashlib
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
WORKERS = [("192.168.1.101",5000), ("192.168.1.102",5000)]  #  IP:port of worker Pis
cracking = False
current_hash = ""
hash_type = "md5"
status = "Ready"
progress = ""
found_password = ""

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
    draw.text((4,3), "DISTRIBUTED CRACKER", font=font_sm, fill=(231, 76, 60))
    draw.text((4,20), f"Hash: {current_hash[:16]}" if current_hash else "No hash", font=font_sm, fill=(171, 178, 185))
    draw.text((4,32), f"Type: {hash_type}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,44), f"Status: {status}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,56), f"Workers: {len(WORKERS)}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,68), f"Found: {found_password[:16]}" if found_password else "Found: --", font=font_sm, fill=(171, 178, 185))
    draw.rectangle((0,H-12,W,H), fill="#220000")
    draw.text((4,H-11), "K1=Load  K2=Crack  K3=Exit", font=font_sm, fill="#FF7777")
    push()

def load_hash():
    global current_hash, hash_type, found_password, cracking
    #  On‑screen keyboard omitted
    current_hash = "5d41402abc4b2a76b9719d911017c592"
    hash_type = "md5"
    found_password = ""
    status = "Hash loaded"

def worker_task(worker_ip, worker_port, start_line, end_line, wordlist_path, target_hash):
    """Worker function – runs on remote Pi."""
    #  Read wordlist segment and test each password
    with open(wordlist_path, "r", errors="ignore") as f:
        for i, line in enumerate(f):
            if i < start_line: continue
            if i > end_line: break
            pwd = line.strip()
            if hashlib.md5(pwd.encode()).hexdigest() == target_hash:
                return pwd
    return None

def run_distributed():
    global status, progress, cracking, found_password
    if not current_hash:
        status = "No hash loaded"
        return
    if not os.path.exists(WORDLIST):
        status = "Wordlist missing"
        return
    cracking = True
    status = "Distributing..."
    progress = "Splitting wordlist"
    draw_ui()
    #  Count lines in wordlist
    total_lines = sum(1 for _ in open(WORDLIST, "rb"))
    lines_per_worker = total_lines // len(WORKERS)
    results = []
    threads = []
    for idx, (ip, port) in enumerate(WORKERS):
        start = idx * lines_per_worker
        end = start + lines_per_worker - 1 if idx < len(WORKERS)-1 else total_lines
        #  For simplicity we simulate remote execution via SSH
        cmd = f"python3 -c \"import hashlib; f=open('{WORDLIST}'); lines=f.readlines()[{start}:{end}]; target='{current_hash}'; [print(pwd.strip()) if hashlib.md5(pwd.strip().encode()).hexdigest()==target else None for pwd in lines]\""
        #  Run in thread and capture output
        def run_remote(cmd):
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if proc.stdout.strip():
                results.append(proc.stdout.strip())
        t = threading.Thread(target=run_remote, args=(cmd,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    if results:
        found_password = results[0]
        status = f"Cracked: {found_password}"
        progress = "Done"
    else:
        status = "Not found"
        progress = "Exhausted"
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
            threading.Thread(target=run_distributed, daemon=True).start()
        draw_ui()
        time.sleep(0.05)
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
