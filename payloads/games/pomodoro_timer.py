#!/usr/bin/env python3
# Pomodoro Timer Payload for KTOx

# --- Section 1: Imports ---
import sys
import os
import time
import signal
from datetime import timedelta

# Add KTOx root to the Python path
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

# --- Section 2: Hardware Imports ---
# CRITICAL: LCD_Config MUST be imported before LCD_1in44
import LCD_Config
import LCD_1in44
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont

# --- Section 3: Global State & Configuration ---
# Pin definitions
PINS = {
    "KEY1": 21,  # Start/Pause
    "KEY2": 20,  # Reset
    "KEY3": 16,  # Exit
    "UP": 6,
    "DOWN": 19,
    "OK": 13,
}

# Timer states
STATE_WORK = "WORK"
STATE_BREAK = "BREAK"
STATE_PAUSED = "PAUSED"
STATE_IDLE = "IDLE"

# Timer durations (in seconds)
WORK_DURATION = 25 * 60
BREAK_DURATION = 5 * 60

# Global variables
RUNNING = True
current_state = STATE_IDLE
time_remaining = WORK_DURATION
timer_end_time = 0
last_press_time = 0
DEBOUNCE_DELAY = 0.3

# Font for display
try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    FONT_SMALL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
except IOError:
    FONT = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()

# --- Section 4: Cleanup Function ---
def cleanup(*_):
    """Safely cleans up GPIO resources."""
    global RUNNING
    if not RUNNING:
        return
    RUNNING = False
    print("Pomodoro Timer: Cleaning up GPIO...")
    GPIO.cleanup()
    print("Pomodoro Timer: Exiting.")

# --- Section 5: Drawing Functions ---
def draw_centered_text(draw, text, y, font, fill="WHITE"):
    """Draws horizontally centered text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (128 - text_width) // 2
    draw.text((x, y), text, font=font, fill=fill)

def display_timer(lcd, state, time_left):
    """Renders the timer display on the LCD."""
    image = Image.new("RGB", (128, 128), "BLACK")
    draw = ImageDraw.Draw(image)

    # Format time as MM:SS
    minutes, seconds = divmod(int(time_left), 60)
    time_str = f"{minutes:02d}:{seconds:02d}"

    # Set colors based on state
    bg_color = "BLACK"
    text_color = "WHITE"
    state_color = "YELLOW"
    if state == STATE_WORK:
        bg_color = "#8B0000" # Dark Red
        text_color = "WHITE"
    elif state == STATE_BREAK:
        bg_color = "#006400" # Dark Green
        text_color = "WHITE"
    elif state == STATE_PAUSED:
        state_color = "#ADD8E6" # Light Blue
    elif state == STATE_IDLE:
        state_color = "CYAN"


    draw.rectangle([(0,0), (128,128)], fill=bg_color)

    # Draw State
    draw_centered_text(draw, state, 20, FONT_SMALL, fill=state_color)

    # Draw Time
    draw_centered_text(draw, time_str, 50, FONT, fill=text_color)

    # Draw Instructions
    draw.text((2, 115), "S/P  Reset  Exit", font=FONT_SMALL, fill="WHITE")

    lcd.LCD_ShowImage(image, 0, 0)

# --- Section 6: Main Execution Block ---
if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # --- Hardware Initialization ---
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        LCD.LCD_Clear()

        # --- Main Loop ---
        while RUNNING:
            current_time = time.time()

            # --- Timer Logic ---
            if current_state in [STATE_WORK, STATE_BREAK] and current_time < timer_end_time:
                time_remaining = timer_end_time - current_time
            elif current_state == STATE_WORK and time_remaining <= 0:
                current_state = STATE_BREAK
                time_remaining = BREAK_DURATION
                timer_end_time = current_time + time_remaining
                # You could add a sound notification here if you have a buzzer
            elif current_state == STATE_BREAK and time_remaining <= 0:
                current_state = STATE_IDLE
                time_remaining = WORK_DURATION

            # --- Input Handling ---
            if (current_time - last_press_time) > DEBOUNCE_DELAY:
                # KEY3: Exit
                if GPIO.input(PINS["KEY3"]) == 0:
                    last_press_time = current_time
                    break

                # KEY1: Start / Pause
                if GPIO.input(PINS["KEY1"]) == 0:
                    last_press_time = current_time
                    if current_state == STATE_IDLE:
                        current_state = STATE_WORK
                        timer_end_time = current_time + time_remaining
                    elif current_state == STATE_PAUSED:
                        # Resume
                        if time_remaining > 0:
                           timer_end_time = current_time + time_remaining
                           # Infer previous state
                           if time_remaining > BREAK_DURATION:
                               current_state = STATE_WORK
                           else:
                               current_state = STATE_BREAK
                        else: # If paused at 00:00
                            current_state = STATE_IDLE
                            time_remaining = WORK_DURATION

                    elif current_state in [STATE_WORK, STATE_BREAK]:
                        # Pause
                        time_remaining = timer_end_time - current_time
                        current_state = STATE_PAUSED


                # KEY2: Reset
                if GPIO.input(PINS["KEY2"]) == 0:
                    last_press_time = current_time
                    current_state = STATE_IDLE
                    time_remaining = WORK_DURATION
                    timer_end_time = 0

            # --- Update Display ---
            display_timer(LCD, current_state, time_remaining)

            time.sleep(0.1) # Loop delay

    finally:
        # This block runs on exit, ensuring cleanup
        LCD.LCD_Clear()
        cleanup()
