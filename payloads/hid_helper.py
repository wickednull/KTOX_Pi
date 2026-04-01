import os
import sys
import time
from zero_hid import Keyboard, Mouse

class HidHelper:
    def __init__(self):
        self.keyboard = None
        self.mouse = None
        self.is_hid_gadget_enabled = self._check_hid_gadget_enabled()
        if self.is_hid_gadget_enabled:
            try:
                self.keyboard = Keyboard()
                self.mouse = Mouse()
            except Exception as e:
                print(f"WARNING: zero-hid initialization failed: {e}", file=sys.stderr)
                self.is_hid_gadget_enabled = False

    def _check_hid_gadget_enabled(self):
        """Checks if the USB HID gadget is enabled by looking for /dev/hidg0."""
        return os.path.exists("/dev/hidg0")

    def type_string(self, text, delay=0.05):
        """Types a string using the emulated keyboard."""
        if not self.keyboard:
            print("ERROR: HID keyboard not initialized.", file=sys.stderr)
            return
        for char in text:
            self.keyboard.type(char)
            time.sleep(delay)

    def press_key(self, key, delay=0.05):
        """Presses and releases a single key."""
        if not self.keyboard:
            print("ERROR: HID keyboard not initialized.", file=sys.stderr)
            return
        self.keyboard.press(key)
        time.sleep(delay)
        self.keyboard.release(key)
        time.sleep(delay)

    def press_modifier_key(self, modifier, key, delay=0.05):
        """Presses a modifier key along with another key."""
        if not self.keyboard:
            print("ERROR: HID keyboard not initialized.", file=sys.stderr)
            return
        self.keyboard.press(modifier)
        self.keyboard.press(key)
        time.sleep(delay)
        self.keyboard.release(key)
        self.keyboard.release(modifier)
        time.sleep(delay)

    def move_mouse(self, x, y, delay=0.01):
        """Moves the mouse cursor."""
        if not self.mouse:
            print("ERROR: HID mouse not initialized.", file=sys.stderr)
            return
        self.mouse.move(x, y)
        time.sleep(delay)

    def click_mouse(self, button, delay=0.05):
        """Clicks a mouse button."""
        if not self.mouse:
            print("ERROR: HID mouse not initialized.", file=sys.stderr)
            return
        self.mouse.click(button)
        time.sleep(delay)

# Global instance for easy access
hid_helper = HidHelper()
