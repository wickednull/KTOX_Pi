#!/usr/bin/env python3
"""
Debug script to test keyboard input detection and reading.
Run this to diagnose keyboard input issues.
"""

import sys
import os

sys.path.insert(0, '/home/user/KTOX_Pi')
sys.path.insert(0, '/home/user/KTOX_Pi/ktox_pi')

print("=" * 70)
print("KTOX Keyboard Debug Tool")
print("=" * 70)
print()

# Check 1: evdev availability
print("1. Checking evdev library...")
print("-" * 70)
try:
    from evdev import InputDevice, ecodes, list_devices
    print("✓ evdev imported successfully")
except ImportError as e:
    print(f"✗ evdev not available: {e}")
    print("  Fix: pip3 install evdev")
    sys.exit(1)

# Check 2: Find devices
print()
print("2. Scanning for keyboard devices...")
print("-" * 70)
devices = []
try:
    for dev_path in list_devices():
        try:
            dev = InputDevice(dev_path)
            caps = dev.capabilities()
            has_key = ecodes.EV_KEY in caps
            print(f"  {dev.path}: {dev.name}")
            print(f"    Capabilities: {list(caps.keys())}")
            if has_key:
                print(f"    ✓ Has EV_KEY (keyboard-like device)")
                devices.append(dev)
            else:
                print(f"    ✗ No EV_KEY")
        except Exception as e:
            print(f"  {dev_path}: Error - {e}")
except Exception as e:
    print(f"✗ Error scanning devices: {e}")
    sys.exit(1)

if not devices:
    print("\n✗ No keyboard devices found!")
    print("\nTroubleshooting:")
    print("  1. Check /dev/input/event* devices exist:")
    print("     ls -la /dev/input/event*")
    print("  2. Check permissions (may need to be in 'input' group):")
    print("     groups")
    print("  3. Try with sudo:")
    print("     sudo python3 debug_keyboard.py")
    sys.exit(1)

print(f"\n✓ Found {len(devices)} keyboard device(s)")

# Check 3: Try reading events
print()
print("3. Testing keyboard event reading...")
print("-" * 70)
print("Press keys on your keyboard (ESC/Ctrl+C to exit):")
print()

import select
import time

try:
    # Set non-blocking mode
    for dev in devices:
        if hasattr(dev, 'set_blocking'):
            dev.set_blocking(False)
        else:
            import fcntl
            fcntl.fcntl(dev.fd, fcntl.F_SETFL,
                       fcntl.fcntl(dev.fd, fcntl.F_GETFL) | os.O_NONBLOCK)

    start_time = time.time()
    events_read = 0

    while True:
        # Check timeout
        if time.time() - start_time > 10:
            print("\n⚠ No keyboard events detected in 10 seconds")
            print("  Keyboard may not be responding or not properly detected")
            break

        # Poll devices
        fds = [dev.fd for dev in devices]
        readable, _, _ = select.select(fds, [], [], 0.5)

        for fd in readable:
            dev = next((d for d in devices if d.fd == fd), None)
            if dev:
                for event in dev.read():
                    if event.type == ecodes.EV_KEY:
                        key_name = ecodes.BTN[event.code] if event.code in ecodes.BTN else \
                                   ecodes.KEY[event.code] if event.code in ecodes.KEY else str(event.code)
                        action = "PRESS" if event.value == 1 else "RELEASE" if event.value == 0 else f"REPEAT({event.value})"
                        print(f"  [{dev.name}] {key_name}: {action}")
                        events_read += 1

except KeyboardInterrupt:
    print("\n\nStopped by user")
except Exception as e:
    print(f"\n✗ Error reading events: {e}")
    import traceback
    traceback.print_exc()

# Check 4: Test keyboard_input module
print()
print("4. Testing keyboard_input module...")
print("-" * 70)
try:
    import keyboard_input
    print("✓ keyboard_input module imported")
    print(f"  HAS_EVDEV: {keyboard_input.HAS_EVDEV}")
    print(f"  Key mappings: {len(keyboard_input._KEY_MAP)}")
    print(f"  Active devices: {len(keyboard_input._active_devices)}")

    time.sleep(0.5)
    btn = keyboard_input.get_keyboard_button()
    print(f"  Test call get_keyboard_button(): {btn}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 70)
print("Debug complete")
print("=" * 70)
