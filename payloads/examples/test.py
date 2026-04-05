#!/usr/bin/env python3
"""
KTOX Purple Ghost v1
===================
AUTO: simulated red/blue scenarios
MANUAL: hook into real tools (user-triggered)
"""

import time
import threading
import random

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except:
    HAS_HW = False

# ── CONFIG ─────────────────────────────
W, H = 128, 128
PINS = {"K1":21, "K2":20, "K3":16}

# ── GLOBALS ────────────────────────────
mode = "AUTO"   # AUTO / MANUAL
running = True

logs = []
alerts = []

ghost_frame = 0
ghost_state = "idle"

lock = threading.Lock()

# ── GHOST FRAMES ───────────────────────
GHOST = [
    [" ██ ", "████", "████", "██ ██"],
    [" ██ ", "████", "████", " ███ "]
]

# ── HW ─────────────────────────────────
LCD = None
_draw = None
_image = None
_font = None

def init_hw():
    global LCD, _draw, _image, _font
    if not HAS_HW:
        return

    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()

    _image = Image.new("RGB", (W,H), "black")
    _draw = ImageDraw.Draw(_image)

    try:
        _font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    except:
        _font = ImageFont.load_default()

def push():
    if LCD:
        LCD.LCD_ShowImage(_image, 0, 0)

# ── GHOST ──────────────────────────────
def draw_ghost(x,y):
    global ghost_frame
    frame = GHOST[ghost_frame]

    color = "#FF3333" if ghost_state == "attack" else "#00AAFF"

    for r,row in enumerate(frame):
        for c,ch in enumerate(row):
            if ch == "█":
                _draw.rectangle((x+c*3, y+r*3, x+c*3+3, y+r*3+3), fill=color)

# ── UI ─────────────────────────────────
def draw_ui():
    if not _draw:
        return

    global ghost_frame

    _draw.rectangle((0,0,W,H), fill="#000000")

    # Header
    _draw.rectangle((0,0,W,18), fill="#222222")
    _draw.text((4,3), f"KTOX [{mode}]", font=_font, fill="#FFFFFF")

    # Logs
    y = 25
    with lock:
        for line in logs[-5:]:
            _draw.text((4,y), line[:22], font=_font, fill="#AAAAAA")
            y += 12

    # Alerts
    if alerts:
        _draw.text((4,90), "ALERT!", font=_font, fill="#FF3333")

    draw_ghost(90, 70)
    ghost_frame = (ghost_frame + 1) % 2

    _draw.text((4,110), "K1 Mode | K2 Run | K3 Exit", font=_font, fill="#777777")

    push()

# ── AUTO MODE ──────────────────────────
def auto_engine():
    global ghost_state

    scenarios = [
        "user:password123",
        "admin:admin",
        "login attempt spike",
        "unknown device joined"
    ]

    while running:
        if mode != "AUTO":
            time.sleep(1)
            continue

        event = random.choice(scenarios)

        with lock:
            logs.append(event)

        # red behavior
        ghost_state = "attack"

        # blue detection
        if "password" in event or "admin" in event:
            alerts.append("Weak Credential Detected")

        time.sleep(2)
        ghost_state = "idle"

# ── MANUAL MODE ────────────────────────
def manual_action():
    global ghost_state

    with lock:
        logs.append("Manual scan started")

    ghost_state = "attack"

    # Placeholder for real tool integration
    time.sleep(2)

    with lock:
        logs.append("Scan complete")

    ghost_state = "idle"

# ── MAIN ──────────────────────────────
def main():
    global running, mode

    init_hw()
    threading.Thread(target=auto_engine, daemon=True).start()

    held = {}

    while running:
        if HAS_HW:
            pressed = {k: GPIO.input(v) == 0 for k,v in PINS.items()}
        else:
            pressed = {}

        now = time.time()

        for k,d in pressed.items():
            if d and k not in held:
                held[k] = now
            elif not d:
                held.pop(k, None)

        def just_pressed(k):
            return pressed.get(k) and (now - held.get(k,0)) < 0.2

        if just_pressed("K3"):
            break

        if just_pressed("K1"):
            mode = "MANUAL" if mode == "AUTO" else "AUTO"
            time.sleep(0.3)

        if just_pressed("K2") and mode == "MANUAL":
            threading.Thread(target=manual_action, daemon=True).start()

        draw_ui()
        time.sleep(0.2)

    running = False

    if HAS_HW:
        LCD.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
