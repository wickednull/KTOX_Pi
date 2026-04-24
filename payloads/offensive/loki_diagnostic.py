#!/usr/bin/env python3
"""
Loki WebUI Diagnostic Tool
===========================
Helps troubleshoot Loki installation and WebUI dashboard issues.
"""

import os
import subprocess
import sys
import socket
from pathlib import Path

KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
VENDOR_DIR = Path(KTOX_DIR) / "vendor" / "loki"
LOKI_DATA = Path(KTOX_DIR) / "loot" / "loki"
LOKI_PORT = 8000


def check_installation():
    """Check if Loki is properly installed"""
    print("\n" + "="*50)
    print("  LOKI INSTALLATION CHECK")
    print("="*50)

    checks = {
        "Vendor directory exists": VENDOR_DIR.exists(),
        "Loki.py exists": (VENDOR_DIR / "Loki.py").exists(),
        "init_shared.py exists": (VENDOR_DIR / "init_shared.py").exists(),
        "webapp.py exists": (VENDOR_DIR / "webapp.py").exists(),
        "ktox_headless_loki.py exists": (VENDOR_DIR / "ktox_headless_loki.py").exists(),
        "pagerctl.py shim exists": (VENDOR_DIR / "lib" / "pagerctl.py").exists(),
        "Data directory exists": LOKI_DATA.exists(),
        "Logs directory exists": (LOKI_DATA / "logs").exists(),
        "Config file exists": (LOKI_DATA / "netkb.csv").exists() or (VENDOR_DIR / "config").exists(),
    }

    for check, result in checks.items():
        status = "[✓]" if result else "[✗]"
        print(f"  {status} {check}")

    all_passed = all(checks.values())
    return all_passed


def check_process():
    """Check if Loki process is running"""
    print("\n" + "="*50)
    print("  LOKI PROCESS CHECK")
    print("="*50)

    try:
        result = subprocess.run(
            ["pgrep", "-f", "ktox_headless_loki"],
            capture_output=True,
            timeout=5
        )
        running = result.returncode == 0
        status = "[✓]" if running else "[✗]"
        print(f"  {status} Process running: {running}")

        if running:
            pids = result.stdout.decode().strip().split('\n')
            for pid in pids:
                if pid:
                    print(f"      PID: {pid}")

        return running
    except Exception as e:
        print(f"  [!] Error checking process: {e}")
        return False


def check_port():
    """Check if Loki port is open"""
    print("\n" + "="*50)
    print("  PORT CHECK")
    print("="*50)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", LOKI_PORT)) == 0
        s.close()
        status = "[✓]" if result else "[✗]"
        print(f"  {status} Port {LOKI_PORT} open: {result}")
        return result
    except Exception as e:
        print(f"  [!] Error checking port: {e}")
        return False


def check_logs():
    """Display recent log entries"""
    print("\n" + "="*50)
    print("  RECENT LOG ENTRIES")
    print("="*50)

    log_file = LOKI_DATA / "logs" / "loki.log"
    if log_file.exists():
        try:
            result = subprocess.run(
                ["tail", "-20", str(log_file)],
                capture_output=True,
                timeout=5
            )
            logs = result.stdout.decode()
            if logs:
                print("\n" + logs)
            else:
                print("  [!] Log file is empty")
        except Exception as e:
            print(f"  [!] Error reading logs: {e}")
    else:
        print(f"  [!] Log file not found: {log_file}")


def check_webapp_files():
    """Check webapp files and structure"""
    print("\n" + "="*50)
    print("  WEBAPP FILES CHECK")
    print("="*50)

    webapp_file = VENDOR_DIR / "webapp.py"
    if webapp_file.exists():
        try:
            with open(webapp_file, 'r') as f:
                content = f.read()

            # Check for key components
            checks = {
                "Flask import": "from flask import" in content or "import flask" in content,
                "app.route decorator": "@app.route" in content or "@route" in content,
                "Dashboard route": "/dashboard" in content or "dashboard" in content,
                "API routes": "/api" in content or "api_" in content,
                "WebUI rendering": "render_template" in content or "index.html" in content,
            }

            for check, result in checks.items():
                status = "[✓]" if result else "[✗]"
                print(f"  {status} {check}")
        except Exception as e:
            print(f"  [!] Error reading webapp.py: {e}")
    else:
        print(f"  [!] webapp.py not found")


def check_templates():
    """Check for HTML templates"""
    print("\n" + "="*50)
    print("  TEMPLATE FILES CHECK")
    print("="*50)

    template_dirs = [
        VENDOR_DIR / "templates",
        VENDOR_DIR / "static",
        VENDOR_DIR / "webapp" / "templates",
        VENDOR_DIR / "static" / "templates",
    ]

    for template_dir in template_dirs:
        if template_dir.exists():
            files = list(template_dir.glob("*.html")) + list(template_dir.glob("*.js")) + list(template_dir.glob("*.css"))
            print(f"  [✓] Found {template_dir.name}/")
            for f in files[:5]:  # Show first 5
                print(f"      - {f.name}")
            if len(files) > 5:
                print(f"      ... and {len(files) - 5} more")

    if not any(d.exists() for d in template_dirs):
        print("  [!] No template directories found")


def main():
    """Run all diagnostics"""
    print("\n" + "="*50)
    print("  LOKI WebUI DIAGNOSTIC TOOL")
    print("="*50)

    install_ok = check_installation()
    process_ok = check_process()
    port_ok = check_port()
    check_logs()
    check_webapp_files()
    check_templates()

    print("\n" + "="*50)
    print("  SUMMARY")
    print("="*50)

    if install_ok and port_ok:
        print("  [✓] Loki appears to be properly configured")
        print("  [+] Try accessing: http://localhost:8000")
    elif install_ok and process_ok and not port_ok:
        print("  [!] Loki is installed and running but port not responding")
        print("  [+] Check logs for startup errors")
    elif install_ok and not process_ok:
        print("  [!] Loki is installed but not running")
        print("  [+] Try starting with the menu system")
    else:
        print("  [!] Loki installation appears incomplete")
        print("  [+] Try reinstalling Loki")

    print("\n" + "="*50)


if __name__ == "__main__":
    main()
