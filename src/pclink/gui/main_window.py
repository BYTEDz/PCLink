# filename: src/pclink/gui/main_window.py
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

import qrcode
import requests
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QColor, QImage,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QListWidgetItem, QMainWindow,
                               QMessageBox)

from ..core import constants
from ..core.config import config_manager
from ..core.controller import Controller
from ..core.device_manager import device_manager
from ..core.update_checker import UpdateChecker
from ..core.utils import (get_startup_manager, is_admin, load_config_value,
                          save_config_value)
from ..core.validators import ValidationError, validate_api_key
from ..core.version import __version__
from .layout import retranslateUi, setupUi
from .localizations import LANGUAGES
from .tray_manager import UnifiedTrayManager
from .update_dialog import UpdateDialog
from .version_dialog import VersionDialog

log = logging.getLogger(__name__)


class UpdateSignalEmitter(QObject):
    """Signal emitter for update notifications to handle thread-safe GUI updates."""
    update_available = Signal(dict)
    no_update_available = Signal()

update_signal_emitter = UpdateSignalEmitter()


class MainWindow(QMainWindow):
    """The main application window for PCLink."""

    def __init__(self, from_headless=False):
        super().__init__()
        self.hide()
        self.from_headless = from_headless

        self.platform = sys.platform
        self.is_admin = is_admin()

        self.setWindowTitle(f"PCLink {__version__}")
        self.is_server_running = False

        self._initialize_core_properties()

        self.controller = Controller(self)
        self.update_checker = UpdateChecker()
        self.tray_manager = UnifiedTrayManager(self)

        self._load_settings()
        self.initialize_ui()
        self.controller.update_ui_for_server_state()

        if not from_headless:
            # Start server automatically on GUI launch after a short delay
            QTimer.singleShot(100, self.controller.start_server)
            QTimer.singleShot(3000, self.check_for_updates_startup)

    def _initialize_core_properties(self):
        """Initializes core properties like API key and port needed by the UI and Controller."""
        self.api_port = config_manager.get("server_port")

        # Load and validate API key from its separate file
        try:
            raw_key = load_config_value(constants.API_KEY_FILE, default=str(uuid.uuid4()))
            self.api_key = validate_api_key(raw_key)
            if self.api_key != raw_key:
                save_config_value(constants.API_KEY_FILE, self.api_key)
        except ValidationError:
            log.warning("Invalid API key found. Generating a new one.")
            self.api_key = str(uuid.uuid4())
            save_config_value(constants.API_KEY_FILE, self.api_key)
        except (ImportError, FileNotFoundError) as e:
             log.error(f"Could not load API key due to missing dependency or file: {e}")
             self.api_key = "fallback-key-error"

    def initialize_ui(self):
        """Initializes all UI elements, actions, menus, and signal connections."""
        self.create_actions()
        self.create_menus()
        setupUi(self)

        self.retranslate_ui()
        self.controller.connect_signals()

        update_signal_emitter.update_available.connect(self.handle_update_available_signal)
        update_signal_emitter.no_update_available.connect(self.handle_no_update_signal)

        self.device_prune_timer = QTimer(self)
        self.device_prune_timer.setInterval(10000)
        self.device_prune_timer.timeout.connect(self.controller.prune_and_update_devices)

        self.server_check_timer = QTimer(self)
        self.server_check_timer.timeout.connect(self.controller._check_server_started)

        self.update_check_timer = QTimer(self)
        self.update_check_timer.timeout.connect(self.check_for_updates_periodic)
        self.update_check_timer.start(4 * 60 * 60 * 1000)

        self.tray_manager.setup_menu(mode="gui")
        if not self.from_headless:
            self.tray_manager.show()

    def _load_settings(self):
        """Loads settings using the global ConfigManager."""
        self.minimize_to_tray = config_manager.get("minimize_to_tray")
        self.current_language = config_manager.get("language")
        self.check_updates_on_startup = config_manager.get("check_updates_on_startup")
        self.translations = LANGUAGES.get(self.current_language, LANGUAGES["en"])

    def tr(self, key, *args, **kwargs):
        """
        Translates a given key.
        An optional positional argument can be provided as a fallback.
        If no fallback is provided, the key itself is used.
        Supports string formatting with keyword arguments.
        """
        fallback = args[0] if args else key
        return self.translations.get(key, fallback).format(**kwargs)

    def retranslate_ui(self):
        retranslateUi(self)
        self.retranslate_menus()

    def create_actions(self):
        self.exit_action = QAction(self)
        self.restart_admin_action = QAction(self, enabled=(self.platform == "win32"))
        self.change_port_action = QAction(self)
        self.update_key_action = QAction(self)
        self.about_action = QAction(self)
        self.open_log_action = QAction(self)
        self.check_updates_now_action = QAction(self)
        self.fix_discovery_action = QAction(self)

        startup_manager = get_startup_manager()
        self.startup_action = QAction(self, checkable=True, checked=startup_manager.is_enabled(constants.APP_NAME))
        self.minimize_action = QAction(self, checkable=True, checked=self.minimize_to_tray)
        self.allow_insecure_shell_action = QAction(self, checkable=True, checked=config_manager.get("allow_insecure_shell"))
        self.show_startup_notification_action = QAction(self, checkable=True, checked=config_manager.get("show_startup_notification"))
        self.check_updates_action = QAction(self, checkable=True, checked=self.check_updates_on_startup)
        self.language_action_group = QActionGroup(self)

    def create_menus(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("")
        self.file_menu.addAction(self.restart_admin_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.open_log_action)
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
        self.settings_menu.addAction(self.allow_insecure_shell_action)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.startup_action)
        self.settings_menu.addAction(self.minimize_action)
        self.settings_menu.addAction(self.show_startup_notification_action)
        self.settings_menu.addAction(self.check_updates_action)
        self.settings_menu.addSeparator()
        self.settings_menu.addAction(self.check_updates_now_action)
        self.settings_menu.addAction(self.fix_discovery_action)

    def retranslate_menus(self):
        self.file_menu.setTitle(self.tr("menu_file"))
        self.exit_action.setText(self.tr("menu_file_exit"))
        self.restart_admin_action.setText(self.tr("menu_file_restart_admin"))
        self.open_log_action.setText("Open Log File")
        self.about_action.setText(self.tr("menu_file_about"))
        self.settings_menu.setTitle(self.tr("menu_settings"))
        self.change_port_action.setText(self.tr("change_port_btn"))
        self.update_key_action.setText(self.tr("regen_api_key_btn"))
        self.startup_action.setText(self.tr("start_with_os_chk"))
        self.minimize_action.setText(self.tr("minimize_on_close_chk"))
        self.allow_insecure_shell_action.setText(self.tr("allow_insecure_shell_chk"))
        self.show_startup_notification_action.setText(self.tr("show_startup_notification_chk"))
        self.check_updates_action.setText(self.tr("check_updates_on_startup_chk"))
        self.check_updates_now_action.setText(self.tr("check_updates_now_btn"))
        self.fix_discovery_action.setText(self.tr("fix_discovery_action", "Fix Discovery Issues"))
        self.language_menu.setTitle(self.tr("menu_language"))

    def update_device_list_ui(self):
        self.device_list.clear()
        if not self.is_server_running:
            self.device_list.addItem(self.tr("devices_stopped_text"))
            return

        now = datetime.now(timezone.utc)
        active_devices = [
            d for d in device_manager.get_approved_devices()
            if (now - d.last_seen).total_seconds() < constants.DEVICE_TIMEOUT
        ]
        
        if not active_devices:
            self.device_list.addItem(self.tr("devices_waiting_text"))
            return

        for device in sorted(active_devices, key=lambda x: x.device_name):
            platform_icon = {'ios': '📱', 'android': '📱'}.get(device.platform.lower(), '💻')
            device_info = f"{platform_icon} {device.device_name} ({device.current_ip})"
            item = QListWidgetItem(device_info)
            item.setForeground(QColor("#a6e22e"))
            self.device_list.addItem(item)

    def on_language_selected(self, action: QAction):
        lang_code = action.data()
        if lang_code and self.current_language != lang_code:
            config_manager.set("language", lang_code)
            QMessageBox.information(self, self.tr("language_changed_title"), self.tr("language_changed_msg"))

    def generate_qr_code(self):
        self.qr_label.setText(self.tr("qr_loading_text"))
        try:
            payload = self.controller.get_qr_payload()
            if not payload:
                raise ValueError("Payload is empty")
            
            payload_str = json.dumps(payload, separators=(",", ":"))
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
            qr.add_data(payload_str)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
            q_img = QImage(img.tobytes("raw", "RGBA"), img.size[0], img.size[1], QImage.Format.Format_RGBA8888)
            pixmap = QPixmap.fromImage(q_img)
            self.qr_label.setPixmap(pixmap.scaled(self.qr_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))

        except Exception as e:
            log.error(f"Failed to generate QR code: {e}")
            self.qr_label.setText(self.tr("qr_error_text"))
            self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def show_about_dialog(self):
        VersionDialog(self).exec()

    def check_for_updates_startup(self):
        if self.check_updates_on_startup:
            self.update_checker.check_for_updates_async(self._emit_update_signal_auto)
    
    def check_for_updates_periodic(self):
        if self.check_updates_on_startup and self.update_checker.should_check_for_updates():
            self.update_checker.check_for_updates_async(self._emit_update_signal_auto)
    
    def check_for_updates(self):
        self.update_checker.check_for_updates_async(self._emit_update_signal_manual)
    
    def _emit_update_signal_auto(self, update_info):
        if update_info:
            skipped = config_manager.get("skipped_version")
            if skipped != update_info["version"]:
                update_signal_emitter.update_available.emit(update_info)
    
    def _emit_update_signal_manual(self, update_info):
        if update_info:
            self._manual_update_check = True
            update_signal_emitter.update_available.emit(update_info)
        else:
            update_signal_emitter.no_update_available.emit()
    
    def handle_update_available_signal(self, update_info):
        dialog = UpdateDialog(update_info, self)
        if getattr(self, '_manual_update_check', False):
            self._manual_update_check = False
            dialog.exec()
        else:
            dialog.show()
    
    def handle_no_update_signal(self):
        QMessageBox.information(self, self.tr("no_updates_title"), self.tr("no_updates_msg"))

    def restart_server(self):
        self.controller.toggle_server_state()

    def quit_application(self):
        self.controller.stop_server()
        self.tray_manager.hide()
        QApplication.instance().quit()

    def toggle_window_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def showEvent(self, event):
        super().showEvent(event)
        self.tray_manager.update_toggle_action_text(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.tray_manager.update_toggle_action_text(False)

    def closeEvent(self, event: QCloseEvent):
        if self.minimize_to_tray:
            self.hide()
            event.ignore()
            return

        reply = QMessageBox.question(self, self.tr("confirm_exit_title"),
            self.tr("confirm_exit_text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.quit_application()
            event.accept()
        else:
            event.ignore()