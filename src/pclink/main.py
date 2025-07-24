#!/usr/bin/env python3
"""
PCLink - Remote PC Control Server
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

import asyncio
import json
import logging
import multiprocessing
import subprocess
import sys
import time
import uuid
from pathlib import Path

import qrcode
import requests
from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QColor, QIcon,
                           QPainter, QPixmap)
from PySide6.QtWidgets import (QApplication, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QSystemTrayIcon)

from .core import constants
from .core.controller import Controller
from .core.state import connected_devices
from .core.utils import (generate_self_signed_cert, get_startup_manager,
                         is_admin, load_config_value, resource_path,
                         save_config_value)
from .core.update_checker import UpdateChecker
from .core.validators import ValidationError, validate_api_key
from .core.version import __app_name__, __version__, version_info
from .gui.layout import retranslateUi, setupUi
from .gui.localizations import LANGUAGES
from .gui.theme import get_stylesheet
from .gui.update_dialog import UpdateDialog
from .gui.version_dialog import VersionDialog

log = logging.getLogger(__name__)


class UpdateSignalEmitter(QObject):
    """Signal emitter for update notifications to handle thread-safe GUI updates."""
    update_available = Signal(dict)  # Emits update_info dict
    no_update_available = Signal()  # Emits when no updates found
    
    
# Global instance for update signals
update_signal_emitter = UpdateSignalEmitter()


def _create_app_icon() -> QIcon:
    """Loads the application icon from PNG only."""
    icon_path = resource_path("assets/icon.png")
    
    log.debug(f"Attempting to load icon from: {icon_path}")

    if icon_path.exists():
        try:
            icon = QIcon(str(icon_path))

            if not icon.isNull() and icon.availableSizes():
                log.info(f"Successfully loaded app icon from: {icon_path}")
                return icon
            else:
                log.warning(f"Icon file exists but failed to load properly: {icon_path}")
                log.debug(f"Icon null: {icon.isNull()}, Available sizes: {icon.availableSizes()}")
        except Exception as e:
            log.warning(f"Error loading icon from {icon_path}: {e}")
    else:
        log.warning(f"Icon file does not exist at: {icon_path}")

    log.warning("No valid icon file found. Creating a fallback icon.")
    return _create_fallback_icon()



def _create_fallback_icon() -> QIcon:
    """Creates a visually appealing fallback icon that matches the app's branding."""
    icon = QIcon()
    for size in [16, 32, 48, 64, 128, 256]:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw purple background (matches brand color #3c096c)
        painter.setBrush(QColor(60, 9, 108))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, size, size)

        # Draw simplified "PC" shape in light gray (#e3e3e3)
        painter.setBrush(QColor(227, 227, 227))

        # Scale elements based on icon size
        margin = size // 8
        monitor_width = size - 2 * margin
        monitor_height = int(monitor_width * 0.6)
        
        # Monitor screen
        painter.drawRect(margin, margin, monitor_width, monitor_height)
        
        # Monitor base
        base_width = monitor_width // 3
        base_height = size // 16
        base_x = margin + (monitor_width - base_width) // 2
        base_y = margin + monitor_height + base_height // 2
        if base_y + base_height < size:
            painter.drawRect(base_x, base_y, base_width, base_height)
        
        painter.end()
        icon.addPixmap(pixmap)
    
    return icon


