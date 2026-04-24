#!/usr/bin/env python3
"""
KTOx WiFi LCD Interface
===========================
Simple LCD-based WiFi management interface

Features:
- Network scanning and selection
- Profile management
- Connection status display
- DarkSecKeyboard for password entry

Button Layout:
- UP/DOWN: Navigate menus
- OK: Select/Confirm
- KEY1: Quick connect/disconnect
- KEY2: Refresh/Scan
- KEY3: Back/Exit
"""

import sys
import time
import threading
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


class WiFiLCDInterface:
    def __init__(self):
        if not LCD_AVAILABLE:
            raise Exception("LCD hardware not available")

        self.wifi_manager = WiFiManager()

        # LCD setup
        self.LCD = LCD_1in44.LCD()
        self.LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        self.W, self.H = 128, 128

        try:
            self.font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
            self.font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        except:
            self.font_sm = self.font_md = ImageFont.load_default()

        # GPIO setup
        GPIO.setmode(GPIO.BCM)
        self.setup_buttons()

        # Keyboard for password entry
        self.keyboard = DarkSecKeyboard(
            width=self.W, height=self.H, lcd=self.LCD,
            gpio_pins=self.buttons, gpio_module=GPIO
        )

        # Menu state
        self.current_menu = "main"
        self.menu_index = 0
        self.running = True

        # Data
        self.scanned_networks = []
        self.saved_profiles = []
        self.refresh_data()

    def setup_buttons(self):
        """Setup GPIO buttons."""
        self.buttons = {
            'UP': 6,
            'DOWN': 19,
            'LEFT': 5,
            'RIGHT': 26,
            'OK': 13,
            'KEY1': 21,
            'KEY2': 20,
            'KEY3': 16
        }

        for pin in self.buttons.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def refresh_data(self):
        """Refresh networks and profiles."""
        self.scanned_networks = self.wifi_manager.scan_networks()
        self.saved_profiles = self.wifi_manager.load_profiles()

    def draw_screen(self, title, lines, button_hint=""):
        """Draw a simple screen with title, content, and hints."""
        img = Image.new("RGB", (self.W, self.H), (10, 0, 0))
        d = ImageDraw.Draw(img)

        # Header
        d.rectangle([(0, 0), (self.W, 16)], fill=(139, 0, 0))
        d.text((4, 3), title[:20], fill=(231, 76, 60), font=self.font_md)

        # Content
        y = 20
        for line in lines[:7]:
            d.text((4, y), line[:20], fill=(171, 178, 185), font=self.font_sm)
            y += 12

        # Footer with hints
        d.rectangle([(0, self.H - 12), (self.W, self.H)], fill=(34, 0, 0))
        if button_hint:
            d.text((4, self.H - 10), button_hint[:26], fill=(113, 125, 126), font=self.font_sm)

        self.LCD.LCD_ShowImage(img, 0, 0)

    def draw_main_menu(self):
        """Draw main WiFi menu."""
        menu_items = [
            "Scan Networks",
            "Saved Profiles",
            "Connection Info",
            "Exit"
        ]

        lines = []
        for i, item in enumerate(menu_items):
            marker = ">" if i == self.menu_index else " "
            lines.append(f"{marker} {item}")

        self.draw_screen("WIFI MANAGER", lines, "UP/DN OK KEY3:back")

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
                ssid = network.get('ssid', 'Unknown')[:16]
                encrypted = "[L]" if network.get('encrypted', False) else "[O]"
                lines.append(f"{marker} {encrypted} {ssid}")

        self.draw_screen("NETWORKS", lines, "OK:Connect K3:back")

    def draw_saved_profiles(self):
        """Draw saved WiFi profiles."""
        lines = []

        if not self.saved_profiles:
            lines = ["No saved profiles", "", "Scan & save networks"]
        else:
            start_idx = max(0, self.menu_index - 2)
            visible = self.saved_profiles[start_idx:start_idx + 5]

            for i, profile in enumerate(visible):
                idx = start_idx + i
                marker = ">" if idx == self.menu_index else " "
                ssid = profile.get('ssid', 'Unknown')[:16]
                lines.append(f"{marker} {ssid}")

        self.draw_screen("PROFILES", lines, "OK:Connect K3:back")

    def draw_connection_info(self):
        """Draw connection status and info."""
        status = self.wifi_manager.get_connection_status()

        lines = [
            f"Status: {status.get('status', 'unknown').upper()[:8]}",
            f"SSID: {status.get('ssid', 'N/A')[:14]}",
            f"Signal: {status.get('signal', 0)}",
            f"IP: {status.get('ip', 'N/A')[:14]}",
        ]

        self.draw_screen("INFO", lines, "K2:Refresh K3:back")

    def handle_main_menu(self):
        """Handle main menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "UP":
            self.menu_index = (self.menu_index - 1) % 4
        elif btn == "DOWN":
            self.menu_index = (self.menu_index + 1) % 4
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
                password = self.keyboard.run()
                if password is None:
                    return

            # Connect
            self.wifi_manager.connect_network(ssid, password)
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
            self.wifi_manager.connect_network(profile['ssid'], profile.get('password', ''))
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

    def wait_btn(self, timeout=0.1):
        """Wait for button press with timeout."""
        start = time.time()
        while time.time() - start < timeout:
            for name, pin in self.buttons.items():
                if GPIO.input(pin) == 0:
                    time.sleep(0.05)
                    return name
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

                time.sleep(0.05)
        finally:
            self.LCD.LCD_Clear()
            GPIO.cleanup()


def main():
    """Launch WiFi LCD interface."""
    try:
        interface = WiFiLCDInterface()
        interface.run()
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    main()
