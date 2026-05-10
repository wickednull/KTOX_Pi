#!/usr/bin/env python3
"""
Diagnostic tool to test WiFi scanning setup
Helps identify where Pet_Rock_WiFi_Pro is failing
"""

import subprocess
import sys
import time

def run_cmd(cmd, desc=""):
    """Run command and show output"""
    print(f"\n{'='*50}")
    print(f"TEST: {desc}")
    print(f"CMD: {' '.join(cmd)}")
    print(f"{'='*50}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            print(f"STDERR:\n{result.stderr}")
        print(f"Return code: {result.returncode}")
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        print("TIMEOUT: Command took too long")
        return False, "", "timeout"
    except Exception as e:
        print(f"ERROR: {e}")
        return False, "", str(e)

def main():
    print("WiFi Scanning Diagnostic Tool")
    print("This will help identify why Pet_Rock_WiFi_Pro isn't working\n")

    # Test 1: Check if airmon-ng is installed
    run_cmd(["which", "airmon-ng"], "Check if airmon-ng is installed")

    # Test 2: Check available interfaces
    run_cmd(["ip", "link", "show"], "List network interfaces")

    # Test 3: Try to enable monitor mode on wlan0 (dry run)
    print(f"\n{'='*50}")
    print("TEST: Check if wlan0 exists")
    print(f"{'='*50}")
    result = subprocess.run(["ip", "link", "show", "wlan0"], capture_output=True)
    if result.returncode == 0:
        print("✓ wlan0 exists")

        # Test 4: Try monitor mode
        print("\nAttempting to enable monitor mode on wlan0...")
        run_cmd(["sudo", "airmon-ng", "start", "wlan0"], "Enable monitor mode on wlan0")

        time.sleep(2)

        # Test 5: Check if monitor interface was created
        run_cmd(["ip", "link", "show"], "Check interfaces after monitor mode")

        # Test 6: Try to capture packets briefly
        print(f"\n{'='*50}")
        print("TEST: Try to capture packets with tcpdump")
        print(f"{'='*50}")
        try:
            result = subprocess.run(
                ["sudo", "timeout", "3", "tcpdump", "-i", "wlan0mon", "-c", "10"],
                capture_output=True, text=True, timeout=5
            )
            print(f"Captured packets:\n{result.stdout}")
            print(f"Errors:\n{result.stderr}")
        except Exception as e:
            print(f"tcpdump failed: {e}")

        # Test 7: Try with Python scapy
        print(f"\n{'='*50}")
        print("TEST: Try to import scapy and sniff packets")
        print(f"{'='*50}")
        try:
            from scapy.all import sniff, Dot11
            print("✓ Scapy imported successfully")

            print("\nAttempting to sniff packets on wlan0mon for 3 seconds...")
            packet_count = [0]

            def pkt_callback(pkt):
                packet_count[0] += 1

            try:
                sniff(iface="wlan0mon", prn=pkt_callback, timeout=3, store=0)
                print(f"✓ Sniffed {packet_count[0]} packets")
            except Exception as e:
                print(f"✗ Sniffing failed: {e}")
        except ImportError as e:
            print(f"✗ Scapy not available: {e}")

        # Cleanup
        print(f"\n{'='*50}")
        print("TEST: Disable monitor mode")
        print(f"{'='*50}")
        run_cmd(["sudo", "airmon-ng", "stop", "wlan0mon"], "Disable monitor mode")

    else:
        print("✗ wlan0 not found - check with 'ip link show'")

if __name__ == "__main__":
    main()
