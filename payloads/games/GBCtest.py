#!/usr/bin/env python3
"""
KTOX GBC Injector - Stable & Safe Version
==========================================
Web ROM uploader + PyBoy gameplay on LCD
"""

import os
import sys
import time
import threading
from flask import Flask, render_template_string, request, redirect

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not available - web server only")

# Optional button helper
try:
    from payloads._input_helper import get_button
    HAS_BUTTON_HELPER = True
except ImportError:
    HAS_BUTTON_HELPER = False
    print("Warning: _input_helper not found - using direct GPIO")

# --- CONFIG ---
ROM_DIR = "/root/KTOx/roms"
os.makedirs(ROM_DIR, exist_ok=True)

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

# --- Flask Web Server ---
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' in request.files:
            f = request.files['file']
            if f and f.filename:
                try:
                    save_path = os.path.join(ROM_DIR, f.filename)
                    f.save(save_path)
                    return redirect('/')
                except Exception as e:
                    return f"<h1 style='color:red;'>Upload failed: {str(e)}</h1><p><a href='/'>Back</a></p>"
    try:
        roms = sorted(os.listdir(ROM_DIR))
    except Exception as e:
        roms = []
        print(f"ROM list error: {e}")

    return render_template_string('''
        <body style="background:#000; color:#0f0; font-family:monospace; text-align:center; padding:20px;">
            <h1 style="color:#f00;">KTOx // GBC_INJECTOR</h1>
            <form method="post" enctype="multipart/form-data">
                <input type="file" name="file" style="background:#111; color:#0f0; border:1px solid #0f0; padding:8px;">
                <button type="submit" style="background:#f00; color:white; border:none; padding:10px 20px; margin-left:10px;">INJECT ROM</button>
            </form>
            <hr style="border-color:#333;">
            <h3>ROM VAULT ({{ len(roms) }} files)</h3>
            <ul style="list-style:none; padding:0; text-align:left; max-width:400px; margin:0 auto;">
                {% for r in roms %}<li style="margin:4px 0;">{{ r }}</li>{% endfor %}
            </ul>
            <p style="margin-top:30px; color:#666;">Upload .gb or .gbc files • Access at PI_IP:5000</p>
        </body>
    ''', roms=roms)

def start_web():
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)  # debug=True shows real errors

# --- LCD & Game ---
def lcd_init():
    if not HAS_HW:
        return None
    try:
        lcd = LCD_1in44.LCD()
        lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        lcd.LCD_Clear()
        return lcd
    except Exception as e:
        print(f"LCD init failed: {e}")
        return None

def play_game(lcd, rom_path):
    if not lcd or not HAS_HW:
        print("No LCD - cannot play")
        return

    try:
        from pyboy import PyBoy, WindowEvent
        pyboy = PyBoy(rom_path, window_type="dummy")
        print(f"Loaded ROM: {rom_path}")

        while not pyboy.tick():
            # Direct GPIO for low-latency controls
            if GPIO.input(PINS["UP"]) == 0:
                pyboy.send_input(WindowEvent.PRESS_ARROW_UP)
            else:
                pyboy.send_input(WindowEvent.RELEASE_ARROW_UP)

            if GPIO.input(PINS["DOWN"]) == 0:
                pyboy.send_input(WindowEvent.PRESS_ARROW_DOWN)
            else:
                pyboy.send_input(WindowEvent.RELEASE_ARROW_DOWN)

            if GPIO.input(PINS["LEFT"]) == 0:
                pyboy.send_input(WindowEvent.PRESS_ARROW_LEFT)
            else:
                pyboy.send_input(WindowEvent.RELEASE_ARROW_LEFT)

            if GPIO.input(PINS["RIGHT"]) == 0:
                pyboy.send_input(WindowEvent.PRESS_ARROW_RIGHT)
            else:
                pyboy.send_input(WindowEvent.RELEASE_ARROW_RIGHT)

            if GPIO.input(PINS["OK"]) == 0:
                pyboy.send_input(WindowEvent.PRESS_BUTTON_A)
            else:
                pyboy.send_input(WindowEvent.RELEASE_BUTTON_A)

            if GPIO.input(PINS["KEY1"]) == 0:
                pyboy.send_input(WindowEvent.PRESS_BUTTON_B)
            else:
                pyboy.send_input(WindowEvent.RELEASE_BUTTON_B)

            if GPIO.input(PINS["KEY2"]) == 0:
                pyboy.send_input(WindowEvent.PRESS_BUTTON_START)
            else:
                pyboy.send_input(WindowEvent.RELEASE_BUTTON_START)

            if GPIO.input(PINS["KEY3"]) == 0:
                break  # Exit game back to menu

            # Render to LCD
            frame = pyboy.screen_image().resize((128, 128), resample=Image.NEAREST)
            lcd.LCD_ShowImage(frame, 0, 0)

        pyboy.stop()
        print("Game exited normally")
    except Exception as e:
        print(f"PyBoy error: {e}")

def rom_selector(lcd):
    cursor = 0
    while True:
        roms = sorted([f for f in os.listdir(ROM_DIR) if f.lower().endswith(('.gb', '.gbc'))])

        img = Image.new("RGB", (128, 128), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, 128, 14), fill="red")
        draw.text((5, 2), "DARKSEC GBC CORE", fill="white")

        if not roms:
            draw.text((10, 50), "NO ROMS - UPLOAD VIA WEB", fill="#00FF41")
            draw.text((10, 70), "http://PI_IP:5000", fill="white")
        else:
            for i, rom in enumerate(roms[:8]):
                prefix = "> " if i == cursor else "  "
                color = "#00FF41" if i == cursor else "#888888"
                draw.text((5, 20 + (i*12)), f"{prefix}{rom[:15]}", fill=color)

        if lcd:
            lcd.LCD_ShowImage(img, 0, 0)

        # Button polling with debounce
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                break

        if btn == "DOWN" and roms:
            cursor = (cursor + 1) % len(roms)
        elif btn == "UP" and roms:
            cursor = (cursor - 1) % len(roms)
        elif btn == "OK" and roms:
            return os.path.join(ROM_DIR, roms[cursor])
        elif btn == "KEY3":
            return None

        time.sleep(0.12)  # debounce

def main():
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    lcd = lcd_init()

    # Start Flask in background thread
    web_thread = threading.Thread(target=start_web, daemon=True)
    web_thread.start()
    print("Web server started on port 5000")

    while True:
        rom = rom_selector(lcd)
        if not rom:
            break
        play_game(lcd, rom)

    if lcd:
        lcd.LCD_Clear()
    GPIO.cleanup()
    print("KTOX GBC Injector exited.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        if HAS_HW:
            try:
                GPIO.cleanup()
            except:
                pass
