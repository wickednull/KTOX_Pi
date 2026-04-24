#!/usr/bin/env python3
# NAME: File Mover
"""
KTOx Payload – Move a file from one location to another
Uses LCD + hardware buttons (no WebUI required)
"""

import os
import time
import shutil

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("[FILE_MOVER] Hardware libs missing – headless mode")

PINS = {
    "UP": 6,
    "DOWN": 19,
    "LEFT": 5,
    "RIGHT": 26,
    "OK": 13,
    "KEY1": 21,
    "KEY2": 20,
    "KEY3": 16,
}

WIDTH, HEIGHT = 128, 128

# DarkSec/shell_plus keyboard palette
BG = (10, 0, 0)
PANEL = (34, 0, 0)
HEADER = (139, 0, 0)
FG = (171, 178, 185)
ACCENT = (231, 76, 60)
WHITE = (245, 245, 245)
WARN = (212, 172, 13)

LCD = None
FONT = None
FONT_SMALL = None

_last_press = {k: 0.0 for k in PINS}
_last_state = {k: False for k in PINS}
DEBOUNCE = 0.18


def init_hw():
    global LCD, FONT, FONT_SMALL
    if not HAS_HW:
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if os.path.exists(path):
            try:
                FONT = ImageFont.truetype(path, 9)
                FONT_SMALL = ImageFont.truetype(path, 8)
                break
            except Exception:
                pass

    if FONT is None:
        FONT = ImageFont.load_default()
        FONT_SMALL = ImageFont.load_default()


def cleanup_hw():
    if not HAS_HW:
        return
    try:
        LCD.LCD_Clear()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass


def show_image(img):
    if HAS_HW and LCD:
        LCD.LCD_ShowImage(img, 0, 0)


def wait_btn(timeout=0.12):
    if not HAS_HW:
        time.sleep(timeout)
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        now = time.time()
        for name, pin in PINS.items():
            pressed = GPIO.input(pin) == 0
            if pressed and not _last_state[name]:
                _last_state[name] = True
                if now - _last_press[name] >= DEBOUNCE:
                    _last_press[name] = now
                    return name
            elif not pressed and _last_state[name]:
                _last_state[name] = False
        time.sleep(0.01)
    return None


def get_directory_contents(path):
    items = []
    if path != "/":
        items.append({"name": "..", "path": os.path.dirname(path), "is_dir": True})

    try:
        entries = sorted(os.listdir(path))
    except (PermissionError, FileNotFoundError, OSError):
        return items

    dirs = []
    files = []
    for entry in entries:
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            dirs.append({"name": entry, "path": full, "is_dir": True})
        else:
            files.append({"name": entry, "path": full, "is_dir": False})
    return items + dirs + files


def draw_browser(header, items, selected):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
    d.text((4, 2), header[:18], font=FONT, fill=ACCENT)

    y = 18
    max_visible = 7
    start_idx = max(0, selected - max_visible + 1)
    end_idx = min(len(items), start_idx + max_visible)

    for idx in range(start_idx, end_idx):
        item = items[idx]
        label = item["name"][:18]
        prefix = "[D] " if item["is_dir"] and item["name"] != ".." else ""

        if idx == selected:
            d.rectangle((2, y - 1, WIDTH - 2, y + 10), fill=(60, 0, 0))
            d.text((4, y), f"> {prefix}{label}"[:22], font=FONT, fill=WHITE)
        else:
            d.text((4, y), f"  {prefix}{label}"[:22], font=FONT, fill=FG)
        y += 12

    d.rectangle((0, HEIGHT - 12, WIDTH, HEIGHT), fill=PANEL)
    d.text((2, HEIGHT - 10), "OK open/select K2/K3 exit", font=FONT_SMALL, fill=ACCENT)
    show_image(img)


def show_message(title, text, seconds=1.8):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
    d.text((4, 2), title[:18], font=FONT, fill=ACCENT)

    y = 20
    for line in text.split("\n")[:6]:
        d.text((4, y), line[:22], font=FONT, fill=WHITE)
        y += 12

    show_image(img)
    time.sleep(seconds)


