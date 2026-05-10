#!/usr/bin/env python3
"""
KTOx Payload – Pet Rock WiFi Edition
===================================================
Active WiFi reconnaissance game. The more PMKIDs and handshakes
you gather, the happier (and smugger) the rock gets.

Press OK to pet it (get motivation).
Press UP/DOWN to select WiFi adapter.
Press KEY2 for status (hs count, pmk count).
Press KEY3 to exit.
"""

import time
import random
import os
import subprocess
import threading
import re
import signal
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

try:
    import LCD_1in44
    HAS_LCD = True
except:
    HAS_LCD = False

# Hardware setup
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13,
        "KEY1":21, "KEY2":20, "KEY3":16}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

if HAS_LCD:
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
f9 = font(9)
f11 = font(11)

# Motivational responses based on progress
MOTIVATIONS = {
    "angry": [
        "Come on, more traffic!",
        "Find some networks!",
        "Stop wasting time!",
        "No handshakes yet?",
        "This is pathetic.",
        "Get to work!",
    ],
    "bored": [
        "You're doing okay...",
        "Keep scanning.",
        "Not bad so far.",
        "Maybe move around?",
        "Patience pays off.",
        "More data needed.",
    ],
    "neutral": [
        "Nice progress!",
        "You're getting it.",
        "Good work!",
        "Keep it up!",
        "Impressive pace.",
        "Not bad at all.",
    ],
    "smug": [
        "I'm proud of you.",
        "You're a natural!",
        "Expert gathering!",
        "Magnificent work!",
        "Absolutely stellar!",
        "I'm impressed!",
    ],
}

def draw_rock_face(expression="neutral", blink=False, shake=0, message=None):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)

    # Title bar
    d.rectangle((0,0,W,17), fill=(139, 0, 0))
    d.text((4,3), "ROCK WiFi", font=f9, fill=(231, 76, 60))
    d.text((75,3), "K2 K3", font=f9, fill=(192, 57, 43))

    # Rock body
    cx, cy = W//2, H//2 - 10
    rx, ry = 40, 30
    off_x = random.randint(-shake, shake) if shake else 0
    off_y = random.randint(-shake, shake) if shake else 0
    d.ellipse((cx-rx+off_x, cy-ry+off_y, cx+rx+off_x, cy+ry+off_y), fill=(113, 125, 126), outline=(86, 101, 115), width=2)

    # Texture cracks
    d.line((cx-20+off_x, cy-10+off_y, cx-10+off_x, cy+5+off_y), fill=(34, 0, 0), width=1)
    d.line((cx+10+off_x, cy-15+off_y, cx+25+off_x, cy+0+off_y), fill=(34, 0, 0), width=1)
    d.line((cx-5+off_x, cy+15+off_y, cx+15+off_x, cy+10+off_y), fill=(34, 0, 0), width=1)

    # Eyes
    eye_y = cy - 8
    eye_spacing = 20
    eye_radius = 6
    if blink:
        d.line((cx-eye_spacing-5+off_x, eye_y+off_y, cx-eye_spacing+5+off_x, eye_y+off_y), fill=(10, 0, 0), width=3)
        d.line((cx+eye_spacing-5+off_x, eye_y+off_y, cx+eye_spacing+5+off_x, eye_y+off_y), fill=(10, 0, 0), width=3)
    else:
        d.ellipse((cx-eye_spacing-eye_radius+off_x, eye_y-eye_radius+off_y, cx-eye_spacing+eye_radius+off_x, eye_y+eye_radius+off_y), fill=(242, 243, 244), outline=(10, 0, 0))
        d.ellipse((cx+eye_spacing-eye_radius+off_x, eye_y-eye_radius+off_y, cx+eye_spacing+eye_radius+off_x, eye_y+eye_radius+off_y), fill=(242, 243, 244), outline=(10, 0, 0))

        # Pupils
        pupil_x = 2 if expression == "angry" else -2 if expression == "smug" else 0
        d.ellipse((cx-eye_spacing-2+pupil_x+off_x, eye_y-2+off_y, cx-eye_spacing+2+pupil_x+off_x, eye_y+2+off_y), fill=(10, 0, 0))
        d.ellipse((cx+eye_spacing-2+pupil_x+off_x, eye_y-2+off_y, cx+eye_spacing+2+pupil_x+off_x, eye_y+2+off_y), fill=(10, 0, 0))

    # Mouth
    mouth_y = cy + 8
    if expression == "neutral":
        d.line((cx-10+off_x, mouth_y+off_y, cx+10+off_x, mouth_y+off_y), fill=(10, 0, 0), width=2)
    elif expression == "angry":
        d.line((cx-12+off_x, mouth_y-4+off_y, cx+0+off_x, mouth_y+off_y), fill=(10, 0, 0), width=2)
        d.line((cx+0+off_x, mouth_y+off_y, cx+12+off_x, mouth_y-4+off_y), fill=(10, 0, 0), width=2)
    elif expression == "smug":
        d.arc((cx-12+off_x, mouth_y-6+off_y, cx+12+off_x, mouth_y+6+off_y), start=0, end=180, fill=(10, 0, 0), width=2)
    elif expression == "bored":
        d.arc((cx-12+off_x, mouth_y-4+off_y, cx+12+off_x, mouth_y+4+off_y), start=180, end=360, fill=(10, 0, 0), width=2)

    # If message, draw bubble
    if message:
        d.rectangle((4, H-70, W-4, H-8), fill=(10, 0, 0), outline="#FF3333")
        lines = []
        words = message.split()
        line = ""
        for w in words:
            if len(line + " " + w) <= 22:
                line += (" " + w if line else w)
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        y = H-66
        for l in lines[:5]:
            d.text((6, y), l, font=f9, fill=(171, 178, 185))
            y += 12

    if HAS_LCD:
        LCD.LCD_ShowImage(img, 0, 0)

