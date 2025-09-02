# filename: src/pclink/gui/tray_manager.py
"""
PCLink - Remote PC Control Server - Tray Manager
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

import logging

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core import constants
from ..core.version import __version__
from .theme import create_app_icon

log = logging.getLogger(__name__)


class UnifiedTrayManager(QObject):
    """
    Unified tray icon manager for both headless and GUI modes.
    Manages the system tray icon, its context menu, and interactions.
    """
    def __init__(self, app_instance):
        super().__init__(app_instance)
        self.app_instance = app_instance
        self.tray_icon = QSystemTrayIcon(create_app_icon(), self)
        self.tray_icon.setToolTip(f"PCLink v{__version__}")

        self.menu = QMenu()
        self.actions = {}

        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

    def setup_menu(self, mode: str):
        """
        Configures the tray menu based on the application mode ('headless' or 'gui').
        """
        self.menu.clear()
        self.actions.clear()

        if mode == "headless":
            status_text = "Status: Starting..."
            self.actions['status'] = self.menu.addAction(status_text)
            self.actions['status'].setEnabled(False)
            self.menu.addSeparator()
            self.actions['show_gui'] = self.menu.addAction("Show PCLink GUI", self.app_instance.show_main_gui)
        else:  # gui mode
            self.actions['toggle_window'] = self.menu.addAction("Hide PCLink", self.app_instance.toggle_window_visibility)

        self.actions['restart'] = self.menu.addAction("Restart Server", self.app_instance.restart_server)
        self.menu.addSeparator()
        self.actions['open_logs'] = self.menu.addAction("Open Log File", self._open_log_file)
        self.actions['open_config'] = self.menu.addAction("Open Config Folder", self._open_config_folder)
        self.actions['check_updates'] = self.menu.addAction("Check for Updates", self.app_instance.check_for_updates)
        self.menu.addSeparator()
        self.actions['exit'] = self.menu.addAction("Exit PCLink", self.app_instance.quit_application)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Handles tray icon activation (e.g., left-click)."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if hasattr(self.app_instance, 'toggle_window_visibility'):
                self.app_instance.toggle_window_visibility()
            elif hasattr(self.app_instance, 'show_main_gui'):
                self.app_instance.show_main_gui()

    def _open_log_file(self):
        """Opens the main log file."""
        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file)))
        else:
            self.show_message("Log file not found", f"File not found: {log_file}", self.tray_icon.Warning)
            log.warning(f"Log file not found at: {log_file}")

    def _open_config_folder(self):
        """Opens the application data folder."""
        config_folder = constants.APP_DATA_PATH
        if config_folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_folder)))
        else:
            self.show_message("Config folder not found", f"Folder not found: {config_folder}", self.tray_icon.Warning)
            log.warning(f"Config folder not found at: {config_folder}")
    
    def update_status(self, status: str, port: int = 0):
        """Updates the server status in the tray menu and tooltip."""
        if 'status' in self.actions:
            self.actions['status'].setText(f"Status: {status.capitalize()}")
        
        status_map = {
            "starting": "PCLink - Starting...",
            "running": f"PCLink - Running on port {port}",
            "error": "PCLink - Error", 
            "stopped": "PCLink - Stopped",
        }
        tooltip = status_map.get(status, f"PCLink v{__version__}")
        self.tray_icon.setToolTip(tooltip)
    
    def update_toggle_action_text(self, is_visible: bool):
        """Updates the show/hide action text based on window visibility."""
        if 'toggle_window' in self.actions:
            text = "Hide PCLink" if is_visible else "Show PCLink"
            self.actions['toggle_window'].setText(text)

    def show_message(self, title: str, message: str, icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.Information, msecs: int = 3000):
        """Displays a tray notification."""
        if self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, icon, msecs)

    def show(self):
        self.tray_icon.show()

    def hide(self):
        self.tray_icon.hide()