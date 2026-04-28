#!/usr/bin/env python3
"""KTOx WiFi LCD interface (cyberpunk theme + shared keyboard)."""

import os
import sys
import time
from typing import List

BASE_DIR = "/root/KTOx"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Allow direct execution from repo checkout as fallback.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    import RPi.GPIO as GPIO
    from wifi_manager import WiFiManager
    from _darksec_keyboard import DarkSecKeyboard
    LCD_AVAILABLE = True
except Exception as exc:
    print(f"LCD not available: {exc}")
    LCD_AVAILABLE = False


COLORS = {
    "BG": (10, 0, 0),
    "PANEL": (34, 0, 0),
    "HEADER": (139, 0, 0),
    "FG": (171, 178, 185),
    "ACCENT": (231, 76, 60),
    "WARN": (212, 172, 13),
    "DIM": (113, 125, 126),
    "WHITE": (255, 255, 255),
    "GOOD": (46, 204, 113),
}


class WiFiLCDInterface:
    BUTTONS = {
        "UP": 6,
        "DOWN": 19,
        "LEFT": 5,
        "RIGHT": 26,
        "OK": 13,
        "CENTER": 13,  # alias for compatibility
        "KEY1": 21,
        "KEY2": 20,
        "KEY3": 16,
    }

    MAIN_MENU = [
        "Scan Networks",
        "Saved Profiles",
        "Quick Connect",
        "Interface Config",
        "Status & Info",
        "Disconnect",
        "Exit",
    ]

    def __init__(self):
        if not LCD_AVAILABLE:
            raise RuntimeError("LCD hardware not available")

        self.wifi_manager = WiFiManager()
        self.lcd = LCD_1in44.LCD()
        self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        self.canvas = Image.new("RGB", (128, 128), COLORS["BG"])
        self.draw = ImageDraw.Draw(self.canvas)

        self.font = self._load_font(8)
        self.bold = self._load_font(9)

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in {v for k, v in self.BUTTONS.items() if k != "CENTER"}:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self.current_menu = "main"
        self.menu_index = 0
        self.running = True

        self.scanned_networks = []
        self.saved_profiles = []
        self.refresh_data()

    def _load_font(self, size: int):
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def refresh_data(self):
        self.scanned_networks = self.wifi_manager.scan_networks()
        self.saved_profiles = self.wifi_manager.load_profiles()

    def _clear(self):
        self.draw.rectangle((0, 0, 127, 127), fill=COLORS["BG"])

    def _header(self, title: str):
        self._clear()
        self.draw.rectangle((0, 0, 127, 13), fill=COLORS["HEADER"])
        self.draw.text((3, 3), title[:19], font=self.bold, fill=COLORS["WHITE"])

    def _status_line(self):
        status = self.wifi_manager.get_connection_status()
        self.draw.rectangle((0, 116, 127, 127), fill=COLORS["PANEL"])
        if status.get("status") == "connected":
            txt = f"UP {status.get('ssid', '')[:12]}"
            clr = COLORS["GOOD"]
        else:
            txt = "DOWN disconnected"
            clr = COLORS["WARN"]
        self.draw.text((2, 118), txt[:20], font=self.font, fill=clr)

    def _draw_list(self, title: str, lines: List[str], selected: int, hint: str):
        self._header(title)
        if not lines:
            self.draw.text((4, 34), "No entries", font=self.bold, fill=COLORS["WARN"])
        else:
            visible = 7
            start = max(0, min(selected - 3, max(0, len(lines) - visible)))
            y = 17
            for i in range(start, min(start + visible, len(lines))):
                if i == selected:
                    self.draw.rectangle((1, y - 1, 126, y + 10), fill=COLORS["PANEL"])
                    mark = ">"
                    color = COLORS["WHITE"]
                else:
                    mark = " "
                    color = COLORS["FG"]
                self.draw.text((3, y), f"{mark} {lines[i][:18]}", font=self.font, fill=color)
                y += 14

        self.draw.text((2, 106), hint[:24], font=self.font, fill=COLORS["DIM"])
        self._status_line()

    def _show_message(self, text: str, seconds: float = 1.3):
        self._header("WiFi Manager")
        self.draw.text((4, 48), text[:20], font=self.bold, fill=COLORS["ACCENT"])
        self._status_line()
        self._flush()
        time.sleep(seconds)

    def _flush(self):
        self.lcd.LCD_ShowImage(self.canvas, 0, 0)

    def _normalize_ok(self, btn):
        return "OK" if btn == "CENTER" else btn

    def _read_button(self):
        if not hasattr(self, "_debounce"):
            self._debounce = {k: 0.0 for k in self.BUTTONS.keys()}
            self._states = {k: 1 for k in self.BUTTONS.keys()}
        now = time.time()

        for name, pin in self.BUTTONS.items():
            if name == "CENTER":
                continue
            state = GPIO.input(pin)
            if self._states[name] == 1 and state == 0 and now - self._debounce[name] > 0.16:
                self._debounce[name] = now
                self._states[name] = state
                return name
            self._states[name] = state
        return None

    def _render_main(self):
        self._draw_list("WiFi Manager", self.MAIN_MENU, self.menu_index, "UP/DN nav  OK select")

    def _render_scan(self):
        rows = []
        for net in self.scanned_networks:
            lock = "L" if net.get("encrypted", False) else "O"
            ssid = net.get("ssid", "<hidden>")
            rows.append(f"{lock} {ssid}")
        self._draw_list("Scan Results", rows, self.menu_index, "OK connect K2 refresh")

    def _render_profiles(self):
        rows = [f"{p.get('ssid', 'unknown')}" for p in self.saved_profiles]
        self._draw_list("Saved Profiles", rows, self.menu_index, "OK connect K2 delete")

    def _render_interfaces(self):
        interfaces = ["eth0"] + self.wifi_manager.wifi_interfaces
        current = self.wifi_manager.get_interface_for_tool()
        rows = [f"* {i}" if i == current else f"  {i}" for i in interfaces]
        self._draw_list("Interface Config", rows, self.menu_index, "OK set  K3 back")

    def _render_status(self):
        self._header("Status & Info")
        st = self.wifi_manager.get_connection_status()
        y = 18
        if st.get("status") == "connected":
            self.draw.text((4, y), f"SSID: {st.get('ssid', '-')}", font=self.font, fill=COLORS["GOOD"])
            y += 12
            self.draw.text((4, y), f"IP: {st.get('ip', '-')}", font=self.font, fill=COLORS["FG"])
            y += 12
            self.draw.text((4, y), f"IF: {st.get('interface', '-')}", font=self.font, fill=COLORS["FG"])
            y += 12
        else:
            self.draw.text((4, y), "WiFi disconnected", font=self.font, fill=COLORS["WARN"])
            y += 12

        self.draw.text((4, y + 4), f"Adapters: {len(self.wifi_manager.wifi_interfaces)}", font=self.font, fill=COLORS["FG"])
        y += 18
        for iface in self.wifi_manager.wifi_interfaces[:4]:
            self.draw.text((8, y), f"- {iface}", font=self.font, fill=COLORS["DIM"])
            y += 10

        self.draw.text((2, 106), "KEY2 refresh  KEY3 back", font=self.font, fill=COLORS["DIM"])
        self._status_line()

    def _run_keyboard(self, title: str = "Password"):
        self._show_message(f"{title} via VKB", 0.35)
        kb = DarkSecKeyboard(
            width=128,
            height=128,
            lcd=self.lcd,
            gpio_pins=self.BUTTONS,
            gpio_module=GPIO,
        )
        return kb.run()

    def _connect_scanned(self):
        if not self.scanned_networks:
            return
        net = self.scanned_networks[self.menu_index]
        ssid = net.get("ssid")
        if not ssid:
            self._show_message("SSID unavailable")
            return

        password = None
        if net.get("encrypted", False):
            password = self._run_keyboard(f"PW {ssid[:10]}")
            if password is None:
                self._show_message("Canceled", 0.8)
                return

        self._show_message(f"Connecting {ssid[:10]}", 0.4)
        ok = self.wifi_manager.connect_to_network(ssid, password=password)
        if ok:
            self.wifi_manager.save_profile(ssid, password or "", "auto", 1, True)
            self._show_message("Connected")
        else:
            self._show_message("Connect failed")

    def _connect_profile(self):
        if not self.saved_profiles:
            return
        profile = self.saved_profiles[self.menu_index]
        ssid = profile.get("ssid", "unknown")
        self._show_message(f"Connecting {ssid[:10]}", 0.4)
        if self.wifi_manager.connect_to_profile(profile):
            self._show_message("Connected")
        else:
            self._show_message("Connect failed")

    def _delete_profile(self):
        if not self.saved_profiles:
            return
        ssid = self.saved_profiles[self.menu_index].get("ssid", "")
        if self.wifi_manager.delete_profile(ssid):
            self._show_message("Profile deleted")
            self.saved_profiles = self.wifi_manager.load_profiles()
            self.menu_index = min(self.menu_index, max(0, len(self.saved_profiles) - 1))
        else:
            self._show_message("Delete failed")

    def _set_interface(self):
        interfaces = ["eth0"] + self.wifi_manager.wifi_interfaces
        if not interfaces:
            return
        selected = interfaces[self.menu_index]
        self.wifi_manager.log(f"Selected default interface: {selected}")
        self._show_message(f"Selected {selected}")

    def _handle_main(self, btn):
        if btn == "UP":
            self.menu_index = (self.menu_index - 1) % len(self.MAIN_MENU)
        elif btn == "DOWN":
            self.menu_index = (self.menu_index + 1) % len(self.MAIN_MENU)
        elif btn == "OK":
            target = self.MAIN_MENU[self.menu_index]
            if target == "Scan Networks":
                self.current_menu = "scan"
                self.menu_index = 0
                self.refresh_data()
            elif target == "Saved Profiles":
                self.current_menu = "profiles"
                self.menu_index = 0
                self.saved_profiles = self.wifi_manager.load_profiles()
            elif target == "Quick Connect":
                self._show_message("Auto connect...", 0.4)
                self._show_message("Connected" if self.wifi_manager.auto_connect() else "No network")
            elif target == "Interface Config":
                self.current_menu = "interface"
                self.menu_index = 0
            elif target == "Status & Info":
                self.current_menu = "status"
            elif target == "Disconnect":
                self._show_message("Disconnecting...", 0.4)
                self._show_message("Disconnected" if self.wifi_manager.disconnect() else "Nothing to do")
            elif target == "Exit":
                self.running = False

    def _handle_scan(self, btn):
        if self.scanned_networks:
            if btn == "UP":
                self.menu_index = (self.menu_index - 1) % len(self.scanned_networks)
            elif btn == "DOWN":
                self.menu_index = (self.menu_index + 1) % len(self.scanned_networks)
            elif btn == "OK":
                self._connect_scanned()
        if btn == "KEY2":
            self.refresh_data()
            self.menu_index = 0
        elif btn == "KEY3":
            self.current_menu = "main"
            self.menu_index = 0

    def _handle_profiles(self, btn):
        if self.saved_profiles:
            if btn == "UP":
                self.menu_index = (self.menu_index - 1) % len(self.saved_profiles)
            elif btn == "DOWN":
                self.menu_index = (self.menu_index + 1) % len(self.saved_profiles)
            elif btn == "OK":
                self._connect_profile()
            elif btn == "KEY2":
                self._delete_profile()
        if btn == "KEY3":
            self.current_menu = "main"
            self.menu_index = 0

    def _handle_interface(self, btn):
        interfaces = ["eth0"] + self.wifi_manager.wifi_interfaces
        if interfaces:
            if btn == "UP":
                self.menu_index = (self.menu_index - 1) % len(interfaces)
            elif btn == "DOWN":
                self.menu_index = (self.menu_index + 1) % len(interfaces)
            elif btn == "OK":
                self._set_interface()
        if btn == "KEY3":
            self.current_menu = "main"
            self.menu_index = 0

    def _handle_status(self, btn):
        if btn == "KEY2":
            self.refresh_data()
        elif btn == "KEY3":
            self.current_menu = "main"
            self.menu_index = 0

    def _render(self):
        if self.current_menu == "main":
            self._render_main()
        elif self.current_menu == "scan":
            self._render_scan()
        elif self.current_menu == "profiles":
            self._render_profiles()
        elif self.current_menu == "interface":
            self._render_interfaces()
        elif self.current_menu == "status":
            self._render_status()
        self._flush()

    def run(self):
        self.wifi_manager.log("Starting WiFi LCD interface (cyberpunk)")
        last = 0.0
        try:
            while self.running:
                now = time.time()
                if now - last > 1.5:
                    self._render()
                    last = now

                btn = self._normalize_ok(self._read_button())
                if btn:
                    if self.current_menu == "main":
                        self._handle_main(btn)
                    elif self.current_menu == "scan":
                        self._handle_scan(btn)
                    elif self.current_menu == "profiles":
                        self._handle_profiles(btn)
                    elif self.current_menu == "interface":
                        self._handle_interface(btn)
                    elif self.current_menu == "status":
                        self._handle_status(btn)
                    self._render()
                    last = time.time()

                time.sleep(0.01)
        finally:
            self.wifi_manager.log("Stopping WiFi LCD interface")
            GPIO.cleanup()


def main():
    if not LCD_AVAILABLE:
        print("LCD/driver stack unavailable")
        return

    ui = WiFiLCDInterface()
    ui.run()


if __name__ == "__main__":
    main()
