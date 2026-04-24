#!/usr/bin/env python3
import os, subprocess, threading
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont
from file_browser import browse_file

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
W,H = 128,128
LCD = None
image = draw = None
font_sm = font_md = None

selected_file = ""
cracking = False
result = ""
status = "Ready"
hash_format = "auto"  # will be detected
wordlist = "/usr/share/wordlists/rockyou.txt"

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
    draw.text((4,3), "GENERIC HASH CRACKER", font=font_sm, fill=(231, 76, 60))
    draw.text((4,20), f"File: {os.path.basename(selected_file) if selected_file else 'None'}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,32), f"Format: {hash_format}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,44), f"Status: {status}", font=font_sm, fill=(171, 178, 185))
    draw.text((4,56), f"Result: {result[:20]}", font=font_sm, fill="#88FF88" if result else "#FFBBBB")
    draw.rectangle((0,H-12,W,H), fill="#220000")
    draw.text((4,H-11), "K1=Select  K2=Crack  K3=Exit", font=font_sm, fill="#FF7777")
    push()

def detect_hash_type(filepath):
    """Use hashid or john to guess format."""
    try:
        # Read first line
        with open(filepath, 'r') as f:
            first_line = f.readline().strip()
        # Use hashid
        proc = subprocess.run(["hashid", first_line], capture_output=True, text=True)
        output = proc.stdout
        if "MD5" in output:
            return "raw-md5"
        elif "NTLM" in output:
            return "nt"
        elif "SHA1" in output:
            return "raw-sha1"
        elif "SHA256" in output:
            return "raw-sha256"
    except:
        pass
    return "auto"

def select_file():
    global selected_file, result, status, hash_format
    f = browse_file("/home/kali", [".txt", ".hash", ".john", ""], prompt="Select hash file")
    if f:
        selected_file = f
        result = ""
        status = "Detecting format..."
        draw_ui()
        hash_format = detect_hash_type(selected_file)
        status = f"Format: {hash_format}"

def run_crack():
    global cracking, status, result, hash_format
    if not selected_file or not os.path.exists(selected_file):
        status = "No file selected"
        return
    if not os.path.exists(wordlist):
        status = "Wordlist missing"
        return
    cracking = True
    status = "Cracking..."
    draw_ui()
    # Use john with potfile
    potfile = "/dev/shm/ktox_john.pot"
    cmd = ["john", f"--format={hash_format}" if hash_format != "auto" else "",
           f"--wordlist={wordlist}", selected_file, f"--pot={potfile}"]
    cmd = [c for c in cmd if c]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # Check potfile for results
    if os.path.exists(potfile):
        with open(potfile, 'r') as f:
            lines = f.readlines()
            if lines:
                # Extract password (after colon)
                result = lines[0].split(":",1)[1].strip()
                status = "Cracked!"
                cracking = False
                draw_ui()
                return
    result = "Not cracked"
    status = "Failed"
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
        if just_pressed("KEY1") and not cracking:
            select_file()
            draw_ui()
        if just_pressed("KEY2") and not cracking:
            threading.Thread(target=run_crack, daemon=True).start()
        draw_ui()
        time.sleep(0.05)
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
