#!/usr/bin/env python3
"""
Diagnostic script for PCLink Windows 11 startup and QR code issues
"""

import json
import sys
import winreg
import requests
from pathlib import Path
import subprocess
import logging

def check_windows_startup():
    """Check Windows startup configuration."""
    print("=== Windows Startup Diagnosis ===")
    
    try:
        key = winreg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        with winreg.OpenKey(key, key_path, 0, winreg.KEY_READ) as reg_key:
            try:
                value, reg_type = winreg.QueryValueEx(reg_key, "PCLink")
                print(f"✅ PCLink found in startup registry:")
                print(f"   Command: {value}")
                print(f"   Type: {reg_type}")
                
                # Check if the executable exists
                if '"' in value:
                    exe_path = value.split('"')[1]
                    if Path(exe_path).exists():
                        print(f"✅ Executable exists: {exe_path}")
                    else:
                        print(f"❌ Executable NOT found: {exe_path}")
                        return False
                
                return True
                
            except FileNotFoundError:
                print("❌ PCLink NOT found in startup registry")
                return False
                
    except Exception as e:
        print(f"❌ Error checking startup: {e}")
        return False

def check_qr_payload():
    """Check QR code payload generation."""
    print("\n=== QR Code Payload Diagnosis ===")
    
    try:
        # Try to get QR payload from running server
        url = "https://127.0.0.1:8000/qr-payload"
        
        # Load API key
        from src.pclink.core import constants
        from src.pclink.core.utils import load_config_value
        
        api_key = load_config_value(constants.API_KEY_FILE, default="")
        if not api_key:
            print("❌ No API key found")
            return False
            
        headers = {"x-api-key": api_key}
        
        print(f"🔍 Testing QR payload endpoint: {url}")
        print(f"🔑 Using API key: {api_key[:8]}...")
        
        response = requests.get(url, headers=headers, verify=False, timeout=5)
        response.raise_for_status()
        
        payload = response.json()
        print("✅ QR payload retrieved successfully:")
        print(f"   Protocol: {payload.get('protocol')}")
        print(f"   IP: {payload.get('ip')}")
        print(f"   Port: {payload.get('port')}")
        print(f"   API Key: {payload.get('apiKey', '')[:8]}...")
        print(f"   Cert Fingerprint: {payload.get('certFingerprint', 'None')}")
        
        # Test QR code generation
        payload_str = json.dumps(payload)
        print(f"📱 QR code data length: {len(payload_str)} characters")
        print(f"📱 QR code data preview: {payload_str[:100]}...")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to PCLink server (not running?)")
        return False
    except requests.exceptions.Timeout:
        print("❌ Timeout connecting to PCLink server")
        return False
    except Exception as e:
        print(f"❌ Error checking QR payload: {e}")
        return False

def check_windows_version():
    """Check Windows version for compatibility."""
    print("\n=== Windows Version Check ===")
    
    try:
        result = subprocess.run(['ver'], shell=True, capture_output=True, text=True)
        version_info = result.stdout.strip()
        print(f"Windows Version: {version_info}")
        
        # Check if Windows 11
        if "Windows" in version_info:
            if "10.0.22" in version_info or "11" in version_info:
                print("✅ Windows 11 detected")
                print("⚠️  Windows 11 may have stricter startup policies")
                return "win11"
            else:
                print("✅ Windows 10 detected")
                return "win10"
        
    except Exception as e:
        print(f"❌ Error checking Windows version: {e}")
    
    return "unknown"

def suggest_windows11_fixes():
    """Suggest fixes for Windows 11 startup issues."""
    print("\n=== Windows 11 Startup Fixes ===")
    
    print("🔧 Potential solutions for Windows 11 startup issues:")
    print("1. Use Task Scheduler instead of registry (more reliable)")
    print("2. Add startup delay to avoid timing issues")
    print("3. Use full path with proper escaping")
    print("4. Check Windows 11 startup app permissions")
    print("5. Use Windows Startup folder as alternative")
    
    startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    print(f"\n📁 Windows Startup folder: {startup_folder}")
    
    if startup_folder.exists():
        print("✅ Startup folder exists")
        pclink_shortcut = startup_folder / "PCLink.lnk"
        if pclink_shortcut.exists():
            print("✅ PCLink shortcut found in startup folder")
        else:
            print("❌ No PCLink shortcut in startup folder")
    else:
        print("❌ Startup folder not found")

def main():
    """Main diagnostic function."""
    print("PCLink Diagnostic Tool")
    print("=" * 50)
    
    # Check Windows version
    win_version = check_windows_version()
    
    # Check startup configuration
    startup_ok = check_windows_startup()
    
    # Check QR code functionality
    qr_ok = check_qr_payload()
    
    # Provide recommendations
    print("\n=== SUMMARY ===")
    print(f"Windows Startup: {'✅ OK' if startup_ok else '❌ ISSUE'}")
    print(f"QR Code Payload: {'✅ OK' if qr_ok else '❌ ISSUE'}")
    
    if win_version == "win11" and not startup_ok:
        suggest_windows11_fixes()
    
    if not qr_ok:
        print("\n🔧 QR Code fixes:")
        print("1. Make sure PCLink server is running")
        print("2. Check API key configuration")
        print("3. Verify HTTPS/HTTP settings")
        print("4. Check firewall/antivirus blocking")

if __name__ == "__main__":
    main()