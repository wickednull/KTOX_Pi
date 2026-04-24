#!/usr/bin/env python3
"""
KTOx WiFi Manager Payload
=============================
Launch the WiFi management interface in KTOx

BUTTON LAYOUT:
- Automatic launch of WiFi LCD interface
- Full WiFi network management with cyberpunk UI
- Profile creation and connection using DarkSecKeyboard
- Real-time interface status monitoring

FEATURES:
- Scan and connect to WiFi networks
- Save network profiles with secure password input
- Manage multiple WiFi dongles
- Interface selection for tools
- Connection status monitoring
- Cyberpunk aesthetic with KTOx theming

CONTROLS:
- UP/DOWN: Navigate menus
- OK: Select/Confirm
- KEY1: Quick connect/disconnect
- KEY2: Refresh/Scan
- KEY3: Back/Exit

This payload provides complete WiFi management for KTOx
while maintaining full ethernet compatibility.
"""

import os
import sys
import subprocess

# Add WiFi system to path
sys.path.append('/root/KTOx/wifi/')
sys.path.append('/root/KTOx/')

def main():
    """Launch the WiFi management interface."""
    try:
        print("\n" + "="*50)
        print("🌐 KTOx WiFi MANAGER")
        print("="*50)
        print()
        print("Launching WiFi management with cyberpunk UI...")
        print()

        # Check if WiFi system is available
        wifi_interface_path = '/root/KTOx/wifi/wifi_lcd_interface.py'

        if not os.path.exists(wifi_interface_path):
            print("❌ WiFi management system not found!")
            print("   Please ensure WiFi system is properly installed.")
            return False

        print("📱 WiFi LCD Interface loaded")
        print("   Cyberpunk theming: ACTIVE")
        print("   DarkSecKeyboard: ENABLED")
        print()
        print("📡 Features available:")
        print("   ✓ Network scanning & connection")
        print("   ✓ Profile management")
        print("   ✓ Real-time status monitoring")
        print("   ✓ Secure password input")
        print()
        print("🔄 WiFi + Ethernet dual support")
        print()
        print("-"*50)
        print()

        # Run the WiFi LCD interface
        result = subprocess.run([
            'python3', wifi_interface_path
        ], capture_output=False)

        print()
        print("="*50)
        print(f"📋 WiFi manager exited with code: {result.returncode}")
        print("="*50)
        return result.returncode == 0

    except KeyboardInterrupt:
        print("\n⏹️  WiFi manager interrupted by user")
        return True
    except Exception as e:
        print(f"❌ Error launching WiFi manager: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    main()
