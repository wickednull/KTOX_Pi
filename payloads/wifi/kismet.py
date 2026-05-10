#!/usr/bin/env python3
"""
KTOx Payload – Kismet Wireless Network Detector (LCD)
======================================================
Simple, robust kismet wrapper with LCD display on KTOx_Pi.

Controls:
  UP / DOWN         – Navigate menu / Scroll output
  OK / CENTER       – Select / Execute
  KEY3              – Exit payload
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

# ─────────────────────────────────────────────────────────────────────────────

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
LCD = None
WIDTH, HEIGHT = 128, 128
FONT = None

if HAS_LCD:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    FONT = ImageFont.load_default()

# ─────────────────────────────────────────────────────────────────────────────

running = True
kismet_process = None
output_lines = []
output_lock = threading.Lock()
scroll_pos = 0

def cleanup(*_):
    global running, kismet_process
    running = False
    if kismet_process and kismet_process.poll() is None:
        try:
            kismet_process.terminate()
            kismet_process.wait(timeout=2)
        except:
            try:
                kismet_process.kill()
            except:
                pass
    if HAS_LCD:
        try:
            LCD.LCD_Clear()
            GPIO.cleanup()
        except:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def strip_ansi(text):
    """Remove ANSI escape codes."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def draw_ui(title="", lines=None):
    """Draw UI on LCD."""
    if not HAS_LCD or not LCD:
        return
    try:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)

        # Title bar
        draw.rectangle((0, 0, WIDTH, 12), fill=(139, 0, 0))
        draw.text((4, 1), title[:20], font=FONT, fill=(192, 57, 43))

        # Content
        y = 16
        if lines:
            for line in lines[-7:]:
                text = strip_ansi(str(line))[:20].strip()
                draw.text((2, y), text, font=FONT, fill=(242, 243, 244))
                y += 12

        # Footer
        draw.rectangle((0, 117, WIDTH, 127), fill=(34, 0, 0))
        draw.text((4, 120), "KEY3=Exit", font=FONT, fill=(113, 125, 126))

        LCD.LCD_ShowImage(img, 0, 0)
    except Exception as e:
        pass

def read_kismet_output():
    """Read and display kismet output."""
    global kismet_process, output_lines
    try:
        while kismet_process and kismet_process.poll() is None and running:
            try:
                line = kismet_process.stdout.readline()
                if line:
                    clean_line = strip_ansi(line.strip())
                    if clean_line:
                        with output_lock:
                            output_lines.append(clean_line)
                            if len(output_lines) > 50:
                                output_lines = output_lines[-50:]
            except:
                pass
            time.sleep(0.05)
    except:
        pass

def run_kismet_scan():
    """Start kismet scanning."""
    global kismet_process, output_lines
    try:
        output_lines = []
        draw_ui("KISMET", ["Starting kismet...", "Please wait..."])

        kismet_process = subprocess.Popen(
            ["sudo", "kismet", "-c", "wlan1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        reader_thread = threading.Thread(target=read_kismet_output, daemon=True)
        reader_thread.start()

        return True
    except FileNotFoundError:
        draw_ui("ERROR", ["Kismet not", "installed"])
        time.sleep(2)
        return False
    except Exception as e:
        draw_ui("ERROR", [str(e)[:20]])
        time.sleep(2)
        return False

def show_menu():
    """Show main menu."""
    menu = ["Start Kismet", "View Networks", "Exit"]
    selected = 0

    while running:
        try:
            img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
            draw = ImageDraw.Draw(img)

            # Title
            draw.rectangle((0, 0, WIDTH, 12), fill=(139, 0, 0))
            draw.text((4, 1), "KISMET", font=FONT, fill=(192, 57, 43))

            # Menu items
            y = 20
            for i, item in enumerate(menu):
                color = (212, 172, 13) if i == selected else (242, 243, 244)
                marker = ">" if i == selected else " "
                draw.text((2, y), f"{marker} {item}", font=FONT, fill=color)
                y += 15

            if HAS_LCD:
                LCD.LCD_ShowImage(img, 0, 0)

            # Button handling
            if HAS_LCD:
                if GPIO.input(PINS["UP"]) == 0:
                    selected = (selected - 1) % len(menu)
                    time.sleep(0.2)
                elif GPIO.input(PINS["DOWN"]) == 0:
                    selected = (selected + 1) % len(menu)
                    time.sleep(0.2)
                elif GPIO.input(PINS["OK"]) == 0:
                    time.sleep(0.2)
                    if selected == 0:
                        show_scan()
                    elif selected == 1:
                        show_networks()
                    elif selected == 2:
                        cleanup()
                elif GPIO.input(PINS["KEY3"]) == 0:
                    cleanup()
            else:
                time.sleep(0.1)
        except KeyboardInterrupt:
            cleanup()
        except Exception:
            time.sleep(0.1)

def show_scan():
    """Show kismet scan results."""
    global kismet_process, output_lines

    if not run_kismet_scan():
        return

    while running:
        try:
            with output_lock:
                lines_copy = output_lines.copy()
            draw_ui("KISMET SCAN", lines_copy)

            if HAS_LCD:
                if GPIO.input(PINS["KEY3"]) == 0:
                    if kismet_process and kismet_process.poll() is None:
                        kismet_process.terminate()
                        try:
                            kismet_process.wait(timeout=1)
                        except:
                            kismet_process.kill()
                    break

            time.sleep(0.1)
        except KeyboardInterrupt:
            if kismet_process:
                kismet_process.terminate()
            break
        except Exception:
            time.sleep(0.1)

def show_networks():
    """Show detected networks."""
    lines = ["Checking for", "kismet logs..."]
    draw_ui("NETWORKS", lines)
    time.sleep(2)

def main():
    """Main entry point."""
    global running

    try:
        show_menu()
    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        if HAS_LCD:
            draw_ui("ERROR", [str(e)[:20]])
            time.sleep(2)
        cleanup()

if __name__ == "__main__":
    main()
