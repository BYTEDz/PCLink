# src/pclink/core/extension_context.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .extension_base import ExtensionMetadata

log = logging.getLogger(__name__)
_ = gettext.gettext


class PermissionDeniedError(Exception):
    pass


class ExtensionAPI:
    def __init__(self, metadata: ExtensionMetadata, ipc_conn=None):
        self.metadata = metadata
        self.ipc_conn = ipc_conn

    def _check_permission(self, permission: str):
        if permission not in self.metadata.permissions:
            raise PermissionDeniedError(
                _("Extension '{name}' missing permission: {permission}").format(
                    name=self.metadata.name, permission=permission
                )
            )

    def _call_ipc(self, api_name: str, method: str, kwargs: Dict[str, Any]) -> Any:
        """Proxy call to host process over IPC when running in isolated process mode."""
        if not self.ipc_conn:
            return None
        try:
            self.ipc_conn.send(
                {
                    "type": "CONTEXT_CALL",
                    "api": api_name,
                    "method": method,
                    "kwargs": kwargs,
                }
            )
            response = self.ipc_conn.recv()
            if response.get("status") == "error":
                raise RuntimeError(response.get("error", _("IPC Call Failed")))
            return response.get("result")
        except Exception as e:
            log.error(f"IPC context call failed ({api_name}.{method}): {e}")
            return None


class ThemeAPI(ExtensionAPI):
    def get_system_theme(self) -> str:
        """Returns 'dark' or 'light'."""
        self._check_permission("theme.read")

        if self.ipc_conn:
            return self._call_ipc("theme", "get_system_theme", {}) or "dark"

        if platform.system() == "Windows":
            try:
                import winreg

                registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
                key = winreg.OpenKey(
                    registry,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if value == 1 else "dark"
            except Exception as e:
                log.warning(f"Failed to read windows theme: {e}")
                return "dark"
        return "dark"


class DialogAPI(ExtensionAPI):
    def open_file_picker(
        self, title: str = "Select a File", file_types: List[str] = None
    ) -> Optional[str]:
        """
        Opens a native file picker dialog on the server host.
        Returns the selected file path or None if cancelled.
        """
        self._check_permission("ui.picker")

        if self.ipc_conn:
            return self._call_ipc(
                "dialog",
                "open_file_picker",
                {"title": title, "file_types": file_types},
            )

        if file_types is None:
            file_types = ["All Files", "*.*"]

        if platform.system() == "Windows":
            ps_script = f"""
            Add-Type -AssemblyName System.Windows.Forms
            $f = New-Object System.Windows.Forms.OpenFileDialog
            $f.Title = "{title}"
            $f.Filter = "All Files (*.*)|*.*"
            if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
                Write-Host $f.FileName
            }}
            """

            try:
                cmd = [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    ps_script,
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                path = result.stdout.strip()
                return path if path else None
            except Exception as e:
                log.error(f"File picker failed: {e}")
                return None
        return None


class NotificationAPI(ExtensionAPI):
    def show(self, title: str, message: str, type: str = "info") -> bool:
        """Pushes a notification directly into PCLink's Notification Center & Web UI toasts."""
        if self.ipc_conn:
            return bool(
                self._call_ipc(
                    "notification",
                    "show",
                    {"title": title, "message": message, "type": type},
                )
            )

        try:
            from ..api_server.ws_manager import ui_manager

            asyncio.create_task(
                ui_manager.broadcast(
                    {
                        "type": "notification",
                        "data": {"title": title, "message": message, "type": type},
                    }
                )
            )
            return True
        except Exception as e:
            log.error(f"Failed to dispatch extension notification: {e}")
            return False


class ExtensionContext:
    def __init__(self, metadata: ExtensionMetadata, ipc_conn=None):
        from . import constants

        self.metadata = metadata
        self.ipc_conn = ipc_conn
        self.theme = ThemeAPI(metadata, ipc_conn=ipc_conn)
        self.dialog = DialogAPI(metadata, ipc_conn=ipc_conn)
        self.notification = NotificationAPI(metadata, ipc_conn=ipc_conn)
        self._event_listeners: Dict[str, List[Callable]] = {}
        self._background_tasks: List[Dict[str, Any]] = []

        # Isolated extension storage directory
        self._data_path = constants.APP_DATA_PATH / "extension_data" / metadata.name
        self._data_path.mkdir(parents=True, exist_ok=True)

    @property
    def extension_data_path(self) -> Path:
        """Returns the isolated persistent storage directory for this extension."""
        return self._data_path

    def notify(self, title: str, message: str, type: str = "info") -> bool:
        """Convenience method for extension developers to trigger PCLink notifications."""
        return self.notification.show(title, message, type)

    def on(self, event_name: str, handler: Callable):
        """Register an event listener for PCLink system or inter-extension events."""
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        self._event_listeners[event_name].append(handler)

    def publish_event(self, event_name: str, data: Dict[str, Any] = None):
        """Publishes an event to the host event bus to notify other extensions or host systems."""
        if self.ipc_conn:
            try:
                self.ipc_conn.send(
                    {
                        "type": "CONTEXT_CALL",
                        "api": "context",
                        "method": "publish_event",
                        "kwargs": {"event_name": event_name, "data": data or {}},
                    }
                )
            except Exception as e:
                log.error(f"IPC publish event error: {e}")
            return

        from .extension_manager import ExtensionManager

        ExtensionManager().dispatch_event(event_name, data or {})

    def register_task(self, task_name: str, interval_seconds: float, handler: Callable):
        """Registers a background task to be run periodically by the host manager loop."""
        self._background_tasks.append(
            {
                "name": task_name,
                "interval": interval_seconds,
                "handler": handler,
                "last_run": 0.0,
            }
        )
        log.info(
            _("Registered background task '{task}' for extension '{ext}'").format(
                task=task_name, ext=self.metadata.name
            )
        )

    def log_audit(self, action: str, details: Dict[str, Any] = None):
        """Logs a high-privilege extension audit record."""
        audit_log = self._data_path / "audit.log"
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ACTION={action} | DETAILS={details or {}}\n"
        try:
            with open(audit_log, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            log.error(f"Failed to write audit entry for {self.metadata.name}: {e}")
