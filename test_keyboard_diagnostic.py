#!/usr/bin/env python3
"""
Diagnostic tool to test keyboard input integration.
This will help identify exactly where the issue is.
"""

import sys
import time
import threading

sys.path.insert(0, '/home/user/KTOX_Pi/ktox_pi')

print("=" * 70)
print("KEYBOARD INPUT DIAGNOSTIC TOOL")
print("=" * 70)
print()

# Test 1: Import and basic checks
print("TEST 1: Module Import")
print("-" * 70)
try:
    import keyboard_input
    print("✓ keyboard_input module imported")
    print(f"  HAS_EVDEV: {keyboard_input.HAS_EVDEV}")
    if not keyboard_input.HAS_EVDEV:
        print("  ✗ EVDEV NOT AVAILABLE - keyboard support disabled")
        print("  Install: pip3 install evdev")
        sys.exit(1)
except Exception as e:
    print(f"✗ Failed to import: {e}")
    sys.exit(1)

print()

# Test 2: Check if initialization completed
print("TEST 2: Initialization Status")
print("-" * 70)
if keyboard_input._keyboards is None:
    print("✗ Keyboards not initialized")
elif not keyboard_input._keyboards:
    print("⚠ Initialization complete but no keyboards found")
    print("  (This is OK if no keyboards are plugged in)")
else:
    print("✓ Initialization complete")

print()

# Test 3: Check if devices were found
print("TEST 3: Device Discovery")
print("-" * 70)
devices = keyboard_input._keyboards or []

if not devices:
    print("✗ NO KEYBOARDS FOUND")
    print("  Checking /dev/input/ for keyboard devices...")
    try:
        from evdev import InputDevice, list_devices, ecodes
        all_devices = list(list_devices())
        print(f"  Total devices found: {len(all_devices)}")
        keyboard_count = 0
        for path in all_devices:
            try:
                dev = InputDevice(path)
                has_key = ecodes.EV_KEY in dev.capabilities()
                if has_key:
                    keyboard_count += 1
                    print(f"    ✓ {path}: {dev.name}")
            except Exception as e:
                print(f"    ✗ {path}: {e}")
        print(f"  Keyboard devices with EV_KEY: {keyboard_count}")
        if keyboard_count == 0:
            print("  → No keyboards detected in /dev/input/")
            print("  → Check: Is keyboard plugged in?")
            print("  → Check: Do you have permission to read /dev/input/?")
    except Exception as e:
        print(f"  Error scanning devices: {e}")
else:
    print(f"✓ Found {len(devices)} keyboard device(s)")
    for i, dev in enumerate(devices):
        print(f"  Device {i}: {dev.name} (fd={dev.fd})")

print()

# Test 4: Check if poller is set up
print("TEST 4: Poller Setup")
print("-" * 70)
if not devices:
    print("⚠ No devices to poll (expected if no keyboards found)")
elif keyboard_input._poller is None:
    print("✗ Poller not initialized but devices exist")
else:
    print(f"✓ Poller initialized for {len(devices)} device(s)")
    print(f"  Poller object: {keyboard_input._poller}")

print()

# Test 5: Test the API
print("TEST 5: API Function Test")
print("-" * 70)
try:
    result = keyboard_input.get_keyboard_button()
    print(f"✓ get_keyboard_button() returned: {result}")
    print("  (None is expected if no key is pressed)")
except Exception as e:
    print(f"✗ Error calling get_keyboard_button(): {e}")

print()

# Test 6: Live test - wait for keyboard input
print("TEST 6: Live Keyboard Input Test")
print("-" * 70)
print("Waiting 5 seconds for keyboard input...")
print("Press arrow keys, Enter, Escape, Home, or Delete to test...")
print()

start = time.time()
timeout = 5
found_input = False

while time.time() - start < timeout:
    try:
        btn = keyboard_input.get_keyboard_button()
        if btn:
            print(f"✓ KEYBOARD INPUT DETECTED: {btn}")
            found_input = True
            break
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(0.05)

if not found_input:
    print("✗ No keyboard input detected in 5 seconds")
    print()
    print("Possible issues:")
    print("1. Keyboard devices not found (see Test 3)")
    print("2. Background thread not running (see Test 2)")
    print("3. Poller not monitoring devices (see Test 4)")
    print("4. Keyboard events not being read from device")
    print("5. Permission issue - check: ls -la /dev/input/event*")
else:
    print()
    print("✓ Keyboard input is working!")

print()
print("=" * 70)
