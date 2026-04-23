#!/usr/bin/env python3
"""
KTOx *payload* – **Unified Loot Viewer**
===========================================
This payload provides a consolidated view of various "loot" collected by other
KTOx payloads. It gathers credentials, logs, and scan results from
designated directories and displays them on the LCD, allowing the user
to browse collected information.

Features:
- Collects data from Responder, DNSSpoof, EvilTwin (ip.txt), and Nmap logs.
- Displays collected loot items on the LCD with scrolling capabilities.
- Allows dynamically adding new loot source directories.
- Parses specific log formats (e.g., Responder NTLMv2, phishing credentials).
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Refresh collected loot.
    - UP/DOWN: Scroll through loot items.
    - KEY1: Add a new loot source directory.
    - KEY3: Exit Payload.
- ADD SOURCE NAME INPUT:
    - UP/DOWN: Cycle characters.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm name.
    - KEY3: Cancel input.
- ADD SOURCE PATH INPUT:
    - UP/DOWN: Cycle characters.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm path.
    - KEY3: Cancel input.
"""
import sys
import os
import time
import signal
import re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import RPi.GPIO as GPIO
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont

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
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

KTOX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOOT_SOURCES = {
    "Responder": os.path.join(KTOX_DIR, "Responder", "logs"),
    "DNSSpoof": os.path.join(KTOX_DIR, "DNSSpoof", "captures"),
    "EvilTwin": os.path.join(KTOX_DIR, "DNSSpoof", "sites", "wifi")
}
loot_items = []
selected_index = 0
running = True
current_loot_source_name = ""
current_loot_source_path = ""
loot_source_path_cursor_pos = 0

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def parse_responder_log(file_path):
    items = []
    try:
        with open(file_path, "r") as f:
            for line in f:
                if "NTLMv2-SSP" in line:
                    match = re.search(r'::\s*(.*?)\s*::', line)
                    if match:
                        user_info = match.group(1).strip()
                        items.append(f"RESP: {user_info}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Error parsing Responder log {file_path}: {e}", file=sys.stderr)
    return items

def parse_phishing_log(file_path, source_name):
    items = []
    try:
        with open(file_path, "r") as f:
            for line in f:
                if "user:" in line and "pass:" in line:
                    parts = line.split('|')
                    user = parts[0].split(':')[1].strip() if len(parts) > 0 and "user:" in parts[0] else "N/A"
                    password = parts[1].split(':')[1].strip() if len(parts) > 1 and "pass:" in parts[1] else "N/A"
                    items.append(f"{source_name}: {user}:{password}")
                elif "user=" in line and "pass=" in line:
                    match = re.search(r'user=(.*?)\s+pass=(.*)', line)
                    if match:
                        user = match.group(1).strip()
                        password = match.group(2).strip()
                        items.append(f"{source_name}: {user}:{password}")
                else:
                    items.append(f"{source_name}: {line.strip()}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Error parsing phishing log {file_path}: {e}", file=sys.stderr)
    return items

def gather_loot():
    global loot_items
    loot_items = []
    
    for name, path in LOOT_SOURCES.items():
        if not os.path.isdir(path):
            print(f"Loot source directory not found: {path}", file=sys.stderr)
            continue

        if name == "Responder":
            for filename in os.listdir(path):
                if filename.endswith(".txt"):
                    loot_items.extend(parse_responder_log(os.path.join(path, filename)))
        elif name in ["DNSSpoof", "EvilTwin"]:
            loot_file = os.path.join(path, "ip.txt")
            if os.path.exists(loot_file):
                loot_items.extend(parse_phishing_log(loot_file, name))
        elif name == "Nmap":
            for filename in os.listdir(path):
                if filename.endswith(".txt") or filename.endswith(".nmap"):
                    try:
                        with open(os.path.join(path, filename), "r") as f:
                            for line in f:
                                if "Host is up" in line or "open" in line:
                                    loot_items.append(f"NMAP: {line.strip()}")
                    except Exception as e:
                        print(f"Error parsing Nmap log {filename}: {e}", file=sys.stderr)

def show_message(lines, color="lime"):
    img = Image.new("RGB", (128, 128), (10, 0, 0))
    d = ImageDraw.Draw(img)
    font = FONT_TITLE
    y = 40
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (128 - w) // 2
        d.text((x, y), line, font=font, fill=color)
        y += h + 5
    LCD.LCD_ShowImage(img, 0, 0)

