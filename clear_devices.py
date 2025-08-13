#!/usr/bin/env python3
"""
PCLink Device Management Utility
Helps clear registered devices when client app data is reset
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# Add src to path to import PCLink modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pclink.core import constants
from pclink.core.device_manager import device_manager

def list_devices():
    """List all registered devices"""
    devices = device_manager.get_all_devices()
    
    if not devices:
        print("No devices registered.")
        return
    
    print(f"\nRegistered devices ({len(devices)}):")
    print("-" * 80)
    print(f"{'Name':<20} {'ID':<12} {'Platform':<10} {'IP':<15} {'Status':<10} {'Last Seen'}")
    print("-" * 80)
    
    for device in devices:
        status = "Approved" if device.is_approved else "Pending"
        last_seen = device.last_seen.strftime("%Y-%m-%d %H:%M")
        device_id_short = device.device_id[:8] + "..."
        
        print(f"{device.device_name:<20} {device_id_short:<12} {device.platform:<10} "
              f"{device.current_ip:<15} {status:<10} {last_seen}")

def clear_all_devices():
    """Clear all registered devices"""
    devices = device_manager.get_all_devices()
    
    if not devices:
        print("No devices to clear.")
        return
    
    print(f"\nFound {len(devices)} registered devices.")
    confirm = input("Are you sure you want to clear ALL devices? (yes/no): ").lower().strip()
    
    if confirm != "yes":
        print("Operation cancelled.")
        return
    
    cleared = 0
    for device in devices:
        if device_manager.revoke_device(device.device_id):
            cleared += 1
            print(f"✓ Cleared: {device.device_name} ({device.device_id[:8]}...)")
        else:
            print(f"✗ Failed to clear: {device.device_name}")
    
    print(f"\nCleared {cleared} devices successfully.")

def clear_device_by_name(name):
    """Clear a specific device by name"""
    devices = device_manager.get_all_devices()
    matching_devices = [d for d in devices if name.lower() in d.device_name.lower()]
    
    if not matching_devices:
        print(f"No devices found matching '{name}'")
        return
    
    if len(matching_devices) > 1:
        print(f"Multiple devices found matching '{name}':")
        for i, device in enumerate(matching_devices, 1):
            print(f"{i}. {device.device_name} ({device.device_id[:8]}...)")
        
        try:
            choice = int(input("Select device number to clear (0 to cancel): "))
            if choice == 0:
                print("Operation cancelled.")
                return
            if 1 <= choice <= len(matching_devices):
                device = matching_devices[choice - 1]
            else:
                print("Invalid selection.")
                return
        except ValueError:
            print("Invalid input.")
            return
    else:
        device = matching_devices[0]
    
    confirm = input(f"Clear device '{device.device_name}' ({device.device_id[:8]}...)? (yes/no): ").lower().strip()
    
    if confirm != "yes":
        print("Operation cancelled.")
        return
    
    if device_manager.revoke_device(device.device_id):
        print(f"✓ Cleared device: {device.device_name}")
    else:
        print(f"✗ Failed to clear device: {device.device_name}")

def main():
    print("PCLink Device Management Utility")
    print("=" * 40)
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python clear_devices.py list                    - List all devices")
        print("  python clear_devices.py clear-all               - Clear all devices")
        print("  python clear_devices.py clear-name <name>       - Clear device by name")
        print("\nExample:")
        print("  python clear_devices.py clear-name 'iPhone'")
        return
    
    command = sys.argv[1].lower()
    
    if command == "list":
        list_devices()
    elif command == "clear-all":
        clear_all_devices()
    elif command == "clear-name" and len(sys.argv) > 2:
        device_name = sys.argv[2]
        clear_device_by_name(device_name)
    else:
        print("Invalid command. Use 'list', 'clear-all', or 'clear-name <name>'")

if __name__ == "__main__":
    main()