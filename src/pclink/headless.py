# filename: src/pclink/headless.py
"""
PCLink - Remote PC Control Server - Headless Application
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

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from .core.config import config_manager
from .core.controller import Controller
from .core.setup_guide import should_show_setup_guide, show_setup_guide
from .core.update_checker import UpdateChecker
from .gui.main_window import MainWindow
from .gui.tray_manager import UnifiedTrayManager

log = logging.getLogger(__name__)


class HeadlessApp(QObject):
    """
    Manages the application in headless mode, providing a tray icon for control
    and facilitating the transition to the full GUI.
    """
    def __init__(self):
        super().__init__()
        self.server_status = "stopped"
        self.main_window = None  # Lazily created
        
        self.controller = Controller(self)
        self.update_checker = UpdateChecker()
        self.tray_manager = UnifiedTrayManager(self)
        self.tray_manager.setup_menu(mode="headless")
        
        self._server_startup_attempts = 0
        # Check every 1.5 seconds, so 10 attempts give 15 seconds total for startup
        self._MAX_SERVER_STARTUP_ATTEMPTS = 10 
        
        self.start_server()
        self.tray_manager.show()

    def start_server(self):
        """Starts the API server and monitors its status."""
        log.info("Headless mode: Attempting to start server.")
        self.server_status = "starting"
        self.tray_manager.update_status(self.server_status)
        self._server_startup_attempts = 0 # Reset attempts
        
        self.controller.start_server()
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_server_status)
        self.check_timer.start(1500) # Check every 1.5 seconds

    def check_server_status(self):
        """Periodically checks if the server has started successfully."""
        self._server_startup_attempts += 1
        
        if self.controller.is_server_running():
            self.on_server_started()
            self.check_timer.stop()
        elif not self.controller.is_server_starting() or self._server_startup_attempts >= self._MAX_SERVER_STARTUP_ATTEMPTS:
            # Server thread is dead OR we've hit max attempts, and server isn't running
            log.warning(f"Server failed to start or timed out after {self._server_startup_attempts} attempts.")
            self.on_server_failed()
            self.check_timer.stop()

    def on_server_started(self):
        """Handles successful server startup."""
        log.info("Server started successfully in headless mode.")
        self.server_status = "running"
        self.tray_manager.update_status(self.server_status, self.controller.get_port())
        
        if config_manager.get("show_startup_notification", True):
            self.tray_manager.show_message("PCLink Server", "Server is running.")

    def on_server_failed(self):
        """Handles server startup failure."""
        log.error("Server failed to start in headless mode.")
        self.server_status = "error"
        self.tray_manager.update_status(self.server_status)
        self.tray_manager.show_message("PCLink Server Error", "Could not start server.", icon=self.tray_manager.tray_icon.Critical)

    def restart_server(self):
        """Restarts the server."""
        log.info("Restarting server from tray menu.")
        self.controller.stop_server()
        self.server_status = "stopped"
        self.tray_manager.update_status(self.server_status)
        QTimer.singleShot(1000, self.start_server)

    def show_main_gui(self):
        """Creates and shows the main GUI, transitioning from headless mode."""
        if self.main_window and self.main_window.isVisible():
            self.main_window.activateWindow()
            return
        
        log.info("Transitioning from headless to GUI mode.")
        if not self.main_window:
            self.main_window = MainWindow(from_headless=True)
            self.main_window.controller = self.controller
            self.controller.window = self.main_window
            self.main_window.is_server_running = self.controller.is_server_running()
            self.main_window.controller.update_ui_for_server_state()
            # The MainWindow creates its own tray manager, so we don't need to assign it here.

        self.tray_manager.hide()
        self.main_window.tray_manager.show()
        
        if should_show_setup_guide():
            QTimer.singleShot(100, self._show_setup_guide_and_window)
        else:
            self.main_window.show()
            self.main_window.activateWindow()

    def _show_setup_guide_and_window(self):
        """Shows the first-time setup guide, then the main window."""
        setup_completed = show_setup_guide(self.main_window)
        self.main_window.show()
        self.main_window.activateWindow()
        if setup_completed:
            log.info("Setup guide completed. Restarting server with new settings.")
            self.main_window.restart_server()

    def check_for_updates(self):
        """Checks for updates and shows a tray notification with the result."""
        def on_result(update_info):
            if update_info:
                self.tray_manager.show_message(
                    "PCLink Update Available",
                    f"Version {update_info['version']} is available for download."
                )
            else:
                self.tray_manager.show_message(
                    "PCLink Updates",
                    "You are running the latest version."
                )
        self.update_checker.check_for_updates_async(on_result)

    def quit_application(self):
        """Shuts down the application cleanly."""
        log.info("Shutting down PCLink from headless mode.")
        self.controller.stop_server()
        self.tray_manager.hide()
        QApplication.instance().quit()