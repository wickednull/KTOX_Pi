#!/usr/bin/env python3
"""
Check Loki Installation Completeness
=====================================
Verifies all required Loki files are present and properly structured.
"""

import sys
from pathlib import Path

KTOX_ROOT = "/root/KTOx"
VENDOR_DIR = Path(KTOX_ROOT) / "vendor" / "loki"
LOKI_DIR = VENDOR_DIR / "payloads" / "user" / "reconnaissance" / "loki"

print("\n" + "=" * 70)
print("  LOKI INSTALLATION STRUCTURE CHECK")
print("=" * 70)

print(f"\nClone location: {VENDOR_DIR}")
print(f"Actual code location: {LOKI_DIR}")

# Check if repo was cloned
if not VENDOR_DIR.exists():
    print("\n[✗] Loki repository not cloned to vendor/loki")
    sys.exit(1)

print("\n[✓] Repository cloned")

# Check nested structure
if not LOKI_DIR.exists():
    print("\n[✗] Nested loki directory not found!")
    print("    Expected: vendor/loki/payloads/user/reconnaissance/loki/")
    print("    Repository might have been cloned to wrong location")
    sys.exit(1)

print("[✓] Nested structure correct")

# Check core Python files
print("\n" + "-" * 70)
print("CORE FILES CHECK:")
print("-" * 70)

core_files = [
    "Loki.py",
    "init_shared.py",
    "shared.py",
    "webapp.py",
    "loki_menu.py",
    "display.py",
    "logger.py",
    "orchestrator.py",
    "__init__.py",
]

missing = []
for fname in core_files:
    fpath = LOKI_DIR / fname
    status = "[✓]" if fpath.exists() else "[✗]"
    print(f"  {status} {fname}")
    if not fpath.exists():
        missing.append(fname)

# Check critical directories
print("\n" + "-" * 70)
print("DIRECTORY CHECK:")
print("-" * 70)

dirs = ["actions", "config", "data", "lib", "resources", "web", "themes"]
for dname in dirs:
    dpath = LOKI_DIR / dname
    status = "[✓]" if dpath.exists() else "[✗]"
    print(f"  {status} {dname}/")

# Check webapp.py specifically
print("\n" + "-" * 70)
print("WEBAPP.PY ANALYSIS:")
print("-" * 70)

webapp_file = LOKI_DIR / "webapp.py"
if webapp_file.exists():
    try:
        with open(webapp_file, 'r') as f:
            content = f.read()

        checks = {
            "Flask import": "from flask import" in content or "import flask" in content,
            "web_thread export": "web_thread" in content,
            "handle_exit_web": "handle_exit_web" in content,
            "app.route": "@app.route" in content,
            "run method": "app.run" in content or "run(" in content,
        }

        for check_name, result in checks.items():
            status = "[✓]" if result else "[✗]"
            print(f"  {status} {check_name}")

    except Exception as e:
        print(f"  [✗] Error reading webapp.py: {e}")
else:
    print("  [✗] webapp.py not found")

# Check init_shared.py
print("\n" + "-" * 70)
print("INIT_SHARED.PY ANALYSIS:")
print("-" * 70)

init_shared = LOKI_DIR / "init_shared.py"
if init_shared.exists():
    try:
        with open(init_shared, 'r') as f:
            content = f.read()

        checks = {
            "SharedData class": "class SharedData" in content or "SharedData =" in content,
            "shared_data instance": "shared_data" in content,
            "load_config method": "load_config" in content,
            "webapp_should_exit attr": "webapp_should_exit" in content,
        }

        for check_name, result in checks.items():
            status = "[✓]" if result else "[✗]"
            print(f"  {status} {check_name}")

    except Exception as e:
        print(f"  [✗] Error reading init_shared.py: {e}")
else:
    print("  [✗] init_shared.py not found")

# Check if launcher exists
print("\n" + "-" * 70)
print("LAUNCHER CHECK:")
print("-" * 70)

launcher = LOKI_DIR / "ktox_headless_loki.py"
if launcher.exists():
    print(f"  [✓] ktox_headless_loki.py exists")
else:
    print(f"  [✗] ktox_headless_loki.py missing (will be created at runtime)")

# Summary
print("\n" + "=" * 70)
print("SUMMARY:")
print("=" * 70)

if missing:
    print(f"\n[!] Missing {len(missing)} critical files:")
    for f in missing:
        print(f"    - {f}")
    print("\n[!] Installation appears INCOMPLETE")
    print("    Solution: Reinstall Loki via loki_engine.py")
else:
    print("\n[✓] All critical files present")
    print("[✓] Installation structure appears COMPLETE")
    print("\nNext steps:")
    print("  1. Start Loki: python3 /home/user/KTOX_Pi/payloads/offensive/loki_engine.py")
    print("  2. Access WebUI: http://<device-ip>:8000")
    print("  3. Check logs: tail -f /root/KTOx/loot/loki/logs/ktox_loki.log")

print("\n" + "=" * 70)
