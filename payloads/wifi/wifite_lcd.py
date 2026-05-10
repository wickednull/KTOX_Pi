#!/usr/bin/env python3
"""
KTOx Payload – Wifite Interactive Wrapper
============================================
Full-featured wifite wrapper with interface selection and options.

Controls:
  UP / DOWN         – Navigate menu
  OK / CENTER       – Select option
  KEY3              – Exit / Back
"""

import sys
import os
import time
import signal
import subprocess
import threading
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Hardware detection
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_LCD = True
except (ImportError, RuntimeError):
    HAS_LCD = False

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
LCD = None
WIDTH, HEIGHT = 128, 128
FONT = None
running = True

if HAS_LCD:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    FONT = ImageFont.load_default()

def cleanup(*_):
    global running
    running = False
    if HAS_LCD:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def get_wifi_interfaces():
    """Get list of available wifi interfaces."""
    try:
        result = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=2)
        interfaces = re.findall(r'Interface (\w+)', result.stdout)
        return [i for i in interfaces if i.startswith('wlan')]
    except:
        return []

def draw_menu(title, items, selected):
    """Draw menu on LCD."""
    if not HAS_LCD or not LCD:
        return
    try:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)

        # Title bar
        draw.rectangle((0, 0, WIDTH, 12), fill=(139, 0, 0))
        draw.text((4, 1), title[:16], font=FONT, fill=(192, 57, 43))

        # Menu items
        y = 16
        for i, item in enumerate(items[:7]):
            color = (212, 172, 13) if i == selected else (242, 243, 244)
            marker = ">" if i == selected else " "
            text = f"{marker} {item}"[:19]
            draw.text((2, y), text, font=FONT, fill=color)
            y += 12

        # Footer
        draw.rectangle((0, 117, WIDTH, 127), fill=(34, 0, 0))
        draw.text((4, 120), "OK=Sel KEY3=Back", font=FONT, fill=(113, 125, 126))
        LCD.LCD_ShowImage(img, 0, 0)
    except:
        pass

def draw_info(title, lines):
    """Draw info screen on LCD."""
    if not HAS_LCD or not LCD:
        return
    try:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)

        # Title bar
        draw.rectangle((0, 0, WIDTH, 12), fill=(139, 0, 0))
        draw.text((4, 1), title[:16], font=FONT, fill=(192, 57, 43))

        # Content
        y = 16
        for line in lines[:7]:
            text = str(line)[:20]
            draw.text((2, y), text, font=FONT, fill=(242, 243, 244))
            y += 12

        # Footer
        draw.rectangle((0, 117, WIDTH, 127), fill=(34, 0, 0))
        draw.text((4, 120), "KEY3=Back", font=FONT, fill=(113, 125, 126))
        LCD.LCD_ShowImage(img, 0, 0)
    except:
        pass

def menu_select(title, items):
    """Show menu and return selected item."""
    selected = 0
    while running:
        draw_menu(title, items, selected)

        if HAS_LCD:
            if GPIO.input(PINS["UP"]) == 0:
                selected = (selected - 1) % len(items)
                time.sleep(0.15)
            elif GPIO.input(PINS["DOWN"]) == 0:
                selected = (selected + 1) % len(items)
                time.sleep(0.15)
            elif GPIO.input(PINS["OK"]) == 0:
                time.sleep(0.15)
                return items[selected]
            elif GPIO.input(PINS["KEY3"]) == 0:
                return None
        time.sleep(0.05)

def select_interface():
    """Let user select wireless interface."""
    draw_info("WiFi Iface", ["Scanning...", ""])
    interfaces = get_wifi_interfaces()

    if not interfaces:
        draw_info("ERROR", ["No wifi", "interfaces found"])
        time.sleep(2)
        return None

    selection = menu_select("Select Interface", interfaces + ["Cancel"])
    return selection if selection != "Cancel" else None

def select_mode():
    """Let user select scan mode."""
    modes = [
        "Standard Scan",
        "Quick Scan",
        "Deep Scan",
        "Handshake Only",
        "Cancel"
    ]
    selection = menu_select("Scan Mode", modes)
    return selection if selection != "Cancel" else None

def get_wifite_args(iface, mode):
    """Build wifite arguments based on mode."""
    args = ["sudo", "wifite", "-i", iface, "-v"]

    if mode == "Quick Scan":
        args.extend(["-t", "10"])
    elif mode == "Deep Scan":
        args.extend(["-t", "30"])
    elif mode == "Handshake Only":
        args.extend(["-c", "1"])

    return args

def run_wifite(iface, mode):
    """Run wifite with selected options."""
    try:
        args = get_wifite_args(iface, mode)
        draw_info("WIFITE", ["Starting...", iface, mode[:15]])
        time.sleep(1)

        subprocess.run(args, cwd="/root/KTOx")

    except FileNotFoundError:
        draw_info("ERROR", ["Wifite not", "found"])
        time.sleep(2)
    except Exception as e:
        draw_info("ERROR", [str(e)[:20]])
        time.sleep(2)

def show_main_menu():
    """Show main menu."""
    while running:
        menu_items = ["Start Wifite", "Info", "Exit"]
        selected = menu_select("WIFITE", menu_items)

        if selected == "Start Wifite":
            iface = select_interface()
            if iface:
                mode = select_mode()
                if mode:
                    run_wifite(iface, mode)

        elif selected == "Info":
            draw_info("WIFITE", [
                "WiFi Auditor",
                "Scanning, deauth,",
                "handshake capture"
            ])
            time.sleep(2)

        elif selected == "Exit" or selected is None:
            cleanup()

def main():
    try:
        show_main_menu()
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        if HAS_LCD:
            draw_info("ERROR", [str(e)[:20]])
            time.sleep(2)
        cleanup()

if __name__ == "__main__":
    main()
