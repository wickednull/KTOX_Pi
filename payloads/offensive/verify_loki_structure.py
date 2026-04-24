#!/usr/bin/env python3
"""
Loki Installation Structure Verifier
=====================================
Verifies that all required Loki files are present and properly structured.
"""

import os
from pathlib import Path

KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
VENDOR_DIR = Path(KTOX_DIR) / "vendor" / "loki"


def print_section(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_file(path, required=True):
    """Check if file exists"""
    exists = path.exists()
    status = "[✓]" if exists else ("[✗]" if required else "[?]")
    rel_path = path.relative_to(VENDOR_DIR) if path.is_relative_to(VENDOR_DIR) else path
    print(f"  {status} {rel_path}")
    return exists


def check_directory(path, required=True):
    """Check if directory exists"""
    exists = path.exists()
    status = "[✓]" if exists else ("[✗]" if required else "[?]")
    rel_path = path.relative_to(VENDOR_DIR) if path.is_relative_to(VENDOR_DIR) else path
    print(f"  {status} {rel_path}/")
    return exists


def main():
    print_section("LOKI INSTALLATION STRUCTURE VERIFICATION")

    if not VENDOR_DIR.exists():
        print(f"\n[!] Loki not installed at {VENDOR_DIR}")
        print("    Run: python3 /home/user/KTOX_Pi/payloads/offensive/loki_engine.py")
        return

    print(f"\nVendor Directory: {VENDOR_DIR}")

    # Check core files
    print_section("CORE FILES")
    files_ok = [
        check_file(VENDOR_DIR / "Loki.py", required=True),
        check_file(VENDOR_DIR / "init_shared.py", required=True),
        check_file(VENDOR_DIR / "webapp.py", required=True),
        check_file(VENDOR_DIR / "config.py", required=True),
        check_file(VENDOR_DIR / "ktox_headless_loki.py", required=True),
    ]

    # Check lib files
    print_section("LIBRARY FILES")
    lib_files = [
        check_file(VENDOR_DIR / "lib" / "__init__.py", required=False),
        check_file(VENDOR_DIR / "lib" / "pagerctl.py", required=True),
    ]

    # Check directories
    print_section("DIRECTORIES")
    dir_ok = [
        check_directory(VENDOR_DIR / "payloads", required=False),
        check_directory(VENDOR_DIR / "actions", required=False),
        check_directory(VENDOR_DIR / "templates", required=False),
        check_directory(VENDOR_DIR / "static", required=False),
        check_directory(VENDOR_DIR / "config", required=False),
    ]

    # List Python files in root
    print_section("PYTHON FILES IN ROOT")
    py_files = sorted([f for f in VENDOR_DIR.glob("*.py") if f.is_file()])
    for f in py_files:
        print(f"  - {f.name}")

    # Check webapp.py content
    print_section("WEBAPP.PY ANALYSIS")
    webapp_file = VENDOR_DIR / "webapp.py"
    if webapp_file.exists():
        try:
            with open(webapp_file, 'r') as f:
                content = f.read()
                size = len(content)
                lines = content.count('\n')

            print(f"  File size: {size} bytes")
            print(f"  Lines: {lines}")

            # Check for key patterns
            patterns = {
                "Flask import": ["from flask import", "import flask"],
                "app.route": ["@app.route", "@route"],
                "render_template": ["render_template"],
                "/dashboard": ["'/dashboard'", '"/dashboard"'],
                "/api": ["'/api'", '"/api"'],
                "web_thread": ["web_thread", "Thread"],
            }

            print("\n  Key patterns found:")
            for pattern_name, patterns_list in patterns.items():
                found = any(p in content for p in patterns_list)
                status = "[✓]" if found else "[✗]"
                print(f"    {status} {pattern_name}")

        except Exception as e:
            print(f"  [!] Error reading webapp.py: {e}")
    else:
        print("  [!] webapp.py not found")

    # Check init_shared.py
    print_section("INIT_SHARED.PY ANALYSIS")
    init_shared = VENDOR_DIR / "init_shared.py"
    if init_shared.exists():
        try:
            with open(init_shared, 'r') as f:
                content = f.read()

            has_shared_data = "shared_data" in content
            has_config = "load_config" in content or "config" in content.lower()

            print(f"  [{'✓' if has_shared_data else '✗'}] shared_data class/object defined")
            print(f"  [{'✓' if has_config else '✗'}] Configuration loading")

        except Exception as e:
            print(f"  [!] Error reading init_shared.py: {e}")
    else:
        print("  [!] init_shared.py not found")

    # Summary
    print_section("VERIFICATION SUMMARY")

    all_files_ok = all(files_ok)
    lib_files_ok = all(lib_files)

    if all_files_ok and lib_files_ok:
        print("\n  [✓] Loki installation appears complete")
        print("      All required files are present")
        print("\n  Next steps:")
        print("  1. Test WebUI: python3 /home/user/KTOX_Pi/payloads/offensive/test_loki_webui.py")
        print("  2. Check logs: tail -f /root/KTOx/loot/loki/logs/loki.log")
        print("  3. Access: http://<device-ip>:8000")
    else:
        print("\n  [!] Loki installation is incomplete")
        if not all_files_ok:
            print("      Missing core files - reinstall required")
        if not lib_files_ok:
            print("      Missing library files - may cause runtime errors")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
