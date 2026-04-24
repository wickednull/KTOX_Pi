#!/usr/bin/env python3
"""
KTOx Network Manager Payload
=============================
Launch the network management interface

Features:
- Scan and connect to WiFi networks
- Manage network profiles
- View connection status
- Configure network preferences
"""

import os
import sys
import subprocess

# Add KTOX root to path
sys.path.append('/root/KTOx/')

def main():
    """Launch the network manager."""
    try:
        print("\n" + "="*50)
        print("🌐 KTOx NETWORK MANAGER")
        print("="*50)
        print()
        print("Launching network management interface...")
        print()

        # Path to network manager
        network_manager_path = '/root/KTOx/wifi/network_manager.py'

        if not os.path.exists(network_manager_path):
            print("❌ Network manager not found!")
            print("   Please ensure it's installed at:", network_manager_path)
            return False

        print("📱 Network Manager loaded")
        print("   LCD Interface: ACTIVE")
        print("   WiFi Scanning: ENABLED")
        print()

        # Run the network manager
        result = subprocess.run([
            'python3', network_manager_path
        ], capture_output=False)

        print()
        print("="*50)
        print(f"📋 Network manager exited with code: {result.returncode}")
        print("="*50)
        return result.returncode == 0

    except KeyboardInterrupt:
        print("\n⏹️  Network manager interrupted by user")
        return True
    except Exception as e:
        print(f"❌ Error launching network manager: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    main()
