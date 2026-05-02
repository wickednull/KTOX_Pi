#!/usr/bin/env python3
# NAME: USB Army Knife Controller
# USB Army Knife Marauder Controller for KTOx_Pi
# Full command set – selects target APs/stations, runs attacks, displays output on LCD

import os
import sys
import time
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except Exception as e:
    serial = None
    HAS_SERIAL = False
    SERIAL_IMPORT_ERROR = str(e)
from datetime import datetime

# KTOx environment
KTOX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, KTOX_DIR)

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except Exception:
    HAS_HW = False

try:
    from ktox_device import draw_lock, LCD, image, draw, text_font, small_font, color, getButton, Dialog_info
    # Check if draw is actually available (None in headless mode)
    HAS_LCD = draw is not None
    if not HAS_LCD:
        print("[WARN] LCD/UI unavailable (headless mode)")
        Dialog_info = None
        getButton = None
except Exception as e:
    print(f"[WARN] LCD/UI unavailable: {e}")
    HAS_LCD = False
    draw_lock = None
    Dialog_info = None
    getButton = None
    color = None
    draw = None
    text_font = None
    small_font = None

# ------------------------------------------------------------
# Serial connection to USB Army Knife
# ------------------------------------------------------------
SERIAL_BAUD = 115200
PROMPT_PATTERNS = ("marauder>", "Marauder>", ">")

class USBArmyKnife:
    def __init__(self):
        self.ser = None
        self.last_error = None
        self.port = self._find_port()

    def _find_port(self):
        if not HAS_SERIAL:
            self.last_error = f"pyserial unavailable: {SERIAL_IMPORT_ERROR}"
            return None

        # Try to auto‑detect by VID/PID (CP210x is common)
        for port in serial.tools.list_ports.comports():
            desc = port.description or ""
            prod = port.product or ""
            # Check for common patterns: USB Army Knife, CP210x, or FTDI chips
            if any(x in desc for x in ["USB Army Knife", "CP210x", "FTDI"]) or "210x" in prod:
                return port.device
        # Fallback to common TTY names
        for dev in ["/dev/ttyACM0", "/dev/ttyUSB0"]:
            if os.path.exists(dev):
                return dev
        return None

    def connect(self):
        if not HAS_SERIAL:
            self.last_error = f"pyserial unavailable: {SERIAL_IMPORT_ERROR}"
            return False
        if not self.port:
            self.last_error = "No serial port detected for USB Army Knife"
            return False
        try:
            self.ser = serial.Serial(self.port, SERIAL_BAUD, timeout=2)
            time.sleep(1.5)
            self.ser.write(b"\r\n")
            time.sleep(0.5)
            self.ser.reset_input_buffer()
            return True
        except Exception as e:
            self.last_error = f"Connect error: {e}"
            print(f"[Marauder] {self.last_error}")
            return False

    def send_command(self, cmd, wait_for_prompt=True, timeout=15):
        if not self.ser or not self.ser.is_open:
            if not self.connect():
                return ["[ERROR] Cannot connect to USB Army Knife"]
        self.ser.write(f"{cmd}\r\n".encode())
        if not wait_for_prompt:
            return []

        output = []
        buffer = ""
        start = time.time()
        last_data = time.time()
        while (time.time() - start) < timeout:
            try:
                chunk = self.ser.read(256).decode(errors='ignore')
                if chunk:
                    last_data = time.time()
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            output.append(line)
                            if any(p in line for p in PROMPT_PATTERNS):
                                return output
                else:
                    if output and (time.time() - last_data) > 1.0:
                        return output
                    time.sleep(0.05)
            except Exception as e:
                self.last_error = f"Serial read error: {e}"
                break

        if buffer.strip():
            output.append(buffer.strip())
        return output if output else ["[TIMEOUT] No response"]

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

