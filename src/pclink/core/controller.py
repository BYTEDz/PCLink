"""
PCLink - Remote PC Control Server - Controller Module
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
import logging
import socket
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import uvicorn
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from ..api_server.api import create_api_app, pairing_events, pairing_results
from ..api_server.discovery import DiscoveryService
from . import constants
from .state import api_signal_emitter, connected_devices
from .utils import get_startup_manager, restart_as_admin, save_config_value

log = logging.getLogger(__name__)


class Controller:
    """Handles the application's core logic and orchestrates UI interactions."""

    def __init__(self, main_window):
        self.window = main_window
        self.discovery_service = None
        self.uvicorn_server = None
        self.server_thread = None
        self.startup_manager = get_startup_manager()

    def connect_signals(self):
        """Connects GUI element signals to controller methods."""
        w = self.window
        w.server_toggle_button.clicked.connect(self.toggle_server_state)
        w.copy_ip_btn.clicked.connect(
            lambda: self.copy_to_clipboard(w.ip_address_combo.currentText())
        )
        w.copy_port_btn.clicked.connect(
            lambda: self.copy_to_clipboard(w.port_entry.text())
        )
        w.copy_key_btn.clicked.connect(
            lambda: self.copy_to_clipboard(w.api_key_entry.text())
        )
        w.ip_address_combo.currentIndexChanged.connect(w.generate_qr_code)

        api_signal_emitter.device_list_updated.connect(w.update_device_list_ui)
        api_signal_emitter.pairing_request.connect(self.handle_pairing_request)

        w.exit_action.triggered.connect(w.quit_application)
        w.restart_admin_action.triggered.connect(self.handle_restart_as_admin)
        w.change_port_action.triggered.connect(self.change_port_ui)
        w.update_key_action.triggered.connect(self.update_api_key_ui)
        w.startup_action.toggled.connect(self.handle_startup_change)
        w.minimize_action.toggled.connect(self.handle_minimize_change)
        w.use_https_action.toggled.connect(self.handle_https_change)
        w.allow_insecure_shell_action.toggled.connect(
            self.handle_allow_insecure_shell_change
        )
        w.show_startup_notification_action.toggled.connect(
            self.handle_startup_notification_change
        )
        w.language_action_group.triggered.connect(w.on_language_selected)
        w.about_action.triggered.connect(w.show_about_dialog)
        w.open_log_action.triggered.connect(self.open_log_file)
        w.check_updates_action.toggled.connect(self.handle_check_updates_change)
        w.check_updates_now_action.triggered.connect(w.check_for_updates_manual)

    def handle_pairing_request(self, pairing_id: str, device_name: str):
        """Shows a confirmation dialog when a new device wants to pair."""
        log.info(f"GUI: Displaying pairing dialog for '{device_name}'")

        reply = QMessageBox.question(
            self.window,
            self.window.tr("pairing_request_title"),
            self.window.tr("pairing_request_text", device_name=device_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        accepted = reply == QMessageBox.StandardButton.Yes
        pairing_results[pairing_id] = accepted

        if event := pairing_events.get(pairing_id):
            event.set()

    def start_server(self):
        if hasattr(self.window, "server_toggle_button"):
            self.window.server_toggle_button.setEnabled(False)
            self.window.status_indicator.set_color("#ffc107")

        hostname = socket.gethostname()
        self.discovery_service = DiscoveryService(
            self.window.api_port, hostname, self.window.use_https
        )
        self.discovery_service.start()

        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        if hasattr(self.window, "server_check_timer"):
            self.window.server_check_timer.start(100)

    def stop_server(self):
        if self.discovery_service:
            self.discovery_service.stop()
            self.discovery_service = None
        if hasattr(self.window, "device_prune_timer"):
            self.window.device_prune_timer.stop()
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        self.uvicorn_server = None
        self.server_thread = None
        if hasattr(self.window, "is_server_running"):
            self.window.is_server_running = False
            connected_devices.clear()
            self.update_ui_for_server_state()
        log.info("Server stopped.")

    def _run_server(self):
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        try:
            app_instance = create_api_app(
                self.window.api_key,
                api_signal_emitter,
                connected_devices,
                self.window.use_https,
                self.window.allow_insecure_shell,
            )
            app_instance.state.host_ip = self.window.ip_address_combo.currentText()
            app_instance.state.host_port = self.window.api_port

            uvicorn_config = {
                "app": app_instance,
                "host": "0.0.0.0",
                "port": self.window.api_port,
                "log_level": "info",
            }
            if self.window.use_https:
                uvicorn_config["ssl_keyfile"] = str(constants.KEY_FILE)
                uvicorn_config["ssl_certfile"] = str(constants.CERT_FILE)

            config = uvicorn.Config(**uvicorn_config)
            self.uvicorn_server = uvicorn.Server(config)
            self.uvicorn_server.run()

        except Exception:
            log.critical("Server failed to run", exc_info=True)
            with open("server_errors.log", "a", encoding="utf-8") as f:
                f.write(
                    f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{traceback.format_exc()}\n"
                )

    def toggle_server_state(self):
        if getattr(self.window, "is_server_running", False):
            self.stop_server()
        else:
            self.start_server()

    def _check_server_started(self):
        if not self.uvicorn_server:
            self.window.server_check_timer.stop()
            return

        if self.uvicorn_server.started:
            self.window.server_check_timer.stop()
            log.info("Server has started successfully.")
            self.window.is_server_running = True
            self.window.server_toggle_button.setEnabled(True)
            self.update_ui_for_server_state()
            if not self.window.device_prune_timer.isActive():
                self.window.device_prune_timer.start()
        elif not self.server_thread.is_alive():
            self.window.server_check_timer.stop()
            self.window.server_toggle_button.setEnabled(True)
            QMessageBox.critical(
                self.window,
                "Server Error",
                "The server failed to start. See server_errors.log for details.",
            )
            self.window.is_server_running = False
            self.update_ui_for_server_state()

    def update_ui_for_server_state(self):
        w = self.window
        if not hasattr(w, "status_indicator"):
            return

        is_running = w.is_server_running
        w.status_indicator.set_color("#28a745" if is_running else "#6c757d")
        w.status_label.setText(
            w.tr("server_running_status")
            if is_running
            else w.tr("server_stopped_status")
        )

        if is_running:
            protocol = "https" if w.use_https else "http"
            w.protocol_label.setText(
                w.tr(
                    f"protocol_{protocol}_secure"
                    if w.use_https
                    else f"protocol_{protocol}_unsecure"
                )
            )
            w.server_toggle_button.setText(w.tr("stop_server_btn"))
            w.server_toggle_button.setStyleSheet("background-color: #dc3545;")
            w.generate_qr_code()
        else:
            w.protocol_label.setText("")
            w.server_toggle_button.setText(w.tr("start_server_btn"))
            w.server_toggle_button.setStyleSheet("background-color: #28a745;")
            w.qr_label.setPixmap(QPixmap())
            w.qr_label.setText(w.tr("qr_stopped_text"))
            w.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for widget in [
            w.change_port_action,
            w.update_key_action,
            w.ip_address_combo,
            w.use_https_action,
            w.allow_insecure_shell_action,
        ]:
            widget.setEnabled(not is_running)

        w.update_device_list_ui()

    def _prompt_for_server_restart(self):
        if self.window.is_server_running:
            reply = QMessageBox.question(
                self.window,
                self.window.tr("setting_saved_title"),
                self.window.tr("restart_server_prompt"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_server()
                self.start_server()

    def handle_startup_change(self, checked: bool):
        try:
            exe_path = Path(sys.executable).resolve()
            if checked:
                self.startup_manager.add(constants.APP_NAME, exe_path)
            else:
                self.startup_manager.remove(constants.APP_NAME)
            self.window.settings.setValue("start_at_boot", checked)
        except Exception as e:
            log.error(f"Could not modify startup settings: {e}")
            QMessageBox.warning(
                self.window, "Startup Error", f"Could not modify startup settings:\n{e}"
            )

    def handle_minimize_change(self, checked: bool):
        self.window.minimize_to_tray = checked
        self.window.settings.setValue("minimize_to_tray", checked)

    def handle_https_change(self, checked: bool):
        if not checked:
            reply = QMessageBox.warning(
                self.window,
                self.window.tr("https_warning_title"),
                self.window.tr("https_warning_msg"),
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                self.window.use_https_action.setChecked(True)
                return
        self.window.use_https = checked
        self.window.settings.setValue("use_https", checked)
        self._prompt_for_server_restart()

    def handle_allow_insecure_shell_change(self, checked: bool):
        if checked:
            reply = QMessageBox.warning(
                self.window,
                self.window.tr("insecure_shell_warning_title"),
                self.window.tr("insecure_shell_warning_msg"),
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                self.window.allow_insecure_shell_action.setChecked(False)
                return
        self.window.allow_insecure_shell = checked
        self.window.settings.setValue("allow_insecure_shell", checked)
        self._prompt_for_server_restart()

    def handle_startup_notification_change(self, checked: bool):
        self.window.settings.setValue("show_startup_notification", checked)

    def handle_restart_as_admin(self):
        self.stop_server()
        restart_as_admin()
        QApplication.quit()

    def update_api_key_ui(self):
        if (
            QMessageBox.question(
                self.window,
                self.window.tr("regen_api_key_btn"),
                self.window.tr("regen_api_key_confirm"),
            )
            == QMessageBox.StandardButton.Yes
        ):
            new_key = str(uuid.uuid4())
            save_config_value(constants.API_KEY_FILE, new_key)
            self.window.api_key = new_key
            self.window.api_key_entry.setText(new_key)
            self._prompt_for_server_restart()

    def change_port_ui(self):
        new_port, ok = QInputDialog.getInt(
            self.window,
            self.window.tr("change_port_btn"),
            self.window.tr("change_port_prompt"),
            self.window.api_port,
            1024,
            65535,
        )
        if ok and new_port != self.window.api_port:
            save_config_value(constants.PORT_FILE, new_port)
            self.window.api_port = new_port
            self.window.port_entry.setText(str(new_port))
            self._prompt_for_server_restart()

    def copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)

    def prune_and_update_devices(self):
        if not getattr(self.window, "is_server_running", False):
            return

        now = time.time()
        if any(
            now - dev["last_seen"] > constants.DEVICE_TIMEOUT
            for dev in connected_devices.values()
        ):
            for ip in list(connected_devices.keys()):
                if now - connected_devices[ip]["last_seen"] > constants.DEVICE_TIMEOUT:
                    del connected_devices[ip]
            api_signal_emitter.device_list_updated.emit()

    def handle_check_updates_change(self, checked: bool):
        """Handle the check for updates on startup setting change."""
        self.window.check_updates_on_startup = checked
        self.window.settings.setValue("check_updates_on_startup", checked)

    def open_log_file(self):
        """Open the log file for debugging."""
        try:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            
            log_file = constants.APP_DATA_PATH / "pclink.log"
            if log_file.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file)))
                log.info("Opened log file from menu")
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self.window,
                    "Log File Not Found",
                    f"Log file does not exist at:\n{log_file}"
                )
        except Exception as e:
            log.error(f"Failed to open log file from menu: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self.window,
                "Error Opening Log File",
                f"Failed to open log file:\n{str(e)}"
            )
