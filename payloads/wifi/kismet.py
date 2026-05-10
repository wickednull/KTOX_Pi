#!/usr/bin/env python3
"""
KTOx Payload – Kismet Interactive LCD
======================================
Runs kismet fully interactive on the LCD with output display.
"""

import sys
import os
import time
import signal
import subprocess
import threading
import pty
import fcntl
import struct
import termios
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

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
kismet_proc = None
master_fd = None

if HAS_LCD:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    FONT = ImageFont.load_default()

output_buffer = []
output_lock = threading.Lock()

def cleanup(*_):
    global running, kismet_proc, master_fd
    running = False
    if kismet_proc:
        try:
            kismet_proc.terminate()
            kismet_proc.wait(timeout=2)
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

def draw_output(title, lines):
    """Display output on LCD."""
    if not HAS_LCD or not LCD:
        return
    try:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, WIDTH, 12), fill=(139, 0, 0))
        draw.text((4, 1), title[:16], font=FONT, fill=(192, 57, 43))

        y = 16
        for line in lines[-7:]:
            text = str(line)[:20]
            draw.text((2, y), text, font=FONT, fill=(242, 243, 244))
            y += 12

        draw.rectangle((0, 117, WIDTH, 127), fill=(34, 0, 0))
        draw.text((4, 120), "KEY3=Exit", font=FONT, fill=(113, 125, 126))

        LCD.LCD_ShowImage(img, 0, 0)
    except:
        pass

def read_kismet_output():
    """Read kismet output from PTY."""
    global kismet_proc, master_fd, output_buffer

    if not master_fd:
        return

    try:
        while kismet_proc and kismet_proc.poll() is None and running:
            try:
                fcntl.fcntl(master_fd, fcntl.F_SETFL, os.O_NONBLOCK)
                data = os.read(master_fd, 4096)
                if data:
                    text = data.decode('utf-8', errors='replace')
                    for char in text:
                        if char == '\n':
                            with output_lock:
                                output_buffer.append("")
                                if len(output_buffer) > 100:
                                    output_buffer = output_buffer[-100:]
                        elif char not in ('\r', '\x00'):
                            if output_buffer:
                                output_buffer[-1] += char
                            else:
                                output_buffer.append(char)
            except (BlockingIOError, OSError):
                pass
            time.sleep(0.02)
    except:
        pass

def send_input(text, add_newline=True):
    """Send input to kismet."""
    global master_fd
    if master_fd:
        try:
            if add_newline:
                os.write(master_fd, (text + '\n').encode())
            else:
                os.write(master_fd, text.encode())
        except:
            pass

def run_kismet_scan(iface="wlan1"):
    """Run kismet interactively on LCD."""
    global kismet_proc, master_fd, running, output_buffer

    output_buffer = []

    try:
        master_fd, slave_fd = pty.openpty()
        s = struct.pack('HHHH', 10, 80, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, s)

        kismet_proc = subprocess.Popen(
            ['sudo', 'kismet', '-c', iface],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
            text=False
        )

        os.close(slave_fd)

        reader = threading.Thread(target=read_kismet_output, daemon=True)
        reader.start()

        while kismet_proc.poll() is None and running:
            with output_lock:
                lines = output_buffer.copy()

            draw_output("KISMET", lines)

            if HAS_LCD:
                # KEY3 to exit
                if GPIO.input(PINS["KEY3"]) == 0:
                    send_input('q', add_newline=True)
                    time.sleep(0.5)
                    try:
                        kismet_proc.terminate()
                        kismet_proc.wait(timeout=1)
                    except:
                        pass
                    break

                # UP/DOWN for navigation (without newline)
                if GPIO.input(PINS["UP"]) == 0:
                    send_input('\x1B[A', add_newline=False)
                    time.sleep(0.2)
                elif GPIO.input(PINS["DOWN"]) == 0:
                    send_input('\x1B[B', add_newline=False)
                    time.sleep(0.2)

                # OK for selection (without newline for return key)
                elif GPIO.input(PINS["OK"]) == 0:
                    send_input('\r', add_newline=False)
                    time.sleep(0.2)

            time.sleep(0.05)

        try:
            kismet_proc.wait(timeout=2)
        except:
            kismet_proc.kill()

        draw_output("KISMET", ["Scan complete"])
        time.sleep(2)

    except FileNotFoundError:
        draw_output("ERROR", ["Kismet not found"])
        time.sleep(2)
    except Exception as e:
        draw_output("ERROR", [str(e)[:20]])
        time.sleep(2)
    finally:
        kismet_proc = None
        if master_fd:
            try:
                os.close(master_fd)
            except:
                pass
            master_fd = None

def draw_menu(title, items, selected):
    """Draw menu on LCD."""
    if not HAS_LCD or not LCD:
        return
    try:
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, WIDTH, 12), fill=(139, 0, 0))
        draw.text((4, 1), title[:16], font=FONT, fill=(192, 57, 43))

        y = 16
        for i, item in enumerate(items[:7]):
            color = (212, 172, 13) if i == selected else (242, 243, 244)
            marker = ">" if i == selected else " "
            text = f"{marker} {item}"[:19]
            draw.text((2, y), text, font=FONT, fill=color)
            y += 12

        draw.rectangle((0, 117, WIDTH, 127), fill=(34, 0, 0))
        draw.text((4, 120), "OK=Sel KEY3=Back", font=FONT, fill=(113, 125, 126))
        LCD.LCD_ShowImage(img, 0, 0)
    except:
        pass

def menu_select(title, items):
    """Show menu and return selection."""
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

def get_wifi_interfaces():
    """Get available wifi interfaces."""
    try:
        result = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=2)
        interfaces = re.findall(r'Interface (\w+)', result.stdout)
        return [i for i in interfaces if i.startswith('wlan')]
    except:
        return ["wlan1", "wlan0"]

def main():
    try:
        while running:
            ifaces = get_wifi_interfaces() + ["Exit"]
            iface = menu_select("Select WiFi", ifaces)

            if iface == "Exit" or iface is None:
                cleanup()
            elif iface:
                run_kismet_scan(iface)

    except KeyboardInterrupt:
        cleanup()
    except Exception as e:
        if HAS_LCD:
            draw_output("ERROR", [str(e)[:20]])
            time.sleep(2)
        cleanup()

if __name__ == "__main__":
    main()
