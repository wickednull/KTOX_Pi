#!/usr/bin/env python3
# NAME: Payload Manager (optimized)

import os, time
from pathlib import Path

import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO

# ----------------------------------------------------------------------
# Persistent hardware
# ----------------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

lcd = LCD_1in44.LCD()
lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
LCD_Config.Driver_Delay_ms(50)

W, H = 128, 128
image = Image.new("RGB", (W, H), "#0a0a0a")
draw = ImageDraw.Draw(image)

try:
    bold_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
except:
    bold_font = font = ImageFont.load_default()

def flush():
    lcd.LCD_ShowImage(image, 0, 0)

def draw_menu(lines, title, selected=0):
    """Redraw only the changed area (full screen but no re-init)."""
    draw.rectangle((0,0,W,H), fill="#0a0a0a")
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
    flush()

def wait_button():
    while True:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)  # debounce
                return name
        time.sleep(0.02)

# ----------------------------------------------------------------------
# Rest of the payload manager logic (same as before, but using draw_menu)
# ----------------------------------------------------------------------
def get_categories():
    payloads_dir = Path("/root/KTOx/payloads")
    cats = []
    for item in payloads_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            if list(item.glob("*.py")):
                cats.append(item.name)
    return sorted(cats)

def get_payloads(category):
    dir_path = Path(f"/root/KTOx/payloads/{category}")
    payloads = []
    for f in dir_path.glob("*.py"):
        if f.name.startswith("_"): continue
        size = f.stat().st_size
        mtime = time.ctime(f.stat().st_mtime)
        payloads.append((f.name, size, mtime, f))
    return sorted(payloads, key=lambda x: x[0])

def confirm_delete(payload_name):
    draw.rectangle((0,0,W,H), fill="#0a0a0a")
    draw.text((4,10), f"Delete {payload_name[:15]}?", font=font, fill="#ff8800")
    draw.text((4,30), "KEY1 = YES", font=font, fill="#2ecc40")
    draw.text((4,42), "KEY2 = NO", font=font, fill="#c8c8c8")
    flush()
    while True:
        btn = wait_button()
        if btn == "KEY1": return True
        if btn in ("KEY2","KEY3"): return False

def delete_payload(filepath):
    try:
        os.remove(filepath)
        return True
    except:
        return False

def show_message(text, delay=2):
    draw.rectangle((0,0,W,H), fill="#0a0a0a")
    draw.text((4,10), text[:20], font=font, fill="#c8c8c8")
    flush()
    time.sleep(delay)

def main():
    while True:
        cats = get_categories()
        if not cats:
            show_message("No payloads found", 2)
            return
        cat_idx = 0
        while True:
            draw_menu(cats, "CATEGORIES", cat_idx)
            btn = wait_button()
            if btn == "UP": cat_idx = (cat_idx - 1) % len(cats)
            elif btn == "DOWN": cat_idx = (cat_idx + 1) % len(cats)
            elif btn == "OK": break
            elif btn == "KEY3": return

        category = cats[cat_idx]
        payloads = get_payloads(category)
        if not payloads:
            show_message(f"No payloads in {category}", 1)
            continue

        pay_idx = 0
        while True:
            lines = [f"{p[0][:-3]} ({p[1]}B)" for p in payloads]
            draw_menu(lines, category.upper(), pay_idx)
            btn = wait_button()
            if btn == "UP": pay_idx = (pay_idx - 1) % len(payloads)
            elif btn == "DOWN": pay_idx = (pay_idx + 1) % len(payloads)
            elif btn == "OK":
                name, size, mtime, path = payloads[pay_idx]
                draw.rectangle((0,0,W,H), fill="#0a0a0a")
                draw.text((4,4), name[:16], font=bold_font, fill="#fff")
                draw.text((4,20), f"Size: {size} bytes", font=font, fill="#c8c8c8")
                draw.text((4,32), "Modified:", font=font, fill="#c8c8c8")
                draw.text((4,44), mtime[:16], font=font, fill="#888")
                draw.text((4,70), "KEY1 = DELETE", font=font, fill="#ff8800")
                draw.text((4,82), "KEY2 = BACK", font=font, fill="#c8c8c8")
                flush()
                while True:
                    btn2 = wait_button()
                    if btn2 == "KEY1":
                        if confirm_delete(name):
                            if delete_payload(path):
                                show_message(f"Deleted {name}", 1)
                                payloads = get_payloads(category)
                                if not payloads: break
                                pay_idx = min(pay_idx, len(payloads)-1)
                            else:
                                show_message("Delete failed", 1)
                            break
                        else:
                            break
                    elif btn2 in ("KEY2","KEY3"):
                        break
            elif btn == "KEY2":
                break
            elif btn == "KEY3":
                return

if __name__ == "__main__":
    main()
