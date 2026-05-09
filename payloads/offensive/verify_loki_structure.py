#!/usr/bin/env python3
"""Verify the vendored brainphreak/loki-recon layout."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_root() -> Path:
    env_root = os.environ.get("KTOX_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


KTOX_ROOT = resolve_root()
VENDOR_DIR = KTOX_ROOT / "vendor" / "loki"
LOKI_PACKAGE = VENDOR_DIR / "loki"


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_path(path: Path, required: bool = True) -> bool:
    exists = path.exists()
    status = "OK" if exists else ("MISSING" if required else "optional")
    try:
        rel_path = path.relative_to(VENDOR_DIR)
    except ValueError:
        rel_path = path
    print(f"  [{status}] {rel_path}")
    return exists


def main() -> int:
    print_section("LOKI VENDOR STRUCTURE VERIFICATION")
    print(f"\nKTOX root: {KTOX_ROOT}")
    print(f"Vendor directory: {VENDOR_DIR}")

    if not VENDOR_DIR.exists():
        print("\n[FAIL] Loki is not installed at vendor/loki")
        print("       Run: bash setup_loki.sh /root/KTOx")
        return 1

    print_section("TOP LEVEL")
    top_level_ok = [
        check_path(VENDOR_DIR / ".git", required=False),
        check_path(VENDOR_DIR / "README.md"),
        check_path(VENDOR_DIR / "requirements.txt"),
        check_path(VENDOR_DIR / "loki.py"),
        check_path(LOKI_PACKAGE),
    ]

    print_section("LOKI PACKAGE")
    package_ok = [
        check_path(LOKI_PACKAGE / "__init__.py"),
        check_path(LOKI_PACKAGE / "Loki.py"),
        check_path(LOKI_PACKAGE / "init_shared.py"),
        check_path(LOKI_PACKAGE / "shared.py"),
        check_path(LOKI_PACKAGE / "webapp.py"),
        check_path(LOKI_PACKAGE / "loki_menu.py"),
        check_path(LOKI_PACKAGE / "orchestrator.py"),
    ]

    print_section("DIRECTORIES")
    dir_ok = [
        check_path(LOKI_PACKAGE / "actions"),
        check_path(LOKI_PACKAGE / "config"),
        check_path(LOKI_PACKAGE / "data"),
        check_path(LOKI_PACKAGE / "resources"),
        check_path(LOKI_PACKAGE / "themes"),
        check_path(LOKI_PACKAGE / "web"),
        check_path(LOKI_PACKAGE / "web" / "index.html"),
    ]

    print_section("WEBAPP ANALYSIS")
    webapp_file = LOKI_PACKAGE / "webapp.py"
    webapp_ok = False
    if webapp_file.exists():
        content = webapp_file.read_text(encoding="utf-8", errors="replace")
        checks = {
            "HTTP server import": "import http.server" in content,
            "Custom request handler": "class CustomHandler" in content,
            "API routes": "/api/v1/" in content,
            "web thread": "web_thread" in content and "WebThread" in content,
        }
        webapp_ok = all(checks.values())
        for name, passed in checks.items():
            print(f"  [{'OK' if passed else 'MISSING'}] {name}")
    else:
        print("  [MISSING] loki/webapp.py")

    print_section("SUMMARY")
    all_ok = all(top_level_ok + package_ok + dir_ok) and webapp_ok
    if all_ok:
        print("\n[OK] Loki vendor structure matches brainphreak/loki-recon.")
        print("     Start with: python3 payloads/offensive/loki_manager.py start")
        return 0

    print("\n[FAIL] Loki vendor structure is incomplete.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
