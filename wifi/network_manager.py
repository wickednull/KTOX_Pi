#!/usr/bin/env python3
"""
KTOx Network Manager
===========================
LCD-based network management interface

Features:
- Network scanning and connection
- Profile management with settings
- Connection status display
- Interface selection and priority

Button Layout:
- UP/DOWN: Navigate menus
- OK: Select/Confirm
- KEY1: Quick actions
- KEY2: Refresh/Scan
- KEY3: Back/Exit
"""

import os
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

sys.path.append('/root/KTOx/')

try:
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    import RPi.GPIO as GPIO
    from wifi_manager import WiFiManager
    from payloads._darksec_keyboard import DarkSecKeyboard
    LCD_AVAILABLE = True
except Exception as e:
    print(f"LCD not available: {e}")
    LCD_AVAILABLE = False

# Initialize hardware at module level (once)
if LCD_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    PINS = {
        'UP': 6, 'DOWN': 19, 'LEFT': 5, 'RIGHT': 26,
        'OK': 13, 'KEY1': 21, 'KEY2': 20, 'KEY3': 16
    }

    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD_Config.Driver_Delay_ms(50)

    W, H = 128, 128

    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except:
        font_sm = font_md = ImageFont.load_default()


class NetworkManager:
    def __init__(self):
        if not LCD_AVAILABLE:
            raise Exception("LCD hardware not available")

        self.wifi_manager = WiFiManager()

        # Button debounce state tracking
        self.button_state = {name: False for name in PINS}
        self.last_press_time = {name: 0 for name in PINS}

        # Menu state
        self.current_menu = "main"
        self.menu_index = 0
        self.running = True

        # Settings
        self.settings = {
            "auto_connect": True,
            "preferred_interface": "auto",
            "save_passwords": True
        }

        # Data
        self.scanned_networks = []
        self.saved_profiles = []
        self.refresh_data()

    def refresh_data(self):
        """Refresh networks and profiles."""
        self.scanned_networks = self.wifi_manager.scan_networks()
        self.saved_profiles = self.wifi_manager.load_profiles()

    def draw_screen(self, title, lines, button_hint=""):
        """Draw a simple screen with title, content, and hints."""
        img = Image.new("RGB", (W, H), (10, 0, 0))
        d = ImageDraw.Draw(img)

        # Header
        d.rectangle([(0, 0), (W, 16)], fill=(139, 0, 0))
        d.text((4, 3), title[:20], fill=(231, 76, 60), font=font_md)

        # Content
        y = 20
        for line in lines[:7]:
            d.text((4, y), line[:20], fill=(171, 178, 185), font=font_sm)
            y += 12

        # Footer with hints
        d.rectangle([(0, H - 12), (W, H)], fill=(34, 0, 0))
        if button_hint:
            d.text((4, H - 10), button_hint[:26], fill=(113, 125, 126), font=font_sm)

        LCD.LCD_ShowImage(img, 0, 0)

    def draw_main_menu(self):
        """Draw main network menu."""
        menu_items = [
            "Scan Networks",
            "Saved Profiles",
            "Connection Info",
            "Settings",
            "Exit"
        ]

        lines = []
        for i, item in enumerate(menu_items):
            marker = ">" if i == self.menu_index else " "
            lines.append(f"{marker} {item}")

        self.draw_screen("NETWORK MGR", lines, "UP/DN OK KEY3:back")

    def draw_network_scan(self):
        """Draw scanned networks list."""
        lines = []

        if not self.scanned_networks:
            lines = ["No networks found", "", "KEY2: Scan again"]
        else:
            start_idx = max(0, self.menu_index - 2)
            visible = self.scanned_networks[start_idx:start_idx + 5]

            for i, network in enumerate(visible):
                idx = start_idx + i
                marker = ">" if idx == self.menu_index else " "
                ssid = network.get('ssid', 'Unknown')[:13]
                encrypted = "[L]" if network.get('encrypted', False) else "[O]"
                lines.append(f"{marker}{encrypted}{ssid}")

        self.draw_screen("NETWORKS", lines, "OK:Connect K3:back")

    def draw_saved_profiles(self):
        """Draw saved network profiles."""
        lines = []

        if not self.saved_profiles:
            lines = ["No saved profiles", "", "Scan & save networks"]
        else:
            start_idx = max(0, self.menu_index - 2)
            visible = self.saved_profiles[start_idx:start_idx + 5]

            for i, profile in enumerate(visible):
                idx = start_idx + i
                marker = ">" if idx == self.menu_index else " "
                ssid = profile.get('ssid', 'Unknown')[:15]
                lines.append(f"{marker} {ssid}")

        self.draw_screen("PROFILES", lines, "OK:Connect K3:back")

    def draw_connection_info(self):
        """Draw connection status and info."""
        status = self.wifi_manager.get_connection_status()

        lines = [
            f"Status: {status.get('status', 'unknown')[:8]}",
            f"SSID: {status.get('ssid', 'N/A')[:13]}",
            f"Signal: {status.get('signal', 0)}",
            f"IP: {status.get('ip', 'N/A')[:13]}",
        ]

        self.draw_screen("INFO", lines, "K2:Refresh K3:back")

    def draw_settings_menu(self):
        """Draw settings menu."""
        auto_conn = "ON" if self.settings['auto_connect'] else "OFF"
        save_pwd = "ON" if self.settings['save_passwords'] else "OFF"

        menu_items = [
            f"AutoConnect: {auto_conn}",
            f"SavePwd: {save_pwd}",
            f"Interface: {self.settings['preferred_interface']}",
            "Back"
        ]

        lines = []
        for i, item in enumerate(menu_items):
            marker = ">" if i == self.menu_index else " "
            lines.append(f"{marker} {item}")

        self.draw_screen("SETTINGS", lines, "UP/DN OK K3:back")

    def get_password(self):
        """Get password using DarkSecKeyboard."""
        kb = DarkSecKeyboard(
            width=W, height=H, lcd=LCD,
            gpio_pins=PINS, gpio_module=GPIO
        )
        result = kb.run()
        return result if result else None

    def handle_main_menu(self):
        """Handle main menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "UP":
            self.menu_index = (self.menu_index - 1) % 5
        elif btn == "DOWN":
            self.menu_index = (self.menu_index + 1) % 5
        elif btn == "OK":
            if self.menu_index == 0:
                self.current_menu = "scan"
                self.menu_index = 0
            elif self.menu_index == 1:
                self.current_menu = "profiles"
                self.menu_index = 0
            elif self.menu_index == 2:
                self.current_menu = "info"
            elif self.menu_index == 3:
                self.current_menu = "settings"
                self.menu_index = 0
            elif self.menu_index == 4:
                self.running = False
        elif btn == "KEY2":
            self.refresh_data()
        elif btn == "KEY3":
            self.running = False

    def handle_scan_menu(self):
        """Handle scan menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "UP":
            self.menu_index = max(0, self.menu_index - 1)
        elif btn == "DOWN":
            if self.scanned_networks:
                self.menu_index = min(len(self.scanned_networks) - 1, self.menu_index + 1)
        elif btn == "OK" and self.scanned_networks:
            network = self.scanned_networks[self.menu_index]
            ssid = network.get('ssid', '')

            # Get password if encrypted
            password = ""
            if network.get('encrypted', False):
                password = self.get_password()
                if password is None:
                    return

            # Connect
            self.wifi_manager.connect_to_network(ssid, password)
            time.sleep(2)
            self.refresh_data()
            self.current_menu = "main"
            self.menu_index = 0
        elif btn == "KEY2":
            self.refresh_data()
            self.menu_index = 0
        elif btn == "KEY3":
            self.current_menu = "main"
            self.menu_index = 0

    def handle_profiles_menu(self):
        """Handle profiles menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "UP":
            self.menu_index = max(0, self.menu_index - 1)
        elif btn == "DOWN":
            if self.saved_profiles:
                self.menu_index = min(len(self.saved_profiles) - 1, self.menu_index + 1)
        elif btn == "OK" and self.saved_profiles:
            profile = self.saved_profiles[self.menu_index]
            self.wifi_manager.connect_to_profile(profile)
            time.sleep(2)
            self.refresh_data()
            self.current_menu = "main"
            self.menu_index = 0
        elif btn == "KEY3":
            self.current_menu = "main"
            self.menu_index = 0

    def handle_info_menu(self):
        """Handle info menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "KEY2":
            self.refresh_data()
        elif btn == "KEY3":
            self.current_menu = "main"

    def handle_settings_menu(self):
        """Handle settings menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "UP":
            self.menu_index = max(0, self.menu_index - 1)
        elif btn == "DOWN":
            self.menu_index = min(3, self.menu_index + 1)
        elif btn == "OK":
            if self.menu_index == 0:
                self.settings['auto_connect'] = not self.settings['auto_connect']
            elif self.menu_index == 1:
                self.settings['save_passwords'] = not self.settings['save_passwords']
            elif self.menu_index == 2:
                options = ["auto", "wlan0", "wlan1"]
                current_idx = options.index(self.settings['preferred_interface'])
                self.settings['preferred_interface'] = options[(current_idx + 1) % len(options)]
            elif self.menu_index == 3:
                self.current_menu = "main"
                self.menu_index = 0
        elif btn == "KEY3":
            self.current_menu = "main"
            self.menu_index = 0

    def wait_btn(self, timeout=0.1):
        """Wait for button press with debounce state tracking."""
        start = time.time()
        while time.time() - start < timeout:
            for name, pin in PINS.items():
                pressed = (GPIO.input(pin) == 0)

                if pressed and not self.button_state[name]:
                    self.button_state[name] = True
                    min_gap = 0.15
                    if time.time() - self.last_press_time[name] >= min_gap:
                        self.last_press_time[name] = time.time()
                        return name
                elif not pressed and self.button_state[name]:
                    self.button_state[name] = False

            time.sleep(0.02)
        return None

    def run(self):
        """Main loop."""
        try:
            while self.running:
                if self.current_menu == "main":
                    self.draw_main_menu()
                    self.handle_main_menu()
                elif self.current_menu == "scan":
                    self.draw_network_scan()
                    self.handle_scan_menu()
                elif self.current_menu == "profiles":
                    self.draw_saved_profiles()
                    self.handle_profiles_menu()
                elif self.current_menu == "info":
                    self.draw_connection_info()
                    self.handle_info_menu()
                elif self.current_menu == "settings":
                    self.draw_settings_menu()
                    self.handle_settings_menu()

                time.sleep(0.05)
        finally:
            LCD.LCD_Clear()
            GPIO.cleanup()


def main():
    """Launch Network Manager."""
    try:
        manager = NetworkManager()
        manager.run()
        return True
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    main()
