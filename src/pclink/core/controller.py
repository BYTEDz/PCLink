# filename: src/pclink/core/controller.py
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
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from ..api_server.api import create_api_app, pairing_events, pairing_results
from ..api_server.discovery import DiscoveryService
from . import constants
from .config import config_manager
from .device_manager import device_manager
from .state import api_signal_emitter, connected_devices
from .utils import (DummyTty, get_startup_manager, restart_as_admin,
                    save_config_value)

log = logging.getLogger(__name__)


class Controller:
    """Handles the application's core logic and orchestrates UI interactions."""

    def __init__(self, main_window):
        self.window = main_window
        self.discovery_service = None
        self.uvicorn_server = None
        self.server_thread = None
        self.startup_manager = get_startup_manager()
        self._signals_connected = False

    def is_server_running(self):
        return self.uvicorn_server and self.uvicorn_server.started

    def is_server_starting(self):
        return self.server_thread and self.server_thread.is_alive()

    def get_port(self):
        return getattr(self.window, 'api_port', config_manager.get('server_port'))

    def connect_signals(self):
        """Connects GUI element signals to controller methods."""
        if self._signals_connected:
            return
        
        w = self.window
        w.server_toggle_button.clicked.connect(self.toggle_server_state)
        w.copy_ip_btn.clicked.connect(lambda: self.copy_to_clipboard(w.ip_address_combo.currentText()))
        w.copy_port_btn.clicked.connect(lambda: self.copy_to_clipboard(w.port_entry.text()))
        w.copy_key_btn.clicked.connect(lambda: self.copy_to_clipboard(w.api_key_entry.text()))
        w.ip_address_combo.currentIndexChanged.connect(w.generate_qr_code)

        api_signal_emitter.device_list_updated.connect(w.update_device_list_ui)
        api_signal_emitter.pairing_request.connect(self.handle_pairing_request)

        w.exit_action.triggered.connect(w.quit_application)
        w.restart_admin_action.triggered.connect(self.handle_restart_as_admin)
        w.change_port_action.triggered.connect(self.change_port_ui)
        w.update_key_action.triggered.connect(self.update_api_key_ui)
        w.startup_action.toggled.connect(self.handle_startup_change)
        w.minimize_action.toggled.connect(self.handle_minimize_change)
        w.allow_insecure_shell_action.toggled.connect(self.handle_allow_insecure_shell_change)
        w.show_startup_notification_action.toggled.connect(self.handle_startup_notification_change)
        w.language_action_group.triggered.connect(w.on_language_selected)
        w.about_action.triggered.connect(w.show_about_dialog)
        w.open_log_action.triggered.connect(self.open_log_file)
        w.check_updates_action.toggled.connect(self.handle_check_updates_change)
        w.check_updates_now_action.triggered.connect(w.check_for_updates)
        w.fix_discovery_action.triggered.connect(self.show_discovery_troubleshoot)
        
        self._signals_connected = True

    def handle_pairing_request(self, pairing_id: str, device_name: str, device_id: str = None):
        """Shows a confirmation dialog when a new device wants to pair."""
        device_info = f"{device_name} ({device_id[:8]}...)" if device_id else device_name
        
        if pairing_id in pairing_results and pairing_results[pairing_id].get("user_decided", False):
            log.warning(f"Pairing request {pairing_id} for '{device_info}' already processed.")
            return

        reply = QMessageBox.question(
            self.window, self.window.tr("pairing_request_title"),
            self.window.tr("pairing_request_text", device_name=device_info),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes
        )
        accepted = reply == QMessageBox.StandardButton.Yes
        
        pairing_results[pairing_id] = {"approved": accepted, "user_decided": True}
        log.info(f"Pairing request for '{device_info}' {'accepted' if accepted else 'denied'}.")

        if event := pairing_events.get(pairing_id):
            event.set()

    def start_server(self):
        if hasattr(self.window, "server_toggle_button"):
            self.window.server_toggle_button.setEnabled(False)
            self.window.status_indicator.set_color("#ffc107")

        hostname = socket.gethostname()
        self.discovery_service = DiscoveryService(self.get_port(), hostname)
        self.discovery_service.start()

        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        if hasattr(self.window, "server_check_timer"):
            self.window.server_check_timer.start(100)

    def stop_server(self):
        if self.discovery_service:
            self.discovery_service.stop()
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        
        self.uvicorn_server = None
        self.server_thread = None
        self.discovery_service = None

        if hasattr(self.window, "is_server_running"):
            self.window.is_server_running = False
            connected_devices.clear()
            api_signal_emitter.device_list_updated.emit()
            self.update_ui_for_server_state()
        log.info("Server stopped.")

    def _run_server(self):
        # In packaged executables without a console, stdout/stderr can be None.
        # Uvicorn's logger crashes on this, so we provide a dummy fallback.
        if sys.stdout is None:
            sys.stdout = DummyTty()
        if sys.stderr is None:
            sys.stderr = DummyTty()

        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        try:
            # In headless mode, `self.window` is the HeadlessApp instance which lacks UI attributes.
            # We must load/get config values with fallbacks to prevent crashes.
            api_key = getattr(self.window, 'api_key', None)
            if api_key is None:
                if constants.API_KEY_FILE.exists():
                    api_key = constants.API_KEY_FILE.read_text().strip()
                else:
                    log.critical("API key file not found. Server cannot start.")
                    return  # Gracefully exit the thread

            app = create_api_app(
                api_key,
                api_signal_emitter,
                connected_devices,
                allow_insecure_shell=config_manager.get("allow_insecure_shell")
            )

            # The IP from the combo box is primarily for the QR code.
            # In headless mode, we can use a placeholder as the QR code is not visible.
            host_ip_combo = getattr(self.window, 'ip_address_combo', None)
            app.state.host_ip = host_ip_combo.currentText() if host_ip_combo else "0.0.0.0"

            app.state.host_port = self.get_port()
            app.state.api_key = api_key
            
            uvicorn_config = {
                "app": app, 
                "host": "0.0.0.0", 
                "port": self.get_port(), 
                "log_level": "info",
                "ssl_keyfile": str(constants.KEY_FILE), 
                "ssl_certfile": str(constants.CERT_FILE)
            }

            config = uvicorn.Config(**uvicorn_config)
            self.uvicorn_server = uvicorn.Server(config)
            self.uvicorn_server.run()
        except Exception:
            log.critical("Server failed to run", exc_info=True)

    def toggle_server_state(self):
        if getattr(self.window, "is_server_running", False):
            self.stop_server()
        else:
            self.start_server()

    def _check_server_started(self):
        if not self.is_server_starting():
            self.window.server_check_timer.stop()
            if not self.is_server_running():
                QMessageBox.critical(self.window, "Server Error", "The server failed to start. See logs for details.")
                self.window.is_server_running = False
                self.update_ui_for_server_state()
            return
        
        if self.is_server_running():
            self.window.server_check_timer.stop()
            log.info("Server has started successfully.")
            self.window.is_server_running = True
            self.update_ui_for_server_state()

    def update_ui_for_server_state(self):
        w = self.window
        if not hasattr(w, "status_indicator"): return

        is_running = w.is_server_running
        w.server_toggle_button.setEnabled(True)
        w.status_indicator.set_color("#28a745" if is_running else "#6c757d")
        w.status_label.setText(w.tr(f"server_{'running' if is_running else 'stopped'}_status"))

        if is_running:
            w.protocol_label.setText(w.tr("protocol_https_secure"))
            w.server_toggle_button.setText(w.tr("stop_server_btn"))
            w.server_toggle_button.setStyleSheet("background-color: #dc3545;")
            w.generate_qr_code()
        else:
            w.protocol_label.setText("")
            w.server_toggle_button.setText(w.tr("start_server_btn"))
            w.server_toggle_button.setStyleSheet("background-color: #28a745;")
            w.qr_label.setPixmap(QPixmap())
            w.qr_label.setText(w.tr("qr_stopped_text"))

        for widget in [w.change_port_action, w.update_key_action, w.allow_insecure_shell_action]:
            widget.setEnabled(not is_running)
        w.update_device_list_ui()

    def _prompt_for_server_restart(self):
        if self.window.is_server_running:
            if QMessageBox.question(self.window, self.window.tr("setting_saved_title"), self.window.tr("restart_server_prompt")) == QMessageBox.StandardButton.Yes:
                self.stop_server()
                QTimer.singleShot(500, self.start_server)

    def handle_startup_change(self, checked: bool):
        try:
            exe = Path(sys.executable)
            app_path = str(exe)
            if exe.name.lower() == "python.exe":
                 app_path = f'"{exe}" -m pclink'
            
            if checked:
                self.startup_manager.add(constants.APP_NAME, app_path, args=["--startup"])
            else:
                self.startup_manager.remove(constants.APP_NAME)
        except Exception as e:
            log.error(f"Could not modify startup settings: {e}")

    def handle_minimize_change(self, checked: bool):
        config_manager.set("minimize_to_tray", checked)
        self.window.minimize_to_tray = checked

    def handle_allow_insecure_shell_change(self, checked: bool):
        if checked and QMessageBox.warning(self.window, self.window.tr("insecure_shell_warning_title"), self.window.tr("insecure_shell_warning_msg"), QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Cancel:
            self.window.allow_insecure_shell_action.setChecked(False)
            return
        config_manager.set("allow_insecure_shell", checked)
        self._prompt_for_server_restart()

    def handle_startup_notification_change(self, checked: bool):
        config_manager.set("show_startup_notification", checked)

    def handle_restart_as_admin(self):
        self.stop_server()
        restart_as_admin()

    def update_api_key_ui(self):
        if QMessageBox.question(self.window, self.window.tr("regen_api_key_btn"), self.window.tr("regen_api_key_confirm")) == QMessageBox.StandardButton.Yes:
            new_key = str(uuid.uuid4())
            save_config_value(constants.API_KEY_FILE, new_key)
            self.window.api_key = new_key
            self.window.api_key_entry.setText(new_key)
            self._prompt_for_server_restart()

    def change_port_ui(self):
        new_port, ok = QInputDialog.getInt(self.window, self.window.tr("change_port_btn"), self.window.tr("change_port_prompt"), self.get_port(), 1024, 65535)
        if ok and new_port != self.get_port():
            config_manager.set("server_port", new_port)
            self.window.api_port = new_port
            self.window.port_entry.setText(str(new_port))
            self._prompt_for_server_restart()

    def copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)

    def prune_and_update_devices(self):
        if self.window.is_server_running and device_manager.prune_devices():
            api_signal_emitter.device_list_updated.emit()

    def handle_check_updates_change(self, checked: bool):
        config_manager.set("check_updates_on_startup", checked)
        self.window.check_updates_on_startup = checked

    def show_discovery_troubleshoot(self):
        from ..gui.discovery_dialog import DiscoveryTroubleshootDialog
        DiscoveryTroubleshootDialog(self.window).exec()

    def open_log_file(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file)))
        else:
            QMessageBox.information(self.window, "Log File Not Found", f"Log file does not exist at:\n{log_file}")
            
    def get_qr_payload(self):
        if not self.window.is_server_running: return None
        try:
            import requests
            protocol = "https"
            url = f"{protocol}://127.0.0.1:{self.get_port()}/qr-payload"
            headers = {"x-api-key": self.window.api_key}
            with requests.packages.urllib3.warnings.catch_warnings():
                requests.packages.urllib3.disable_warnings()
                response = requests.get(url, headers=headers, verify=False, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"Failed to fetch QR payload: {e}")
            return None