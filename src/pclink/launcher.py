 # SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

# src/pclink/launcher.py
#!/usr/bin/env python3
"""
PCLink Standalone Launcher
Handles platform-specific bootstrapping for frozen applications.
"""

import sys
import os
import logging

# Hide console window IMMEDIATELY on Windows frozen builds
# This must happen before ANY other imports or operations that might output to console
if sys.platform == "win32" and getattr(sys, "frozen", False):
    try:
        from pclink.core.windows_console import hide_console_window, setup_console_redirection
        hide_console_window()
        setup_console_redirection()
    except ImportError:
        # Fallback: try to hide console directly if import fails
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            console_window = kernel32.GetConsoleWindow()
            if console_window != 0:
                user32 = ctypes.windll.user32
                user32.ShowWindow(console_window, 0)  # SW_HIDE = 0
        except Exception:
            pass

log = logging.getLogger(__name__)

def set_dpi_awareness():
    """Makes the application DPI-aware on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            log.debug("Launcher: Set DPI awareness for Windows 8.1+")
        except (ImportError, AttributeError, OSError):
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
                log.debug("Launcher: Set DPI awareness for older Windows")
            except (ImportError, AttributeError, OSError):
                log.debug("Launcher: Could not set DPI awareness.")

def setup_network_permissions():
    """Setup network permissions for Windows firewall."""
    if sys.platform == "win32" and getattr(sys, 'frozen', False):
        try:
            import subprocess
            
            exe_path = sys.executable
            app_name = "PCLink Server"
            
            check_cmd = [
                "netsh", "advfirewall", "firewall", "show", "rule", 
                f"name={app_name}", "dir=in"
            ]
            
            result = subprocess.run(check_cmd, capture_output=True, text=True, 
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            
            if "No rules match" in result.stdout:
                log.info("Launcher: Adding Windows Firewall rule...")
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
                log.info("Launcher: Firewall rule added successfully")
            else:
                log.debug("Launcher: Firewall rule already exists")
                
        except Exception as e:
            log.warning(f"Launcher: Could not setup firewall rule: {e}")
            log.warning("Launcher: You may need to manually allow PCLink through Windows Firewall")

def main():
    set_dpi_awareness()
    setup_network_permissions()

    try:
        # Handle PyInstaller frozen state
        if getattr(sys, 'frozen', False):
            application_path = sys._MEIPASS
            if application_path not in sys.path:
                sys.path.insert(0, application_path)
        else:
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

        try:
            from pclink.main import main as pclink_main
            return pclink_main()
        except ImportError as e:
            log.error(f"Failed to import pclink.main: {e}")
            log.error(f"sys.path: {sys.path}")
            log.error(f"Current working directory: {os.getcwd()}")
            if hasattr(sys, '_MEIPASS'):
                log.error(f"PyInstaller temp directory: {sys._MEIPASS}")
                log.error(f"Contents: {os.listdir(sys._MEIPASS) if os.path.exists(sys._MEIPASS) else 'Not found'}")
            return 1
            
    except Exception as e:
        log.error(f"Launcher error: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())