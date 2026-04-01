#!/usr/bin/env python3
"""
KTOx *payload* – **Service Manager**
=======================================
This utility provides an interface to view and manage system services
(systemd units) on the KTOx's LCD. It allows you to check the status
of services and perform actions like starting, stopping, or restarting them.

Features:
- Lists common system services with their current status (active/inactive/failed).
- Allows scrolling through the service list.
- Provides options to Start, Stop, or Restart selected services.
- Displays status messages and confirmation prompts on the LCD.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - UP/DOWN: Scroll through services.
    - OK: Select service to view actions.
    - KEY3: Exit Payload.
- SERVICE ACTION SCREEN:
    - UP/DOWN: Navigate actions (Start, Stop, Restart).
    - OK: Confirm action.
    - KEY3: Cancel action.
"""
import sys
import os
import time
import signal
import subprocess
import threading
from collections import deque
# Ensure KTOx root on sys.path
sys.path.append(os.path.abspath(os.path.join(__file__, '..', '..')))
import RPi.GPIO as GPIO
import LCD_Config
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# --- Constants and Globals ---
# Load PINS from KTOx gui_conf.json
PINS: dict[str, int] = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
try:
    import json
    def _find_gui_conf():
        candidates = [
            os.path.join(os.getcwd(), 'gui_conf.json'),
            os.path.join('/root/KTOx', 'gui_conf.json'),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'KTOx', 'gui_conf.json'),
        ]
        for sp in sys.path:
            try:
                if sp and os.path.basename(sp) == 'KTOx':
                    candidates.append(os.path.join(sp, 'gui_conf.json'))
            except Exception:
                pass
        for p in candidates:
            if os.path.exists(p):
                return p
        return None
    conf_path = _find_gui_conf()
    if conf_path:
        with open(conf_path, 'r') as f:
            data = json.load(f)
        conf_pins = data.get("PINS", {})
        PINS = {
            "UP": conf_pins.get("KEY_UP_PIN", PINS["UP"]),
            "DOWN": conf_pins.get("KEY_DOWN_PIN", PINS["DOWN"]),
            "LEFT": conf_pins.get("KEY_LEFT_PIN", PINS["LEFT"]),
            "RIGHT": conf_pins.get("KEY_RIGHT_PIN", PINS["RIGHT"]),
            "OK": conf_pins.get("KEY_PRESS_PIN", PINS["OK"]),
            "KEY1": conf_pins.get("KEY1_PIN", PINS["KEY1"]),
            "KEY2": conf_pins.get("KEY2_PIN", PINS["KEY2"]),
            "KEY3": conf_pins.get("KEY3_PIN", PINS["KEY3"]),
        }
except Exception:
    pass

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
services = []
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

