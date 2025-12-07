# src/pclink/core/startup.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sys
import os
import logging
import platform
from pathlib import Path

log = logging.getLogger(__name__)

class StartupManager:
    def __init__(self):
        self.system = platform.system()
        self.app_name = "PCLink"
        
        # Determine the execution command
        if getattr(sys, 'frozen', False):
            # Running as compiled exe
            self.executable = sys.executable
            self.args = ""
        else:
            # Running from source
            self.executable = sys.executable
            self.args = "-m pclink" 

    def is_enabled(self) -> bool:
        if self.system == "Windows":
            return self._is_enabled_windows()
        elif self.system == "Linux":
            return self._is_enabled_linux()
        return False

    def enable(self) -> bool:
        log.info(f"Enabling auto-start for {self.system}")
        try:
            if self.system == "Windows":
                return self._enable_windows()
            elif self.system == "Linux":
                return self._enable_linux()
        except Exception as e:
            log.error(f"Enable auto-start failed: {e}")
            return False
        return False

    def disable(self) -> bool:
        log.info(f"Disabling auto-start for {self.system}")
        try:
            if self.system == "Windows":
                return self._disable_windows()
            elif self.system == "Linux":
                return self._disable_linux()
        except Exception as e:
            log.error(f"Disable auto-start failed: {e}")
            return False
        return False

    # --- Windows Implementation (Registry) ---
    def _get_windows_key(self):
        import winreg
        return winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_ALL_ACCESS
        )

    def _is_enabled_windows(self) -> bool:
        try:
            import winreg
            key = self._get_windows_key()
            winreg.QueryValueEx(key, self.app_name)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def _enable_windows(self) -> bool:
        try:
            import winreg
            key = self._get_windows_key()
            if self.args:
                cmd = f'"{self.executable}" {self.args}'
            else:
                cmd = f'"{self.executable}"'
            winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            return True
        except Exception as e:
            log.error(f"Failed to enable Windows startup: {e}")
            return False

    def _disable_windows(self) -> bool:
        try:
            import winreg
            key = self._get_windows_key()
            try:
                winreg.DeleteValue(key, self.app_name)
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
            return True
        except Exception as e:
            log.error(f"Failed to disable Windows startup: {e}")
            return False

    # --- Linux Implementation (XDG Autostart .desktop file) ---
    # This is much safer than systemd for GUI/Tray apps as it doesn't 
    # involve reloading system daemons that might kill the process.

    def _get_linux_autostart_path(self) -> Path:
        return Path.home() / ".config" / "autostart" / "pclink.desktop"

    def _is_enabled_linux(self) -> bool:
        # Also clean up legacy systemd service if it exists to avoid conflicts
        self._cleanup_legacy_systemd()
        return self._get_linux_autostart_path().exists()

    def _enable_linux(self) -> bool:
        try:
            desktop_file = self._get_linux_autostart_path()
            desktop_file.parent.mkdir(parents=True, exist_ok=True)

            if self.args:
                # Running from source
                exec_cmd = f"{self.executable} {self.args}"
            else:
                # Running binary
                exec_cmd = self.executable

            # Standard .desktop entry format
            content = f"""[Desktop Entry]
Type=Application
Name=PCLink
Comment=PCLink Server
Exec={exec_cmd}
Icon=utilities-terminal
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
"""
            desktop_file.write_text(content)
            # Ensure permissions are correct (rw-r--r--)
            os.chmod(desktop_file, 0o644)
            
            # Cleanup legacy systemd to prevent double-start
            self._cleanup_legacy_systemd()
            
            log.info(f"Created XDG autostart file: {desktop_file}")
            return True
        except Exception as e:
            log.error(f"Failed to enable Linux autostart: {e}")
            return False

    def _disable_linux(self) -> bool:
        try:
            desktop_file = self._get_linux_autostart_path()
            if desktop_file.exists():
                desktop_file.unlink()
                log.info(f"Removed XDG autostart file: {desktop_file}")
            
            # Cleanup legacy systemd
            self._cleanup_legacy_systemd()
            return True
        except Exception as e:
            log.error(f"Failed to disable Linux autostart: {e}")
            return False

    def _cleanup_legacy_systemd(self):
        """Helper to remove the old systemd service if it exists to prevent conflicts."""
        try:
            # We don't use 'systemctl' commands here to avoid touching the running process.
            # We just delete the file so it won't start on NEXT boot.
            systemd_file = Path.home() / ".config" / "systemd" / "user" / "pclink.service"
            symlink = Path.home() / ".config" / "systemd" / "user" / "default.target.wants" / "pclink.service"
            
            if symlink.exists():
                symlink.unlink()
                log.info("Removed legacy systemd symlink")
            
            if systemd_file.exists():
                systemd_file.unlink()
                log.info("Removed legacy systemd service file")
                
        except Exception as e:
            log.debug(f"Legacy systemd cleanup skipped: {e}")