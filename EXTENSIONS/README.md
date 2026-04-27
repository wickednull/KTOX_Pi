# KTOX Extensions API

Shared helpers and utilities that payloads can import for common tasks. Instead of embedding the same logic in multiple payloads, KTOX exposes a small extension API that any payload can call.

## Public API

Payloads should import helpers from `EXTENSIONS.api`:

```python
from EXTENSIONS.api import (
    WAIT_FOR_PRESENT,
    WAIT_FOR_NOTPRESENT,
    REQUIRE_CAPABILITY,
    RUN_PAYLOAD,
)
```

Alternatively, import from EXTENSIONS directly:

```python
from EXTENSIONS import REQUIRE_CAPABILITY, RUN_PAYLOAD
```

These are regular Python functions—no special payload language or parser layer required.

---

## API Reference

### Gates (Workflow Control)

#### WAIT_FOR_PRESENT
Wait until a monitored signal (Bluetooth, Wi-Fi, or GPIO) becomes present.

**Signature:**
```python
def WAIT_FOR_PRESENT(
    *,
    signal_type: str = "bluetooth",
    identifier: str = "",
    name: str = "",
    mac: str = "",
    service_uuid: str = "",
    timeout_seconds: int = 0,
    scan_window_seconds: int = 4,
    poll_interval_seconds: int = 2,
    fail_closed: bool = True,
) -> bool
```

**Parameters:**
- `signal_type` (str): One of `"bluetooth"`, `"wifi"`, or `"gpio"` (default: bluetooth)
- `identifier` (str): Device name/MAC (bluetooth), SSID (wifi), or GPIO label/path (gpio)
- `name` (str): Device advertised name to match (bluetooth only, partial, case-insensitive)
- `mac` (str): MAC address to match (bluetooth only, e.g., "AA:BB:CC:DD:EE:FF")
- `service_uuid` (str): Service UUID to match (bluetooth only)
- `timeout_seconds` (int): Max wait time in seconds (0 = infinite)
- `scan_window_seconds` (int): Duration of each scan window
- `poll_interval_seconds` (int): Interval between scans
- `fail_closed` (bool): If True, raise on timeout; if False, return False

**Returns:** True if signal found

**Raises:**
- `TimeoutError`: If timeout and fail_closed=True
- `RuntimeError`: If scan unavailable and fail_closed=True
- `ValueError`: If invalid signal_type or missing identifier

**Examples:**

Wait for Bluetooth device by name:
```python
from EXTENSIONS.api import WAIT_FOR_PRESENT

try:
    found = WAIT_FOR_PRESENT(
        signal_type="bluetooth",
        identifier="M5Cardputer",
        timeout_seconds=30,
    )
    if found:
        print("M5Cardputer connected!")
except TimeoutError:
    print("M5Cardputer not found within 30 seconds")
```

Wait for Wi-Fi network:
```python
found = WAIT_FOR_PRESENT(
    signal_type="wifi",
    identifier="MySSID",
    timeout_seconds=60,
    fail_closed=False,
)
if found:
    print("WiFi network available")
else:
    print("WiFi network not available")
```

Wait for GPIO pin high:
```python
high = WAIT_FOR_PRESENT(
    signal_type="gpio",
    identifier="21",  # GPIO pin 21
    poll_interval_seconds=0.5,
)
print("GPIO pin 21 went high")
```

#### WAIT_FOR_NOTPRESENT
Wait until a monitored signal is no longer present.

**Signature:**
```python
def WAIT_FOR_NOTPRESENT(
    *,
    signal_type: str = "bluetooth",
    identifier: str = "",
    name: str = "",
    mac: str = "",
    service_uuid: str = "",
    timeout_seconds: int = 0,
    scan_window_seconds: int = 4,
    poll_interval_seconds: int = 2,
    fail_closed: bool = True,
) -> bool
```

Same parameters as WAIT_FOR_PRESENT.

**Returns:** True if signal disappeared

---

### Actions (Execution Control)

#### REQUIRE_CAPABILITY
Validate that required tooling, radio hardware, or services exist before payload execution.

**Signature:**
```python
def REQUIRE_CAPABILITY(
    capability_type: str,
    value: str,
    *,
    failure_policy: str = "fail_closed",
) -> bool
```

**Parameters:**
- `capability_type` (str): One of `"binary"`, `"service"`, `"interface"`, `"config"`
  - `"binary"`: Check if executable exists in PATH
  - `"service"`: Check if systemd service is running
  - `"interface"`: Check if network interface exists
  - `"config"`: Check if config file/directory exists
- `value` (str): Dependency identifier
  - For binary: command name (e.g., `"bluetoothctl"`)
  - For service: service name (e.g., `"bluetooth"`)
  - For interface: interface name (e.g., `"wlan0"`)
  - For config: path relative to repo root or absolute (e.g., `"config.json"`)
- `failure_policy` (str): `"fail_closed"` (raise) or `"warn_only"` (return False)

**Returns:** True if capability exists, False if missing and warn_only

**Raises:**
- `ValueError`: If capability_type or value invalid
- `RuntimeError`: If fail_closed and capability missing

**Examples:**

Check for required binary:
```python
from EXTENSIONS.api import REQUIRE_CAPABILITY

REQUIRE_CAPABILITY("binary", "bluetoothctl")  # Raises if missing
```

Check for service with warning:
```python
has_bluetooth = REQUIRE_CAPABILITY(
    "service", "bluetooth",
    failure_policy="warn_only"
)
if not has_bluetooth:
    print("Warning: Bluetooth service not running")
```

