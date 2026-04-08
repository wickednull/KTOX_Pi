#!/usr/bin/env python3
"""
KTOx *payload* – **Process Manager**
=======================================
This utility provides a simple interface to view and manage running processes
on the KTOx's LCD. It's similar to a mini 'top' or 'htop', allowing you
to monitor system resource usage and terminate unresponsive applications.

Features:
- Lists running processes with PID, CPU%, MEM%, and command.
- Sorts processes by CPU or Memory usage.
- Allows scrolling through the process list.
- Provides an option to terminate (kill) selected processes.
- Displays status messages on the LCD.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - UP/DOWN: Scroll through processes.
    - LEFT/RIGHT: Change sort order (CPU/MEM).
    - OK: Select process for action (e.g., kill).
    - KEY3: Exit Payload.
- PROCESS ACTION SCREEN:
    - OK: Confirm kill.
    - KEY3: Cancel action.
"""
import sys
import os
import time
import signal
import subprocess
import threading
from collections import deque
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
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
processes = []
display_offset = 0
sort_by_cpu = True # True for CPU, False for Memory
ui_lock = threading.Lock()

# --- Signal Handling and Cleanup ---
def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# --- UI Drawing Functions ---
def draw_message(lines, color="yellow"):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2
        d.text((x, y), line, font=FONT_TITLE, fill=color)
        y += 15
    LCD.LCD_ShowImage(img, 0, 0)

def draw_process_list_ui(current_selection_index):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    with ui_lock:
        sort_label = "CPU" if sort_by_cpu else "MEM"
        d.text((5, 5), f"Processes (Sort: {sort_label})", font=FONT_TITLE, fill="#00FF00")
        d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

        visible_processes = processes[display_offset:]
        y_pos = 25
        for i, p in enumerate(visible_processes):
            if y_pos > HEIGHT - 25: # Leave space for footer
                break
            
            color = "yellow" if i == current_selection_index - display_offset else "white"
            
            # Format: PID %CPU %MEM Command
            # Max 16 chars for command to fit
            cmd_display = p['cmd'][:16] if p['cmd'] else "N/A"
            line = f"{p['pid']:<5} {p['cpu']:.1f}% {p['mem']:.1f}% {cmd_display}"
            d.text((5, y_pos), line, font=FONT, fill=color)
            y_pos += 11
    
    d.text((5, 115), "UP/DOWN=Scroll | L/R=Sort | OK=Action | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

# --- Process Management Functions ---
def get_processes():
    global processes
    new_processes = []
    try:
        # Using 'ps aux' and parsing for simplicity, psutil would be better if installed
        # PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
        proc = subprocess.run(["ps", "aux"], capture_output=True, text=True, check=True)
        lines = proc.stdout.splitlines()
        
        # Skip header
        for line in lines[1:]:
            parts = line.split(None, 10) # Split into max 11 parts
            if len(parts) >= 11:
                try:
                    pid = int(parts[1])
                    cpu = float(parts[2])
                    mem = float(parts[3])
                    cmd = parts[10]
                    new_processes.append({'pid': pid, 'cpu': cpu, 'mem': mem, 'cmd': cmd})
                except ValueError:
                    continue # Skip malformed lines
        
        # Sort
        if sort_by_cpu:
            new_processes.sort(key=lambda x: x['cpu'], reverse=True)
        else:
            new_processes.sort(key=lambda x: x['mem'], reverse=True)
            
        with ui_lock:
            processes = new_processes
            
    except Exception as e:
        draw_message([f"Error getting processes:", str(e)[:20]], "red")
        print(f"Error getting processes: {e}", file=sys.stderr)

def kill_process(pid):
    try:
        os.kill(pid, signal.SIGTERM) # Send SIGTERM first for graceful shutdown
        time.sleep(1)
        if subprocess.run(["pgrep", "-F", str(pid)], capture_output=True).returncode == 0:
            os.kill(pid, signal.SIGKILL) # If still running, force kill
        draw_message([f"Killed PID {pid}."], "lime")
    except ProcessLookupError:
        draw_message([f"PID {pid} not found."], "red")
    except Exception as e:
        draw_message([f"Failed to kill PID {pid}:", str(e)[:20]], "red")
        print(f"Failed to kill PID {pid}: {e}", file=sys.stderr)
    time.sleep(2)

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
    LINES_PER_SCREEN = HEIGHT // 11 - 3 # Approx lines that fit, minus header/footer

    try:
        current_selection_index = 0
        
        while running:
            current_time = time.time()
            get_processes() # Refresh process list
            
            if not processes:
                draw_message(["No processes found!"], "yellow")
                time.sleep(1)
                continue

            # Ensure selection is within bounds
            if current_selection_index >= len(processes):
                current_selection_index = max(0, len(processes) - 1)
            
            draw_process_list_ui(current_selection_index)
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                current_selection_index = max(0, current_selection_index - 1)
                if current_selection_index < display_offset:
                    display_offset = current_selection_index
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                current_selection_index = min(len(processes) - 1, current_selection_index + 1)
                if current_selection_index >= display_offset + LINES_PER_SCREEN:
                    display_offset = current_selection_index - LINES_PER_SCREEN + 1
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["LEFT"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                sort_by_cpu = True
                current_selection_index = 0 # Reset selection on sort change
                display_offset = 0
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["RIGHT"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                sort_by_cpu = False
                current_selection_index = 0 # Reset selection on sort change
                display_offset = 0
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if processes:
                    selected_process = processes[current_selection_index]
                    draw_message([f"Kill PID {selected_process['pid']}?", f"{selected_process['cmd'][:16]}", "OK=Yes | KEY3=No"], "red")
                    
                    action_confirmed = False
                    action_cancelled = False
                    action_start_time = time.time()
                    while running and (time.time() - action_start_time < 5.0): # 5 second timeout for confirmation
                        if GPIO.input(PINS["OK"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = time.time()
                            kill_process(selected_process['pid'])
                            action_confirmed = True
                            break
                        if GPIO.input(PINS["KEY3"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = time.time()
                            draw_message(["Kill cancelled."], "yellow")
                            time.sleep(1)
                            action_cancelled = True
                            break
                        time.sleep(0.05)
                    
                    if not action_confirmed and not action_cancelled:
                        draw_message(["Kill timed out."], "yellow")
                        time.sleep(1)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        draw_message([f"CRITICAL ERROR:", str(e)[:20]], "red")
        print(f"Critical error in Process Manager: {e}", file=sys.stderr)
        time.sleep(5)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Process Manager payload finished.")