#!/usr/bin/env python3
"""
WiFi Interface Switcher - Quick wlan0 vs wlan1 Tool
===================================================
Simple command-line tool to quickly switch between WiFi interfaces
and fix the issue where KTOx keeps using the wrong interface.

Usage:
    python3 wifi_switch.py                    # Show current status
    python3 wifi_switch.py wlan0              # Switch to wlan0
    python3 wifi_switch.py wlan1              # Switch to wlan1
    python3 wifi_switch.py status             # Show detailed status
    python3 wifi_switch.py list               # List all WiFi interfaces
    python3 wifi_switch.py toggle             # Toggle between wlan0/wlan1
"""

import sys

# Add required paths
sys.path.append('/root/KTOx/wifi/')

try:
    from ktox_integration import (
        set_ktox_interface,
        switch_wifi_interface,
        get_current_ktox_interface,
        list_wifi_interfaces_with_status,
        get_interface_status,
        get_available_interfaces
    )
    IMPORTS_OK = True
except Exception as e:
    print(f"❌ Import error: {e}")
    IMPORTS_OK = False

def show_usage():
    """Show usage information."""
    print("WiFi Interface Switcher")
    print("="*25)
    print("USAGE:")
    print("  python3 wifi_switch.py                    # Show current interface")
    print("  python3 wifi_switch.py wlan0              # Switch to wlan0")
    print("  python3 wifi_switch.py wlan1              # Switch to wlan1")
    print("  python3 wifi_switch.py status             # Show detailed status")
    print("  python3 wifi_switch.py list               # List WiFi interfaces")
    print("  python3 wifi_switch.py toggle             # Toggle between wlan0/wlan1")
    print("")
    print("EXAMPLES:")
    print("  python3 wifi_switch.py wlan1              # Switch KTOx to wlan1")
    print("  python3 wifi_switch.py toggle             # Switch from current to other")

def cmd_status():
    """Show current interface status."""
    current = get_current_ktox_interface()
    
    print("📡 Current KTOx Interface Status")
    print("="*38)
    print(f"🎯 KTOx using: {current}")
    
    if current != 'unknown':
        status = get_interface_status(current)
        print(f"🔗 Status: {status['status']}")
        print(f"🌐 Connected: {'Yes' if status['connected'] else 'No'}")
        print(f"📍 IP Address: {status['ip'] or 'None'}")
    
    print("")
    list_wifi_interfaces_with_status()

def cmd_list():
    """List all WiFi interfaces."""
    interfaces = list_wifi_interfaces_with_status()
    
    if not interfaces:
        print("❌ No WiFi interfaces found")
        return
    
    print(f"\n📋 Found {len(interfaces)} WiFi interfaces")
    for iface_info in interfaces:
        name = iface_info['name']
        mark = "👉 CURRENT" if iface_info['current'] else ""
        print(f"   {name} {mark}")

def cmd_switch(interface):
    """Switch to specified interface."""
    print(f"🔄 Switching KTOx to {interface}")
    print("="*40)
    
    # Check if interface exists
    available = get_available_interfaces()
    if interface not in available:
        print(f"❌ Interface {interface} not found!")
        print(f"Available interfaces: {', '.join(available)}")
        return False
    
    # Check if it's a WiFi interface
    if not interface.startswith('wlan'):
        print(f"❌ {interface} is not a WiFi interface!")
        print("Use: wlan0, wlan1, wlan2, etc.")
        return False
    
    # Perform the switch
    success = set_ktox_interface(interface)
    
    if success:
        print(f"\n🎉 SUCCESS! KTOx now using {interface}")
        print("🔄 Verifying the change...")
        
        # Verify
        current = get_current_ktox_interface()
        if current == interface:
            print(f"✅ Verified: KTOx is using {interface}")
            print("✅ All nmap scans will now use this interface")
            print("✅ All MITM attacks will now use this interface")
            print("✅ All tools will now use this interface")
            return True
        else:
            print(f"⚠️  Warning: Expected {interface}, but KTOx using {current}")
            return False
    else:
        print(f"\n❌ Failed to switch to {interface}")
        return False

def cmd_toggle():
    """Toggle between wlan0 and wlan1."""
    current = get_current_ktox_interface()
    
    print("🔄 Toggling WiFi Interface")
    print("="*28)
    print(f"Current: {current}")
    
    # Determine target interface
    if current == 'wlan0':
        target = 'wlan1'
    elif current == 'wlan1':
        target = 'wlan0'
    else:
        # Not currently using wlan0 or wlan1, pick the best available
        available = get_available_interfaces()
        wifi_interfaces = [iface for iface in available if iface.startswith('wlan')]
        
        if 'wlan1' in wifi_interfaces:
            target = 'wlan1'
        elif 'wlan0' in wifi_interfaces:
            target = 'wlan0'
        else:
            print("❌ No wlan0 or wlan1 interfaces found!")
            return False
    
    print(f"Target: {target}")
    
    # Check if target is available and connected
    status = get_interface_status(target)
    if not status['connected']:
        print(f"❌ Target interface {target} is not connected!")
        print("Connect to a WiFi network first, then try again.")
        return False
    
    # Perform the switch
    print(f"\n🚀 Switching from {current} to {target}...")
    success = switch_wifi_interface(current, target)
    
    if success:
        print(f"✅ Successfully toggled to {target}")
        return True
    else:
        print(f"❌ Failed to toggle to {target}")
        return False

def main():
    """Main function."""
    if not IMPORTS_OK:
        print("❌ Required modules not available")
        print("Make sure you're running from KTOx directory")
        return 1
    
    if len(sys.argv) < 2:
        # No arguments - show current status
        cmd_status()
        return 0
    
    command = sys.argv[1].lower()
    
    try:
        if command == "status":
            cmd_status()
            
        elif command == "list":
            cmd_list()
            
        elif command == "toggle":
            success = cmd_toggle()
            return 0 if success else 1
            
        elif command.startswith("wlan"):
            # Switch to specific interface
            success = cmd_switch(command)
            return 0 if success else 1
            
        else:
            print(f"❌ Unknown command: {command}")
            show_usage()
            return 1
            
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 