Check for interface:
```python
REQUIRE_CAPABILITY("interface", "wlan1")  # Raises if wlan1 doesn't exist
```

Check for config file:
```python
REQUIRE_CAPABILITY("config", "configs/attack_config.json")
```

#### RUN_PAYLOAD
Execute another payload with proper environment and path handling.

**Signature:**
```python
def RUN_PAYLOAD(
    payload: str,
    *payload_args: str,
    selector_mode: str = "auto",
    cooldown_seconds: float = 0,
) -> int
```

**Parameters:**
- `payload` (str): Relative path to payload (e.g., `"utilities/marker.py"`)
- `*payload_args` (str): Arguments to pass to the payload
- `selector_mode` (str): `"auto"` (direct), `"manual"` (user selects), or `"policy"` (rule-based)
- `cooldown_seconds` (float): Optional cooldown to avoid repeated immediate launches

**Returns:** Exit code of the payload process (124 if cooldown in effect)

**Raises:**
- `ValueError`: If payload path escapes payload root
- `FileNotFoundError`: If payload not found

**Examples:**

Run utility payload:
```python
from EXTENSIONS.api import RUN_PAYLOAD

exit_code = RUN_PAYLOAD("utilities/trigger_marker.py", "test_run")
print(f"Payload exited with code: {exit_code}")
```

Run with cooldown (prevent repeated launches):
```python
exit_code = RUN_PAYLOAD(
    "attacks/wifi_scan.py",
    "interface", "wlan1",
    cooldown_seconds=30.0  # Wait 30s before allowing another launch
)
if exit_code == 124:
    print("Payload on cooldown")
```

---

## Usage Patterns

### Preflight Checks

Validate all requirements before running the main payload:

```python
from EXTENSIONS.api import REQUIRE_CAPABILITY, RUN_PAYLOAD
from _input_helper import get_button

# Preflight: Check capabilities
try:
    REQUIRE_CAPABILITY("binary", "bluetoothctl")
    REQUIRE_CAPABILITY("service", "bluetooth")
    REQUIRE_CAPABILITY("interface", "hci0")
except RuntimeError as e:
    print(f"Preflight failed: {e}")
    exit(1)

# Main logic
print("All dependencies available!")
```

### Conditional Execution

Chain payloads based on signal detection:

```python
from EXTENSIONS.api import WAIT_FOR_PRESENT, RUN_PAYLOAD

# Wait for M5Cardputer Bluetooth device
found = WAIT_FOR_PRESENT(
    signal_type="bluetooth",
    identifier="M5Cardputer",
    timeout_seconds=60,
    fail_closed=False,
)

if found:
    exit_code = RUN_PAYLOAD("attacks/m5_attack.py")
else:
    exit_code = RUN_PAYLOAD("attacks/wifi_scan.py")
```

Multi-signal detection pattern:

```python
from EXTENSIONS.api import WAIT_FOR_PRESENT, RUN_PAYLOAD

# Check for target Wi-Fi first
wifi_found = WAIT_FOR_PRESENT(
    signal_type="wifi",
    identifier="TargetSSID",
    timeout_seconds=15,
    fail_closed=False,
)

if wifi_found:
    # Then check for Bluetooth beacon
    ble_found = WAIT_FOR_PRESENT(
        signal_type="bluetooth",
        identifier="BLE_Beacon",
        timeout_seconds=30,
        fail_closed=False,
    )
    if ble_found:
        exit_code = RUN_PAYLOAD("attacks/combined_attack.py")
    else:
        exit_code = RUN_PAYLOAD("attacks/wifi_only.py")
else:
    print("Target network not available")
    exit(1)
```

### Cooldown Pattern

Prevent attack replay during a session:

```python
from EXTENSIONS.api import RUN_PAYLOAD

# Run attack with 60-second cooldown
exit_code = RUN_PAYLOAD(
    "attacks/deauth.py",
    "wlan0",
    cooldown_seconds=60.0  # Only run once per 60s
)

if exit_code == 124:
    print("Attack already ran recently, skipping")
else:
    print(f"Attack completed with exit code: {exit_code}")
```

---

## Notes for Payload Authors

1. **Extensions don't replace normal payloads** - Use standard `try/finally` with `LCD.LCD_Clear()` and `GPIO.cleanup()`
2. **Interactive payloads still use ScaledDraw** - Extensions are for non-visual tasks
3. **Environment is set automatically** - `PYTHONPATH` is configured to include `REPO_ROOT`
4. **Relative paths are relative to payloads/**, - Use `"utilities/helper.py"` not absolute paths
5. **Cooldown markers go to /dev/shm** - Survives across runs but clears on reboot

---

## Internals

### File Structure
```
EXTENSIONS/
├── __init__.py          # Package exports
├── api.py               # Public API re-exports
├── gates.py             # BLE workflow gates (WAIT_FOR_PRESENT, WAIT_FOR_NOTPRESENT)
├── actions.py           # Execution actions (REQUIRE_CAPABILITY, RUN_PAYLOAD)
└── README.md            # This file
```

### Implementation Notes

- **BLE scanning** uses `bluetoothctl` via subprocess
- **Service checking** uses `systemctl is-active`
- **Interface checking** uses `ip link show`
- **Config checking** looks in repo root or absolute path
- **Cooldown tracking** uses `/dev/shm/ktox_cooldown_*` marker files
- **All functions are thread-safe** through subprocess isolation

---

## RaspyJack Compatibility

This API is designed to be compatible with RaspyJack's EXTENSIONS API. Payloads written for either system can use these helpers identically.

