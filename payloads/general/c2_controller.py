#!/usr/bin/env python3
import sys
import os
import time
import signal
import subprocess

# --- Setup Paths & Imports ---
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import LCD_1in44
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("This payload must be run on the KTOx hardware.")
    sys.exit(0)

# --- CONFIGURATION ---
PINS = {"UP": 6, "DOWN": 19, "KEY_PRESS": 13, "KEY3": 16}
DEBOUNCE_DELAY = 0.25
CLIENT_SCRIPT_PATH = "c2_client/client.py"
CLIENT_PROCESS_NAME = f"python3 {CLIENT_SCRIPT_PATH}"
RUNNING = True # Global flag to control the main loop

# --- CLEANUP ---
def cleanup(*_):
    global RUNNING
    if not RUNNING: return
    RUNNING = False
    GPIO.cleanup()
    sys.exit(0)

# --- CORE LOGIC ---
def get_client_status():
    try:
        subprocess.check_output(["pgrep", "-f", CLIENT_PROCESS_NAME])
        return "Running"
    except subprocess.CalledProcessError:
        return "Stopped"

def start_client():
    if get_client_status() == "Running": return
    command = f"nohup python3 {CLIENT_SCRIPT_PATH} > /tmp/c2_client.log 2>&1 &"
    subprocess.Popen(command, shell=True, cwd=KTOX_ROOT)

def stop_client():
    if get_client_status() == "Stopped": return
    subprocess.run(["pkill", "-f", CLIENT_PROCESS_NAME])

# --- DRAWING ---
def draw_display(draw, menu_items, selected_index, status):
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    font = ImageFont.load_default()
    
    def draw_centered(text, y, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (128 - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), text, font=font, fill=fill)

    draw_centered("C2 Controller", 5, "CYAN")
    status_color = "LIME" if status == "Running" else "RED"
    draw_centered(f"Status: {status}", 25, status_color)

    y = 50
    for i, item in enumerate(menu_items):
        fill = "WHITE"
        if i == selected_index:
            draw.rectangle([(0, y - 2), (128, y + 12)], fill="BLUE")
            fill = "YELLOW"
        draw_centered(item, y, fill)
        y += 20
    
    draw_centered("KEY3 to Exit", 115, "WHITE")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # --- Hardware Init ---
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()
        
        image = Image.new("RGB", (128, 128), "BLACK")
        draw = ImageDraw.Draw(image)
        
        # --- State Variables ---
        menu_items = ["Start Client", "Stop Client", "Refresh Status"]
        selected_index = 0
        last_press_time = 0
        
        while RUNNING:
            current_time = time.time()
            
            # --- Input Handling ---
            if (current_time - last_press_time) > DEBOUNCE_DELAY:
                if GPIO.input(PINS["KEY3"]) == 0:
                    RUNNING = False
                    continue
                elif GPIO.input(PINS["UP"]) == 0:
                    last_press_time = current_time
                    selected_index = (selected_index - 1) % len(menu_items)
                elif GPIO.input(PINS["DOWN"]) == 0:
                    last_press_time = current_time
                    selected_index = (selected_index + 1) % len(menu_items)
                elif GPIO.input(PINS["KEY_PRESS"]) == 0:
                    last_press_time = current_time
                    action = menu_items[selected_index]
                    if action == "Start Client":
                        start_client()
                    elif action == "Stop Client":
                        stop_client()
            
            # --- Drawing ---
            client_status = get_client_status()
            draw_display(draw, menu_items, selected_index, client_status)
            LCD.LCD_ShowImage(image, 0, 0)
            
            time.sleep(0.1)

    finally:
        LCD.LCD_Clear()
        cleanup()
