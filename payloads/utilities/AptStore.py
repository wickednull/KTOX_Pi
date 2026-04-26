#!/usr/bin/env python3
# NAME: APT Store

import os, subprocess, time, sys
from pathlib import Path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from _darksec_keyboard import DarkSecKeyboard

# ----------------------------------------------------------------------
# Persistent LCD hardware (no re-init on every draw)
# ----------------------------------------------------------------------
import LCD_1in44, LCD_Config
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

lcd = LCD_1in44.LCD()
lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
LCD_Config.Driver_Delay_ms(50)

W, H = 128, 128
image = Image.new("RGB", (W, H), "#0a0000")
draw = ImageDraw.Draw(image)

try:
    bold_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
except:
    bold_font = font = ImageFont.load_default()

def flush():
    lcd.LCD_ShowImage(image, 0, 0)

def draw_menu(lines, title, selected=0, page=0, total_pages=1):
    draw.rectangle((0,0,W,H), fill="#0a0000")
    draw.rectangle((0,0,W,12), fill="#8B0000")
    draw.text((2,2), title[:16], font=bold_font, fill="#fff")
    if total_pages > 1:
        draw.text((W-30,2), f"{page+1}/{total_pages}", font=font, fill="#888")
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

def show_message(text, delay=2):
    draw.rectangle((0,0,W,H), fill="#0a0000")
    draw.text((4,10), text[:20], font=font, fill="#c8c8c8")
    flush()
    time.sleep(delay)

