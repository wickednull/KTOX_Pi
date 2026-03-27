#!/usr/bin/env python3
# KTOx Video Player Payload

import sys
import os
import time
import signal
import subprocess
import shutil

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

# --- Configuration ---
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "KEY_PRESS": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16
}
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov'}
START_PATH = "/media/" if os.path.isdir("/media/") else "/"

# --- Global State ---
RUNNING = True
LCD = None

# --- Helper Functions ---
def cleanup(*_):
    global RUNNING
    if not RUNNING: return
    RUNNING = False
    print("Video Player: Cleaning up GPIO...")
    if LCD: LCD.LCD_Clear()
    GPIO.cleanup()
    print("Video Player: Exiting.")
    sys.exit(0)

def check_dependencies():
    """Check if mplayer is installed."""
    return shutil.which("mplayer") is not None

def draw_message(draw, message, fill="WHITE"):
    """Draws a multi-line message centered on the screen."""
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    y = 10
    for line in message.split('\n'):
        bbox = draw.textbbox((0, 0), line)
        text_width = bbox[2] - bbox[0]
        draw.text(((128 - text_width) // 2, y), line, fill=fill)
        y += 15
    LCD.LCD_ShowImage(image, 0, 0)

def play_video(file_path):
    """Plays a video using mplayer, waits for KEY3 to stop."""
    draw_message(draw, f"Loading...\n{os.path.basename(file_path)}")
    
    command = [
        "mplayer",
        "-vo", "fbdev2:/dev/fb1",  # Output to framebuffer 1
        "-vf", "scale=128:128",   # Scale video to screen size
        "-framedrop",             # Drop frames to keep sync
        "-quiet",                 # Suppress console output
        file_path
    ]
    
    try:
        proc = subprocess.Popen(command)
        
        # Wait for stop signal
        while RUNNING:
            if GPIO.input(PINS["KEY3"]) == 0:
                proc.terminate() # Send SIGTERM to mplayer
                # Wait a moment for it to close
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill() # Force kill if it doesn't respond
                break
            
            # Check if process has ended on its own
            if proc.poll() is not None:
                break
                
            time.sleep(0.1)
            
    except Exception as e:
        draw_message(draw, f"Playback Error:\n{e}", fill="RED")
        time.sleep(3)

# --- Main Execution Block ---
if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        
        image = Image.new("RGB", (128, 128), "BLACK")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        # --- Dependency Check ---
        if not check_dependencies():
            draw_message(draw, "Error:\nmplayer not found.\n\nPlease install:\nsudo apt-get\ninstall mplayer", fill="RED")
            time.sleep(10)
            cleanup()

        # --- File Browser ---
        current_path = START_PATH
        selected_index = 0
        last_press_time = 0
        DEBOUNCE_DELAY = 0.25

        while RUNNING:
            # Get file/dir list
            try:
                all_files = sorted(os.listdir(current_path))
                # Separate dirs and files
                dirs = [d for d in all_files if os.path.isdir(os.path.join(current_path, d))]
                files = [f for f in all_files if not os.path.isdir(os.path.join(current_path, f))]
                display_list = ["[..]"] + dirs + files
            except OSError:
                current_path = os.path.dirname(current_path.rstrip('/'))
                continue

            # --- Input Handling ---
            now = time.time()
            if (now - last_press_time) > DEBOUNCE_DELAY:
                if GPIO.input(PINS["KEY3"]) == 0: break
                if GPIO.input(PINS["UP"]) == 0:
                    last_press_time = now
                    selected_index = (selected_index - 1) % len(display_list)
                if GPIO.input(PINS["DOWN"]) == 0:
                    last_press_time = now
                    selected_index = (selected_index + 1) % len(display_list)
                if GPIO.input(PINS["LEFT"]) == 0:
                    last_press_time = now
                    current_path = os.path.dirname(current_path.rstrip('/'))
                    selected_index = 0
                if GPIO.input(PINS["KEY_PRESS"]) == 0:
                    last_press_time = now
                    selection = display_list[selected_index]
                    new_path = os.path.join(current_path, selection)
                    
                    if selection == "[..]":
                        current_path = os.path.dirname(current_path.rstrip('/'))
                        selected_index = 0
                    elif os.path.isdir(new_path):
                        current_path = new_path
                        selected_index = 0
                    elif os.path.splitext(selection)[1].lower() in VIDEO_EXTENSIONS:
                        play_video(new_path)

            # --- Drawing ---
            draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
            
            # Display up to 8 items
            display_start = max(0, selected_index - 4)
            display_end = display_start + 8
            
            y = 5
            for i, item in enumerate(display_list[display_start:display_end]):
                idx = i + display_start
                
                prefix = ">" if idx == selected_index else " "
                
                # Add '/' for directories
                display_item = item
                if item != "[..]" and os.path.isdir(os.path.join(current_path, item)):
                    display_item += "/"
                
                # Truncate long names
                if len(display_item) > 18:
                    display_item = display_item[:17] + "…"

                draw.text((5, y), f"{prefix} {display_item}", fill="YELLOW" if idx == selected_index else "WHITE", font=font)
                y += 15

            LCD.LCD_ShowImage(image, 0, 0)
            time.sleep(0.05)

    finally:
        cleanup()