def confirm_move(src, dst_dir):
    src_name = os.path.basename(src)
    while True:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        d = ImageDraw.Draw(img)

        d.rectangle((0, 0, WIDTH, 13), fill=HEADER)
        d.text((4, 2), "Confirm Move", font=FONT, fill=ACCENT)

        d.rectangle((4, 18, WIDTH - 4, 100), outline=ACCENT, fill=(25, 0, 0))
        d.text((8, 24), "Move:", font=FONT_SMALL, fill=WARN)
        d.text((8, 36), src_name[:18], font=FONT_SMALL, fill=WHITE)
        d.text((8, 52), "to:", font=FONT_SMALL, fill=WARN)
        d.text((8, 64), dst_dir[-18:], font=FONT_SMALL, fill=WHITE)

        d.rectangle((6, 104, 60, 118), fill=(60, 0, 0))
        d.text((12, 106), "OK=Yes", font=FONT_SMALL, fill=WHITE)
        d.rectangle((68, 104, 122, 118), fill=(60, 0, 0))
        d.text((76, 106), "K3=No", font=FONT_SMALL, fill=WHITE)

        show_image(img)
        btn = wait_btn(0.2)
        if btn == "OK":
            return True
        if btn == "KEY3":
            return False


def main():
    init_hw()

    phase = "source"
    source_file = None

    current_dir = "/root"
    loot = os.environ.get("PAYLOAD_LOOT_DIR", "/root/KTOx/loot")
    if os.path.isdir(loot):
        current_dir = loot

    items = get_directory_contents(current_dir)
    selected = 0

    while True:
        if not items:
            items = [{"name": "..", "path": os.path.dirname(current_dir), "is_dir": True}]
        selected = max(0, min(selected, len(items) - 1))

        header_prefix = "SRC " if phase == "source" else "DST "
        draw_browser(f"{header_prefix}{current_dir[-14:]}", items, selected)

        btn = wait_btn(0.15)
        if btn is None:
            continue

        if btn == "UP":
            selected = max(0, selected - 1)
            continue
        if btn == "DOWN":
            selected = min(len(items) - 1, selected + 1)
            continue
        if btn in ("KEY2", "KEY3"):
            cleanup_hw()
            return
        if btn == "KEY1":
            parent = os.path.dirname(current_dir)
            if parent != current_dir:
                current_dir = parent
                items = get_directory_contents(current_dir)
                selected = 0
            continue

        if btn in ("LEFT",):
            parent = os.path.dirname(current_dir)
            if parent != current_dir:
                current_dir = parent
                items = get_directory_contents(current_dir)
                selected = 0
            continue

        if btn in ("RIGHT", "OK"):
            sel_item = items[selected]

            if phase == "source":
                if sel_item["is_dir"]:
                    current_dir = sel_item["path"]
                    items = get_directory_contents(current_dir)
                    selected = 0
                else:
                    source_file = sel_item["path"]
                    phase = "dest"
                    current_dir = os.path.dirname(source_file)
                    items = get_directory_contents(current_dir)
                    selected = 0
                    show_message("Source selected", os.path.basename(source_file), 1.0)
                continue

            # phase == "dest"
            if sel_item["is_dir"]:
                if sel_item["name"] == "..":
                    current_dir = sel_item["path"]
                    items = get_directory_contents(current_dir)
                    selected = 0
                    continue
                dest_dir = sel_item["path"]
            else:
                dest_dir = os.path.dirname(sel_item["path"])

            if not source_file:
                show_message("Error", "No source selected")
                phase = "source"
                continue

            if confirm_move(source_file, dest_dir):
                try:
                    dest = os.path.join(dest_dir, os.path.basename(source_file))
                    shutil.move(source_file, dest)
                    show_message("Success", f"Moved to:\n{dest_dir}")
                except Exception as exc:
                    show_message("Move failed", str(exc)[:44])

            cleanup_hw()
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup_hw()