def show_text_scroll(lines, title="INFO"):
    """Scrollable text with up/down."""
    page = 0
    total = max(1, (len(lines) + 5) // 6)
    while True:
        draw.rectangle((0,0,W,H), fill="#0a0000")
        draw.rectangle((0,0,W,12), fill="#8B0000")
        draw.text((2,2), title[:16], font=bold_font, fill="#fff")
        if total > 1:
            draw.text((W-30,2), f"{page+1}/{total}", font=font, fill="#888")
        y = 16
        start = page * 6
        end = min(start+6, len(lines))
        for i in range(start, end):
            draw.text((4, y), lines[i][:20], font=font, fill="#c8c8c8")
            y += 11
        flush()
        btn = wait_button()
        if btn == "UP" and page > 0: page -= 1
        elif btn == "DOWN" and (page+1)*6 < len(lines): page += 1
        elif btn in ("OK","KEY2","KEY3"): break

def confirm(msg):
    draw.rectangle((0,0,W,H), fill="#0a0000")
    draw.text((4,10), msg[:20], font=font, fill="#ff8800")
    draw.text((4,30), "KEY1 = YES", font=font, fill="#e74c3c")
    draw.text((4,42), "KEY2 = NO", font=font, fill="#c8c8c8")
    flush()
    while True:
        btn = wait_button()
        if btn == "KEY1": return True
        if btn in ("KEY2","KEY3"): return False

def run_apt(cmd, title="APT"):
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            lines.append(line.strip())
            if len(lines) > 6: lines = lines[-6:]
            draw.rectangle((0,0,W,H), fill="#0a0000")
            draw.rectangle((0,0,W,12), fill="#8B0000")
            draw.text((2,2), title[:16], font=bold_font, fill="#fff")
            y = 16
            for l in lines:
                draw.text((4, y), l[:20], font=font, fill="#c8c8c8")
                y += 11
            flush()
    return proc.returncode == 0

def get_installed_packages():
    result = subprocess.run(["apt", "list", "--installed"], capture_output=True, text=True)
    pkgs = []
    for line in result.stdout.splitlines():
        if "/" in line and "installed" in line:
            parts = line.split()
            name = parts[0].split("/")[0]
            version = parts[1] if len(parts) > 1 else "?"
            pkgs.append(f"{name} ({version})")
    return sorted(pkgs)

def get_package_details(pkg_name):
    result = subprocess.run(["apt", "show", pkg_name], capture_output=True, text=True)
    lines = result.stdout.splitlines()
    details = []
    for line in lines[:30]:
        if any(line.startswith(k) for k in ("Package:","Version:","Description:","Homepage:","Depends:","Size:")):
            details.append(line)
    return details or ["No details found"]

def search_packages(query):
    result = subprocess.run(f"apt-cache search --names-only '{query}'", shell=True, capture_output=True, text=True)
    lines = result.stdout.splitlines()
    return [line.split(" - ")[0] for line in lines[:50]]

def install_package(pkg_name):
    if confirm(f"Install {pkg_name}?"):
        return run_apt(f"apt install --yes {pkg_name}", title="INSTALL")
    return False

def uninstall_package(pkg_name):
    if confirm(f"Remove {pkg_name}?"):
        return run_apt(f"apt remove --yes {pkg_name}", title="REMOVE")
    return False

def update_package_list():
    return run_apt("apt update", title="UPDATE")

def upgrade_all():
    if confirm("Upgrade all packages?"):
        return run_apt("apt upgrade --yes", title="UPGRADE")
    return False

# ----------------------------------------------------------------------
# On‑screen keyboard (same as before, but uses persistent draw)
# ----------------------------------------------------------------------
KEYBOARD = [
    ['a','b','c','d','e','f','g','h','i','j'],
    ['k','l','m','n','o','p','q','r','s','t'],
    ['u','v','w','x','y','z','-','_','.',' '],
    ['←','⌫','🔍','OK','EXIT']
]

def keyboard_input(title="SEARCH"):
    kb = DarkSecKeyboard(width=W, height=H, lcd=lcd, gpio_pins=PINS, gpio_module=GPIO)
    result = kb.run()
    return result.strip() if result else None

# ----------------------------------------------------------------------
# Main menu
# ----------------------------------------------------------------------
def main():
    while True:
        options = ["Installed Packages", "Search & Install", "Update Package List", "Upgrade All", "Exit"]
        sel = 0
        while True:
            draw_menu(options, "APT STORE", sel)
            btn = wait_button()
            if btn == "UP": sel = (sel-1) % len(options)
            elif btn == "DOWN": sel = (sel+1) % len(options)
            elif btn == "OK": break
            elif btn == "KEY3": return

        if sel == 0:  # Installed Packages
            pkgs = get_installed_packages()
            if not pkgs:
                show_message("No packages found", 1)
                continue
            p_idx = 0
            while True:
                draw_menu(pkgs, "INSTALLED", p_idx)
                btn = wait_button()
                if btn == "UP": p_idx = (p_idx-1) % len(pkgs)
                elif btn == "DOWN": p_idx = (p_idx+1) % len(pkgs)
                elif btn == "OK":
                    pkg_line = pkgs[p_idx]
                    pkg_name = pkg_line.split(" (")[0]
                    details = get_package_details(pkg_name)
                    show_text_scroll(details, f"DETAILS: {pkg_name[:10]}")
                    if uninstall_package(pkg_name):
                        show_message(f"Removed {pkg_name}", 1)
                        pkgs = get_installed_packages()
                        if not pkgs: break
                        p_idx = min(p_idx, len(pkgs)-1)
                elif btn == "KEY2": break
                elif btn == "KEY3": return

        elif sel == 1:  # Search & Install
            query = keyboard_input("SEARCH PACKAGE")
            if not query:
                continue
            show_message(f"Searching: {query}", 1)
            results = search_packages(query)
            if not results:
                show_message("No matches", 1)
                continue
            r_idx = 0
            while True:
                draw_menu(results, f"RESULTS ({len(results)})", r_idx)
                btn = wait_button()
                if btn == "UP": r_idx = (r_idx-1) % len(results)
                elif btn == "DOWN": r_idx = (r_idx+1) % len(results)
                elif btn == "OK":
                    pkg = results[r_idx]
                    details = get_package_details(pkg)
                    show_text_scroll(details, f"DETAILS: {pkg[:10]}")
                    if install_package(pkg):
                        show_message(f"Installed {pkg}", 1)
                    else:
                        show_message("Install failed", 1)
                elif btn == "KEY2": break
                elif btn == "KEY3": return

        elif sel == 2:  # Update
            show_message("Updating...", 1)
            if update_package_list():
                show_message("Done", 1)
            else:
                show_message("Update failed", 1)

        elif sel == 3:  # Upgrade
            if upgrade_all():
                show_message("Upgrade done", 1)
            else:
                show_message("Upgrade failed", 1)

        elif sel == 4:
            return

if __name__ == "__main__":
    main()
