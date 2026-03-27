#!/usr/bin/env python3
"""
KTOx *payload* – **Simple Web Browser**
==========================================
This payload provides a simple text-based web browser on the LCD screen,
using the `w3m` command-line browser to render pages.

Features:
- Allows the user to enter a URL.
- Renders the specified URL using `w3m`.
- Displays the rendered text on the LCD.
- Allows scrolling up and down through the page content.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- URL INPUT SCREEN:
    - Use the on-screen keyboard to enter a URL.
    - KEY2: Save/Go
    - KEY3: Cancel and exit.
- BROWSER VIEW:
    - UP/DOWN: Scroll through the page content.
    - KEY1: Enter a new URL.
    - KEY3: Exit the payload.
"""

import sys
import os
import time
import signal
import subprocess
import threading

# Add KTOx root to path for imports
KTOX_ROOT = '/root/KTOx'
if os.path.isdir(KTOX_ROOT) and KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

try:
    import RPi.GPIO as GPIO
    import LCD_Config
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Hardware libraries not found.", file=sys.stderr)
    sys.exit(1)

# --- Global State ---
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
RUNNING = True
UI_LOCK = threading.Lock()
PAGE_CONTENT_LINES = ["Enter a URL to start..."]
SCROLL_OFFSET = 0
CURRENT_URL = "duckduckgo.com"

# --- Cleanup Handler ---
def cleanup(*_):
    global RUNNING
    if not RUNNING:
        return
    RUNNING = False
    print("Browser: Cleaning up GPIO...")
    GPIO.cleanup()
    print("Browser: Exiting.")

# --- UI Drawing ---
def draw_ui(screen_state="browser"):
    with UI_LOCK:
        image = Image.new("RGB", (128, 128), "BLACK")
        draw = ImageDraw.Draw(image)
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            font_mono = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
        except IOError:
            font_title = ImageFont.load_default()
            font_mono = ImageFont.load_default()

        if screen_state == "browser":
            draw.text((5, 5), f"w3m: {CURRENT_URL[:15]}", font_title, fill="CYAN")
            draw.line([(0, 22), (128, 22)], fill="CYAN", width=1)

            y = 25
            # Display 10 lines of content based on scroll offset
            for i in range(10):
                line_index = SCROLL_OFFSET + i
                if line_index < len(PAGE_CONTENT_LINES):
                    draw.text((2, y), PAGE_CONTENT_LINES[line_index], font=font_mono, fill="WHITE")
                y += 10
            
            # Scrollbar
            if len(PAGE_CONTENT_LINES) > 10:
                total_h = 128 - 25
                bar_h = max(5, total_h * (10 / len(PAGE_CONTENT_LINES)))
                bar_y = 25 + (SCROLL_OFFSET / len(PAGE_CONTENT_LINES)) * total_h
                draw.rectangle([(124, 25), (127, 127)], fill="#333")
                draw.rectangle([(124, bar_y), (127, bar_y + bar_h)], fill="CYAN")

        LCD.LCD_ShowImage(image, 0, 0)

# --- Web Content Fetching ---
def fetch_url(url):
    global PAGE_CONTENT_LINES, SCROLL_OFFSET
    with UI_LOCK:
        PAGE_CONTENT_LINES = [f"Loading {url}..."]
        SCROLL_OFFSET = 0
    
    try:
        # Use w3m to dump the rendered text content of the page
        # -T text/html: Specify the content type
        # -dump: Dump the rendered page to stdout
        # -cols 20: Render for a narrow screen (approx 20 chars on our LCD)
        command = ["w3m", "-T", "text/html", "-dump", "-cols", "20", url]
        process = subprocess.run(command, capture_output=True, text=True, timeout=30)
        
        if process.returncode == 0:
            with UI_LOCK:
                PAGE_CONTENT_LINES = process.stdout.splitlines()
                if not PAGE_CONTENT_LINES:
                    PAGE_CONTENT_LINES = ["Page is empty."]
        else:
            with UI_LOCK:
                error_lines = process.stderr.splitlines()
                PAGE_CONTENT_LINES = ["w3m Error:"] + error_lines[-5:] # Show last 5 error lines
    except FileNotFoundError:
        with UI_LOCK:
            PAGE_CONTENT_LINES = ["Error:", "w3m not found!", "Please install it:", "sudo apt-get", "install w3m"]
    except subprocess.TimeoutExpired:
        with UI_LOCK:
            PAGE_CONTENT_LINES = ["Error:", "Request timed out."]
    except Exception as e:
        with UI_LOCK:
            PAGE_CONTENT_LINES = [f"Error: {str(e)[:20]}"]

