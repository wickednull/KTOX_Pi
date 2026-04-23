#!/usr/bin/env python3
"""
KTOx *payload* – **Internet Connectivity Check**
==================================================
This payload checks internet connectivity by pinging a user-defined list
of hosts. It displays the results on the LCD, indicating whether each host
is reachable and providing a summary of overall connectivity.

Features:
- Interactive UI to edit the list of hosts to check.
- Pings each host and displays individual success/failure status.
- Provides a summary "Internet OK" or "No Internet".
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- MAIN SCREEN:
    - OK: Re-run the internet check.
    - KEY1: Edit the list of hosts to check.
    - KEY3: Exit Payload.
- HOSTS INPUT SCREEN:
    - UP/DOWN: Change character at cursor position.
    - LEFT/RIGHT: Move cursor.
    - OK: Confirm host list.
    - KEY3: Cancel input.
"""
import sys
import os
import time
import signal
import subprocess
import json
# Ensure KTOx root on path for local LCD modules (prefer installed path)
if os.path.isdir('/root/KTOx') and '/root/KTOx' not in sys.path:
    sys.path.insert(0, '/root/KTOx')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import RPi.GPIO as GPIO
import LCD_Config
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

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
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT_BIG = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)

HOSTS_TO_CHECK = ["8.8.8.8", "1.1.1.1", "google.com"]
running = True
current_hosts_input = ", ".join(HOSTS_TO_CHECK)
hosts_input_cursor_pos = 0

def cleanup(*_):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

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

def draw_ui(screen_state="main", results=None, summary=""):
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)

    d.text((5, 5), "Internet Check", font=FONT_TITLE, fill=(30, 132, 73))
    d.line([(0, 22), (128, 22)], fill=(30, 132, 73), width=1)

    if screen_state == "main":
        y_pos = 25
        if results:
            for line in results:
                d.text((5, y_pos), line, font=FONT, fill=(242, 243, 244))
                y_pos += 12
        else:
            d.text((5, y_pos), "Press OK to run", font=FONT, fill=(242, 243, 244))
            y_pos += 12
            d.text((5, y_pos), f"Hosts: {', '.join(HOSTS_TO_CHECK)[:16]}...", font=FONT, fill=(242, 243, 244))
            
        if summary:
            color = "lime" if "OK" in summary else "red"
            bbox = d.textbbox((0, 0), summary, font=FONT_BIG)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (WIDTH - w) // 2
            d.text((x, 90), summary, font=FONT_BIG, fill=color)

        d.text((5, 115), "OK=Re-run | KEY1=Edit Hosts | KEY3=Exit", font=FONT, fill=(171, 178, 185))
    elif screen_state == "hosts_input":
        d.text((5, 30), "Enter Hosts (CSV):", font=FONT, fill=(242, 243, 244))
        display_hosts = list(current_hosts_input)
        if hosts_input_cursor_pos < len(display_hosts):
            display_hosts[hosts_input_cursor_pos] = '_'
        d.text((5, 50), "".join(display_hosts[:16]), font=FONT_TITLE, fill=(212, 172, 13))
        d.text((5, 115), "UP/DOWN=Char | LEFT/RIGHT=Move | OK=Confirm", font=FONT, fill=(171, 178, 185))
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_text_input_logic(initial_text, screen_state_name, char_set):
    global current_hosts_input, hosts_input_cursor_pos
    
    current_input_ref = current_hosts_input
    cursor_pos_ref = hosts_input_cursor_pos

    current_input_ref = initial_text
    cursor_pos_ref = len(initial_text) - 1
    
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
                cursor_pos_ref = len(initial_text) - 1
                draw_ui(screen_state_name)
        
        if btn == "LEFT":
            cursor_pos_ref = max(0, cursor_pos_ref - 1)
            draw_ui(screen_state_name)
        elif btn == "RIGHT":
            cursor_pos_ref = min(len(current_input_ref), cursor_pos_ref + 1)
            draw_ui(screen_state_name)
        elif btn == "UP" or btn == "DOWN":
            if cursor_pos_ref < len(current_input_ref):
                char_list = list(current_input_ref)
                current_char = char_list[cursor_pos_ref]
                
                try:
                    char_index = char_set.index(current_char)
                    if btn == "UP":
                        char_index = (char_index + 1) % len(char_set)
                    else:
                        char_index = (char_index - 1 + len(char_set)) % len(char_set)
                    char_list[cursor_pos_ref] = char_set[char_index]
                    current_input_ref = "".join(char_list)
                except ValueError:
                    char_list[cursor_pos_ref] = char_set[0]
                    current_input_ref = "".join(char_list)
                draw_ui(screen_state_name)
        
        time.sleep(0.1)
    return None

def run_test():
    results = []
    success_count = 0
    
    for host in HOSTS_TO_CHECK:
        if not running: return
        
        results.append(f"Pinging {host}...")
        draw_ui("main", results=results)
        
        try:
            command = f"ping -c 1 -W 2 {host}"
            response = subprocess.run(command, shell=True, capture_output=True)
            
            if response.returncode == 0:
                results[-1] = f"[  OK  ] {host}"
                success_count += 1
            else:
                results[-1] = f"[ FAIL ] {host}"
        except Exception:
            results[-1] = f"[ ERROR ] {host}"
            
        draw_ui("main", results=results)
        time.sleep(0.5)

    if not running: return
    
    if success_count > 0:
        summary = "Internet OK"
    else:
        summary = "No Internet"
        
    draw_ui("main", results=results, summary=summary)

if __name__ == "__main__":
    current_screen = "main"
    try:
        last_button_press_time = 0
        BUTTON_DEBOUNCE_TIME = 0.3 # seconds
    
        while running:
            current_time = time.time()
            
            if current_screen == "main":
                draw_ui("main", results=None, summary="Ready")
                
                if GPIO.input(PINS["KEY3"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    cleanup()
                    break
                
                if GPIO.input(PINS["OK"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    run_test()
                    time.sleep(BUTTON_DEBOUNCE_TIME)
                
                if GPIO.input(PINS["KEY1"]) == 0 and (current_time - last_button_press_time > BUTTON_DEBOUNCE_TIME):
                    last_button_press_time = current_time
                    current_hosts_input = ", ".join(HOSTS_TO_CHECK)
                    current_screen = "hosts_input"
                    time.sleep(BUTTON_DEBOUNCE_TIME)
            
            elif current_screen == "hosts_input":
                char_set = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-, "
                new_hosts_str = handle_text_input_logic(current_hosts_input, "hosts_input", char_set)
                if new_hosts_str:
                    HOSTS_TO_CHECK = [h.strip() for h in new_hosts_str.split(',') if h.strip()]
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
        print("Internet Check payload finished.")