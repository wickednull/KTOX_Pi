#!/usr/bin/env python3
# KTOx Clock Payload

import sys
import os
import time
import signal
import math
from datetime import datetime

# Add KTOx root to the Python path
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import LCD_Config
    import LCD_1in44
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Required libraries not found. Please run install_ktox.sh")
    sys.exit(1)

# --- Pin Definitions ---
PINS = {
    "KEY_UP": 6, "KEY_DOWN": 19, "KEY_LEFT": 5, "KEY_RIGHT": 26,
    "KEY_PRESS": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16
}

# --- Global State ---
RUNNING = True
MODE = "digital"  # "digital", "analog", "binary"

# --- Cleanup Function ---
def cleanup(*_):
    global RUNNING
    if not RUNNING: return
    RUNNING = False
    print("Clock: Cleaning up GPIO...")
    GPIO.cleanup()
    print("Clock: Exiting.")
    sys.exit(0)

# --- Main Drawing Functions ---
def draw_digital_clock(draw, font):
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    time_bbox = draw.textbbox((0, 0), time_str, font=font)
    time_width = time_bbox[2] - time_bbox[0]
    time_height = time_bbox[3] - time_bbox[1]
    draw.text(((128 - time_width) // 2, (128 - time_height) // 2 - 10), time_str, font=font, fill="LIME")
    date_bbox = draw.textbbox((0, 0), date_str, font=font)
    date_width = date_bbox[2] - date_bbox[0]
    draw.text(((128 - date_width) // 2, (128 // 2) + 10), date_str, font=font, fill="CYAN")

def draw_analog_clock(draw):
    now = datetime.now()
    center_x, center_y = 64, 64
    radius = 60
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    draw.ellipse([(center_x - radius, center_y - radius), (center_x + radius, center_y + radius)], outline="WHITE", width=2)
    for i in range(12):
        angle = math.radians(i * 30 - 90)
        x1 = center_x + int(radius * 0.9 * math.cos(angle))
        y1 = center_y + int(radius * 0.9 * math.sin(angle))
        x2 = center_x + int(radius * math.cos(angle))
        y2 = center_y + int(radius * math.sin(angle))
        draw.line([(x1, y1), (x2, y2)], fill="WHITE", width=2)
    hour_angle = math.radians((now.hour % 12 + now.minute / 60) * 30 - 90)
    hx = center_x + int(radius * 0.5 * math.cos(hour_angle))
    hy = center_y + int(radius * 0.5 * math.sin(hour_angle))
    draw.line([(center_x, center_y), (hx, hy)], fill="RED", width=4)
    minute_angle = math.radians((now.minute + now.second / 60) * 6 - 90)
    mx = center_x + int(radius * 0.8 * math.cos(minute_angle))
    my = center_y + int(radius * 0.8 * math.sin(minute_angle))
    draw.line([(center_x, center_y), (mx, my)], fill="CYAN", width=3)
    second_angle = math.radians(now.second * 6 - 90)
    sx = center_x + int(radius * 0.9 * math.cos(second_angle))
    sy = center_y + int(radius * 0.9 * math.sin(second_angle))
    draw.line([(center_x, center_y), (sx, sy)], fill="YELLOW", width=1)

def draw_binary_clock(draw, font_small):
    now = datetime.now()
    h, m, s = now.hour, now.minute, now.second
    
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    
    col_h = 30
    col_m = 64
    col_s = 98
    
    draw.text((col_h - 5, 10), "H", font=font_small, fill="RED")
    draw.text((col_m - 5, 10), "M", font=font_small, fill="LIME")
    draw.text((col_s - 5, 10), "S", font=font_small, fill="CYAN")

    def draw_col(x, value, color):
        y_start = 30
        dot_size = 12
        spacing = 15
        
        for i in range(6):
            power_of_2 = 2**(5-i)
            is_set = (value & power_of_2) != 0
            
            fill_color = color if is_set else "GRAY"
            outline_color = "WHITE" if is_set else "DARKGRAY"
            
            y = y_start + i * spacing
            draw.ellipse([(x - dot_size//2, y - dot_size//2), (x + dot_size//2, y + dot_size//2)], fill=fill_color, outline=outline_color)

    draw_col(col_h, h, "RED")
    draw_col(col_m, m, "LIME")
    draw_col(col_s, s, "CYAN")

# --- Main Execution Block ---
if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    last_press_time = 0
    DEBOUNCE_DELAY = 0.2

    try:
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        image = Image.new("RGB", (128, 128), "BLACK")
        draw = ImageDraw.Draw(image)
        
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except IOError:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

        while RUNNING:
            current_time = time.time()

            if (current_time - last_press_time) > DEBOUNCE_DELAY:
                if GPIO.input(PINS["KEY3"]) == 0:
                    break
                elif GPIO.input(PINS["KEY_PRESS"]) == 0:
                    last_press_time = current_time
                    MODE = "digital"
                elif GPIO.input(PINS["KEY1"]) == 0:
                    last_press_time = current_time
                    MODE = "binary"
                elif GPIO.input(PINS["KEY2"]) == 0:
                    last_press_time = current_time
                    MODE = "analog"

            if MODE == "digital":
                draw_digital_clock(draw, font)
            elif MODE == "analog":
                draw_analog_clock(draw)
            elif MODE == "binary":
                draw_binary_clock(draw, font_small)

            LCD.LCD_ShowImage(image, 0, 0)
            time.sleep(0.1)

    finally:
        LCD.LCD_Clear()
        cleanup()
