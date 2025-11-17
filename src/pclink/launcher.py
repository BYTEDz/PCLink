# src/pclink/launcher.py
#!/usr/bin/env python3
"""
PCLink Standalone Launcher

This script is used to launch PCLink when packaged as a standalone application.
It handles the necessary imports and starts the application.
"""

import sys
import os

def set_dpi_awareness():
    """Makes the application DPI-aware on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            # Try to set DPI awareness for Windows 8.1+
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            print("Launcher: Set DPI awareness for Windows 8.1+")
        except (ImportError, AttributeError, OSError):
            try:
                # Fallback for older Windows versions
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
                print("Launcher: Set DPI awareness for older Windows")
            except (ImportError, AttributeError, OSError):
                print("Launcher: Could not set DPI awareness.")

def setup_network_permissions():
    """Setup network permissions for Windows firewall."""
    if sys.platform == "win32" and getattr(sys, 'frozen', False):
        try:
            import subprocess
            import os
            
            # Get the executable path
            exe_path = sys.executable
            app_name = "PCLink Server"
            
            # Check if firewall rule exists
            check_cmd = [
                "netsh", "advfirewall", "firewall", "show", "rule", 
                f"name={app_name}", "dir=in"
            ]
            
            result = subprocess.run(check_cmd, capture_output=True, text=True, 
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            
            if "No rules match" in result.stdout:
                print("Launcher: Adding Windows Firewall rule...")
                # Add firewall rule for inbound connections
                add_cmd = [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={app_name}",
                    "dir=in",
                    "action=allow",
                    f"program={exe_path}",
                    "enable=yes"
                ]
                
                subprocess.run(add_cmd, capture_output=True, 
                             creationflags=subprocess.CREATE_NO_WINDOW)
                print("Launcher: Firewall rule added successfully")
            else:
                print("Launcher: Firewall rule already exists")
                
        except Exception as e:
            print(f"Launcher: Could not setup firewall rule: {e}")
            print("Launcher: You may need to manually allow PCLink through Windows Firewall")

def main():
    """Main launcher function."""
    # Set DPI awareness at the very beginning of the application start.
    set_dpi_awareness()
    
    # Setup network permissions for frozen builds
    setup_network_permissions()

    try:
        # For PyInstaller, we need to handle the frozen state
        if getattr(sys, 'frozen', False):
            # Running in a PyInstaller bundle
            application_path = sys._MEIPASS
            if application_path not in sys.path:
                sys.path.insert(0, application_path)
        else:
            # Running in normal Python environment
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

        # Import and run the main function
        try:
            from pclink.main import main as pclink_main
            return pclink_main()
        except ImportError as e:
            print(f"Failed to import pclink.main: {e}")
            print(f"sys.path: {sys.path}")
            print(f"Current working directory: {os.getcwd()}")
            if hasattr(sys, '_MEIPASS'):
                print(f"PyInstaller temp directory: {sys._MEIPASS}")
                print(f"Contents: {os.listdir(sys._MEIPASS) if os.path.exists(sys._MEIPASS) else 'Not found'}")
            return 1
            
    except Exception as e:
        print(f"Launcher error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())