# WiFi capture management
class WiFiCaptureManager:
    def __init__(self, interface):
        self.interface = interface
        self.mon_interface = None
        self.capture_proc = None
        self.capture_file = Path(f"/tmp/petrock_capture_{interface}")
        self.pmkid_count = 0
        self.handshake_count = 0
        self.scan_thread = None
        self.running = False

    def enable_monitor_mode(self):
        """Enable monitor mode on the interface."""
        try:
            # Kill conflicting processes
            subprocess.run(["airmon-ng", "check", "kill"], capture_output=True, timeout=10)
            time.sleep(1)

            # Enable monitor mode
            result = subprocess.run(
                ["airmon-ng", "start", self.interface],
                capture_output=True, text=True, timeout=10
            )

            time.sleep(2)  # Wait for mode change

            # Determine monitor interface name
            for candidate in [f"{self.interface}mon", f"{self.interface}-mon", f"{self.interface.replace('wlan', 'wlan')}mon"]:
                if self._interface_exists(candidate):
                    self.mon_interface = candidate
                    return True

            # Try to find any mon interface
            result = subprocess.run(["ip", "link", "show"], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'mon' in line and self.interface.replace('wlan', '') in line:
                    match = re.search(r'(\w+):', line)
                    if match:
                        self.mon_interface = match.group(1)
                        return True

            return False
        except Exception as e:
            print(f"Monitor mode error: {e}")
            return False

    def disable_monitor_mode(self):
        """Disable monitor mode and restart NetworkManager."""
        try:
            if self.mon_interface:
                subprocess.run(["airmon-ng", "stop", self.mon_interface], capture_output=True)
            subprocess.run(["systemctl", "restart", "NetworkManager"], capture_output=True)
        except:
            pass

    def _interface_exists(self, iface):
        """Check if interface exists."""
        result = subprocess.run(["ip", "link", "show", iface], capture_output=True)
        return result.returncode == 0

    def start_capture(self):
        """Start airodump-ng capture in background."""
        if not self.mon_interface:
            return False

        try:
            # Clean old files
            for f in Path("/tmp").glob(f"petrock_capture_{self.interface}*"):
                f.unlink()

            # Start airodump-ng
            self.capture_proc = subprocess.Popen(
                ["airodump-ng", "-w", str(self.capture_file), "--output-format", "csv", self.mon_interface],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            time.sleep(2)  # Let it start

            # Start background thread to parse captures
            self.running = True
            self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
            self.scan_thread.start()

            return True
        except Exception as e:
            print(f"Capture error: {e}")
            return False

    def _scan_loop(self):
        """Background thread to parse capture file and count PMKIDs/handshakes."""
        while self.running:
            self._parse_capture_file()
            time.sleep(3)  # Rescan every 3 seconds

    def _parse_capture_file(self):
        """Parse airodump-ng CSV for PMKIDs and handshakes."""
        csv_file = Path(f"{self.capture_file}-01.csv")
        if not csv_file.exists():
            return

        try:
            with open(csv_file, 'r', errors='ignore') as f:
                content = f.read()

            # Count PMKIDs (marked with [PMKID])
            pmkids = content.count('[PMKID]')
            self.pmkid_count = pmkids

            # Count handshakes (marked with [HT] or "EAPOL")
            # In airodump-ng CSV, completed handshakes appear with (4/4) or similar
            handshakes = content.count('(4/4)') or content.count('[HT]')
            self.handshake_count = handshakes

        except Exception as e:
            pass

    def stop_capture(self):
        """Stop capturing."""
        self.running = False
        if self.capture_proc:
            try:
                self.capture_proc.terminate()
                self.capture_proc.wait(timeout=5)
            except:
                self.capture_proc.kill()

    def get_status(self):
        """Get current counts."""
        return self.pmkid_count, self.handshake_count

# Pet Rock with WiFi hunting
class WiFiPetRock:
    def __init__(self, interface):
        self.interface = interface
        self.capture_mgr = WiFiCaptureManager(interface)
        self.mood = "angry"
        self.blink_timer = time.time() + random.uniform(2, 6)
        self.last_interaction = time.time()
        self.msg_display = None
        self.msg_expire = 0

    def update_mood(self):
        """Update mood based on captured data."""
        total = self.capture_mgr.pmkid_count + self.capture_mgr.handshake_count

        if total >= 60:
            self.mood = "smug"
        elif total >= 30:
            self.mood = "neutral"
        elif total >= 15:
            self.mood = "bored"
        else:
            self.mood = "angry"

    def pet(self):
        """User petted the rock - give motivation."""
        self.update_mood()
        msg = random.choice(MOTIVATIONS[self.mood])
        self.msg_display = msg
        self.msg_expire = time.time() + 2.5

    def status(self):
        """Show current captures."""
        pmks, hs = self.capture_mgr.get_status()
        msg = f"pmk:{pmks} hs:{hs}"
        self.msg_display = msg
        self.msg_expire = time.time() + 3.0

    def should_blink(self):
        now = time.time()
        if now >= self.blink_timer:
            self.blink_timer = now + random.uniform(3, 8)
            return True
        return False

# WiFi adapter selection
def select_adapter():
    """Let user choose which WiFi adapter to use."""
    adapters = []
    for iface in ["wlan0", "wlan1", "wlan2"]:
        result = subprocess.run(["ip", "link", "show", iface], capture_output=True)
        if result.returncode == 0:
            adapters.append(iface)

    if not adapters:
        show_message("No WiFi\nadapters\nfound!", 3)
        return None

    if len(adapters) == 1:
        return adapters[0]

    # Show menu
    selection = 0
    while True:
        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        d.rectangle((0,0,W,17), fill=(139, 0, 0))
        d.text((4,3), "Select WiFi", font=f9, fill=(231, 76, 60))

        for i, adapter in enumerate(adapters):
            y = 30 + (i * 20)
            color = "#FF3333" if i == selection else "#AAAAAA"
            d.text((20, y), adapter, font=f11, fill=color)

        d.text((4,110), "K1=start K3=exit", font=f9, fill=(192, 57, 43))

        if HAS_LCD:
            LCD.LCD_ShowImage(img, 0, 0)

        btn = wait_btn(0.1)
        if btn == "UP" and selection > 0:
            selection -= 1
        elif btn == "DOWN" and selection < len(adapters) - 1:
            selection += 1
        elif btn == "KEY1":
            return adapters[selection]
        elif btn == "KEY3":
            return None

def show_message(text, duration=2):
    """Show status message on screen."""
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill=(139, 0, 0))
    d.text((4,3), "ROCK WiFi", font=f9, fill=(231, 76, 60))

    # Draw text centered
    lines = text.split('\n')
    y = 40
    for line in lines:
        d.text((10, y), line, font=f11, fill=(171, 178, 185))
        y += 25

    if HAS_LCD:
        LCD.LCD_ShowImage(img, 0, 0)

    time.sleep(duration)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def main():
    print("[+] Pet Rock WiFi Edition")

    adapter = select_adapter()
    if not adapter:
        show_message("Cancelled", 1)
        return

    show_message(f"Using\n{adapter}", 1.5)
    print(f"[+] Using {adapter}")

    rock = WiFiPetRock(adapter)

    show_message("Enabling\nmonitor\nmode...", 2)
    print("[+] Enabling monitor mode...")

    # Enable monitor mode
    if not rock.capture_mgr.enable_monitor_mode():
        print("[-] Failed to enable monitor mode")
        show_message("Monitor\nmode\nfailed!", 2)
        GPIO.cleanup()
        return

    print(f"[+] Monitor mode: {rock.capture_mgr.mon_interface}")

    show_message("Starting\ncapture...", 2)
    print("[+] Starting capture...")

    # Start capturing
    if not rock.capture_mgr.start_capture():
        print("[-] Failed to start capture")
        show_message("Capture\nfailed!", 2)
        rock.capture_mgr.disable_monitor_mode()
        GPIO.cleanup()
        return

    show_message("Scanning...", 1.5)
    print("[+] Scanning for PMKIDs and handshakes...")

    # Main loop
    try:
        while True:
            now = time.time()
            btn = wait_btn(0.05)

            if btn == "KEY3":
                break
            elif btn == "OK":
                rock.pet()
            elif btn == "KEY2":
                rock.status()

            # Clear message after timeout
            if now >= rock.msg_expire:
                rock.msg_display = None

            # Update mood
            rock.update_mood()

            # Blink animation
            if rock.should_blink():
                draw_rock_face(
                    expression=rock.mood,
                    blink=True,
                    message=rock.msg_display if now < rock.msg_expire else None
                )
                time.sleep(0.1)

            # Draw normal
            draw_rock_face(
                expression=rock.mood,
                blink=False,
                message=rock.msg_display if now < rock.msg_expire else None
            )

            time.sleep(0.05)

    finally:
        print("[+] Cleaning up...")
        rock.capture_mgr.stop_capture()
        rock.capture_mgr.disable_monitor_mode()

        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        d.text((10,50), "Thanks!", font=f11, fill=(231, 76, 60))
        pmks, hs = rock.capture_mgr.get_status()
        d.text((10,70), f"Gathered {pmks+hs}", font=f9, fill=(171, 178, 185))
        if HAS_LCD:
            LCD.LCD_ShowImage(img, 0, 0)

        time.sleep(1)
        GPIO.cleanup()
        print(f"[+] Final: {pmks} PMKIDs, {hs} handshakes")

if __name__ == "__main__":
    main()
