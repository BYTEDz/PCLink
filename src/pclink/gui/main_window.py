import json
import logging
import sys
import time
import uuid
import warnings

import qrcode
import requests
from PIL import Image
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QColor, QIcon,
                           QImage, QPixmap)
from PySide6.QtWidgets import (QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QSystemTrayIcon)

from ..core.controller import Controller
from ..core.exceptions import PCLinkError
from ..core.state import connected_devices
from ..core.utils import (API_KEY_FILE, APP_NAME, DEFAULT_PORT, PORT_FILE,
                        generate_self_signed_cert, get_app_data_path,
                        is_startup_enabled, load_or_create_config,
                        resource_path)
from ..core.version import version_info
from .version_dialog import VersionDialog
from .layout import retranslateUi, setupUi
from .localizations import LANGUAGES
from .theme import get_stylesheet

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.platform = sys.platform

        try:
            self._initialize_window()
            self._setup_components()
            self._connect_signals()
            self._start_timers()
        except Exception as e:
            logger.error(f"Failed to initialize main window: {e}")
            self._show_error_message("Initialization Error", str(e))
            raise

    def _initialize_window(self):
        """Initialize window settings and configuration"""
        generate_self_signed_cert()

        self.settings = QSettings(APP_NAME, "AppGUI")
        self.api_key = load_or_create_config(API_KEY_FILE, uuid.uuid4, "API_KEY=")
        self.api_port = int(load_or_create_config(PORT_FILE, DEFAULT_PORT))
        self.load_settings()

        self.is_server_running = False
        self.tray_icon = None

        logger.info("Main window initialized successfully")

    def _setup_components(self):
        """Setup UI components and controller"""
        self.controller = Controller(self)
        self.create_actions()
        self.create_menus()
        setupUi(self)
        self.retranslate_ui()
        self.apply_theme(self.current_theme)
        self.setup_tray_icon()

    def _connect_signals(self):
        """Connect all signals and slots"""
        try:
            self.controller.connect_signals()
        except Exception as e:
            logger.error(f"Failed to connect signals: {e}")
            raise

    def _start_timers(self):
        """Initialize and start application timers"""
        self.device_prune_timer = QTimer(self)
        self.device_prune_timer.setInterval(10000)
        self.device_prune_timer.timeout.connect(
            self.controller.prune_and_update_devices
        )

        self.server_check_timer = QTimer(self)
        self.server_check_timer.timeout.connect(self.controller._check_server_started)

    def _show_error_message(self, title: str, message: str):
        """Show error message to user"""
        try:
            QMessageBox.critical(self, title, message)
        except Exception:
            # Fallback if GUI isn't available
            logger.critical(f"{title}: {message}")

    def tr(self, key, **kwargs):
        return self.translations.get(key, key).format(**kwargs)

    def retranslate_ui(self):
        retranslateUi(self)

    def load_settings(self):
        """Load application settings from QSettings"""
        try:
            self.minimize_to_tray = self.settings.value(
                "minimize_to_tray", True, type=bool
            )
            self.current_theme = self.settings.value("theme", "dark")
            self.current_language = self.settings.value("language", "en")
            self.use_https = self.settings.value("use_https", True, type=bool)
            self.allow_insecure_shell = self.settings.value(
                "allow_insecure_shell", False, type=bool
            )
            self.translations = LANGUAGES.get(self.current_language, LANGUAGES["en"])
            self.is_rtl = self.current_language == "ar"

            logger.info(
                f"Settings loaded: theme={self.current_theme}, lang={self.current_language}"
            )
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            # Use defaults
            self.minimize_to_tray = True
            self.current_theme = "dark"
            self.current_language = "en"
            self.use_https = True
            self.allow_insecure_shell = False
            self.translations = LANGUAGES["en"]
            self.is_rtl = False

    def generate_qr_code(self):
        """Generate QR code for device pairing with improved error handling"""
        try:
            protocol = "https" if self.use_https else "http"
            url = f"{protocol}://127.0.0.1:{self.api_port}/qr-payload"
            headers = {"x-api-key": self.api_key}

            with warnings.catch_warnings():
                warnings.simplefilter(
                    "ignore",
                    requests.packages.urllib3.exceptions.InsecureRequestWarning,
                )
                response = requests.get(url, headers=headers, verify=False, timeout=5)

            response.raise_for_status()
            payload_str = json.dumps(response.json())

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=2,
            )
            qr.add_data(payload_str)
            qr.make(fit=True)

            # Calculate optimal size
            label_size = self.qr_label.size().width()
            num_modules = len(qr.get_matrix())
            optimal_box_size = max(1, label_size // num_modules)
            qr.box_size = optimal_box_size

            # Generate QR code image
            fill_color = (
                (224, 224, 224) if self.current_theme == "dark" else (30, 30, 30)
            )
            pil_img = qr.make_image(
                fill_color=fill_color, back_color=(0, 0, 0, 0)
            ).convert("RGBA")

            q_img = QImage(
                pil_img.tobytes("raw", "RGBA"),
                pil_img.size[0],
                pil_img.size[1],
                QImage.Format.Format_RGBA8888,
            )
            pixmap = QPixmap.fromImage(q_img)
            self.qr_label.setPixmap(pixmap)

            logger.debug("QR code generated successfully")

        except requests.exceptions.Timeout:
            error_msg = "QR Error:\nServer timeout"
            self.qr_label.setText(error_msg)
            logger.warning("QR code generation timed out")
        except requests.exceptions.RequestException as e:
            error_msg = f"QR Error:\nServer not responding\n{str(e)[:50]}..."
            self.qr_label.setText(error_msg)
            logger.error(f"QR code generation failed: {e}")
        except Exception as e:
            error_msg = f"QR Error:\n{str(e)[:50]}..."
            self.qr_label.setText(error_msg)
            logger.error(f"Unexpected error generating QR code: {e}")

    def quit_application(self):
        """Safely shutdown the application"""
        logger.info("Application shutdown initiated")
        try:
            self.controller.stop_server()
            if self.tray_icon:
                self.tray_icon.hide()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            from PySide6.QtWidgets import QApplication

            QApplication.quit()

    def closeEvent(self, event: QCloseEvent):
        """Handle window close event with proper error handling"""
        try:
            if self.minimize_to_tray and self.isVisible():
                event.ignore()
                self.hide()
                logger.debug("Window minimized to tray")
            else:
                self.quit_application()
                event.accept()
                logger.info("Window closed, application exiting")
        except Exception as e:
            logger.error(f"Error handling close event: {e}")
            event.accept()  # Force close on error

    # ... (other methods would be moved here from main.py)
    def create_actions(self):
        """Create menu actions"""
        self.exit_action = QAction(self)
        self.exit_action.triggered.connect(self.quit_application)
        
        self.about_action = QAction("About PCLink", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        
        # Add other actions as needed
        
    def create_menus(self):
        """Create application menus"""
        menu_bar = self.menuBar()
        
        # File menu
        file_menu = menu_bar.addMenu("File")
        file_menu.addAction(self.exit_action)
        
        # Help menu
        help_menu = menu_bar.addMenu("Help")
        help_menu.addAction(self.about_action)
        
    def show_about_dialog(self):
        """Show the version information dialog"""
        dialog = VersionDialog(self)
        dialog.exec()