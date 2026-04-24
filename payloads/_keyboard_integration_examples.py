#!/usr/bin/env python3
"""
Example: Integrating DarkSecKeyboard into a Payload

This demonstrates how to use the reusable DarkSecKeyboard module
instead of maintaining individual keyboard implementations.

Replace your existing keyboard code with this pattern.
"""

import os
import sys

# Add KTOX root to path
KTOX_ROOT = "/root/KTOx" if os.path.isdir("/root/KTOx") else os.path.dirname(__file__)
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)

# Import the keyboard module
from payloads._darksec_keyboard import DarkSecKeyboard

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ============================================================================
# Example 1: Using DarkSecKeyboard with GPIO buttons
# ============================================================================

def example_with_gpio():
    """Use DarkSecKeyboard with physical GPIO buttons."""
    if not HAS_HW:
        print("Hardware not available")
        return

    # GPIO pins (adjust as needed for your device)
    PINS = {
        "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
    }

    # Initialize LCD
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Create keyboard instance
    keyboard = DarkSecKeyboard(
        width=128,
        height=128,
        lcd=LCD,
        gpio_pins=PINS,
        gpio_module=GPIO
    )

    # Run keyboard and get user input
    user_input = keyboard.run()

    if user_input:
        print(f"User entered: {user_input}")
        return user_input
    else:
        print("User cancelled")
        return None


# ============================================================================
# Example 2: Using in a shell-like interface
# ============================================================================

def example_interactive_shell():
    """Example of using keyboard for interactive shell input."""
    if not HAS_HW:
        print("Hardware not available")
        return

    PINS = {
        "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
        "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
    }

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    keyboard = DarkSecKeyboard(
        width=128,
        height=128,
        lcd=LCD,
        gpio_pins=PINS,
        gpio_module=GPIO
    )

    # Interactive loop
    commands = []
    while True:
        # Run keyboard
        user_input = keyboard.run()

        if user_input is None:
            # User cancelled/exited
            break

        # Process command
        if user_input.strip():
            commands.append(user_input)
            print(f"Executed: {user_input}")

            # Could execute command here
            # result = execute_command(user_input)
            # display result on LCD

    print(f"Session ended. Executed {len(commands)} commands")


# ============================================================================
# Example 3: Migration from old keyboard code
# ============================================================================

"""
OLD CODE (to replace):

KB_LOWER = [["q","w","e","r","t","y","u","i","o","p"], ...]
KB_UPPER = [["Q","W","E","R","T","Y","U","I","O","P"], ...]
...

def run_vkb():
    global vkb_page, vkb_row, vkb_col
    while True:
        normalize_vkb_cursor()
        draw_vkb(compose)
        btn = wait_action(0.15)
        ...
        if btn == "OK":
            ...
        if done:
            return compose


NEW CODE (replacement):

from payloads._darksec_keyboard import DarkSecKeyboard

keyboard = DarkSecKeyboard(...)
result = keyboard.run()
"""


# ============================================================================
# Example 4: Using in Flask web app with GPIO input
# ============================================================================

def example_web_app_with_keyboard():
    """Example of combining Flask web server with keyboard input."""
    from flask import Flask, render_template_string
    import threading

    app = Flask(__name__)

    keyboard_input = None

    def keyboard_thread():
        nonlocal keyboard_input
        # Background thread running keyboard
        PINS = {
            "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
            "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
        }
        LCD = LCD_1in44.LCD()
        LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        GPIO.setmode(GPIO.BCM)
        for pin in PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        keyboard = DarkSecKeyboard(
            width=128, height=128, lcd=LCD, gpio_pins=PINS, gpio_module=GPIO
        )
        keyboard_input = keyboard.run()

    @app.route('/')
    def index():
        return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head><title>Web + Keyboard</title></head>
            <body>
                <h1>Web Interface with GPIO Keyboard</h1>
                <p>Use LCD keyboard to input, or web form below</p>
                <form method="post" action="/submit">
                    <input type="text" name="input" placeholder="Type or use LCD keyboard">
                    <button type="submit">Submit</button>
                </form>
            </body>
            </html>
        """)

    @app.route('/submit', methods=['POST'])
    def submit():
        return "Input received"

    # Start keyboard in background
    thread = threading.Thread(target=keyboard_thread, daemon=True)
    thread.start()

    app.run(host='0.0.0.0', port=8080)


# ============================================================================
# Benefits of Using DarkSecKeyboard
# ============================================================================

"""
✅ Code Reuse
   - Single implementation instead of duplicating in every payload
   - Updates in one place benefit all payloads

✅ Consistency
   - Same keyboard behavior across all tools
   - Users learn once, apply everywhere
   - Command history works uniformly

✅ Maintenance
   - Bug fixes apply to all payloads
   - Feature additions available to all
   - No divergence between implementations

✅ Features Included
   - 4 keyboard pages (lowercase, uppercase, symbols, tools)
   - Command history with UP/DOWN navigation
   - Tool shortcuts (ls, cd, pwd, cat, grep, echo, pipes, redirects)
   - Proper debouncing and button state tracking
   - Cyberpunk theme colors (yt-ripper aesthetic)

✅ Easy Migration
   - Remove old KB_LOWER, KB_UPPER, etc.
   - Remove old run_vkb() function
   - Add: keyboard = DarkSecKeyboard(...)
   - Replace: old_result = old_run_vkb()
   - With:    result = keyboard.run()
"""


if __name__ == '__main__':
    import time

    print("DarkSecKeyboard Integration Examples")
    print("=" * 50)
    print("\n1. GPIO Button Example")
    print("2. Interactive Shell Example")
    print("3. Web App Example")
    print("\nSelect example (or 'q' to quit):")

    choice = input("> ").strip()

    if choice == '1':
        example_with_gpio()
    elif choice == '2':
        example_interactive_shell()
    elif choice == '3':
        try:
            example_web_app_with_keyboard()
        except Exception as e:
            print(f"Error: {e}")
    elif choice != 'q':
        print("Unknown choice")
