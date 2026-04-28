#!/usr/bin/env python3
"""
Loki WebUI Test & Verification Script
======================================
Tests Loki WebUI connectivity and endpoint availability.
"""

import sys
import socket
import time
import urllib.request
import urllib.error
import json
from pathlib import Path

LOKI_HOST = "127.0.0.1"
LOKI_PORT = 8000
TIMEOUT = 5


def check_port_open():
    """Test if Loki port is open"""
    print("[*] Testing port connectivity...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        result = s.connect_ex((LOKI_HOST, LOKI_PORT)) == 0
        s.close()

        if result:
            print(f"  [✓] Port {LOKI_PORT} is open")
            return True
        else:
            print(f"  [✗] Port {LOKI_PORT} is closed - Loki not running?")
            return False
    except Exception as e:
        print(f"  [✗] Error: {e}")
        return False


def check_endpoint(path, description):
    """Test a specific endpoint"""
    url = f"http://{LOKI_HOST}:{LOKI_PORT}{path}"
    print(f"\n[*] Testing {description}")
    print(f"    URL: {url}")

    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Loki-TestClient/1.0')

        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            status = response.status
            content_type = response.headers.get('Content-Type', 'unknown')
            content_length = response.headers.get('Content-Length', 'unknown')
            data = response.read()

            print(f"  [✓] Status: {status}")
            print(f"      Content-Type: {content_type}")
            print(f"      Content-Length: {content_length}")

            # Display preview
            if b'html' in data[:200].lower() or b'<!DOCTYPE' in data[:50]:
                print(f"      [✓] HTML content detected")
                # Check for key elements
                if b'dashboard' in data.lower():
                    print(f"      [✓] Dashboard elements found")
                if b'loki' in data.lower():
                    print(f"      [✓] Loki references found")
            elif b'json' in content_type.lower():
                try:
                    json_data = json.loads(data)
                    print(f"      [✓] Valid JSON response")
                    print(f"      Keys: {list(json_data.keys())[:5]}")
                except:
                    print(f"      [!] Invalid JSON")
            else:
                preview = data[:100].decode('utf-8', errors='ignore')
                print(f"      Preview: {preview}")

            return True

    except urllib.error.HTTPError as e:
        print(f"  [✗] HTTP {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"  [✗] Connection error: {e.reason}")
        return False
    except socket.timeout:
        print(f"  [✗] Timeout (>{TIMEOUT}s)")
        return False
    except Exception as e:
        print(f"  [✗] Error: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("  LOKI WebUI ENDPOINT TEST")
    print("=" * 60)

    # Test connectivity
    if not check_port_open():
        print("\n[!] Cannot connect to Loki on port 8000")
        print("    Make sure Loki is running: python3 /root/KTOx/payloads/offensive/loki_engine.py")
        return

    time.sleep(1)

    # Test endpoints
    endpoints = [
        ("/", "Root / Homepage"),
        ("/index.html", "Index page"),
        ("/dashboard", "Dashboard"),
        ("/dashboard/", "Dashboard with slash"),
        ("/api", "API root"),
        ("/api/status", "API status"),
        ("/api/hosts", "API hosts"),
        ("/api/results", "API results"),
        ("/static/", "Static files"),
        ("/templates", "Templates"),
    ]

    results = []
    for path, desc in endpoints:
        results.append((path, check_endpoint(path, desc)))

    # Summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)

    successful = sum(1 for _, result in results if result)
    total = len(results)

    print(f"\nEndpoints tested: {total}")
    print(f"Successful: {successful}")
    print(f"Failed: {total - successful}")

    print("\nResults:")
    for path, result in results:
        status = "[✓]" if result else "[✗]"
        print(f"  {status} {path}")

    # Recommendations
    print("\n" + "=" * 60)
    print("  RECOMMENDATIONS")
    print("=" * 60)

    if successful == 0:
        print("  [!] No endpoints responded - Loki web server may not be running")
        print("      Check: ps aux | grep loki")
        print("      Logs: tail -f /root/KTOx/loot/loki/logs/loki.log")
    elif successful < total / 2:
        print("  [!] Many endpoints failed - Flask app may be partially broken")
        print("      Check logs for Flask initialization errors")
    else:
        print("  [✓] WebUI is responding")
        if any(r for p, r in results if "/dashboard" in p):
            print("      [✓] Dashboard endpoint is working")
        else:
            print("      [!] Dashboard endpoint not responding - may need route fixes")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