def draw_service_list_ui(current_selection_index):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    d.text((5, 5), "Service Manager", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    with ui_lock:
        visible_services = services[display_offset:]
        y_pos = 25
        for i, s in enumerate(visible_services):
            if y_pos > HEIGHT - 25: # Leave space for footer
                break
            
            color = "yellow" if i == current_selection_index - display_offset else "white"
            status_color = "lime" if s['status'] == "active" else ("red" if s['status'] == "failed" else "white")
            
            line = f"{s['name'][:10]:<10} {s['status'][:7]:<7}"
            d.text((5, y_pos), line, font=FONT, fill=color)
            d.text((70, y_pos), s['status'][:7], font=FONT, fill=status_color) # Color status
            y_pos += 11
    
    d.text((5, 115), "UP/DOWN=Scroll | OK=Action | KEY3=Exit", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

def draw_service_action_ui(service_name, actions, current_selection):
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    d = ImageDraw.Draw(img)
    
    d.text((5, 5), f"Actions for {service_name[:10]}", font=FONT_TITLE, fill="#00FF00")
    d.line([(0, 22), (128, 22)], fill="#00FF00", width=1)

    y_pos = 25
    for i, action in enumerate(actions):
        color = "yellow" if i == current_selection else "white"
        d.text((5, y_pos), action, font=FONT, fill=color)
        y_pos += 11
    
    d.text((5, 115), "UP/DOWN=Select | OK=Confirm | KEY3=Cancel", font=FONT, fill="cyan")
    LCD.LCD_ShowImage(img, 0, 0)

# --- Service Management Functions ---
def get_services():
    global services
    new_services = []
    try:
        # systemctl list-units --type=service --all
        # UNIT                                    LOAD   ACTIVE SUB     DESCRIPTION
        # NetworkManager.service                  loaded active running Network Manager
        proc = subprocess.run(["systemctl", "list-units", "--type=service", "--all", "--no-pager"], capture_output=True, text=True, check=True)
        lines = proc.stdout.splitlines()
        
        # Skip header and footer
        for line in lines[1:-7]: # Adjust based on actual systemctl output
            parts = line.split()
            if len(parts) >= 4:
                name = parts[0].replace(".service", "")
                status = parts[2] # active, inactive, failed
                new_services.append({'name': name, 'status': status})
        
        new_services.sort(key=lambda x: x['name'].lower()) # Sort alphabetically
        
        with ui_lock:
            services = new_services
            
    except Exception as e:
        draw_message([f"Error getting services:", str(e)[:20]], "red")
        print(f"Error getting services: {e}", file=sys.stderr)

def perform_service_action(service_name, action):
    try:
        cmd = ["sudo", "systemctl", action, service_name + ".service"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        draw_message([f"{service_name} {action}ed!", "Success."], "lime")
    except subprocess.CalledProcessError as e:
        draw_message([f"Failed to {action} {service_name}:", str(e.stderr)[:20]], "red")
        print(f"Failed to {action} {service_name}: {e.stderr}", file=sys.stderr)
    except Exception as e:
        draw_message([f"Error: {str(e)[:20]}"], "red")
        print(f"Error performing service action: {e}", file=sys.stderr)
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
            get_services() # Refresh service list
            
            if not services:
                draw_message(["No services found!"], "yellow")
                time.sleep(1)
                continue

            # Ensure selection is within bounds
            if current_selection_index >= len(services):
                current_selection_index = max(0, len(services) - 1)
            
            draw_service_list_ui(current_selection_index)
            
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
                current_selection_index = min(len(services) - 1, current_selection_index + 1)
                if current_selection_index >= display_offset + LINES_PER_SCREEN:
                    display_offset = current_selection_index - LINES_PER_SCREEN + 1
                time.sleep(BUTTON_DEBOUNCE_TIME)
            elif GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                last_button_press_time = current_time
                if services:
                    selected_service = services[current_selection_index]
                    actions = ["start", "stop", "restart"]
                    selected_action_index = 0
                    
                    while running:
                        current_time_action = time.time()
                        draw_service_action_ui(selected_service['name'], actions, selected_action_index)
                        
                        if GPIO.input(PINS["KEY3"]) == 0 and (current_time_action - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = current_time_action
                            break # Exit action selection
                        
                        if GPIO.input(PINS["UP"]) == 0 and (current_time_action - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = current_time_action
                            selected_action_index = (selected_action_index - 1 + len(actions)) % len(actions)
                            time.sleep(BUTTON_DEBOUNCE_TIME)
                        elif GPIO.input(PINS["DOWN"]) == 0 and (current_time_action - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = current_time_action
                            selected_action_index = (selected_action_index + 1) % len(actions)
                            time.sleep(BUTTON_DEBOUNCE_TIME)
                        elif GPIO.input(PINS["OK"]) == 0 and (current_time_action - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                            last_button_press_time = current_time_action
                            action_to_perform = actions[selected_action_index]
                            
                            confirm_action = True
                            if action_to_perform in ["stop", "disable"]: # Potentially destructive actions
                                draw_message([f"Confirm {action_to_perform}", f"{selected_service['name']}?", "OK=Yes | KEY3=No"], "red")
                                confirm_start_time = time.time()
                                confirmed = False
                                while running and (time.time() - confirm_start_time < 5.0):
                                    if GPIO.input(PINS["OK"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                                        last_button_press_time = time.time()
                                        confirmed = True
                                        break
                                    if GPIO.input(PINS["KEY3"]) == 0 and (time.time() - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                                        last_button_press_time = time.time()
                                        draw_message(["Action cancelled."], "yellow")
                                        time.sleep(1)
                                        confirm_action = False
                                        break
                                    time.sleep(0.05)
                                if not confirmed:
                                    confirm_action = False
                                    draw_message(["Confirmation timed out."], "yellow")
                                    time.sleep(1)

                            if confirm_action:
                                perform_service_action(selected_service['name'], action_to_perform)
                            break # Exit action selection after performing/cancelling
                        
                        time.sleep(0.05)
                time.sleep(BUTTON_DEBOUNCE_TIME)
            
            time.sleep(0.05)

    except SystemExit:
        pass
    except Exception as e:
        draw_message([f"CRITICAL ERROR:", str(e)[:20]], "red")
        print(f"Critical error in Service Manager: {e}", file=sys.stderr)
        time.sleep(5)
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Service Manager payload finished.")