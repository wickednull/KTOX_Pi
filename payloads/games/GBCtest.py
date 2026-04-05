#!/usr/bin/env python3
"""
KTOx GBC Emulator – Fully Playable
Using PyBoy headless with GPIO controls and 1.44" LCD display
"""

import os, time
from pyboy import PyBoy, WindowEvent
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO
import psutil

# ── CONFIG ───────────────────────────────────────────
LCD_WIDTH, LCD_HEIGHT = 128, 128
ROM_PATH = "roms/"
SAVE_PATH = "saves/"
FPS = 30

PINS = {
    "UP":6, "DOWN":19, "LEFT":5, "RIGHT":26,
    "A":13, "B":21, "START":20, "SELECT":16
}

HAS_HW = True

# ── LOAD ROMS ───────────────────────────────────────
roms = [f for f in os.listdir(ROM_PATH) if f.endswith(('.gbc','.gb'))]
if not roms:
    raise RuntimeError("No ROMs found in roms/")

current_rom_index = 0

# ── LCD INIT ───────────────────────────────────────
if HAS_HW:
    import LCD_1in44
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    lcd.LCD_Clear()
    screen_img = Image.new("RGB", (LCD_WIDTH, LCD_HEIGHT))
    draw = ImageDraw.Draw(screen_img)
    font = ImageFont.load_default()

# ── GPIO SETUP ─────────────────────────────────────
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ── HELPER FUNCTIONS ───────────────────────────────
def read_inputs(pyboy):
    """Map GPIO buttons to PyBoy inputs"""
    inputs = {btn: GPIO.input(pin) == 0 for btn, pin in PINS.items()}

    if inputs["UP"]:      pyboy.send_input(WindowEvent.UP, 1)
    if inputs["DOWN"]:    pyboy.send_input(WindowEvent.DOWN, 1)
    if inputs["LEFT"]:    pyboy.send_input(WindowEvent.LEFT, 1)
    if inputs["RIGHT"]:   pyboy.send_input(WindowEvent.RIGHT, 1)
    if inputs["A"]:       pyboy.send_input(WindowEvent.A, 1)
    if inputs["B"]:       pyboy.send_input(WindowEvent.B, 1)
    if inputs["START"]:   pyboy.send_input(WindowEvent.START, 1)
    if inputs["SELECT"]:  pyboy.send_input(WindowEvent.SELECT, 1)

    return inputs

def draw_frame(pyboy, rom_name):
    """Render PyBoy framebuffer to LCD with overlay"""
    pyboy.send_input(WindowEvent.TICK)
    img = pyboy.screen_image()

    # Resize to LCD
    scaled = img.resize((LCD_WIDTH, LCD_HEIGHT))

    # Draw to screen buffer
    draw.rectangle((0, 0, LCD_WIDTH, LCD_HEIGHT), fill=(0,0,0))
    draw.paste(scaled,(0,0))

    # Overlay stats
    cpu = psutil.cpu_percent()
    try:
        temp = float(open("/sys/class/thermal/thermal_zone0/temp").read())/1000.0
    except:
        temp = 0.0

    draw.text((2,2), f"{rom_name}", fill="#FF44FF", font=font)
    draw.text((2,LCD_HEIGHT-12), f"CPU:{cpu:.0f}% T:{temp:.1f}C", fill="#44FFFF", font=font)

    if HAS_HW:
        lcd.LCD_ShowImage(screen_img,0,0)

# ── MAIN LOOP ───────────────────────────────────────
try:
    while True:
        rom_file = os.path.join(ROM_PATH, roms[current_rom_index])

        # Initialize PyBoy headless
        pyboy = PyBoy(rom_file, window_type="headless", audio="silent")

        # Load save state if exists
        state_file = os.path.join(SAVE_PATH, roms[current_rom_index] + ".state")
        if os.path.exists(state_file):
            pyboy.load_state(state_file)

        while not pyboy.tick():
            inputs = read_inputs(pyboy)
            draw_frame(pyboy, roms[current_rom_index])
            time.sleep(1.0/FPS)

            # Save state: A + B
            if inputs["A"] and inputs["B"]:
                os.makedirs(SAVE_PATH, exist_ok=True)
                pyboy.save_state(state_file)

            # Next ROM: SELECT + START
            if inputs["SELECT"] and inputs["START"]:
                pyboy.stop()
                current_rom_index = (current_rom_index + 1) % len(roms)
                break

        pyboy.stop()

finally:
    if HAS_HW:
        lcd.LCD_Clear()
    GPIO.cleanup()
