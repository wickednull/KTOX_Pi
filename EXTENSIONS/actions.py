#!/usr/bin/env python3
"""Shared action helpers for KTOX extensions."""
from __future__ import annotations

import os
import time
from pathlib import Path
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_ROOT = REPO_ROOT / "payloads"


def REQUIRE_CAPABILITY(
    capability_type: str,
    value: str,
    *,
    failure_policy: str = "fail_closed",
) -> bool:
    """
    Validate that required tooling, radio hardware, or services exist.

    Args:
        capability_type: One of "binary", "service", "interface", "config"
        value: Dependency identifier (e.g., "bluetoothctl", "wlan1", "caddy", "config.json")
        failure_policy: "fail_closed" (raise on missing) or "warn_only" (return False)

    Returns:
        True if capability exists, False if warn_only and missing, raises if fail_closed and missing

    Raises:
        ValueError: If capability_type or value invalid
        RuntimeError: If fail_closed and capability missing
    """
    capability_type = str(capability_type).strip().lower()
    value = str(value).strip()
    if capability_type not in {"binary", "service", "interface", "config"}:
        raise ValueError(f"unsupported capability_type: {capability_type}")
    if not value:
        raise ValueError("value is required")

    if capability_type == "binary":
        ok = shutil.which(value) is not None
    elif capability_type == "service":
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "--quiet", value],
                capture_output=True,
                timeout=5,
            )
            ok = result.returncode == 0
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            ok = False
    elif capability_type == "interface":
        try:
            result = subprocess.run(
                ["ip", "link", "show", value],
                capture_output=True,
                timeout=5,
            )
            ok = result.returncode == 0
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            ok = False
    else:  # config
        raw = Path(value)
        target = raw if raw.is_absolute() else (REPO_ROOT / raw)
        ok = target.exists()

    if ok:
        return True
    if str(failure_policy).strip().lower() == "warn_only":
        return False
    raise RuntimeError(f"missing required capability: {capability_type}={value}")


def RUN_PAYLOAD(
    payload: str,
    *payload_args: str,
    selector_mode: str = "auto",
    cooldown_seconds: float = 0,
) -> int:
    """
    Execute another payload with proper environment and path handling.

    Args:
        payload: Relative path to payload (e.g., "utilities/marker.py")
        payload_args: Arguments to pass to the payload
        selector_mode: "auto" (direct), "manual" (user selects), or "policy" (rule-based)
        cooldown_seconds: Optional cooldown to avoid repeated immediate launches

    Returns:
        Exit code of the payload process

    Raises:
        ValueError: If payload path escapes payload root
        FileNotFoundError: If payload not found
    """
    payload_path = (PAYLOAD_ROOT / payload).resolve()
    try:
        payload_root = PAYLOAD_ROOT.resolve()
    except FileNotFoundError:
        payload_root = PAYLOAD_ROOT
    if payload_root not in payload_path.parents and payload_path != payload_root:
        raise ValueError("payload path escapes payload root")
    if not payload_path.is_file():
        raise FileNotFoundError(f"payload not found: {payload_path}")

    # Cooldown handling
    if cooldown_seconds > 0:
        cooldown_marker = Path(f"/dev/shm/ktox_cooldown_{payload_path.stem}")
        if cooldown_marker.exists():
            try:
                elapsed = time.monotonic() - float(cooldown_marker.read_text())
                if elapsed < cooldown_seconds:
                    return 124  # Return code indicating cooldown in effect
            except (ValueError, OSError):
                pass

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = ["python3", str(payload_path), *payload_args]

    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env).returncode
    finally:
        # Update cooldown marker
        if cooldown_seconds > 0:
            try:
                cooldown_marker = Path(f"/dev/shm/ktox_cooldown_{payload_path.stem}")
                cooldown_marker.write_text(str(time.monotonic()))
            except OSError:
                pass

    return result
