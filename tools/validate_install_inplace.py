#!/usr/bin/env python3
"""Static validation for install.sh in-place update behavior."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    text = INSTALL.read_text(encoding="utf-8", errors="replace")
    require(
        'readlink -f "$FIRMWARE_DIR"' in text and 'readlink -f "$KTOX_DIR"' in text,
        "install.sh should detect when it is running from /root/KTOx",
    )
    require(
        "skipping file copy" in text,
        "install.sh should skip self-copying during in-place updates",
    )
    guard_pos = text.find('readlink -f "$FIRMWARE_DIR"')
    copy_pos = text.find("# Core system files")
    close_pos = text.find('info "KTOx main suite installed"')
    require(guard_pos != -1 and copy_pos != -1 and close_pos != -1, "install copy section markers missing")
    require(guard_pos < copy_pos < close_pos, "in-place guard should wrap the copy section")
    require(
        'chmod +x "$KTOX_DIR/ktox_device.py"' in text and text.find('chmod +x "$KTOX_DIR/ktox_device.py"') > close_pos,
        "installer should continue into permissions after skipping copy",
    )
    print("install in-place validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
