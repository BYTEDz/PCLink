# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz


import logging
import platform
import subprocess
import json
from pathlib import Path
from typing import Optional, List

from .extension_base import ExtensionMetadata

log = logging.getLogger(__name__)

class PermissionDeniedError(Exception):
    pass

class ExtensionAPI:
    def __init__(self, metadata: ExtensionMetadata):
        self.metadata = metadata

    def _check_permission(self, permission: str):
        if permission not in self.metadata.permissions:
            raise PermissionDeniedError(f"Extension '{self.metadata.name}' missing permission: {permission}")

class ThemeAPI(ExtensionAPI):
    def get_system_theme(self) -> str:
        """Returns 'dark' or 'light'."""
        # Permission: theme.read (Tier 1 - Safe)
        self._check_permission("theme.read")
        
        if platform.system() == "Windows":
            try:
                import winreg
                registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
                key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if value == 1 else "dark"
            except Exception as e:
                log.warning(f"Failed to read windows theme: {e}")
                return "dark" # Default fallback
        return "dark"

class DialogAPI(ExtensionAPI):
    def open_file_picker(self, title: str = "Select a File", file_types: List[str] = None) -> Optional[str]:
        """
        Opens a native file picker dialog on the server.
        Returns the selected file path or None if cancelled.
        """
        # Permission: ui.picker (Tier 1 - Safe, requires user interaction)
        self._check_permission("ui.picker")
        
        if file_types is None:
            file_types = ["All Files", "*.*"]

        if platform.system() == "Windows":
            # Use PowerShell for a native-looking dialog without heavy dependencies like tkinter
            filter_str = "|".join(file_types)
            ps_script = f"""
            Add-Type -AssemblyName System.Windows.Forms
            $f = New-Object System.Windows.Forms.OpenFileDialog
            $f.Title = "{title}"
            $f.Filter = "All Files (*.*)|*.*" 
            if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
                Write-Host $f.FileName
            }}
            """
            # Note: Filter implementation in PS simple script above is basic.
            
            try:
                cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]
                # UI rendering requirement: Execution must occur within an active user session context.
                # Potential failure if executing as a background service without GUI access.
                # Assumption: Execution occurs within a standard user session.
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                path = result.stdout.strip()
                return path if path else None
            except Exception as e:
                log.error(f"File picker failed: {e}")
                return None
        return None

class ExtensionContext:
    def __init__(self, metadata: ExtensionMetadata):
        self.metadata = metadata
        self.theme = ThemeAPI(metadata)
        self.dialog = DialogAPI(metadata)
        # self.system = SystemAPI(metadata) # Future: Tier 2 dangerous API
