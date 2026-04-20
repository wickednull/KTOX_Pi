#!/usr/bin/env python3
"""
KTOx Payload – ZRAM 
=========================================================
- Create/resize ZRAM or swap file.
- Adjust swappiness.
- Settings saved to JSON and applied at boot via systemd.
- Live LCD dashboard with RAM, swap, compression stats.

Controls:
  KEY1 – Open settings menu
  KEY3 – Exit (swap stays active)
  UP/DOWN – Adjust values in settings
  OK – Confirm / toggle
  LEFT/RIGHT – Change value (in settings)
"""

import os
import sys
import json
import time
import subprocess
import threading

# KTOx hardware
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# GPIO & LCD setup
# ----------------------------------------------------------------------
PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
FONT = font(9)
FONT_BOLD = font(10)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def show_message(msg, sub=""):
    img = Image.new("RGB", (W, H), "black")
    draw = ImageDraw.Draw(img)
    draw.text((10, 50), msg, font=FONT_BOLD, fill="#00FF00")
    if sub:
        draw.text((4, 65), sub, font=FONT, fill="#888")
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(2)

# ----------------------------------------------------------------------
# Config file
# ----------------------------------------------------------------------
CONFIG_PATH = "/root/KTOx/zram_config.json"
DEFAULT_CONFIG = {
    "type": "zram",           # "zram" or "swapfile"
    "size_mb": 1024,          # 1 GB
    "swappiness": 100,        # 0-200 (default 100)
    "persist": True,          # enable systemd service
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
                # merge with defaults
                for k, v in DEFAULT_CONFIG.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

# ----------------------------------------------------------------------
# Systemd service for persistence
# ----------------------------------------------------------------------
SERVICE_FILE = "/etc/systemd/system/ktox-zram.service"
def create_persistence_service(cfg):
    """Create systemd service to reapply swap settings at boot."""
    service_content = f"""[Unit]
Description=KTOx ZRAM/Swap Configuration
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /root/KTOx/zram_manager.py --apply
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
    with open(SERVICE_FILE, "w") as f:
        f.write(service_content)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    if cfg["persist"]:
        subprocess.run(["systemctl", "enable", "ktox-zram.service"], capture_output=True)
    else:
        subprocess.run(["systemctl", "disable", "ktox-zram.service"], capture_output=True)

# ----------------------------------------------------------------------
# ZRAM / Swap setup functions
# ----------------------------------------------------------------------
def stop_current_swap():
    """Deactivate any existing swap (zram or swap file)."""
    # Turn off all swaps that we might have created
    subprocess.run(["swapoff", "/dev/zram0"], capture_output=True)
    subprocess.run(["swapoff", "/root/KTOx/swapfile"], capture_output=True)
    # Reset zram if it exists
    if os.path.exists("/sys/block/zram0"):
        subprocess.run(["echo", "1", ">", "/sys/block/zram0/reset"], shell=True, capture_output=True)

def setup_zram(size_mb):
    """Create zram device of given size (MB) and enable swap."""
    # Load module if needed
    subprocess.run(["modprobe", "zram"], capture_output=True)
    # Reset first
    subprocess.run(["echo", "1", ">", "/sys/block/zram0/reset"], shell=True, capture_output=True)
    # Set size
    size_bytes = size_mb * 1024 * 1024
    subprocess.run(["echo", str(size_bytes), ">", "/sys/block/zram0/disksize"], shell=True, capture_output=True)
    # Set compression algorithm (zstd if available)
    try:
        with open("/sys/block/zram0/comp_algorithm", "w") as f:
            f.write("zstd")
    except:
        pass
    # Format as swap
    subprocess.run(["mkswap", "/dev/zram0"], capture_output=True)
    subprocess.run(["swapon", "/dev/zram0"], capture_output=True)
    return True

def setup_swapfile(size_mb):
    """Create swap file of given size (MB) and enable."""
    swap_path = "/root/KTOx/swapfile"
    # Remove old
    subprocess.run(["swapoff", swap_path], capture_output=True)
    if os.path.exists(swap_path):
        os.remove(swap_path)
    # Create new
    subprocess.run(["fallocate", "-l", f"{size_mb}M", swap_path], capture_output=True)
    subprocess.run(["chmod", "600", swap_path], capture_output=True)
    subprocess.run(["mkswap", swap_path], capture_output=True)
    subprocess.run(["swapon", swap_path], capture_output=True)
    return True

def apply_swappiness(value):
    """Set vm.swappiness sysctl."""
    subprocess.run(["sysctl", "-w", f"vm.swappiness={value}"], capture_output=True)
    # Make persistent across reboots
    with open("/etc/sysctl.d/99-ktox-swappiness.conf", "w") as f:
        f.write(f"vm.swappiness={value}\n")

def apply_config(cfg):
    """Apply all settings from config."""
    stop_current_swap()
    if cfg["type"] == "zram":
        setup_zram(cfg["size_mb"])
    else:
        setup_swapfile(cfg["size_mb"])
    apply_swappiness(cfg["swappiness"])
    create_persistence_service(cfg)

# ----------------------------------------------------------------------
# Data collection for dashboard
# ----------------------------------------------------------------------
def get_ram_usage():
    with open("/proc/meminfo", "r") as f:
        lines = f.readlines()
    total = avail = None
    for line in lines:
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) // 1024
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1]) // 1024
    if total and avail:
        used = total - avail
        return total, used, avail
    return 0, 0, 0

def get_swap_stats():
    stats = {"type": "none", "total_mb": 0, "used_mb": 0, "compressed_mb": 0, "ratio": 0.0}
    # Check zram
    if os.path.exists("/sys/block/zram0/disksize"):
        try:
            with open("/sys/block/zram0/disksize", "r") as f:
                stats["total_mb"] = int(f.read().strip()) // 1024 // 1024
            with open("/sys/block/zram0/orig_data_size", "r") as f:
                stats["compressed_mb"] = int(f.read().strip()) // 1024 // 1024
            with open("/sys/block/zram0/compr_data_size", "r") as f:
                compr = int(f.read().strip()) // 1024 // 1024
            if compr > 0:
                stats["ratio"] = stats["compressed_mb"] / compr
            stats["type"] = "zram"
        except:
            pass
    # Get used swap from /proc/swaps
    try:
        with open("/proc/swaps", "r") as f:
            for line in f:
                if "zram" in line or "swapfile" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        stats["used_mb"] = int(parts[3]) // 1024
                        if stats["total_mb"] == 0:
                            stats["total_mb"] = int(parts[2]) // 1024
    except:
        pass
    return stats

# ----------------------------------------------------------------------
# Dashboard drawing
# ----------------------------------------------------------------------
def draw_dashboard(ram_total, ram_used, ram_free, swap_stats, cfg):
    img = Image.new("RGB", (W, H), "black")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W-1, 13), fill="#8B0000")
    draw.text((4, 2), "ZRAM MANAGER", font=FONT_BOLD, fill="#FF3333")
    y = 16
    draw.text((4, y), f"RAM: {ram_used}/{ram_total} MB", font=FONT, fill="#FFBBBB")
    y += 10
    if ram_total > 0:
        bar = int((ram_used/ram_total)*100)
        draw.rectangle((4, y, 4+bar, y+6), fill="#00FF00")
        draw.rectangle((4+bar, y, 104, y+6), fill="#333")
        draw.text((108, y-1), f"{bar}%", font=FONT, fill="#AAA")
    y += 12
    if swap_stats["type"] == "zram":
        draw.text((4, y), f"ZRAM: {swap_stats['compressed_mb']}/{swap_stats['total_mb']} MB", font=FONT, fill="#FFBBBB")
        y += 10
        if swap_stats["total_mb"] > 0:
            bar = int((swap_stats["compressed_mb"]/swap_stats["total_mb"])*100)
            draw.rectangle((4, y, 4+bar, y+6), fill="#00FF00")
            draw.rectangle((4+bar, y, 104, y+6), fill="#333")
            draw.text((108, y-1), f"{bar}%", font=FONT, fill="#AAA")
        y += 12
        draw.text((4, y), f"Orig: {swap_stats['compressed_mb']} MB", font=FONT, fill="#FFBBBB")
        y += 10
        draw.text((4, y), f"Ratio: {swap_stats['ratio']:.1f}x", font=FONT, fill="#FFBBBB")
    else:
        draw.text((4, y), f"SWAP: {swap_stats['used_mb']}/{swap_stats['total_mb']} MB", font=FONT, fill="#FFBBBB")
        y += 10
        if swap_stats["total_mb"] > 0:
            bar = int((swap_stats["used_mb"]/swap_stats["total_mb"])*100)
            draw.rectangle((4, y, 4+bar, y+6), fill="#00FF00")
            draw.rectangle((4+bar, y, 104, y+6), fill="#333")
            draw.text((108, y-1), f"{bar}%", font=FONT, fill="#AAA")
    draw.rectangle((0, H-12, W-1, H-1), fill="#220000")
    draw.text((4, H-10), "K1=Settings  K3=Exit", font=FONT, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Settings menu
# ----------------------------------------------------------------------
def settings_menu(cfg):
    items = [
        ("Type", cfg["type"]),
        ("Size (MB)", cfg["size_mb"]),
        ("Swappiness", cfg["swappiness"]),
        ("Persist", cfg["persist"]),
        ("Apply & Exit", None),
    ]
    idx = 0
    while True:
        img = Image.new("RGB", (W, H), "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, W-1, 13), fill="#8B0000")
        draw.text((4, 2), "ZRAM SETTINGS", font=FONT_BOLD, fill="#FF3333")
        y = 18
        for i, (label, value) in enumerate(items):
            if i == idx:
                draw.rectangle((0, y-2, W-1, y+10), fill="#330000")
                draw.text((4, y), f"> {label}: {value}", font=FONT, fill="#FFFF00")
            else:
                draw.text((4, y), f"  {label}: {value}", font=FONT, fill="#FFBBBB")
            y += 12
        draw.rectangle((0, H-12, W-1, H-1), fill="#220000")
        draw.text((4, H-10), "UP/DOWN OK LEFT/RIGHT K3=Back", font=FONT, fill="#FF7777")
        LCD.LCD_ShowImage(img, 0, 0)

        btn = wait_btn(0.2)
        if btn == "KEY3":
            return False  # back without applying
        elif btn == "UP":
            idx = (idx - 1) % len(items)
        elif btn == "DOWN":
            idx = (idx + 1) % len(items)
        elif btn == "LEFT":
            label, val = items[idx]
            if label == "Type":
                cfg["type"] = "swapfile" if cfg["type"] == "zram" else "zram"
                items[idx] = (label, cfg["type"])
            elif label == "Size (MB)":
                cfg["size_mb"] = max(256, cfg["size_mb"] - 256)
                items[idx] = (label, cfg["size_mb"])
            elif label == "Swappiness":
                cfg["swappiness"] = max(0, cfg["swappiness"] - 10)
                items[idx] = (label, cfg["swappiness"])
            elif label == "Persist":
                cfg["persist"] = not cfg["persist"]
                items[idx] = (label, cfg["persist"])
        elif btn == "RIGHT":
            label, val = items[idx]
            if label == "Size (MB)":
                cfg["size_mb"] = min(4096, cfg["size_mb"] + 256)
                items[idx] = (label, cfg["size_mb"])
            elif label == "Swappiness":
                cfg["swappiness"] = min(200, cfg["swappiness"] + 10)
                items[idx] = (label, cfg["swappiness"])
        elif btn == "OK":
            if label == "Apply & Exit":
                return True
            # For toggle items, already handled by LEFT/RIGHT, but OK toggles Persist
            if label == "Persist":
                cfg["persist"] = not cfg["persist"]
                items[idx] = (label, cfg["persist"])

# ----------------------------------------------------------------------
# Apply mode (for systemd --apply argument)
# ----------------------------------------------------------------------
def apply_mode():
    cfg = load_config()
    apply_config(cfg)
    print("ZRAM configuration applied.")
    sys.exit(0)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if "--apply" in sys.argv:
        apply_mode()

    cfg = load_config()
    # Ensure settings are applied at startup
    apply_config(cfg)

    running = True
    try:
        while running:
            ram_total, ram_used, ram_free = get_ram_usage()
            swap_stats = get_swap_stats()
            draw_dashboard(ram_total, ram_used, ram_free, swap_stats, cfg)

            btn = wait_btn(1.0)
            if btn == "KEY3":
                running = False
            elif btn == "KEY1":
                if settings_menu(cfg):
                    # Apply new settings
                    save_config(cfg)
                    apply_config(cfg)
                    show_message("Settings applied", "Restarting swap...")
                    # Refresh cfg
                    cfg = load_config()
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
