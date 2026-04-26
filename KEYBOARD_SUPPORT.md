# USB/Bluetooth Keyboard Support for KTOX_Pi

This document describes how to use USB and Bluetooth keyboards to control KTOX_Pi's menu system and payloads.

## Overview

KTOX_Pi now supports USB and Bluetooth keyboard input for menu navigation and payload control. This allows you to use standard computer keyboards to control KTOX_Pi in addition to:
- Physical GPIO buttons on the Waveshare LCD HAT
- WebUI virtual buttons in the browser interface

## Installation

### 1. Install evdev dependency

```bash
pip3 install evdev
# Or with system Python
sudo pip3 install evdev --break-system-packages
```

### 2. Connect Keyboard

**USB Keyboard:**
- Simply plug in a USB keyboard via USB-C OTG adapter (same as any other USB peripheral)
- The keyboard will be automatically detected

**Bluetooth Keyboard:**
- Pair the keyboard with the Raspberry Pi using standard Bluetooth tools:
  ```bash
  bluetoothctl
  # In bluetoothctl:
  # scan on
  # pair <device_mac>
  # connect <device_mac>
  ```
- The keyboard will appear in `/dev/input/event*` like any USB keyboard

## Keyboard Mappings

The following keyboard keys are mapped to KTOX_Pi button functions:

| Key(s) | Function | Equivalent Button |
|--------|----------|-------------------|
| **Arrow Up** | Navigate up in menu | Joystick UP |
| **Arrow Down** | Navigate down in menu | Joystick DOWN |
| **Arrow Left** | Navigate left / Back | Joystick LEFT / KEY1 |
| **Arrow Right** | Navigate right / Select | Joystick RIGHT |
| **Enter / Space** | Confirm / Select menu item | Joystick CENTER / OK |
| **Escape** | Go back (previous menu) | KEY1 |
| **Home / H** | Go to home menu | KEY2 |
| **Delete / Q** | Stop attack / Lock device | KEY3 |

## Usage Examples

### Navigation
- Use **arrow keys** to move up/down through menu items
- Press **Enter** or **Space** to select the highlighted item
- Press **Escape** to go back to the previous menu

### Launching Payloads
1. Navigate to "Payloads" menu using arrow keys
2. Select a payload with **Enter**
3. The payload will execute

### Stopping Payloads
- Press **Delete** or **Q** to stop a running payload
- Or hold **Delete**/**Q** for 2+ seconds to lock the device (like KEY3)

### Home Menu
- Press **Home** or **H** at any time to jump to the home menu

## Multiple Keyboards

KTOX_Pi supports multiple keyboards simultaneously. You can:
- Use multiple USB keyboards connected via a USB hub
- Mix USB and Bluetooth keyboards
- All keyboards will work together seamlessly

## Hotplug Support

Keyboards can be connected or disconnected at any time:
- **Connect:** New keyboard is automatically detected and works immediately
- **Disconnect:** System gracefully handles disconnection and continues operating
- **Re-pair Bluetooth:** If a Bluetooth keyboard loses connection, re-pair it using `bluetoothctl`

## Troubleshooting

### Keyboard not detected
1. **Check permissions:** Keyboard input requires read access to `/dev/input/event*`
   - On most systems, being in the `input` group is sufficient
   - If running as non-root, ensure: `sudo usermod -a -G input $(whoami)`

2. **Verify keyboard is recognized:**
   ```bash
   ls -la /dev/input/event*
   # Should show devices
   
   evtest /dev/input/event0
   # Press keys to see events
   ```

3. **Check evdev is installed:**
   ```bash
   python3 -c "import evdev; print(evdev.__version__)"
   # Should print version, not an error
   ```

### Keyboard works but keys aren't recognized
- Ensure you're using the mapped keys listed in the table above
- Non-standard keyboard layouts may have different key locations
- Test with `evtest` to see what keycodes your keyboard sends

### Bluetooth keyboard not connecting
- Ensure Bluetooth adapter is enabled: `bluetoothctl power on`
- Try re-pairing the device
- Check if Bluetooth is conflicting with attack payloads that use Bluetooth
- Use a separate USB Bluetooth adapter if conflicts occur

## Architecture

The keyboard support is implemented via:

1. **`ktox_pi/keyboard_input.py`** - Keyboard event handler
   - Monitors `/dev/input/event*` for keyboard devices
   - Maps evdev keycodes to KTOX button names
   - Provides `get_keyboard_button()` API

2. **`ktox_device.py`** - Integration with main menu system
   - Checks keyboard input in `getButton()` function
   - Keyboard input checked between WebUI and GPIO buttons (priority order)
   - Graceful fallback if evdev unavailable

3. **Auto-detection:** System detects on startup and disables gracefully if evdev not installed

## Fallback Behavior

If evdev is not installed:
- Keyboard support is silently disabled
- GPIO buttons and WebUI continue to work normally
- No errors or warnings (except initial boot message)
- Install evdev anytime to enable keyboard support

## Performance Impact

- **Minimal:** Keyboard input monitoring runs in background thread
- Uses efficient epoll/select for multi-device polling
- No impact on menu rendering or payload execution
- ~1-2% additional CPU usage while idle

## Security Considerations

- Keyboard input is processed at the same priority as GPIO buttons
- All button presses are subject to the same debouncing and safety checks
- The device lock timeout still applies with keyboard input
- Long-held buttons (>4s) are discarded for safety (except KEY3/lock button)

## Future Enhancements

Possible future improvements:
- Configurable key mappings
- Game controller support (DirectInput API)
- Mouse wheel/trackpad support for menu scrolling
- Custom keyboard profiles per payload