# ------------------------------------------------------------
# Menu structure – full command set
# ------------------------------------------------------------
COMMAND_CATEGORIES = {
    "📡 Scan / Sniff": [
        ("scanap",              "Scan for access points"),
        ("scansta",             "Scan for stations (clients)"),
        ("scanall",             "Scan for both APs and stations"),
        ("sniffbeacon",         "Capture beacon frames"),
        ("sniffdeauth",         "Capture deauth packets"),
        ("sniffpmkid -c 1",     "Capture PMKID on channel 1"),
        ("packetcount",         "Show packet rate"),
        ("sigmon",              "Signal strength monitor"),
    ],
    "⚔️ Attacks": [
        ("attack -t deauth -a",     "Deauth attack (all clients)"),
        ("attack -t deauth -s",     "Deauth attack (selected target)"),
        ("attack -t beacon -r",     "Beacon flood (random SSIDs)"),
        ("attack -t beacon -l",     "Beacon flood (from SSID list)"),
        ("attack -t probe",         "Probe request flood"),
        ("attack -t rickroll",      "Rick Roll beacon flood"),
    ],
    "🎯 Target Mgmt": [
        ("list -a",                 "List all APs"),
        ("list -s",                 "List all stations (clients)"),
        ("list -c",                 "List all clients"),
        ("select -a 0",             "Select AP index 0"),
        ("select -s 0,1",           "Select stations 0 and 1"),
        ("select -f 'contains Home'", "Select APs containing 'Home'"),
        ("clearlist -a",            "Clear AP list"),
        ("clearlist -s",            "Clear station list"),
    ],
    "📀 SSID Mgmt (beacon lists)": [
        ("ssid -a -n 'FreeWiFi'",   "Add SSID 'FreeWiFi'"),
        ("ssid -r 0",               "Remove first SSID"),
        ("save -a",                 "Save AP list to SD"),
        ("load -a",                 "Load AP list from SD"),
        ("clearlist -s",            "Clear SSID list"),
    ],
    "🧠 Bluetooth": [
        ("sniffbt -t airtag",       "Scan for AirTags"),
        ("sniffbt -t flipper",      "Scan for Flipper Zero devices"),
        ("blespam -t apple",        "Apple BLE spam"),
        ("blespam -t samsung",      "Samsung BLE spam"),
        ("blespam -t windows",      "Windows BLE spam"),
        ("spoofat -t 0",            "Spoof AirTag #0"),
    ],
    "🖥️ System / LED / Logs": [
        ("help",                    "Show command list"),
        ("channel -s 6",            "Set WiFi channel 6"),
        ("reboot",                  "Reboot USB Army Knife"),
        ("settings -s SavePCAP enable", "Enable PCAP saving"),
        ("led -s #FF0000",          "Set LED to red"),
        ("stopscan",                "Stop any scan/attack"),
        ("clear",                   "Clear device screen"),
        ("ls /",                    "List files on SD card"),
    ],
    "✨ Advanced": [
        ("evilportal -c start",     "Start Evil Portal"),
        ("gps -g fix",              "Get GPS fix"),
    ],
}

# ------------------------------------------------------------
# UI helper functions (LCD or headless fallback)
# ------------------------------------------------------------


def _port_label(port_info):
    desc = port_info.description or "Unknown"
    return f"{port_info.device} — {desc[:40]}"

def select_serial_port(current_port=None):
    """Return a serial device path selected by user/LCD, or None if cancelled."""
    if not HAS_SERIAL:
        return None

    ports = list(serial.tools.list_ports.comports())
    if not ports:
        # fallback to common device names when enumeration fails
        fallback = [dev for dev in ["/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyUSB1"] if os.path.exists(dev)]
        if len(fallback) == 1:
            return fallback[0]
        if fallback:
            return get_menu_selection(fallback, title="SELECT SERIAL")
        return None

    menu = [_port_label(p) for p in ports]
    selected = get_menu_selection(menu, title="SELECT SERIAL")
    if not selected:
        return current_port

    idx = menu.index(selected)
    return ports[idx].device

def show_message(text, wait=True, timeout=None):
    """Display message on LCD if available, otherwise print to console."""
    if HAS_LCD and Dialog_info:
        Dialog_info(text, wait=wait, timeout=timeout)
    else:
        print(f"[INFO] {text.replace(chr(10), ' / ')}")
        if wait and not timeout:
            try:
                input("Press Enter to continue...")
            except EOFError:
                pass
        elif timeout:
            time.sleep(timeout)

def get_menu_selection(items, title="Select"):
    """Get menu selection from LCD or console."""
    if HAS_LCD:
        return _get_menu_string(items, title=title)
    else:
        print(f"\n{title}")
        for i, item in enumerate(items):
            print(f"  {i+1}. {item}")
        try:
            choice = int(input("Enter number (0 to cancel): ")) - 1
            return items[choice] if 0 <= choice < len(items) else None
        except (ValueError, IndexError, EOFError):
            return None

# ------------------------------------------------------------
# LCD scrolling text viewer
# ------------------------------------------------------------
def show_scrollable_text(title, lines):
    if not lines:
        lines = ["(no output)"]

    if not HAS_LCD or draw is None:
        # Headless mode: just print output
        print(f"\n--- {title} ---")
        for line in lines:
            print(line)
        print("\nPress Enter to continue...")
        try:
            input()
        except EOFError:
            pass
        return

    # LCD mode: scrollable text viewer
    # Truncate long lines to fit 128px width
    max_len = 21
    display_lines = []
    for l in lines:
        if len(l) > max_len:
            l = l[:max_len-3] + "..."
        display_lines.append(l)

    idx = 0
    window = 5
    total = len(display_lines)
    while True:
        offset = max(0, min(idx, total - window))
        with draw_lock:
            draw.rectangle([0, 12, 128, 128], fill=color.background)
            color.DrawBorder()
            draw.rectangle([3, 13, 125, 24], fill="#1a0000")
            _centered(title[:18], 13, font=small_font, fill=color.border)
            draw.line([(3,24),(125,24)], fill=color.border, width=1)
            y = 28
            for i in range(window):
                line_idx = offset + i
                if line_idx >= total: break
                draw.text((5, y), display_lines[line_idx], font=text_font, fill=color.text)
                y += 12
            draw.line([3, 118, 125, 118], fill="#2a0505", width=1)
            _centered("▲/▼ scroll  ●=back", 120, font=small_font, fill="#888888")
        btn = getButton()
        if btn == "KEY_UP_PIN":
            idx = max(0, idx-1)
        elif btn == "KEY_DOWN_PIN":
            idx = min(total-1, idx+1)
        elif btn in ("KEY_PRESS_PIN", "KEY_LEFT_PIN", "KEY1_PIN", "KEY2_PIN", "KEY3_PIN"):
            break

