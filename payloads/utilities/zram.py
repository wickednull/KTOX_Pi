#!/usr/bin/env python3
"""
KTOx Payload – ZRAM Manager & Monitor
=======================================
- Creates 1 GB zram device (zstd compression) if not present.
- Displays live RAM and zram usage on LCD.
- Updates every second.

Controls:
  KEY3 – Exit (zram stays active)

Loot: none
"""

import os
import sys
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

# ----------------------------------------------------------------------
# ZRAM setup (1 GB, zstd compression)
# ----------------------------------------------------------------------
def zram_setup():
    """Create 1 GB zram device if not already present."""
    # Check if zram module is loaded
    if not os.path.exists("/sys/block/zram0"):
        subprocess.run(["modprobe", "zram"], check=False)
        time.sleep(0.5)
    # Check if already configured
    try:
        with open("/sys/block/zram0/disksize", "r") as f:
            current = int(f.read().strip())
            if current > 0:
                print(f"ZRAM already configured: {current//1024//1024} MB")
                return True
    except:
        pass
    # Configure: 1 GB, zstd compression
    try:
        subprocess.run(["echo", "1G", ">", "/sys/block/zram0/disksize"], shell=True, check=True)
        subprocess.run(["echo", "zstd", ">", "/sys/block/zram0/comp_algorithm"], shell=True, check=True)
        # Optionally use as swap
        subprocess.run(["mkswap", "/dev/zram0"], check=True)
        subprocess.run(["swapon", "/dev/zram0"], check=True)
        print("ZRAM set up: 1 GB, zstd compression, added as swap")
        return True
    except Exception as e:
        print(f"ZRAM setup failed: {e}")
        return False

# ----------------------------------------------------------------------
# Data collection
# ----------------------------------------------------------------------
def get_ram_usage():
    """Return (total_mb, used_mb, free_mb)."""
    with open("/proc/meminfo", "r") as f:
        lines = f.readlines()
    mem_total = None
    mem_available = None
    for line in lines:
        if line.startswith("MemTotal:"):
            mem_total = int(line.split()[1]) // 1024  # kB -> MB
        elif line.startswith("MemAvailable:"):
            mem_available = int(line.split()[1]) // 1024
    if mem_total and mem_available:
        used = mem_total - mem_available
        free = mem_available
        return mem_total, used, free
    return 0, 0, 0

def get_zram_stats():
    """Return dict with zram stats (MB, ratio)."""
    stats = {}
    try:
        with open("/sys/block/zram0/disksize", "r") as f:
            stats["disksize"] = int(f.read().strip()) // 1024 // 1024  # MB
    except:
        stats["disksize"] = 0
    try:
        with open("/sys/block/zram0/orig_data_size", "r") as f:
            stats["orig_size"] = int(f.read().strip()) // 1024 // 1024
    except:
        stats["orig_size"] = 0
    try:
        with open("/sys/block/zram0/compr_data_size", "r") as f:
            stats["compr_size"] = int(f.read().strip()) // 1024 // 1024
    except:
        stats["compr_size"] = 0
    if stats["compr_size"] > 0:
        stats["ratio"] = stats["orig_size"] / stats["compr_size"]
    else:
        stats["ratio"] = 0.0
    # Swap usage
    try:
        with open("/proc/swaps", "r") as f:
            for line in f:
                if "/dev/zram0" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        stats["swap_used"] = int(parts[3]) // 1024  # MB
                    else:
                        stats["swap_used"] = 0
                    break
    except:
        stats["swap_used"] = 0
    return stats

# ----------------------------------------------------------------------
# LCD drawing
# ----------------------------------------------------------------------
def draw_dashboard(ram_total, ram_used, ram_free, zram):
    img = Image.new("RGB", (W, H), "black")
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle((0, 0, W-1, 13), fill="#8B0000")
    draw.text((4, 2), "ZRAM MONITOR", font=FONT_BOLD, fill="#FF3333")

    y = 16
    # RAM info
    draw.text((4, y), f"RAM: {ram_used} / {ram_total} MB", font=FONT, fill="#FFBBBB")
    y += 10
    # RAM bar
    if ram_total > 0:
        bar_len = int((ram_used / ram_total) * 100)
        bar_len = min(100, max(0, bar_len))
        draw.rectangle((4, y, 4 + bar_len, y+6), fill="#00FF00")
        draw.rectangle((4+bar_len, y, 104, y+6), fill="#333")
        draw.text((108, y-1), f"{bar_len}%", font=FONT, fill="#AAA")
    y += 12

    # ZRAM info
    draw.text((4, y), f"ZRAM: {zram['compr_size']} / {zram['disksize']} MB", font=FONT, fill="#FFBBBB")
    y += 10
    if zram["disksize"] > 0:
        bar_len = int((zram["compr_size"] / zram["disksize"]) * 100)
        bar_len = min(100, max(0, bar_len))
        draw.rectangle((4, y, 4 + bar_len, y+6), fill="#00FF00")
        draw.rectangle((4+bar_len, y, 104, y+6), fill="#333")
        draw.text((108, y-1), f"{bar_len}%", font=FONT, fill="#AAA")
    y += 12

    # Original data & compression ratio
    draw.text((4, y), f"Orig: {zram['orig_size']} MB", font=FONT, fill="#FFBBBB")
    y += 10
    draw.text((4, y), f"Ratio: {zram['ratio']:.1f}x", font=FONT, fill="#FFBBBB")
    y += 10
    draw.text((4, y), f"Swap used: {zram['swap_used']} MB", font=FONT, fill="#FFBBBB")

    # Footer
    draw.rectangle((0, H-12, W-1, H-1), fill="#220000")
    draw.text((4, H-10), "KEY3 = Exit", font=FONT, fill="#FF7777")

    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def main():
    # Setup zram
    if not zram_setup():
        # Show error on LCD
        img = Image.new("RGB", (W, H), "black")
        draw = ImageDraw.Draw(img)
        draw.text((10, 50), "ZRAM setup failed", font=FONT, fill="red")
        draw.text((10, 65), "Check kernel support", font=FONT, fill="white")
        LCD.LCD_ShowImage(img, 0, 0)
        time.sleep(3)
        GPIO.cleanup()
        return

    running = True
    try:
        while running:
            ram_total, ram_used, ram_free = get_ram_usage()
            zram_stats = get_zram_stats()
            draw_dashboard(ram_total, ram_used, ram_free, zram_stats)

            btn = wait_btn(1.0)  # wait up to 1 sec, update every second
            if btn == "KEY3":
                running = False
                break
            # No other controls needed
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("ZRAM monitor stopped. ZRAM remains active.")

if __name__ == "__main__":
    main()
