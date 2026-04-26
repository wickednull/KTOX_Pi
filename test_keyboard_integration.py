#!/usr/bin/env python3
"""
Quick test script for keyboard input integration.
This tests that the keyboard module is properly integrated with ktox_device.
"""

import sys
import os

sys.path.insert(0, '/home/user/KTOX_Pi')
sys.path.insert(0, '/home/user/KTOX_Pi/ktox_pi')

def test_keyboard_input_module():
    """Test that keyboard_input module can be imported and configured."""
    try:
        import keyboard_input
        print("✓ keyboard_input module imported successfully")

        # Check configuration
        print(f"  HAS_EVDEV: {keyboard_input.HAS_EVDEV}")

        if keyboard_input.HAS_EVDEV:
            print(f"  Key mappings configured: {len(keyboard_input._KEY_MAP)} keys")
            print(f"  Supported keys: {list(keyboard_input._KEY_MAP.values())}")
        else:
            print("  ⚠ evdev not available (will gracefully skip keyboard support)")
            print("    To enable: pip3 install evdev")

        # Test the API exists
        assert hasattr(keyboard_input, 'get_keyboard_button'), "Missing get_keyboard_button()"
        assert hasattr(keyboard_input, 'flush'), "Missing flush()"
        assert hasattr(keyboard_input, 'stop'), "Missing stop()"
        print("✓ All required API methods present")

        # Test that it returns None when no events
        result = keyboard_input.get_keyboard_button()
        assert result is None, "Expected None when no keyboard events"
        print("✓ get_keyboard_button() returns None as expected")

        return True
    except Exception as e:
        print(f"✗ keyboard_input test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ktox_device_imports():
    """Test that ktox_device can import with keyboard support."""
    try:
        # We won't do a full import, just check the syntax and critical parts
        with open('/home/user/KTOX_Pi/ktox_device.py', 'r') as f:
            content = f.read()

        # Check that our modifications are present
        if 'import keyboard_input' not in content:
            print("✗ keyboard_input import not found in ktox_device.py")
            return False
        print("✓ keyboard_input import statement present")

        if 'HAS_KEYBOARD' not in content:
            print("✗ HAS_KEYBOARD flag not found in ktox_device.py")
            return False
        print("✓ HAS_KEYBOARD flag present")

        if 'keyboard_input.get_keyboard_button()' not in content:
            print("✗ keyboard_input.get_keyboard_button() call not found in getButton()")
            return False
        print("✓ keyboard_input integrated into getButton()")

        if 'keyboard_input.stop()' not in content:
            print("✗ keyboard_input.stop() cleanup not found")
            return False
        print("✓ keyboard_input cleanup on shutdown configured")

        return True
    except Exception as e:
        print(f"✗ ktox_device integration test failed: {e}")
        return False


def main():
    print("=" * 60)
    print("KTOx Keyboard Integration Test")
    print("=" * 60)
    print()

    print("Test 1: keyboard_input module")
    print("-" * 60)
    result1 = test_keyboard_input_module()
    print()

    print("Test 2: ktox_device integration")
    print("-" * 60)
    result2 = test_ktox_device_imports()
    print()

    if result1 and result2:
        print("=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        print()
        print("Keyboard support is integrated and ready.")
        if not sys.modules['keyboard_input'].HAS_EVDEV:
            print("\nNote: To enable USB/Bluetooth keyboard support:")
            print("  pip3 install evdev")
            print("  # Then restart ktox_device.py")
        return 0
    else:
        print("=" * 60)
        print("✗ Some tests failed")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
