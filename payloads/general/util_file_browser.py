#!/usr/bin/env python3
"""
KTOx *payload* – **File Browser**
====================================
This utility provides a simple file browser interface on the KTOx's LCD.
It allows you to navigate the filesystem, view file and directory properties,
and perform basic file operations like deleting or renaming.

Features:
- Navigate directories (go up, enter subdirectories).
- Lists files and directories, differentiating between them.
- Displays file properties (size, permissions, last modified).
- Allows scrolling through file/directory listings.
- Provides options to delete or rename files/directories (with confirmation).
- Displays status messages on the LCD.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - UP/DOWN: Scroll through items.
    - LEFT: Go to parent directory.
    - RIGHT: Enter selected directory.
    - OK: View properties of selected item / Perform action.
    - KEY1: Delete selected item.
    - KEY2: Rename selected item.
    - KEY3: Exit Payload.
- CONFIRMATION/INPUT SCREENS:
    - OK: Confirm action/input.
    - KEY3: Cancel action/input.
"""
import sys
import os
import time
import signal
import subprocess
import threading
from collections import deque
import stat # For file permissions
import shutil # For file operations

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
current_path = "/" # Start at root
file_list = []
display_offset = 0
selected_index = 0
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

def draw_file_browser_ui():
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    with ui_lock:
        d.text((5, 5), f"Path: {os.path.basename(current_path)[:10]}", font=FONT_TITLE, fill="#00FF00")
        d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

        visible_items = file_list[display_offset:]
        y_pos = 25
        for i, item in enumerate(visible_items):
            if y_pos > HEIGHT - 25: # Leave space for footer
                break
            
            color = "yellow" if i == selected_index - display_offset else "white"
            
            display_name = item['name']
            if item['is_dir']:
                display_name += "/"
            
            d.text((5, y_pos), display_name[:COLS], font=FONT, fill=color)
            y_pos += 11
    
    d.text((5, 115), "L/R=Nav | OK=Prop | K1=Del | K2=Ren | K3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_properties_ui(item_name, properties):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    d.text((5, 5), f"Properties: {item_name[:10]}", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    y_pos = 25
    for key, value in properties.items():
        d.text((5, y_pos), f"{key}: {value}", font=FONT, fill="white")
        y_pos += 11
        if y_pos > HEIGHT - 15:
            break
    
    d.text((5, 115), "OK=Back | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

# --- File System Functions ---
def list_directory(path):
    global file_list, selected_index, display_offset
    new_file_list = []
    try:
        # Add ".." for parent directory navigation
        if path != "/":
            new_file_list.append({'name': "..", 'is_dir': True, 'path': os.path.dirname(path)})

        for item_name in sorted(os.listdir(path), key=str.lower):
            item_path = os.path.join(path, item_name)
            if os.path.isdir(item_path):
                new_file_list.append({'name': item_name, 'is_dir': True, 'path': item_path})
            elif os.path.isfile(item_path):
                new_file_list.append({'name': item_name, 'is_dir': False, 'path': item_path})
        
        with ui_lock:
            file_list = new_file_list
            selected_index = 0
            display_offset = 0
    except PermissionError:
        draw_message(["Permission Denied!", f"Cannot access {os.path.basename(path)[:10]}"], "red")
        time.sleep(2)
        go_up_directory() # Try to go up if permission denied
    except Exception as e:
        draw_message([f"Error listing dir:", str(e)[:20]], "red")
        time.sleep(2)

def go_up_directory():
    global current_path
    if current_path != "/":
        current_path = os.path.dirname(current_path)
        list_directory(current_path)

def enter_directory(path):
    global current_path
    if os.path.isdir(path) and os.access(path, os.R_OK):
        current_path = path
        list_directory(current_path)
    else:
        draw_message(["Cannot enter dir:", f"{os.path.basename(path)[:10]}"], "red")
        time.sleep(2)

def get_file_properties(file_path):
    properties = {}
    try:
        stats = os.stat(file_path)
        properties["Size"] = f"{stats.st_size} bytes"
        properties["Modified"] = time.strftime('%Y-%m-%d %H:%M', time.localtime(stats.st_mtime))
        properties["Perms"] = stat.filemode(stats.st_mode)
        properties["Owner"] = str(stats.st_uid)
        properties["Group"] = str(stats.st_gid)
    except Exception as e:
        properties["Error"] = str(e)[:20]
    return properties

def delete_item(item_path, is_dir):
    try:
        if is_dir:
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)
        draw_message(["Deleted:", f"{os.path.basename(item_path)[:10]}"], "lime")
        list_directory(current_path) # Refresh list
    except PermissionError:
        draw_message(["Permission Denied!", "Cannot delete."], "red")
    except Exception as e:
        draw_message(["Delete Failed:", str(e)[:20]], "red")
    time.sleep(2)

def rename_item(old_path, new_name):
    try:
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        os.rename(old_path, new_path)
        draw_message(["Renamed to:", f"{new_name[:10]}"], "lime")
        list_directory(current_path) # Refresh list
    except PermissionError:
        draw_message(["Permission Denied!", "Cannot rename."], "red")
    except Exception as e:
        draw_message(["Rename Failed:", str(e)[:20]], "red")
    time.sleep(2)

def handle_text_input_logic(initial_text, prompt):
    # Simplified text input for rename
    # This is a basic implementation, full char set and cursor movement would be complex
    current_input = list(initial_text)
    cursor_pos = max(0, len(initial_text) - 1)
    char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+. "

    while running:
        img = Image.new("RGB", (WIDTH, HEIGHT), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), prompt, font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)

        display_text = list(current_input)
        if cursor_pos < len(display_text):
            display_text[cursor_pos] = '_'
        d.text((5, 40), "".join(display_text[:COLS]), font=FONT_TITLE, fill="yellow")
        d.text((5, 115), "UP/DOWN=Char | L/R=Move | OK=Save | K3=Cancel", font=FONT, fill="cyan")
        LCD.LCD_ShowImage(img, 0, 0)

        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.2 # seconds
        current_time = time.time()

        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                btn = name
                last_button_press_time = current_time
                break
        
        if btn == "KEY3":
            return None
        
        if btn == "OK":
            return "".join(current_input)
        
        if btn == "LEFT":
            cursor_pos = max(0, cursor_pos - 1)
        elif btn == "RIGHT":
            cursor_pos = min(len(current_input), cursor_pos + 1)
        elif btn == "UP" or btn == "DOWN":
            if cursor_pos < len(current_input):
                char = current_input[cursor_pos]
                char_index = char_set.index(char) if char in char_set else 0
                if btn == "UP":
                    char_index = (char_index + 1) % len(char_set)
                else:
                    char_index = (char_index - 1 + len(char_set)) % len(char_set)
                current_input[cursor_pos] = char_set[char_index]
            elif btn == "UP": # Add new char at end
                current_input.append(char_set[0])
                cursor_pos = len(current_input) - 1
        
        time.sleep(0.05)
    return None

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
        list_directory(current_path)
        
        while running:
            current_time = time.time()
            
            if not file_list:
                draw_message(["Empty Directory!", f"Path: {os.path.basename(current_path)[:10]}"], "yellow")
                time.sleep(1)
                list_directory(current_path) # Try refreshing
                continue

            # Ensure selection is within bounds
            if selected_index >= len(file_list):
                selected_index = max(0, len(file_list) - 1)
            
            draw_file_browser_ui()
            
            if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                cleanup()
                break
            
            if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_index = max(0, selected_index - 1)
                if selected_index < display_offset:
                    display_offset = selected_index
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                selected_index = min(len(file_list) - 1, selected_index + 1)
                if selected_index >= display_offset + LINES_PER_SCREEN:
                    display_offset = selected_index - LINES_PER_SCREEN + 1
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["LEFT"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                go_up_directory()
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["RIGHT"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if file_list and file_list[selected_index]['is_dir']:
                    enter_directory(file_list[selected_index]['path'])
                else:
                    draw_message(["Not a directory!"], "red")
                    time.sleep(1)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if file_list:
                    selected_item = file_list[selected_index]
                    if selected_item['is_dir'] and selected_item['name'] != "..":
                        enter_directory(selected_item['path'])
                    else:
                        properties = get_file_properties(selected_item['path'])
                        draw_properties_ui(selected_item['name'], properties)
                        
                        prop_view_start_time = time.time()
                        while running and (time.time() - prop_view_start_time < 5.0): # View properties for 5 seconds or until OK/KEY3
                            if GPIO.input(PINS["OK"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                                last_button_press_time = time.time()
                                break
                            if GPIO.input(PINS["KEY3"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                                last_button_press_time = time.time()
                                cleanup()
                                break
                            time.sleep(0.05)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if file_list and file_list[selected_index]['name'] != "..":
                    selected_item = file_list[selected_index]
                    draw_message([f"Delete {selected_item['name']}?", "OK=Yes | KEY3=No"], "red")
                    confirm_start_time = time.time()
                    confirmed = False
                    while running and (time.time() - confirm_start_time < 5.0):
                        if GPIO.input(PINS["OK"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = time.time()
                            delete_item(selected_item['path'], selected_item['is_dir'])
                            confirmed = True
                            break
                        if GPIO.input(PINS["KEY3"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = time.time()
                            draw_message(["Delete cancelled."], "yellow")
                            time.sleep(1)
                            break
                        time.sleep(0.05)
                    if not confirmed:
                        draw_message(["Delete timed out."], "yellow")
                        time.sleep(1)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["KEY2"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if file_list and file_list[selected_index]['name'] != "..":
                    selected_item = file_list[selected_index]
                    new_name = handle_text_input_logic(selected_item['name'], "Rename to:")
                    if new_name:
                        rename_item(selected_item['path'], new_name)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        draw_message([f"CRITICAL ERROR:", str(e)[:20]], "red")
        print(f"Critical error in File Browser: {e}", file=sys.stderr)
        time.sleep(5)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("File Browser payload finished.")