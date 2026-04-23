#!/usr/bin/env python3
# NAME: Payload Manager

import os, time, stat, shutil
from pathlib import Path

# ---- LCD & GPIO setup ----
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

W, H = 128, 128
font = ImageFont.load_default()
bold_font = None
try:
    bold_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
except:
    bold_font = font

def _key(pin):
    return GPIO.input(pin) == 0

def wait_button():
    while True:
        if _key(PINS["UP"]): return "UP"
        if _key(PINS["DOWN"]): return "DOWN"
        if _key(PINS["OK"]): return "OK"
        if _key(PINS["KEY1"]): return "KEY1"
        if _key(PINS["KEY2"]): return "KEY2"
        if _key(PINS["KEY3"]): return "KEY3"
        time.sleep(0.05)

def clear_screen():
    lcd = LCD_1in44.LCD()
    lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD_Config.Driver_Delay_ms(50)
    return lcd

def draw_menu(lcd, lines, title, selected=0):
    img = Image.new("RGB", (W, H), "#0a0a0a")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0,0,W,12), fill="#8B0000")
    draw.text((2,2), title[:16], font=bold_font, fill="#fff")
    y = 16
    start = max(0, selected - 4)
    end = min(len(lines), start + 6)
    for i in range(start, end):
        prefix = "> " if i == selected else "  "
        text = lines[i][:18]
        draw.text((4, y), prefix + text, font=font, fill="#c8c8c8")
        y += 12
    lcd.LCD_ShowImage(img, 0, 0)

def get_categories():
    payloads_dir = Path("/root/KTOx/payloads")
    cats = []
    for item in payloads_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            py_files = list(item.glob("*.py"))
            if py_files:
                cats.append(item.name)
    return sorted(cats)

def get_payloads(category):
    dir_path = Path(f"/root/KTOx/payloads/{category}")
    payloads = []
    for f in dir_path.glob("*.py"):
        if f.name.startswith("_"):
            continue
        size = f.stat().st_size
        mtime = time.ctime(f.stat().st_mtime)
        payloads.append((f.name, size, mtime, f))
    return sorted(payloads, key=lambda x: x[0])

def confirm_delete(payload_name):
    lcd = clear_screen()
    img = Image.new("RGB", (W, H), "#0a0a0a")
    draw = ImageDraw.Draw(img)
    draw.text((4,10), f"Delete {payload_name[:15]}?", font=font, fill="#ff8800")
    draw.text((4,30), "KEY1 = YES", font=font, fill="#2ecc40")
    draw.text((4,42), "KEY2 = NO", font=font, fill="#c8c8c8")
    lcd.LCD_ShowImage(img, 0, 0)
    while True:
        btn = wait_button()
        if btn == "KEY1":
            return True
        if btn == "KEY2" or btn == "KEY3":
            return False

def delete_payload(filepath):
    try:
        os.remove(filepath)
        return True
    except Exception as e:
        return False

def show_message(text, delay=2):
    lcd = clear_screen()
    img = Image.new("RGB", (W, H), "#0a0a0a")
    draw = ImageDraw.Draw(img)
    draw.text((4,10), text[:20], font=font, fill="#c8c8c8")
    lcd.LCD_ShowImage(img, 0, 0)
    time.sleep(delay)

def main():
    while True:
        # ---- Category selection ----
        cats = get_categories()
        if not cats:
            show_message("No payloads found", 2)
            return
        cat_idx = 0
        while True:
            draw_menu(clear_screen(), cats, "CATEGORIES", cat_idx)
            btn = wait_button()
            if btn == "UP":
                cat_idx = (cat_idx - 1) % len(cats)
            elif btn == "DOWN":
                cat_idx = (cat_idx + 1) % len(cats)
            elif btn == "OK":
                break
            elif btn == "KEY3":
                return

        category = cats[cat_idx]
        payloads = get_payloads(category)
        if not payloads:
            show_message(f"No payloads in {category}", 1)
            continue

        # ---- Payload selection ----
        pay_idx = 0
        while True:
            lines = [f"{p[0][:-3]} ({p[1]}B)" for p in payloads]
            draw_menu(clear_screen(), lines, category.upper(), pay_idx)
            btn = wait_button()
            if btn == "UP":
                pay_idx = (pay_idx - 1) % len(payloads)
            elif btn == "DOWN":
                pay_idx = (pay_idx + 1) % len(payloads)
            elif btn == "OK":
                # Show details + delete option
                name, size, mtime, path = payloads[pay_idx]
                lcd = clear_screen()
                img = Image.new("RGB", (W, H), "#0a0a0a")
                draw = ImageDraw.Draw(img)
                draw.text((4,4), name[:16], font=bold_font, fill="#fff")
                draw.text((4,20), f"Size: {size} bytes", font=font, fill="#c8c8c8")
                draw.text((4,32), f"Modified:", font=font, fill="#c8c8c8")
                draw.text((4,44), mtime[:16], font=font, fill="#888")
                draw.text((4,70), "KEY1 = DELETE", font=font, fill="#ff8800")
                draw.text((4,82), "KEY2 = BACK", font=font, fill="#c8c8c8")
                lcd.LCD_ShowImage(img, 0, 0)
                while True:
                    btn2 = wait_button()
                    if btn2 == "KEY1":
                        if confirm_delete(name):
                            if delete_payload(path):
                                show_message(f"Deleted {name}", 1)
                                # Refresh payload list
                                payloads = get_payloads(category)
                                if not payloads:
                                    break
                                pay_idx = min(pay_idx, len(payloads)-1)
                            else:
                                show_message("Delete failed", 1)
                            break
                        else:
                            break
                    elif btn2 == "KEY2" or btn2 == "KEY3":
                        break
            elif btn == "KEY2":
                break
            elif btn == "KEY3":
                return

if __name__ == "__main__":
    main()