def draw_ui(screen_state="main"):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)

    d.text((5, 5), "Unified Loot Viewer", font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

    if screen_state == "main":
        if not loot_items:
            d.text((20, 60), "No loot found.", font=FONT, fill=(242, 243, 244))
        else:
            start_display_index = max(0, selected_index - 3)
            end_display_index = min(len(loot_items), start_display_index + 7)
            
            y_pos = 25
            for i in range(start_display_index, end_display_index):
                color = "yellow" if i == selected_index else "white"
                item_text = loot_items[i]
                if len(item_text) > 20:
                    item_text = item_text[:19] + "..."
                d.text((5, y_pos), item_text, font=FONT, fill=color)
                y_pos += 12

        d.text((5, 115), "OK=Refresh | KEY1=Add Source | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    elif screen_state == "add_source_name":
        d.text((5, 30), "New Source Name:", font=FONT, fill=(242, 243, 244))
        display_name = list(current_loot_source_name)
        if len(display_name) > 0 and loot_source_path_cursor_pos < len(display_name):
            display_name[loot_source_path_cursor_pos] = '_'
        d.text((5, 50), "".join(display_name[:16]), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
    elif screen_state == "add_source_path":
        d.text((5, 30), "New Source Path:", font=FONT, fill=(242, 243, 244))
        display_path = list(current_loot_source_path)
        if len(display_path) > 0 and loot_source_path_cursor_pos < len(display_path):
            display_path[loot_source_path_cursor_pos] = '_'
        d.text((5, 50), "".join(display_path[:16]), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_text_input_logic(initial_text, screen_state_name, char_set):
    global current_loot_source_name, current_loot_source_path, loot_source_path_cursor_pos
    
    if screen_state_name == "add_source_name":
        current_input_ref = current_loot_source_name
    else:
        current_input_ref = current_loot_source_path

    current_input_ref = initial_text
    loot_source_path_cursor_pos = len(initial_text) - 1
    
    draw_ui(screen_state_name)
    
    while running:
        btn = None
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                btn = name
                while GPIO.input(pin) == 0:
                    time.sleep(0.05)
                break
        
        if btn == "KEY3":
            return None
        
        if btn == "OK":
            if current_input_ref:
                return current_input_ref
            else:
                show_message(["Input cannot", "be empty!"], "red")
                time.sleep(2)
                current_input_ref = initial_text
                loot_source_path_cursor_pos = len(initial_text) - 1
                draw_ui(screen_state_name)
        
        if btn == "LEFT":
            loot_source_path_cursor_pos = max(0, loot_source_path_cursor_pos - 1)
            draw_ui(screen_state_name)
        elif btn == "RIGHT":
            loot_source_path_cursor_pos = min(len(current_input_ref), loot_source_path_cursor_pos + 1)
            draw_ui(screen_state_name)
        elif btn == "UP" or btn == "DOWN":
            if loot_source_path_cursor_pos < len(current_input_ref):
                char_list = list(current_input_ref)
                current_char = char_list[loot_source_path_cursor_pos]
                
                try:
                    char_index = char_set.index(current_char)
                    if btn == "UP":
                        char_index = (char_index + 1) % len(char_set)
                    else:
                        char_index = (char_index - 1 + len(char_set)) % len(char_set)
                    char_list[loot_source_path_cursor_pos] = char_set[char_index]
                    current_input_ref = "".join(char_list)
                except ValueError:
                    char_list[loot_source_path_cursor_pos] = char_set[0]
                    current_input_ref = "".join(char_list)
                draw_ui(screen_state_name)
        
        time.sleep(0.1)
    return None

if __name__ == "__main__":
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds

        # Initial data load
        draw_ui("main")
        gather_loot()

        while running:
            current_time = time.time()
            
            if current_screen == "main":
                draw_ui("main")
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    gather_loot()
                    selected_index = 0
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["UP"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    if loot_items:
                        selected_index = (selected_index - 1) % len(loot_items)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                elif GPIO.input(PINS["DOWN"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    if loot_items:
                        selected_index = (selected_index + 1) % len(loot_items)
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_loot_source_name = ""
                    current_screen = "add_source_name"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "add_source_name":
                char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                new_name = handle_text_input_logic(current_loot_source_name, "add_source_name", char_set)
                if new_name:
                    current_loot_source_name = new_name
                    current_loot_source_path = ""
                    current_screen = "add_source_path"
                else:
                    current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "add_source_path":
                char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-"
                new_path = handle_text_input_logic(current_loot_source_path, "add_source_path", char_set)
                if new_path:
                    if os.path.isdir(new_path):
                        LOOT_SOURCES[current_loot_source_name] = new_path
                        show_message(["Source added!", f"{current_loot_source_name}"], "lime")
                        time.sleep(2)
                        gather_loot()
                    else:
                        show_message(["Invalid Path!", "Not found."], "red")
                        time.sleep(2)
                current_screen = "main"
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.1)
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        show_message(["CRITICAL ERROR:", str(e)[:20]], "red")
        time.sleep(3)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Loot Viewer payload finished.")
