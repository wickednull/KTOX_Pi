#!/usr/bin/env python3
"""
KTOx WiFi LCD Interface
===========================
LCD-based WiFi management with cyberpunk UI and DarkSecKeyboard

Features:
- Network scanning and selection
- Profile management with DarkSecKeyboard
- Connection status with live monitoring
- Cyberpunk KTOx aesthetic with CRT scanlines

Button Layout:
- UP/DOWN: Navigate menus
- LEFT/RIGHT: Change values
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

# Cyberpunk color palette
COLOR_BG_0 = "#0a0000"
COLOR_BG_1 = "#220000"
COLOR_HEADER = "#8b0000"
COLOR_ACCENT = "#e74c3c"
COLOR_WARN = "#d4ac0d"
COLOR_FG = "#abb2b9"
COLOR_FG_MUTED = "#717d7e"

# Convert hex to RGB tuples for PIL
def hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

class WiFiLCDInterface:
    def __init__(self):
        if not LCD_AVAILABLE:
            raise Exception("LCD hardware not available")

        self.wifi_manager = WiFiManager()

        # LCD setup
        self.LCD = LCD_1in44.LCD()
        self.LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        self.canvas = Image.new("RGB", (128, 128), hex_to_rgb(COLOR_BG_0))
        self.font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
        self.font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)

        # GPIO setup
        GPIO.setmode(GPIO.BCM)
        self.setup_buttons()

        # DarkSecKeyboard for password entry
        self.keyboard = DarkSecKeyboard(
            width=128, height=128, lcd=self.LCD,
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

    def draw_scanlines(self, img):
        """Add CRT scanlines overlay."""
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        for y in range(0, 128, 2):
            d.line([(0, y), (128, y)], fill=hex_to_rgb("#1a0000"))

    def draw_header(self, title):
        """Draw cyberpunk menu header."""
        d = ImageDraw.Draw(self.canvas)
        d.rectangle([(0, 0), (128, 16)], fill=hex_to_rgb(COLOR_HEADER))
        d.text((4, 3), title[:20], fill=hex_to_rgb(COLOR_ACCENT), font=self.font_md)

    def draw_status_bar(self):
        """Draw connection status at bottom."""
        d = ImageDraw.Draw(self.canvas)
        status = self.wifi_manager.get_connection_status()

        d.rectangle([(0, 116), (128, 128)], fill=hex_to_rgb(COLOR_BG_1))
        d.rectangle([(0, 115), (128, 116)], fill=hex_to_rgb(COLOR_ACCENT))

        if status["status"] == "connected":
            status_text = f"📶 {status['ssid'][:12]}"
            color = hex_to_rgb(COLOR_WARN)
        else:
            status_text = "Disconnected"
            color = hex_to_rgb(COLOR_FG_MUTED)

        d.text((4, 118), status_text[:20], fill=color, font=self.font_sm)

    def draw_main_menu(self):
        """Draw main WiFi menu."""
        self.canvas.paste(Image.new("RGB", (128, 128), hex_to_rgb(COLOR_BG_0)))
        d = ImageDraw.Draw(self.canvas)

        self.draw_header("WiFi MANAGER")

        menu_items = [
            "SCAN NETWORKS",
            "SAVED PROFILES",
            "QUICK CONNECT",
            "STATUS & INFO",
            "EXIT"
        ]

        y_pos = 20
        for i, item in enumerate(menu_items):
            if i == self.menu_index:
                d.rectangle([(0, y_pos-1), (128, y_pos+11)], fill=hex_to_rgb(COLOR_ACCENT))
                color = hex_to_rgb(COLOR_BG_0)
            else:
                color = hex_to_rgb(COLOR_FG)

            d.text((4, y_pos), item[:18], fill=color, font=self.font_md)
            y_pos += 14

        # Button hints
        d.text((2, 101), "UP/DN OK KEY3:back", fill=hex_to_rgb(COLOR_FG_MUTED), font=self.font_sm)
        self.draw_status_bar()
        self.draw_scanlines(self.canvas)
        self.LCD.LCD_ShowImage(self.canvas, 0, 0)

    def draw_network_scan(self):
        """Draw scanned networks list."""
        self.canvas.paste(Image.new("RGB", (128, 128), hex_to_rgb(COLOR_BG_0)))
        d = ImageDraw.Draw(self.canvas)

        self.draw_header("AVAILABLE NETWORKS")

        if not self.scanned_networks:
            d.text((4, 30), "No networks found", fill=hex_to_rgb(COLOR_FG_MUTED), font=self.font_md)
            d.text((4, 45), "KEY2: Scan again", fill=hex_to_rgb(COLOR_WARN), font=self.font_sm)
        else:
            y_pos = 20
            display_count = min(5, len(self.scanned_networks))
            start_idx = max(0, self.menu_index - 2)

            for i in range(start_idx, min(start_idx + display_count, len(self.scanned_networks))):
                network = self.scanned_networks[i]
                ssid = network.get('ssid', 'Unknown')[:14]
                signal = network.get('signal', 0)

                if i == self.menu_index:
                    d.rectangle([(0, y_pos-1), (128, y_pos+11)], fill=hex_to_rgb(COLOR_ACCENT))
                    color = hex_to_rgb(COLOR_BG_0)
                else:
                    color = hex_to_rgb(COLOR_FG)

                encrypted = "🔒" if network.get('encrypted', False) else "🔓"
                d.text((4, y_pos), f"{encrypted} {ssid}", fill=color, font=self.font_md)
                y_pos += 13

        d.text((2, 101), "OK:Connect K3:back", fill=hex_to_rgb(COLOR_FG_MUTED), font=self.font_sm)
        self.draw_status_bar()
        self.draw_scanlines(self.canvas)
        self.LCD.LCD_ShowImage(self.canvas, 0, 0)

    def draw_saved_profiles(self):
        """Draw saved WiFi profiles."""
        self.canvas.paste(Image.new("RGB", (128, 128), hex_to_rgb(COLOR_BG_0)))
        d = ImageDraw.Draw(self.canvas)

        self.draw_header("SAVED PROFILES")

        if not self.saved_profiles:
            d.text((4, 30), "No saved profiles", fill=hex_to_rgb(COLOR_FG_MUTED), font=self.font_md)
            d.text((4, 45), "Scan & save networks", fill=hex_to_rgb(COLOR_WARN), font=self.font_sm)
        else:
            y_pos = 20
            display_count = min(5, len(self.saved_profiles))
            start_idx = max(0, min(self.menu_index, len(self.saved_profiles) - display_count))

            for i in range(start_idx, min(start_idx + display_count, len(self.saved_profiles))):
                profile = self.saved_profiles[i]
                ssid = profile.get('ssid', 'Unknown')[:14]

                if i == self.menu_index:
                    d.rectangle([(0, y_pos-1), (128, y_pos+11)], fill=hex_to_rgb(COLOR_ACCENT))
                    color = hex_to_rgb(COLOR_BG_0)
                else:
                    color = hex_to_rgb(COLOR_FG)

                d.text((4, y_pos), ssid, fill=color, font=self.font_md)
                y_pos += 13

        d.text((2, 101), "OK:Connect K3:back", fill=hex_to_rgb(COLOR_FG_MUTED), font=self.font_sm)
        self.draw_status_bar()
        self.draw_scanlines(self.canvas)
        self.LCD.LCD_ShowImage(self.canvas, 0, 0)

    def draw_status_info(self):
        """Draw connection status and info."""
        self.canvas.paste(Image.new("RGB", (128, 128), hex_to_rgb(COLOR_BG_0)))
        d = ImageDraw.Draw(self.canvas)

        self.draw_header("STATUS & INFO")

        status = self.wifi_manager.get_connection_status()
        lines = [
            f"Status: {status['status'].upper()}",
            f"SSID: {status.get('ssid', 'N/A')[:12]}",
            f"Signal: {status.get('signal', 0)}",
            f"IP: {status.get('ip', 'N/A')[:15]}",
        ]

        y_pos = 20
        for line in lines:
            d.text((4, y_pos), line[:20], fill=hex_to_rgb(COLOR_FG), font=self.font_sm)
            y_pos += 13

        d.text((2, 101), "K2:Refresh K3:back", fill=hex_to_rgb(COLOR_FG_MUTED), font=self.font_sm)
        self.draw_status_bar()
        self.draw_scanlines(self.canvas)
        self.LCD.LCD_ShowImage(self.canvas, 0, 0)

    def get_password_input(self):
        """Get password using DarkSecKeyboard."""
        return self.keyboard.run()

    def handle_main_menu(self):
        """Handle main menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "UP":
            self.menu_index = (self.menu_index - 1) % 5
        elif btn == "DOWN":
            self.menu_index = (self.menu_index + 1) % 5
        elif btn == "OK":
            if self.menu_index == 0:  # Scan Networks
                self.current_menu = "scan"
                self.menu_index = 0
            elif self.menu_index == 1:  # Saved Profiles
                self.current_menu = "profiles"
                self.menu_index = 0
            elif self.menu_index == 2:  # Quick Connect
                self.current_menu = "quick"
                self.menu_index = 0
            elif self.menu_index == 3:  # Status & Info
                self.current_menu = "status"
            elif self.menu_index == 4:  # Exit
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
            self.menu_index = min(len(self.scanned_networks) - 1, self.menu_index + 1)
        elif btn == "OK" and self.scanned_networks:
            network = self.scanned_networks[self.menu_index]
            ssid = network.get('ssid', '')

            # Get password if encrypted
            password = ""
            if network.get('encrypted', False):
                password = self.get_password_input()
                if password is None:
                    self.current_menu = "main"
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

    def handle_status_menu(self):
        """Handle status menu navigation."""
        btn = self.wait_btn(0.3)

        if btn == "KEY2":
            self.refresh_data()
        elif btn == "KEY3":
            self.current_menu = "main"

    def wait_btn(self, timeout=0.1):
        """Wait for button press."""
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
                elif self.current_menu == "status":
                    self.draw_status_info()
                    self.handle_status_menu()

                time.sleep(0.05)
        finally:
            self.LCD.LCD_Clear()
            GPIO.cleanup()


def main():
    """Launch WiFi LCD interface."""
    try:
        interface = WiFiLCDInterface()
        interface.run()
    except Exception as e:
        print(f"Error: {e}")
        return False
    return True


if __name__ == "__main__":
    main()
