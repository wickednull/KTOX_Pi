#!/usr/bin/env python3
"""
KTOx *payload* – **System Log Viewer**
=========================================
This utility allows you to view various system logs directly on the KTOx's
LCD. It provides a convenient way to monitor system activity, debug issues,
and check for security-related events without needing external access.

Features:
- Discovers common system log files (e.g., syslog, auth.log).
- Interactive UI to select a log file to view.
- Displays the tail of the selected log file on the LCD.
- Allows scrolling through log entries.
- Automatically refreshes log content.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- LOG SELECTION SCREEN:
    - UP/DOWN: Navigate available log files.
    - OK: Select log file.
    - KEY3: Exit Payload.
- LOG VIEWING SCREEN:
    - UP/DOWN: Scroll through log entries.
    - OK: Refresh log content.
    - KEY3: Exit Payload.
"""
import sys
import os
import time
import signal
import subprocess
import threading
from collections import deque
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

# --- Constants and Globals ---
PINS: dict[str, int] = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
current_log_file = None
log_lines = deque(maxlen=1000) # Store up to 1000 lines for scrolling
display_offset = 0
ui_lock = threading.Lock()

# --- Signal Handling and Cleanup ---
def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# --- UI Drawing Functions ---
def draw_message(lines, color="yellow"):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2
        d.text((x, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def draw_log_selection_ui(log_files, current_selection):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((5, 5), "Select Log File", font=FONT_TITLE, fill=(171, 178, 185))
    d.line([(0, 22), (128, 22)], fill=(171, 178, 185), width=1)

    y_pos = 25
    for i, log_name in enumerate(log_files):
        color = "yellow" if i == current_selection else "white"
        d.text((5, y_pos), log_name, font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 115), "UP/DOWN=Select | OK=View | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

def draw_log_viewer_ui():
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    
    with ui_lock:
        if current_log_file:
            d.text((5, 5), f"Log: {os.path.basename(current_log_file)}", font=FONT_TITLE, fill=(30, 132, 73))
        else:
            d.text((5, 5), "Log Viewer", font=FONT_TITLE, fill=(30, 132, 73))
        d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

        visible_lines = [line for line in log_lines][display_offset:]
        y_pos = 25
        for line in visible_lines:
            d.text((5, y_pos), line[:COLS], font=FONT, fill=(242, 243, 244)) # Truncate long lines
            y_pos += 11
            if y_pos > HEIGHT - 15: # Stop if we run out of screen space
                break
    
    d.text((5, 115), "UP/DOWN=Scroll | OK=Refresh | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img, 0, 0)

# --- Log Management Functions ---
def get_common_log_files():
    logs = {
        "Syslog": "/var/log/syslog",
        "Auth Log": "/var/log/auth.log",
        "Kernel Log": "/var/log/kern.log",
        "Boot Log": "/var/log/boot.log",
        "Daemon Log": "/var/log/daemon.log",
        "Messages": "/var/log/messages",
        "Debug": "/var/log/debug",
    }
    
    found_logs = {}
    for name, path in logs.items():
        if os.path.exists(path) and os.access(path, os.R_OK):
            found_logs[name] = path
    
    # Add KTOx specific logs if they exist and are readable
    ktox_log_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')), 'KTOx', 'ktox.log')
    if os.path.exists(ktox_log_path) and os.access(ktox_log_path, os.R_OK):
        found_logs["KTOx Log"] = ktox_log_path

    return found_logs

def load_log_content(file_path):
    global log_lines, display_offset
    new_lines = deque(maxlen=1000)
    try:
        # Use 'tail -n' for efficiency and to get recent lines
        proc = subprocess.run(["tail", "-n", "1000", file_path], capture_output=True, text=True, check=True)
        for line in proc.stdout.splitlines():
            new_lines.append(line)
        with ui_lock:
            log_lines = new_lines
            display_offset = max(0, len(log_lines) - (HEIGHT // 11 - 3)) # Adjust offset to show latest lines
    except Exception as e:
        with ui_lock:
            log_lines = deque([f"Error reading log: {e}"])
            display_offset = 0

# --- Main Logic ---
if __name__ == "__main__":
    last_button_press_time = 0
    BUTTON_DEBOUNCE_TIME = 0.3 # seconds
    
    # Calculate character width and height for font
    _img = Image.new("RGB", (10, 10))
    _d = ImageDraw.Draw(_img)
    _bbox = _d.textbbox((0, 0), "M", font=FONT)
    CHAR_W, CHAR_H = _bbox[2] - _bbox[0], _bbox[3] - _bbox[1]
    COLS = WIDTH // CHAR_W

    try:
        # --- Log File Selection Screen ---
        available_logs = get_common_log_files()
        if not available_logs:
            draw_message(["No readable log", "files found!"], "red")
            time.sleep(3)
            raise SystemExit("No readable log files found.")
        
        log_names = list(available_logs.keys())
        selected_log_index = 0
        
        while running and not current_log_file:
            current_time = time.time()
            draw_log_selection_ui(log_names, selected_log_index)
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_log_index = (selected_log_index - 1 + len(log_names)) % len(log_names)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_log_index = (selected_log_index + 1) % len(log_names)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                current_log_file = available_logs[log_names[selected_log_index]]
                draw_message([f"Loading {log_names[selected_log_index]}..."], "yellow")
                load_log_content(current_log_file)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

        # --- Log Viewing Screen ---
        if current_log_file:
            while running:
                current_time = time.time()
                draw_log_viewer_ui()
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    with ui_lock:
                        display_offset = max(0, display_offset - 1)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    with ui_lock:
                        display_offset = min(len(log_lines) - 1, display_offset + 1)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    draw_message(["Refreshing log..."], "yellow")
                    load_log_content(current_log_file)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        draw_message([f"CRITICAL ERROR:", str(e)[:20]], "red")
        print(f"Critical error in Log Viewer: {e}", file=sys.stderr)
        time.sleep(5)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Log Viewer payload finished.")