def _centered(text, y, font=small_font, fill="#c8c8c8"):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
    except Exception:
        try:
            w, _ = draw.textsize(text, font=font)
        except Exception:
            w = len(text) * 6
    draw.text(((128 - w) // 2, y), text, font=font, fill=fill)

# ------------------------------------------------------------
# Main payload entry point
# ------------------------------------------------------------
def run():
    show_message("USB Army Knife\nInitialising...", wait=False, timeout=1)
    knife = USBArmyKnife()

    # Let user choose serial port when multiple adapters are attached
    if HAS_SERIAL:
        chosen_port = select_serial_port(knife.port)
        if chosen_port:
            knife.port = chosen_port

    if not knife.connect():
        err = knife.last_error or "Device not found"
        show_message(f"Connection failed:\n{err[:70]}", wait=True)
        return

    # Test communication by asking for help
    test = knife.send_command("help", timeout=6)
    if not test or any("[ERROR]" in x for x in test):
        show_message("Device not responding\nCheck connection", wait=True)
        knife.close()
        return

    # Main menu loop
    while True:
        # Build category list for menu
        cat_labels = list(COMMAND_CATEGORIES.keys())
        # Use KTOx's built‑in menu selector or console fallback
        selected_cat = get_menu_selection(cat_labels, title="SELECT CATEGORY")
        if not selected_cat:
            break

        # Show commands in that category
        cmd_list = COMMAND_CATEGORIES[selected_cat]
        menu_items = [f"{cmd[0]}  ({cmd[1][:15]})" for cmd in cmd_list]
        selected_cmd_desc = get_menu_selection(menu_items, title=selected_cat[:18])
        if not selected_cmd_desc:
            continue

        # Extract pure command string
        chosen_cmd = None
        for cmd, desc in cmd_list:
            if cmd in selected_cmd_desc:
                chosen_cmd = cmd
                break
        if not chosen_cmd:
            continue

        # Sanity check before dangerous commands
        dangerous = ["reboot", "attack -t deauth", "attack -t beacon", "attack -t probe"]
        if any(d in chosen_cmd for d in dangerous):
            if not _confirm_choice(f"Send:\n{chosen_cmd[:18]}"):
                continue

        # Dispatch command and show output
        show_message(f"Sending: {chosen_cmd[:20]}...", wait=False, timeout=1)
        if HAS_LCD and draw_lock and draw and color:
            try:
                with draw_lock:
                    draw.rectangle([0,12,128,128], fill=color.background)
                    color.DrawBorder()
                    _centered("Sending command...", 40)
                    _centered(chosen_cmd[:20], 60)
            except Exception:
                pass
        output = knife.send_command(chosen_cmd, wait_for_prompt=True, timeout=15)
        show_scrollable_text(chosen_cmd[:18], output)

    knife.close()

def _get_menu_string(items, title="Select"):
    """Use KTOx's GetMenuString if available, otherwise use a button-driven fallback."""
    try:
        from ktox_device import GetMenuString
        return GetMenuString(items)
    except Exception:
        pass

    if not items:
        return None
    if not (HAS_LCD and draw is not None and getButton is not None):
        return items[0]

    idx = 0
    window = 5
    while True:
        start = max(0, min(idx, len(items) - window))
        with draw_lock:
            draw.rectangle([0, 12, 128, 128], fill=color.background)
            color.DrawBorder()
            draw.rectangle([3, 13, 125, 24], fill="#1a0000")
            _centered(title[:18], 13, font=small_font, fill=color.border)
            y = 28
            for i in range(window):
                item_idx = start + i
                if item_idx >= len(items):
                    break
                prefix = ">" if item_idx == idx else " "
                line = f"{prefix} {items[item_idx]}"[:20]
                draw.text((5, y), line, font=text_font, fill=color.text)
                y += 12

        btn = getButton()
        if btn == "KEY_UP_PIN":
            idx = (idx - 1) % len(items)
        elif btn == "KEY_DOWN_PIN":
            idx = (idx + 1) % len(items)
        elif btn in ("KEY_PRESS_PIN", "KEY_RIGHT_PIN", "KEY1_PIN"):
            return items[idx]
        elif btn in ("KEY_LEFT_PIN", "KEY3_PIN"):
            return None

def _confirm_choice(msg):
    """Confirm a dangerous action (headless or LCD)."""
    if HAS_LCD:
        try:
            from ktox_device import YNDialog
            return YNDialog(msg, y="Yes", n="No")
        except Exception:
            pass
    # Headless fallback
    print(f"\n{msg}")
    try:
        response = input("Proceed? (yes/no): ").strip().lower()
    except EOFError:
        return False
    return response in ("yes", "y", "true", "1")

if __name__ == "__main__":
    run()