# --- On-screen Keyboard for URL input ---
def handle_text_input_logic(initial_text):
    global CURRENT_URL
    char_set = "abcdefghijklmnopqrstuvwxyz0123456789./:_-?=&"
    char_index = 0
    input_text = initial_text

    while RUNNING:
        # --- Draw UI for keyboard ---
        img = Image.new("RGB", (128, 128), "black")
        d = ImageDraw.Draw(img)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        font = ImageFont.load_default()
        
        d.text((5, 5), "Enter URL", font=font_title, fill="cyan")
        d.line([(0, 22), (128, 22)], fill="cyan", width=1)
        d.text((5, 30), f"> {input_text[-18:]}", font=font, fill="white") # Show last 18 chars
        
        d.text((5, 60), f"Char: < {char_set[char_index]} >", font_title, fill="yellow")
        
        d.text((5, 90), "U/D=Char | OK=Add", font=font, fill="lime")
        d.text((5, 100), "L=Del | R=Space", font=font, fill="lime")
        d.text((5, 110), "K2=Go | K3=Exit", font=font, fill="orange")
        LCD.LCD_ShowImage(img, 0, 0)

        # --- Handle Input ---
        btn = None
        while not btn and RUNNING:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    btn = name
                    break
            time.sleep(0.05)
        
        if not RUNNING: break

        if btn == "KEY3":
            return False # Canceled
        if btn == "KEY2":
            if input_text:
                CURRENT_URL = input_text
                return True # URL entered
        elif btn == "OK":
            input_text += char_set[char_index]
        elif btn == "LEFT":
            input_text = input_text[:-1]
        elif btn == "RIGHT":
            input_text += " "
        elif btn == "UP":
            char_index = (char_index - 1 + len(char_set)) % len(char_set)
        elif btn == "DOWN":
            char_index = (char_index + 1) % len(char_set)
        
        time.sleep(0.15) # Debounce
    return False


# --- Main Execution Block ---
if __name__ == "__main__":
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

        current_screen = "browser"
        
        # Initial URL prompt
        if not handle_text_input_logic(CURRENT_URL):
            raise SystemExit("User canceled URL input.")
        
        # Initial fetch
        fetch_thread = threading.Thread(target=fetch_url, args=(CURRENT_URL,), daemon=True)
        fetch_thread.start()

        # --- Main Loop ---
        while RUNNING:
            draw_ui(current_screen)

            # --- Handle Input ---
            if GPIO.input(PINS["KEY3"]) == 0:
                break # Exit loop
            
            if GPIO.input(PINS["KEY1"]) == 0:
                if handle_text_input_logic(CURRENT_URL):
                    fetch_thread = threading.Thread(target=fetch_url, args=(CURRENT_URL,), daemon=True)
                    fetch_thread.start()
                time.sleep(0.2)

            if GPIO.input(PINS["UP"]) == 0:
                with UI_LOCK:
                    SCROLL_OFFSET = max(0, SCROLL_OFFSET - 1)
                time.sleep(0.1)

            if GPIO.input(PINS["DOWN"]) == 0:
                with UI_LOCK:
                    # Ensure we don't scroll past the end
                    max_scroll = len(PAGE_CONTENT_LINES) - 10
                    SCROLL_OFFSET = min(max_scroll, SCROLL_OFFSET + 1)
                time.sleep(0.1)
            
            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        # Log any fatal error
        with open("/tmp/browser_payload_error.log", "w") as f:
            f.write(f"FATAL ERROR: {e}\n")
            import traceback
            traceback.print_exc(file=f)
    finally:
        LCD.LCD_Clear()
        cleanup()
