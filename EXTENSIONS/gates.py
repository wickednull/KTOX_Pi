#!/usr/bin/env python3
"""Shared gate helpers for KTOX extensions - Bluetooth, Wi-Fi, and GPIO signal monitoring."""
from __future__ import annotations

import time
import subprocess
from pathlib import Path
from typing import Optional


def _scan_ble_devices(scan_window_seconds: int = 4) -> dict[str, dict]:
    """
    Scan for BLE devices using bluetoothctl.

    Returns dict of device_address -> {"name": str, "rssi": int, "services": [uuid, ...]}
    """
    devices = {}
    try:
        # Start BLE scan
        subprocess.run(
            ["bluetoothctl", "scan", "on"],
            capture_output=True,
            timeout=2,
        )
        time.sleep(scan_window_seconds)

        # Get devices
        result = subprocess.run(
            ["bluetoothctl", "devices"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        for line in result.stdout.split('\n'):
            parts = line.split()
            if len(parts) >= 3 and parts[0] == 'Device':
                addr = parts[1]
                name = ' '.join(parts[2:])
                devices[addr] = {"name": name, "rssi": 0, "services": []}

        # Stop scan
        subprocess.run(
            ["bluetoothctl", "scan", "off"],
            capture_output=True,
            timeout=2,
        )
    except Exception:
        pass

    return devices


def _scan_wifi_networks(scan_window_seconds: int = 4) -> dict[str, dict]:
    """
    Scan for Wi-Fi networks using nmcli or iw.

    Returns dict of SSID -> {"strength": int, "bssid": str, "frequency": str}
    """
    networks = {}
    try:
        # Try nmcli first (NetworkManager)
        result = subprocess.run(
            ["nmcli", "dev", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n')[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 7:
                    bssid = parts[0]
                    ssid = ' '.join(parts[1:-5])
                    mode = parts[-5]
                    chan = parts[-4]
                    rate = parts[-3]
                    signal = int(parts[-2])
                    networks[ssid] = {
                        "strength": signal,
                        "bssid": bssid,
                        "frequency": chan,
                    }
    except Exception:
        pass

    return networks


def _check_gpio(label: str) -> bool:
    """Check if GPIO pin is high. Label can be pin number or sysfs path."""
    try:
        path = Path(f"/sys/class/gpio/gpio{label}/value")
        if path.exists():
            value = path.read_text().strip()
            return value == "1"
    except Exception:
        pass
    return False


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
) -> bool:
    """
    Wait until a monitored signal becomes present.

    Args:
        signal_type: "bluetooth", "wifi", or "gpio"
        identifier: Name/MAC (bluetooth), SSID (wifi), or GPIO label/path (gpio)
        name: Device name to match (bluetooth only, partial match)
        mac: MAC address to match (bluetooth only, e.g., "AA:BB:CC:DD:EE:FF")
        service_uuid: Service UUID to match (bluetooth only)
        timeout_seconds: Max wait time (0 = infinite)
        scan_window_seconds: Duration of each scan window
        poll_interval_seconds: Interval between scans
        fail_closed: If True, raise on timeout; if False, return False

    Returns:
        True if signal found, False if timeout and fail_closed=False

    Raises:
        TimeoutError: If timeout and fail_closed=True
        RuntimeError: If scan unavailable and fail_closed=True
    """
    signal_type = str(signal_type).strip().lower()
    if signal_type not in ("bluetooth", "wifi", "gpio"):
        raise ValueError(f"unsupported signal_type: {signal_type}")
    if not identifier:
        raise ValueError("identifier is required")

    start = time.monotonic()

    while True:
        try:
            if signal_type == "gpio":
                # GPIO is synchronous - check immediately
                if _check_gpio(identifier):
                    return True
            elif signal_type == "bluetooth":
                devices = _scan_ble_devices(scan_window_seconds)
                for addr, info in devices.items():
                    # Match by MAC
                    if mac and addr.upper() != mac.upper():
                        continue
                    # Match by identifier (name)
                    if identifier and identifier.lower() not in info["name"].lower():
                        continue
                    # Match by service (stub)
                    if service_uuid:
                        if service_uuid not in info.get("services", []):
                            continue
                    return True
            elif signal_type == "wifi":
                networks = _scan_wifi_networks(scan_window_seconds)
                for ssid in networks.keys():
                    # Match by SSID (exact or partial)
                    if identifier.lower() in ssid.lower():
                        return True
        except Exception as e:
            if fail_closed:
                raise RuntimeError(f"{signal_type} scan failed: {e}")
            return False

        if timeout_seconds > 0:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                if fail_closed:
                    raise TimeoutError(f"WAIT_FOR_PRESENT({signal_type}={identifier}) timed out")
                return False

        time.sleep(poll_interval_seconds)


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
) -> bool:
    """
    Wait until a monitored signal is no longer present.

    Args:
        signal_type: "bluetooth", "wifi", or "gpio"
        identifier: Name/MAC (bluetooth), SSID (wifi), or GPIO label/path (gpio)
        name: Device name to match (bluetooth only, partial match)
        mac: MAC address to match (bluetooth only, e.g., "AA:BB:CC:DD:EE:FF")
        service_uuid: Service UUID to match (bluetooth only)
        timeout_seconds: Max wait time (0 = infinite)
        scan_window_seconds: Duration of each scan window
        poll_interval_seconds: Interval between scans
        fail_closed: If True, raise on timeout; if False, return False

    Returns:
        True if signal gone, False if timeout and fail_closed=False

    Raises:
        TimeoutError: If timeout and fail_closed=True
        RuntimeError: If scan unavailable and fail_closed=True
    """
    signal_type = str(signal_type).strip().lower()
    if signal_type not in ("bluetooth", "wifi", "gpio"):
        raise ValueError(f"unsupported signal_type: {signal_type}")
    if not identifier:
        raise ValueError("identifier is required")

    start = time.monotonic()

    while True:
        try:
            signal_found = False

            if signal_type == "gpio":
                # GPIO is synchronous - check immediately
                signal_found = _check_gpio(identifier)
            elif signal_type == "bluetooth":
                devices = _scan_ble_devices(scan_window_seconds)
                for addr, info in devices.items():
                    # Match by MAC
                    if mac and addr.upper() != mac.upper():
                        continue
                    # Match by identifier (name)
                    if identifier and identifier.lower() not in info["name"].lower():
                        continue
                    # Match by service (stub)
                    if service_uuid:
                        if service_uuid not in info.get("services", []):
                            continue
                    signal_found = True
                    break
            elif signal_type == "wifi":
                networks = _scan_wifi_networks(scan_window_seconds)
                for ssid in networks.keys():
                    # Match by SSID (exact or partial)
                    if identifier.lower() in ssid.lower():
                        signal_found = True
                        break

            if not signal_found:
                return True
        except Exception as e:
            if fail_closed:
                raise RuntimeError(f"{signal_type} scan failed: {e}")
            return False

        if timeout_seconds > 0:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                if fail_closed:
                    raise TimeoutError(f"WAIT_FOR_NOTPRESENT({signal_type}={identifier}) timed out")
                return False

        time.sleep(poll_interval_seconds)