class HeadlessApp(QObject):
    """Manages the application in headless mode (e.g., on system startup)."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.controller = None
        self.tray_icon = None
        self.server_status = "starting"

        class DummyWindow:
            pass
        self.dummy_window = DummyWindow()
        
        # Initialize update checker for headless mode
        self.update_checker = UpdateChecker()

        self.load_config_and_settings()
        generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)

        self.controller = Controller(self.dummy_window)
        self.setup_tray_icon()
        self.start_server()

    def load_config_and_settings(self):
        try:
            raw_key = load_config_value(constants.API_KEY_FILE, default=str(uuid.uuid4()))
            self.dummy_window.api_key = validate_api_key(raw_key)
            if self.dummy_window.api_key != raw_key:
                save_config_value(constants.API_KEY_FILE, self.dummy_window.api_key)
        except ValidationError:
            log.warning("Invalid API key found. Generating a new one.")
            self.dummy_window.api_key = str(uuid.uuid4())
            save_config_value(constants.API_KEY_FILE, self.dummy_window.api_key)

        self.dummy_window.api_port = int(load_config_value(constants.PORT_FILE, str(constants.DEFAULT_PORT)))
        settings = QSettings(constants.APP_NAME, "AppGUI")
        self.dummy_window.use_https = settings.value("use_https", True, type=bool)
        self.dummy_window.allow_insecure_shell = settings.value("allow_insecure_shell", False, type=bool)
        self.show_startup_notification = settings.value("show_startup_notification", True, type=bool)
        self.dummy_window.is_server_running = False
        self.dummy_window.server_check_timer = None
        
        class MockCombo:
            def currentText(self): return "127.0.0.1"
        self.dummy_window.ip_address_combo = MockCombo()

    def setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(_create_app_icon(), self)
        menu = QMenu()
        self.status_action = menu.addAction("Status: Starting...")
        self.status_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Show PCLink GUI", self.show_main_gui)
        self.restart_action = menu.addAction("Restart Server", self.restart_server)
        menu.addSeparator()
        menu.addAction("Check for Updates", self.check_for_updates_headless)
        menu.addSeparator()
        menu.addAction("Exit PCLink", self.quit_application)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()
        self.update_tray_status()

    def update_tray_status(self):
        status_map = {
            "starting": "PCLink Server - Starting...",
            "running": f"PCLink Server - Running on port {self.dummy_window.api_port}",
            "error": "PCLink Server - Error", "stopped": "PCLink Server - Stopped",
        }
        tooltip = status_map.get(self.server_status, "PCLink Server")
        self.tray_icon.setToolTip(tooltip)
        self.status_action.setText(f"Status: {self.server_status.capitalize()}")
        self.restart_action.setEnabled(self.server_status in ["running", "error", "stopped"])

    def start_server(self):
        log.info("Headless mode: Attempting to start server.")
        self.server_status = "starting"
        self.update_tray_status()
        self.controller.start_server()
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_server_status)
        self.check_timer.start(1500)

    def check_server_status(self):
        if self.controller.uvicorn_server and self.controller.uvicorn_server.started:
            self.on_server_started()
            self.check_timer.stop()
        elif not self.controller.server_thread.is_alive():
            self.on_server_failed()
            self.check_timer.stop()

    def on_server_started(self):
        log.info("Server started successfully in headless mode.")
        self.server_status = "running"
        self.dummy_window.is_server_running = True
        self.update_tray_status()
        if self.show_startup_notification:
            self.tray_icon.showMessage("PCLink Server", "Server is running.", QSystemTrayIcon.Icon.Information, 3000)

    def on_server_failed(self):
        log.error("Server failed to start in headless mode.")
        self.server_status = "error"
        self.update_tray_status()
        self.tray_icon.showMessage("PCLink Server Error", "Could not start server.", QSystemTrayIcon.Icon.Critical, 5000)

    def restart_server(self):
        log.info("Restarting server from tray menu.")
        self.controller.stop_server()
        self.server_status = "stopped"
        self.update_tray_status()
        QTimer.singleShot(1000, self.start_server)

    def show_main_gui(self):
        log.info("Transitioning from headless to GUI mode.")
        self.controller.stop_server()
        self.tray_icon.hide()
        QApplication.quit()
        subprocess.Popen([sys.executable] + [arg for arg in sys.argv if arg != "--startup"])

    def check_for_updates_headless(self):
        """Check for updates in headless mode."""
        def handle_result(update_info):
            # Use QTimer.singleShot to ensure this runs in the main thread
            def show_notification():
                if update_info:
                    self.tray_icon.showMessage(
                        "PCLink Update Available",
                        f"Version {update_info['version']} is available for download.",
                        QSystemTrayIcon.Icon.Information,
                        5000
                    )
                else:
                    self.tray_icon.showMessage(
                        "PCLink Updates",
                        "You are running the latest version.",
                        QSystemTrayIcon.Icon.Information,
                        3000
                    )
            
            QTimer.singleShot(0, show_notification)
        
        self.update_checker.check_for_updates_async(handle_result)

    def quit_application(self):
        log.info("Shutting down PCLink from headless mode.")
        self.controller.stop_server()
        self.tray_icon.hide()
        QApplication.quit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.hide()  # Hide window during setup to prevent flicker

        self.platform = sys.platform
        self.is_admin = is_admin()

        generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)

        self.settings = QSettings(constants.APP_NAME, "AppGUI")
        self.load_settings()

        self.is_server_running = False
        self.tray_icon = None
        
        self.setWindowTitle(f"PCLink {__version__}")

        # Initialize update checker
        self.update_checker = UpdateChecker()
        
        self.controller = Controller(self)
        self.initialize_ui()
        self.controller.update_ui_for_server_state()
        
        # Check for updates on startup (after a short delay)
        QTimer.singleShot(3000, self.check_for_updates_startup)

    def initialize_ui(self):
        # UI components are created here, inheriting the app's stylesheet
        self.create_actions()
        self.create_menus()
        setupUi(self)
        
        self.retranslate_ui()
        self.controller.connect_signals()

        # Connect update signals for thread-safe GUI updates
        update_signal_emitter.update_available.connect(self.handle_update_available_signal)
        update_signal_emitter.no_update_available.connect(self.handle_no_update_signal)

        self.device_prune_timer = QTimer(self)
        self.device_prune_timer.setInterval(10000)
        self.device_prune_timer.timeout.connect(self.controller.prune_and_update_devices)

        self.server_check_timer = QTimer(self)
        self.server_check_timer.timeout.connect(self.controller._check_server_started)

        # Setup periodic update checking (every 4 hours)
        self.update_check_timer = QTimer(self)
        self.update_check_timer.timeout.connect(self.check_for_updates_periodic)
        self.update_check_timer.start(4 * 60 * 60 * 1000)  # 4 hours in milliseconds

        self.setup_tray_icon()

    def tr(self, key, **kwargs):
        return self.translations.get(key, key).format(**kwargs)

    def retranslate_ui(self):
        retranslateUi(self)

    def load_settings(self):
        try:
            raw_key = load_config_value(constants.API_KEY_FILE, default=str(uuid.uuid4()))
            self.api_key = validate_api_key(raw_key)
            if self.api_key != raw_key:
                save_config_value(constants.API_KEY_FILE, self.api_key)
        except ValidationError:
            log.warning("Invalid API key found. Generating a new one.")
            self.api_key = str(uuid.uuid4())
            save_config_value(constants.API_KEY_FILE, self.api_key)

        self.api_port = int(load_config_value(constants.PORT_FILE, str(constants.DEFAULT_PORT)))
        self.minimize_to_tray = self.settings.value("minimize_to_tray", True, type=bool)
        self.current_language = self.settings.value("language", "en")
        self.use_https = self.settings.value("use_https", True, type=bool)
        self.allow_insecure_shell = self.settings.value("allow_insecure_shell", False, type=bool)
        self.check_updates_on_startup = self.settings.value("check_updates_on_startup", True, type=bool)
        self.translations = LANGUAGES.get(self.current_language, LANGUAGES["en"])

    def create_actions(self):
        self.exit_action = QAction(self)
        self.restart_admin_action = QAction(self, enabled=(self.platform == "win32"))
        self.change_port_action = QAction(self)
        self.update_key_action = QAction(self)
        self.about_action = QAction(self)

        startup_manager = get_startup_manager()
        self.startup_action = QAction(self, checkable=True, checked=startup_manager.is_enabled(constants.APP_NAME))
        self.minimize_action = QAction(self, checkable=True, checked=self.minimize_to_tray)
        self.use_https_action = QAction(self, checkable=True, checked=self.use_https)
        self.allow_insecure_shell_action = QAction(self, checkable=True, checked=self.allow_insecure_shell)
        self.show_startup_notification_action = QAction(self, checkable=True, checked=self.settings.value("show_startup_notification", True, type=bool))
        self.check_updates_action = QAction(self, checkable=True, checked=self.check_updates_on_startup)
        self.check_updates_now_action = QAction(self)
        self.language_action_group = QActionGroup(self)

    def create_menus(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("")
        self.file_menu.addAction(self.restart_admin_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.about_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)
        
        self.settings_menu = menu_bar.addMenu("")
        self.settings_menu.addAction(self.change_port_action)
        self.settings_menu.addAction(self.update_key_action)
        self.settings_menu.addSeparator()

        self.language_menu = self.settings_menu.addMenu("")
        for lang_code, lang_data in LANGUAGES.items():
            action = QAction(lang_data["lang_name"], self, checkable=True, data=lang_code)
            action.setChecked(self.current_language == lang_code)
            self.language_menu.addAction(action)
            self.language_action_group.addAction(action)

        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.use_https_action)
        self.settings_menu.addAction(self.allow_insecure_shell_action)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.startup_action)
        self.settings_menu.addAction(self.minimize_action)
        self.settings_menu.addAction(self.show_startup_notification_action)
        self.settings_menu.addAction(self.check_updates_action)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.check_updates_now_action)

    def retranslate_menus(self):
        self.file_menu.setTitle(self.tr("menu_file"))
        self.exit_action.setText(self.tr("menu_file_exit"))
        self.restart_admin_action.setText(self.tr("menu_file_restart_admin"))
        self.about_action.setText(self.tr("menu_file_about"))
        self.settings_menu.setTitle(self.tr("menu_settings"))
        self.change_port_action.setText(self.tr("change_port_btn"))
        self.update_key_action.setText(self.tr("regen_api_key_btn"))
        self.startup_action.setText(self.tr("start_with_os_chk"))
        self.startup_action.setToolTip(self.tr("start_with_os_tooltip"))
        self.minimize_action.setText(self.tr("minimize_on_close_chk"))
        self.use_https_action.setText(self.tr("use_https_chk"))
        self.use_https_action.setToolTip(self.tr("use_https_tooltip"))
        self.allow_insecure_shell_action.setText(self.tr("allow_insecure_shell_chk"))
        self.allow_insecure_shell_action.setToolTip(self.tr("allow_insecure_shell_tooltip"))
        self.show_startup_notification_action.setText(self.tr("show_startup_notification_chk"))
        self.check_updates_action.setText(self.tr("check_updates_on_startup_chk"))
        self.check_updates_now_action.setText(self.tr("check_updates_now_btn"))
        self.language_menu.setTitle(self.tr("menu_language"))

    def update_device_list_ui(self):
        self.device_list.clear()
        if not self.is_server_running:
            self.device_list.addItem(self.tr("devices_stopped_text"))
            return

        active_devices = [d for d in connected_devices.values() if time.time() - d.get("last_seen", 0) < constants.DEVICE_TIMEOUT]
        if not active_devices:
            self.device_list.addItem(self.tr("devices_waiting_text"))
            return

        for d in sorted(active_devices, key=lambda x: x.get("name", "Unknown")):
            item = QListWidgetItem(f"● {d.get('name', 'Unknown')} ({d.get('ip', '?.?.?.?')})")
            item.setForeground(QColor("#a6e22e"))
            self.device_list.addItem(item)

    def on_language_selected(self, action: QAction):
        if (lang_code := action.data()) and self.current_language != lang_code:
            self.settings.setValue("language", lang_code)
            QMessageBox.information(self, self.tr("language_changed_title"), self.tr("language_changed_msg"))

    def generate_qr_code(self):
        try:
            protocol = "https" if self.use_https else "http"
            url = f"{protocol}://127.0.0.1:{self.api_port}/qr-payload"
            headers = {"x-api-key": self.api_key}
            response = requests.get(url, headers=headers, verify=False, timeout=5)
            response.raise_for_status()
            payload_str = json.dumps(response.json())
        except Exception as e:
            log.error(f"Failed to fetch QR payload: {e}")
            self.qr_label.setText(self.tr("qr_error_text"))
            self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return

        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=2)
        qr.add_data(payload_str)
        qr.make(fit=True)
        matrix = qr.get_matrix()

        label_size = self.qr_label.size()
        pixmap = QPixmap(label_size)
        pixmap.fill(Qt.GlobalColor.transparent)

        with QPainter(pixmap) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor("#e0e0e0"))
            painter.setPen(Qt.PenStyle.NoPen)

            module_count = len(matrix)
            if module_count == 0: return

            module_size = min(label_size.width(), label_size.height()) / module_count
            offset_x = (label_size.width() - (module_size * module_count)) / 2
            offset_y = (label_size.height() - (module_size * module_count)) / 2

            for y, row in enumerate(matrix):
                for x, module in enumerate(row):
                    if module:
                        painter.drawRect(
                            int(offset_x + x * module_size), int(offset_y + y * module_size),
                            int(module_size) + 1, int(module_size) + 1,
                        )
        
        self.qr_label.setText("")
        self.qr_label.setPixmap(pixmap)

    def setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.windowIcon())
        self.tray_icon.setToolTip(f"{self.tr('tray_tooltip')} v{__version__}")
        menu = QMenu(self)
        menu.addAction(self.tr("tray_show"), self.show_window)
        menu.addSeparator()
        menu.addAction(self.exit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(lambda r: self.show_window() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray_icon.show()

    def show_window(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.activateWindow()

    def show_about_dialog(self):
        log.info("About dialog requested")
        try:
            dialog = VersionDialog(self)
            dialog.exec()
        except Exception as e:
            log.error(f"Failed to show about dialog: {e}")
            QMessageBox.information(self, "About PCLink", f"PCLink v{__version__}\n{version_info.copyright}")

    def check_for_updates_startup(self):
        """Check for updates on application startup."""
        if not self.check_updates_on_startup:
            return
        
        log.info("Checking for updates on startup")
        self.update_checker.check_for_updates_async(self._emit_update_signal_auto)
    
    def check_for_updates_periodic(self):
        """Periodic update check (background)."""
        if not self.check_updates_on_startup:
            return
            
        if self.update_checker.should_check_for_updates():
            log.debug("Performing periodic update check")
            self.update_checker.check_for_updates_async(self._emit_update_signal_auto)
    
    def check_for_updates_manual(self):
        """Manual update check triggered by user."""
        log.info("Manual update check requested")
        self.update_checker.check_for_updates_async(self._emit_update_signal_manual)
    
    def _emit_update_signal_auto(self, update_info):
        """Emit update signal for automatic checks (thread-safe)."""
        if update_info:
            # Check if this version was already skipped
            skipped_version = self.settings.value("skipped_version", "")
            if skipped_version == update_info["version"]:
                log.debug(f"Skipping notification for version {update_info['version']} (user skipped)")
                return
            update_signal_emitter.update_available.emit(update_info)
    
    def _emit_update_signal_manual(self, update_info):
        """Emit update signal for manual checks (thread-safe)."""
        if update_info:
            self._manual_update_check = True  # Set flag for modal dialog
            update_signal_emitter.update_available.emit(update_info)
        else:
            update_signal_emitter.no_update_available.emit()
    
    def handle_update_available_signal(self, update_info):
        """Handle update available signal (runs in main thread)."""
        try:
            dialog = UpdateDialog(update_info, self)
            # Check if this was triggered by manual check (use exec) or automatic (use show)
            if hasattr(self, '_manual_update_check') and self._manual_update_check:
                self._manual_update_check = False  # Reset flag
                dialog.exec()
            else:
                dialog.show()
        except Exception as e:
            log.error(f"Failed to show update dialog: {e}")
            # Fallback to tray notification
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "PCLink Update Available",
                    f"Version {update_info['version']} is available for download.",
                    QSystemTrayIcon.Icon.Information,
                    5000
                )
    
    def handle_no_update_signal(self):
        """Handle no update available signal (runs in main thread)."""
        QMessageBox.information(
            self,
            self.tr("no_updates_title"),
            self.tr("no_updates_msg")
        )

    def quit_application(self):
        log.info("Shutting down PCLink from GUI.")
        self.controller.stop_server()
        if self.tray_icon: self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent):
        if self.minimize_to_tray:
            event.ignore()
            self.hide()
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr("confirm_exit_title"))
        msg_box.setText(self.tr("confirm_exit_text"))
        msg_box.setIcon(QMessageBox.Icon.Question)
        exit_button = msg_box.addButton(self.tr("exit_button"), QMessageBox.ButtonRole.DestructiveRole)
        minimize_button = msg_box.addButton(self.tr("minimize_button"), QMessageBox.ButtonRole.ActionRole)
        cancel_button = msg_box.addButton(QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(cancel_button)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == exit_button:
            self.quit_application()
            event.accept()
        elif clicked == minimize_button:
            self.hide()
            event.ignore()
        else:
            event.ignore()


def main():
    """Main entry point for the application."""
    if getattr(sys, "frozen", False):
        from .core.windows_console import hide_console_window, setup_console_redirection
        hide_console_window()
        setup_console_redirection()
    
    multiprocessing.freeze_support()
    
    from .core.logging_config import setup_logging
    setup_logging()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(__app_name__)
        app.setApplicationVersion(__version__)
        app.setOrganizationName("BYTEDz")
        
        # Apply the application icon and stylesheet BEFORE creating the main window.
        # This is the critical step to prevent flickering.
        app.setWindowIcon(_create_app_icon())
        app.setStyleSheet(get_stylesheet())

        is_startup_mode = "--startup" in sys.argv
        main_component = HeadlessApp() if is_startup_mode else MainWindow()
        
        if not is_startup_mode:
            main_component.show()
            main_component.activateWindow()

        log.info(f"PCLink started {'in headless mode' if is_startup_mode else 'with GUI'}.")
        exit_code = app.exec()
        log.info(f"Application exiting with code {exit_code}.")
        return exit_code

    except Exception as e:
        log.critical("A fatal error occurred during application startup.", exc_info=True)
        QMessageBox.critical(None, "Fatal Error", f"PCLink failed to start:\n{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())