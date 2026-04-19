#!/usr/bin/env python3
"""
KTOx Payload – ZRAM Manager & Monitor (Auto-Setup)
=====================================================
- Automatically installs zram kernel module if missing.
- Creates 1 GB zram (zstd compression) OR 1 GB swap file as fallback.
- Displays live RAM and swap/zram usage on LCD.
- Updates every second.

Controls:
  KEY3 – Exit (zram/swap stays active)

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

def show_message(msg, sub=""):
    img = Image.new("RGB", (W, H), "black")
    draw = ImageDraw.Draw(img)
    draw.text((10, 50), msg, font=FONT_BOLD, fill="#00FF00")
    if sub:
        draw.text((4, 65), sub, font=FONT, fill="#888")
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(2)

# ----------------------------------------------------------------------
# Auto-install zram kernel module if missing
# ----------------------------------------------------------------------
def install_zram_module():
    """Try to install kernel headers and build zram module."""
    show_message("ZRAM module missing", "Installing headers...")
    try:
        # Install kernel headers
        subprocess.run(["apt", "update"], capture_output=True, timeout=60)
        subprocess.run(["apt", "install", "-y", f"linux-headers-$(uname -r)"],
                       shell=True, capture_output=True, timeout=120)
        subprocess.run(["depmod", "-a"], capture_output=True, timeout=30)
        # Try to load module
        subprocess.run(["modprobe", "zram"], capture_output=True, timeout=10)
        return True
    except Exception as e:
        print(f"ZRAM install failed: {e}")
        return False

# ----------------------------------------------------------------------
# ZRAM setup (1 GB, zstd compression)
# ----------------------------------------------------------------------
def setup_zram():
    """Configure 1 GB zram device, return True if successful."""
    # Check if zram module is loaded
    result = subprocess.run(["lsmod", "|", "grep", "zram"], shell=True, capture_output=True)
    if result.returncode != 0:
        # Try to load
        subprocess.run(["modprobe", "zram"], capture_output=True)
        result = subprocess.run(["lsmod", "|", "grep", "zram"], shell=True, capture_output=True)
        if result.returncode != 0:
            return False
    # Check if already configured
    try:
        with open("/sys/block/zram0/disksize", "r") as f:
            current = int(f.read().strip())
            if current > 0:
                print(f"ZRAM already configured: {current//1024//1024} MB")
                return True
    except:
        pass
    # Configure
    try:
        subprocess.run(["echo", "1G", ">", "/sys/block/zram0/disksize"], shell=True, check=True)
        subprocess.run(["echo", "zstd", ">", "/sys/block/zram0/comp_algorithm"], shell=True, check=True)
        subprocess.run(["mkswap", "/dev/zram0"], check=True)
        subprocess.run(["swapon", "/dev/zram0"], check=True)
        return True
    except Exception as e:
        print(f"ZRAM config failed: {e}")
        return False

# ----------------------------------------------------------------------
# Fallback: create swap file (1 GB)
# ----------------------------------------------------------------------
SWAP_FILE = "/root/KTOx/swapfile"
def setup_swapfile():
    """Create 1 GB swap file if zram fails."""
    if os.path.exists(SWAP_FILE):
        # Check if already active
        result = subprocess.run(["swapon", "--show", "--noheadings"], capture_output=True, text=True)
        if SWAP_FILE in result.stdout:
            return True
    try:
        subprocess.run(["fallocate", "-l", "1G", SWAP_FILE], check=True)
        subprocess.run(["chmod", "600", SWAP_FILE], check=True)
        subprocess.run(["mkswap", SWAP_FILE], check=True)
        subprocess.run(["swapon", SWAP_FILE], check=True)
        return True
    except Exception as e:
        print(f"Swap file creation failed: {e}")
        return False

# ----------------------------------------------------------------------
# Data collection (handles both zram and swap file)
# ----------------------------------------------------------------------
def get_ram_usage():
    """Return (total_mb, used_mb, free_mb)."""
    with open("/proc/meminfo", "r") as f:
        lines = f.readlines()
    mem_total = None
    mem_available = None
    for line in lines:
        if line.startswith("MemTotal:"):
            mem_total = int(line.split()[1]) // 1024
        elif line.startswith("MemAvailable:"):
            mem_available = int(line.split()[1]) // 1024
    if mem_total and mem_available:
        used = mem_total - mem_available
        free = mem_available
        return mem_total, used, free
    return 0, 0, 0

def get_swap_stats():
    """Return dict with swap size, used, type (zram or file), and compression ratio if zram."""
    stats = {
        "type": "none",
        "total_mb": 0,
        "used_mb": 0,
        "compressed_mb": 0,
        "ratio": 0.0,
    }
    # Check if zram is active
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
    # Get swap usage from /proc/swaps
    try:
        with open("/proc/swaps", "r") as f:
            for line in f:
                if "partition" in line or "file" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        size = int(parts[2]) // 1024
                        used = int(parts[3]) // 1024
                        if stats["type"] == "zram" and "/dev/zram0" in line:
                            stats["used_mb"] = used
                            stats["total_mb"] = size
                        elif stats["type"] == "none" and "file" in line:
                            stats["type"] = "file"
                            stats["total_mb"] = size
                            stats["used_mb"] = used
    except:
        pass
    return stats

# ----------------------------------------------------------------------
# LCD drawing
# ----------------------------------------------------------------------
def draw_dashboard(ram_total, ram_used, ram_free, swap_stats):
    img = Image.new("RGB", (W, H), "black")
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle((0, 0, W-1, 13), fill="#8B0000")
    draw.text((4, 2), "SWAP MONITOR", font=FONT_BOLD, fill="#FF3333")

    y = 16
    # RAM info
    draw.text((4, y), f"RAM: {ram_used} / {ram_total} MB", font=FONT, fill="#FFBBBB")
    y += 10
    if ram_total > 0:
        bar_len = int((ram_used / ram_total) * 100)
        bar_len = min(100, max(0, bar_len))
        draw.rectangle((4, y, 4 + bar_len, y+6), fill="#00FF00")
        draw.rectangle((4+bar_len, y, 104, y+6), fill="#333")
        draw.text((108, y-1), f"{bar_len}%", font=FONT, fill="#AAA")
    y += 12

    # Swap / ZRAM info
    if swap_stats["type"] == "zram":
        draw.text((4, y), f"ZRAM: {swap_stats['compressed_mb']} / {swap_stats['total_mb']} MB", font=FONT, fill="#FFBBBB")
        y += 10
        if swap_stats["total_mb"] > 0:
            bar_len = int((swap_stats["compressed_mb"] / swap_stats["total_mb"]) * 100)
            bar_len = min(100, max(0, bar_len))
            draw.rectangle((4, y, 4 + bar_len, y+6), fill="#00FF00")
            draw.rectangle((4+bar_len, y, 104, y+6), fill="#333")
            draw.text((108, y-1), f"{bar_len}%", font=FONT, fill="#AAA")
        y += 12
        draw.text((4, y), f"Orig: {swap_stats['compressed_mb']} MB", font=FONT, fill="#FFBBBB")
        y += 10
        draw.text((4, y), f"Ratio: {swap_stats['ratio']:.1f}x", font=FONT, fill="#FFBBBB")
    else:
        draw.text((4, y), f"SWAP: {swap_stats['used_mb']} / {swap_stats['total_mb']} MB", font=FONT, fill="#FFBBBB")
        y += 10
        if swap_stats["total_mb"] > 0:
            bar_len = int((swap_stats["used_mb"] / swap_stats["total_mb"]) * 100)
            bar_len = min(100, max(0, bar_len))
            draw.rectangle((4, y, 4 + bar_len, y+6), fill="#00FF00")
            draw.rectangle((4+bar_len, y, 104, y+6), fill="#333")
            draw.text((108, y-1), f"{bar_len}%", font=FONT, fill="#AAA")
        y += 12
        draw.text((4, y), "No compression", font=FONT, fill="#888")

    # Footer
    draw.rectangle((0, H-12, W-1, H-1), fill="#220000")
    draw.text((4, H-10), "KEY3 = Exit", font=FONT, fill="#FF7777")

    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    # Step 1: try to set up zram
    show_message("Setting up ZRAM...", "1 GB, zstd compression")

    # Check if zram module exists
    mod_check = subprocess.run(["modinfo", "zram"], capture_output=True)
    if mod_check.returncode != 0:
        show_message("ZRAM module missing", "Attempting to install...")
        if not install_zram_module():
            show_message("ZRAM install failed", "Falling back to swap file")
            use_zram = False
        else:
            use_zram = setup_zram()
    else:
        use_zram = setup_zram()

    if not use_zram:
        show_message("Using swap file", "1 GB fallback")
        if not setup_swapfile():
            show_message("Swap setup failed", "Check disk space")
            time.sleep(3)
            GPIO.cleanup()
            return

    # Main monitoring loop
    running = True
    try:
        while running:
            ram_total, ram_used, ram_free = get_ram_usage()
            swap_stats = get_swap_stats()
            draw_dashboard(ram_total, ram_used, ram_free, swap_stats)

            btn = wait_btn(1.0)
            if btn == "KEY3":
                running = False
                break
    finally:
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Monitor stopped. ZRAM/swap remains active.")

if __name__ == "__main__":
    main()
