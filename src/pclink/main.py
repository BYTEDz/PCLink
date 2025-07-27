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
from typing import Optional

import qrcode
import requests
from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QColor, QIcon,
                           QPainter, QPixmap, QDesktopServices)
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


class PCLinkSingleton:
    """System-wide singleton pattern to ensure only one PCLink instance runs."""
    _instance = None
    _initialized = False
    _lock_file = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.app_instance = None
            self.tray_manager = None
            self._initialized = True

    def acquire_lock(self):
        """Acquire system-wide lock to prevent multiple instances."""
        try:
            import tempfile
            if sys.platform != "win32":
                import fcntl
            
            if sys.platform == "win32":
                # Windows: Use named mutex
                import ctypes
                from ctypes import wintypes
                
                kernel32 = ctypes.windll.kernel32
                mutex_name = "Global\\PCLink_SingleInstance_Mutex"
                
                # Try to create or open the mutex
                self._mutex_handle = kernel32.CreateMutexW(None, True, mutex_name)
                
                if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                    log.warning("Another PCLink instance is already running")
                    return False
                
                log.info("Acquired system-wide lock successfully")
                return True
            else:
                # Unix-like: Use file lock
                lock_file_path = Path(tempfile.gettempdir()) / "pclink.lock"
                self._lock_file = open(lock_file_path, 'w')
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock_file.write(str(os.getpid()))
                self._lock_file.flush()
                log.info("Acquired file lock successfully")
                return True
                
        except Exception as e:
            log.warning(f"Failed to acquire system lock: {e}")
            return False

    def release_lock(self):
        """Release system-wide lock."""
        try:
            if sys.platform == "win32":
                if hasattr(self, '_mutex_handle'):
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    kernel32.ReleaseMutex(self._mutex_handle)
                    kernel32.CloseHandle(self._mutex_handle)
            else:
                if self._lock_file:
                    self._lock_file.close()
                    self._lock_file = None
        except Exception as e:
            log.warning(f"Failed to release system lock: {e}")

    def set_instance(self, instance):
        """Set the current app instance."""
        self.app_instance = instance

    def get_instance(self):
        """Get the current app instance."""
        return self.app_instance

    def set_tray_manager(self, tray_manager):
        """Set the tray manager."""
        self.tray_manager = tray_manager

    def get_tray_manager(self):
        """Get the tray manager."""
        return self.tray_manager


class UnifiedTrayManager(QObject):
    """Unified tray icon manager for both headless and GUI modes."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray_icon = None
        self.parent_app = None
        self.menu_actions = {}
        
    def setup_tray_icon(self, parent_app, mode="headless"):
        """Setup tray icon with unified menu system."""
        self.parent_app = parent_app
        
        try:
            self.tray_icon = QSystemTrayIcon(_create_app_icon(), self)
            self.tray_icon.setToolTip(f"PCLink v{__version__}")
            
            # Create unified menu
            menu = QMenu()
            self._create_unified_menu(menu, mode)
            
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.activated.connect(self._on_tray_activated)
            self.tray_icon.show()
            
            log.info(f"Tray icon setup complete for {mode} mode")
            return True
            
        except Exception as e:
            log.error(f"Failed to setup tray icon: {e}", exc_info=True)
            return False
    
    def _create_unified_menu(self, menu, mode):
        """Create unified tray menu for both modes."""
        # Server status (for headless mode)
        if mode == "headless" and hasattr(self.parent_app, 'server_status'):
            status_text = f"Status: {self.parent_app.server_status.capitalize()}"
            self.menu_actions['status'] = menu.addAction(status_text)
            self.menu_actions['status'].setEnabled(False)
            menu.addSeparator()
        
        # Show/Hide GUI
        if mode == "headless":
            self.menu_actions['show_gui'] = menu.addAction("Show PCLink GUI")
            self.menu_actions['show_gui'].triggered.connect(self._show_gui)
        else:
            self.menu_actions['toggle_window'] = menu.addAction("Show PCLink")
            self.menu_actions['toggle_window'].triggered.connect(self._toggle_window)
        
        # Server controls (if applicable)
        if hasattr(self.parent_app, 'restart_server'):
            self.menu_actions['restart'] = menu.addAction("Restart Server")
            self.menu_actions['restart'].triggered.connect(self._restart_server)
        
        menu.addSeparator()
        
        # Debug and utility options
        self.menu_actions['open_logs'] = menu.addAction("Open Log File")
        self.menu_actions['open_logs'].triggered.connect(self._open_log_file)
        self.menu_actions['open_config'] = menu.addAction("Open Config Folder")
        self.menu_actions['open_config'].triggered.connect(self._open_config_folder)
        
        # Update check
        if hasattr(self.parent_app, 'check_for_updates_headless'):
            self.menu_actions['check_updates'] = menu.addAction("Check for Updates")
            self.menu_actions['check_updates'].triggered.connect(self._check_updates)
        
        menu.addSeparator()
        
        # Exit
        self.menu_actions['exit'] = menu.addAction("Exit PCLink")
        self.menu_actions['exit'].triggered.connect(self._quit_application)
    
    def _on_tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Single left-click
            log.info(f"Tray icon clicked, reason: {reason}")
            try:
                # Check if we're in GUI mode (MainWindow instance)
                if hasattr(self.parent_app, '__class__') and self.parent_app.__class__.__name__ == 'MainWindow':
                    log.info("Tray click: GUI mode detected, toggling window")
                    self._toggle_window()
                # Check if we're in headless mode with show_main_gui method
                elif hasattr(self.parent_app, 'show_main_gui'):
                    log.info("Tray click: Headless mode detected, showing GUI")
                    self._show_gui()
                else:
                    log.warning("Tray click: Unknown parent app type, attempting fallback")
                    # Fallback: try both methods
                    if hasattr(self.parent_app, 'main_window') and self.parent_app.main_window:
                        self._toggle_window()
                    else:
                        self._show_gui()
            except Exception as e:
                log.error(f"Error handling tray activation: {e}", exc_info=True)
    
    def _show_gui(self):
        """Show GUI from headless mode."""
        try:
            log.info("Tray menu: Show GUI requested")
            if hasattr(self.parent_app, 'show_main_gui'):
                log.info("Calling parent_app.show_main_gui()")
                self.parent_app.show_main_gui()
            elif hasattr(self.parent_app, 'headless_app') and hasattr(self.parent_app.headless_app, 'show_main_gui'):
                log.info("Calling parent_app.headless_app.show_main_gui()")
                self.parent_app.headless_app.show_main_gui()
            elif hasattr(self.parent_app, '__class__') and self.parent_app.__class__.__name__ == 'MainWindow':
                log.info("GUI already visible, just showing window")
                self._toggle_window()
            else:
                log.error("parent_app does not have show_main_gui method")
                self._show_error_message("Error", "Cannot show GUI - method not available")
        except Exception as e:
            log.error(f"Failed to show GUI: {e}", exc_info=True)
            self._show_error_message("Failed to show GUI", str(e))
    
    def _toggle_window(self):
        """Toggle window visibility in GUI mode."""
        try:
            log.info("Tray menu: Toggle window requested")
            
            # Handle different parent app types
            window = None
            if hasattr(self.parent_app, 'main_window') and self.parent_app.main_window:
                window = self.parent_app.main_window
            elif hasattr(self.parent_app, '__class__') and self.parent_app.__class__.__name__ == 'MainWindow':
                window = self.parent_app
            
            if window:
                log.info(f"Window found, current state: visible={window.isVisible()}, minimized={window.isMinimized()}")
                
                # Find the correct menu action (could be 'show_gui' or 'toggle_window')
                action_key = 'show_gui' if 'show_gui' in self.menu_actions else 'toggle_window'
                
                if window.isVisible() and not window.isMinimized():
                    log.info("Hiding window")
                    window.hide()
                    if action_key in self.menu_actions:
                        self.menu_actions[action_key].setText("Show PCLink")
                else:
                    log.info("Showing window")
                    if window.isMinimized():
                        window.showNormal()
                    else:
                        window.show()
                    window.activateWindow()
                    if action_key in self.menu_actions:
                        self.menu_actions[action_key].setText("Hide PCLink")
            else:
                log.error("No window found to toggle")
                self._show_error_message("Error", "No window available to toggle")
        except Exception as e:
            log.error(f"Failed to toggle window: {e}", exc_info=True)
    
    def _restart_server(self):
        """Restart server."""
        try:
            log.info("Tray menu: Restart server requested")
            if hasattr(self.parent_app, 'restart_server'):
                log.info("Calling parent_app.restart_server()")
                self.parent_app.restart_server()
            elif hasattr(self.parent_app, 'controller') and hasattr(self.parent_app.controller, 'restart_server'):
                log.info("Calling parent_app.controller.restart_server()")
                self.parent_app.controller.restart_server()
            else:
                log.error("No restart_server method found")
                self._show_error_message("Error", "Restart server method not available")
        except Exception as e:
            log.error(f"Failed to restart server: {e}", exc_info=True)
            self._show_error_message("Failed to restart server", str(e))
    
    def _open_log_file(self):
        """Open the log file for debugging."""
        try:
            log.info("Tray menu: Open log file requested")
            log_file = constants.APP_DATA_PATH / "pclink.log"
            if log_file.exists():
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file)))
                log.info("Opened log file for user")
            else:
                log.warning(f"Log file not found at: {log_file}")
                self._show_error_message("Log file not found", f"Log file does not exist at: {log_file}")
        except Exception as e:
            log.error(f"Failed to open log file: {e}", exc_info=True)
            self._show_error_message("Failed to open log file", str(e))
    
    def _open_config_folder(self):
        """Open the config folder."""
        try:
            log.info("Tray menu: Open config folder requested")
            config_folder = constants.APP_DATA_PATH
            if config_folder.exists():
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_folder)))
                log.info("Opened config folder for user")
            else:
                log.warning(f"Config folder not found at: {config_folder}")
                self._show_error_message("Config folder not found", f"Config folder does not exist at: {config_folder}")
        except Exception as e:
            log.error(f"Failed to open config folder: {e}", exc_info=True)
            self._show_error_message("Failed to open config folder", str(e))
    
    def _check_updates(self):
        """Check for updates."""
        try:
            log.info("Tray menu: Check updates requested")
            if hasattr(self.parent_app, 'check_for_updates_headless'):
                log.info("Calling parent_app.check_for_updates_headless()")
                self.parent_app.check_for_updates_headless()
            elif hasattr(self.parent_app, 'check_for_updates_manual'):
                log.info("Calling parent_app.check_for_updates_manual()")
                self.parent_app.check_for_updates_manual()
            else:
                log.error("No update check method found")
                self._show_error_message("Error", "Update check method not available")
        except Exception as e:
            log.error(f"Failed to check updates: {e}", exc_info=True)
            self._show_error_message("Failed to check updates", str(e))
    
    def _quit_application(self):
        """Quit the application."""
        try:
            log.info("Tray menu: Quit application requested")
            if hasattr(self.parent_app, 'quit_application'):
                log.info("Calling parent_app.quit_application()")
                self.parent_app.quit_application()
            else:
                log.info("Using QApplication.quit() fallback")
                QApplication.quit()
        except Exception as e:
            log.error(f"Failed to quit application: {e}", exc_info=True)
            QApplication.quit()
    
    def _show_error_message(self, title, message):
        """Show error message via tray notification."""
        if self.tray_icon:
            try:
                self.tray_icon.showMessage(title, message, QSystemTrayIcon.Critical, 5000)
            except Exception as e:
                log.error(f"Failed to show tray message: {e}")
    
    def update_status(self, status):
        """Update server status in tray menu."""
        if 'status' in self.menu_actions:
            self.menu_actions['status'].setText(f"Status: {status.capitalize()}")
    
    def hide(self):
        """Hide tray icon."""
        if self.tray_icon:
            self.tray_icon.hide()
    
    def show(self):
        """Show tray icon."""
        if self.tray_icon:
            self.tray_icon.show()


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
    """Singleton headless application manager with improved error handling."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Register with singleton
        singleton = PCLinkSingleton()
        singleton.set_instance(self)
        
        # Initialize state
        self.controller = None
        self.server_status = "starting"
        self.main_window = None
        self.dummy_window = self._create_dummy_window()
        
        # Initialize components with error handling
        self._initialize_components()
    
    def _create_dummy_window(self):
        """Create a dummy window object for headless mode."""
        class DummyWindow:
            def __init__(self):
                self.is_server_running = False
                self.server_check_timer = None
                self.device_prune_timer = None
                self.api_key = None
                self.api_port = None
                self.use_https = None
                self.allow_insecure_shell = None
                self.ip_address_combo = None
        
        return DummyWindow()
    
    def _initialize_components(self):
        """Initialize all components with comprehensive error handling."""
        try:
            log.info("Initializing HeadlessApp components...")
            
            # Initialize update checker
            self.update_checker = UpdateChecker()
            
            # Load configuration
            self._load_config_and_settings()
            
            # Generate certificates
            generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)
            
            # Create controller
            self.controller = Controller(self.dummy_window)
            
            # Connect device prune timer
            if self.dummy_window.device_prune_timer:
                self.dummy_window.device_prune_timer.timeout.connect(
                    self.controller.prune_and_update_devices
                )
            
            # Create GUI window in background (hidden)
            self._create_background_gui()
            
            # Setup unified tray system
            self._setup_tray_system()
            
            # Start server
            self.start_server()
            
            import os
            process_id = os.getpid()
            log.info(f"HeadlessApp with background GUI initialized successfully (PID: {process_id})")
            
        except Exception as e:
            log.error(f"Failed to initialize HeadlessApp: {e}", exc_info=True)
            self.server_status = "error"
            self._handle_initialization_error(e)
    
    def _handle_initialization_error(self, error):
        """Handle initialization errors gracefully."""
        try:
            # Try to setup tray icon for error reporting
            if not hasattr(self, 'tray_manager') or not self.tray_manager:
                self._setup_tray_system()
            
            # Show error via tray
            if hasattr(self, 'tray_manager') and self.tray_manager:
                self.tray_manager._show_error_message(
                    "PCLink Initialization Error",
                    f"Failed to start: {str(error)[:100]}..."
                )
        except Exception as tray_error:
            log.error(f"Failed to show initialization error: {tray_error}", exc_info=True)
    
    def _create_background_gui(self):
        """Create GUI window in background, hidden and ready to show."""
        try:
            log.info("Creating background GUI window...")
            
            # Create MainWindow but keep it hidden and don't create tray icon
            self.main_window = MainWindow(
                existing_controller=self.controller, 
                from_headless=True, 
                create_tray=False
            )
            
            # Transfer server state to GUI window
            self._transfer_server_state_to_gui()
            
            # Update controller's window reference to GUI window
            self.controller.window = self.main_window
            
            # Note: Don't call connect_signals() here as MainWindow initialization will handle it
            # This prevents duplicate signal connections that cause double pairing dialogs
            
            # Update UI to reflect current server state
            self.controller.update_ui_for_server_state()
            
            # Start device prune timer if server will be running
            if self.dummy_window.device_prune_timer:
                self.main_window.device_prune_timer = self.dummy_window.device_prune_timer
            
            # Keep window hidden initially
            self.main_window.hide()
            
            log.info("Background GUI window created and ready")
            
        except Exception as e:
            log.error(f"Failed to create background GUI: {e}", exc_info=True)
            # Continue without GUI - headless mode will still work
            self.main_window = None
    
    def _transfer_server_state_to_gui(self):
        """Transfer server state from dummy window to GUI window."""
        try:
            self.main_window.is_server_running = self.dummy_window.is_server_running
            self.main_window.api_key = self.dummy_window.api_key
            self.main_window.api_port = self.dummy_window.api_port
            self.main_window.use_https = self.dummy_window.use_https
            self.main_window.allow_insecure_shell = self.dummy_window.allow_insecure_shell
        except Exception as e:
            log.error(f"Failed to transfer server state to GUI: {e}", exc_info=True)
            raise

    def _setup_tray_system(self):
        """Setup unified tray system."""
        try:
            singleton = PCLinkSingleton()
            self.tray_manager = UnifiedTrayManager(self)
            singleton.set_tray_manager(self.tray_manager)
            
            if self.tray_manager.setup_tray_icon(self, mode="headless"):
                log.info("Tray system setup completed")
            else:
                log.warning("Tray system setup failed")
                
        except Exception as e:
            log.error(f"Failed to setup tray system: {e}", exc_info=True)

    def _load_config_and_settings(self):
        """Load configuration and settings with error handling."""
        try:
            # Load and validate API key
            raw_key = load_config_value(constants.API_KEY_FILE, default=str(uuid.uuid4()))
            try:
                self.dummy_window.api_key = validate_api_key(raw_key)
                if self.dummy_window.api_key != raw_key:
                    save_config_value(constants.API_KEY_FILE, self.dummy_window.api_key)
            except ValidationError:
                log.warning("Invalid API key found. Generating a new one.")
                self.dummy_window.api_key = str(uuid.uuid4())
                save_config_value(constants.API_KEY_FILE, self.dummy_window.api_key)

            # Load port configuration
            self.dummy_window.api_port = int(load_config_value(
                constants.PORT_FILE, str(constants.DEFAULT_PORT)
            ))

            # Load Qt settings
            settings = QSettings(constants.APP_NAME, "AppGUI")
            self.dummy_window.use_https = settings.value("use_https", True, type=bool)
            self.dummy_window.allow_insecure_shell = settings.value("allow_insecure_shell", False, type=bool)
            self.show_startup_notification = settings.value("show_startup_notification", True, type=bool)
            
            # Initialize server state
            self.dummy_window.is_server_running = False
            
            # Create timers
            self.dummy_window.server_check_timer = QTimer(self)
            self.dummy_window.device_prune_timer = QTimer(self)
            self.dummy_window.device_prune_timer.setInterval(10000)
            
            # Create mock IP combo
            class MockCombo:
                def currentText(self): 
                    return "127.0.0.1"
            self.dummy_window.ip_address_combo = MockCombo()
            
            log.info("Configuration loaded successfully")
            
        except Exception as e:
            log.error(f"Failed to load configuration: {e}", exc_info=True)
            raise

    def update_tray_status(self):
        """Update tray status using unified tray manager."""
        try:
            if hasattr(self, 'tray_manager') and self.tray_manager:
                self.tray_manager.update_status(self.server_status)
                
                # Update tooltip
                status_map = {
                    "starting": "PCLink Server - Starting...",
                    "running": f"PCLink Server - Running on port {self.dummy_window.api_port}",
                    "error": "PCLink Server - Error", 
                    "stopped": "PCLink Server - Stopped",
                }
                tooltip = status_map.get(self.server_status, "PCLink Server")
                if self.tray_manager.tray_icon:
                    self.tray_manager.tray_icon.setToolTip(tooltip)
        except Exception as e:
            log.warning(f"Failed to update tray status: {e}", exc_info=True)

    def start_server(self):
        """Start the server with comprehensive error handling."""
        log.info("Headless mode: Attempting to start server.")
        self.server_status = "starting"
        self.update_tray_status()
        
        if self.controller is None:
            error_msg = "Controller initialization failed"
            log.error(error_msg)
            self.server_status = "error"
            self.update_tray_status()
            self._show_error_notification("PCLink Server Error", error_msg)
            return
            
        try:
            self.controller.start_server()
            self.check_timer = QTimer(self)
            self.check_timer.timeout.connect(self.check_server_status)
            self.check_timer.start(1500)
            log.info("Server start initiated successfully")
            
        except Exception as e:
            error_msg = f"Failed to start server: {str(e)}"
            log.error(error_msg, exc_info=True)
            self.server_status = "error"
            self.update_tray_status()
            self._show_error_notification("PCLink Server Error", error_msg)

    def check_server_status(self):
        """Check server status with error handling."""
        if not self.controller:
            if hasattr(self, 'check_timer'):
                self.check_timer.stop()
            self.on_server_failed()
            return
            
        try:
            if self.controller.uvicorn_server and self.controller.uvicorn_server.started:
                self.on_server_started()
                if hasattr(self, 'check_timer'):
                    self.check_timer.stop()
            elif self.controller.server_thread and not self.controller.server_thread.is_alive():
                self.on_server_failed()
                if hasattr(self, 'check_timer'):
                    self.check_timer.stop()
        except Exception as e:
            log.error(f"Error checking server status: {e}", exc_info=True)
            self.on_server_failed()
            if hasattr(self, 'check_timer'):
                self.check_timer.stop()

    def on_server_started(self):
        """Handle successful server startup."""
        log.info("Server started successfully in headless mode.")
        self.server_status = "running"
        self.dummy_window.is_server_running = True
        
        # Also update the background GUI window if it exists
        if hasattr(self, 'main_window') and self.main_window:
            self.main_window.is_server_running = True
            log.info("Updated background GUI window server state to running")
        
        self.update_tray_status()
        
        # Show GUI window if requested (for normal mode)
        if hasattr(self, 'show_gui_after_start') and self.show_gui_after_start:
            log.info("Server started, now showing GUI window for normal mode")
            QTimer.singleShot(100, self.show_main_gui)  # Small delay to ensure everything is ready
            self.show_gui_after_start = False  # Only show once
        
        if self.show_startup_notification:
            self._show_success_notification("PCLink Server", "Server is running.")

    def on_server_failed(self):
        """Handle server startup failure."""
        log.error("Server failed to start in headless mode.")
        self.server_status = "error"
        self.update_tray_status()
        self._show_error_notification("PCLink Server Error", "Could not start server.")
    
    def _show_success_notification(self, title, message):
        """Show success notification via tray."""
        try:
            if hasattr(self, 'tray_manager') and self.tray_manager and self.tray_manager.tray_icon:
                self.tray_manager.tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 3000)
        except Exception as e:
            log.warning(f"Failed to show success notification: {e}")
    
    def _show_error_notification(self, title, message):
        """Show error notification via tray."""
        try:
            if hasattr(self, 'tray_manager') and self.tray_manager:
                self.tray_manager._show_error_message(title, message)
        except Exception as e:
            log.warning(f"Failed to show error notification: {e}")

    def restart_server(self):
        """Restart server with error handling."""
        log.info("Restarting server from tray menu.")
        try:
            if self.controller is not None:
                self.controller.stop_server()
            self.server_status = "stopped"
            self.update_tray_status()
            QTimer.singleShot(1000, self.start_server)
        except Exception as e:
            log.error(f"Failed to restart server: {e}", exc_info=True)
            self._show_error_notification("Server Restart Error", str(e))

    def show_main_gui(self):
        """Show the background GUI window (instant transition)."""
        import os
        process_id = os.getpid()
        log.info(f"Showing background GUI window (PID: {process_id}) - instant transition")
        try:
            if self.main_window is None:
                log.warning("Background GUI not available, creating new window...")
                self._create_background_gui()
            
            if self.main_window:
                # Update server state in case anything changed
                self._transfer_server_state_to_gui()
                
                # Ensure server state is properly synchronized
                log.info(f"Server state transfer: dummy_window.is_server_running={self.dummy_window.is_server_running}, main_window.is_server_running={self.main_window.is_server_running}")
                
                # Update UI to reflect current server state
                if self.controller:
                    self.controller.update_ui_for_server_state()
                
                # Show the window
                self.main_window.show()
                self.main_window.activateWindow()
                
                # Update tray manager to GUI mode but keep reference to HeadlessApp for show_main_gui
                if hasattr(self, 'tray_manager') and self.tray_manager:
                    # Keep a reference to the headless app for GUI transitions
                    self.main_window.headless_app = self
                    self.tray_manager.parent_app = self.main_window
                
                log.info("Background GUI window shown instantly - no recreation needed")
            else:
                log.error("Failed to show GUI window - background GUI creation failed")
                self._handle_gui_transition_error(Exception("Background GUI not available"))
            
        except Exception as e:
            log.error(f"Failed to show GUI window: {e}", exc_info=True)
            self._handle_gui_transition_error(e)
    

    
    def _handle_gui_transition_error(self, error):
        """Handle GUI transition error with fallback."""
        try:
            self._show_error_notification("GUI Transition Error", str(error))
            
            # Fallback: restart as GUI mode
            if self.controller is not None:
                self.controller.stop_server()
            if hasattr(self, 'tray_manager') and self.tray_manager:
                self.tray_manager.hide()
            QApplication.quit()
            subprocess.Popen([sys.executable] + [arg for arg in sys.argv if arg != "--startup"])
            
        except Exception as fallback_error:
            log.error(f"Fallback transition also failed: {fallback_error}", exc_info=True)



    def check_for_updates_headless(self):
        """Check for updates in headless mode with error handling."""
        try:
            def handle_result(update_info):
                def show_notification():
                    try:
                        if hasattr(self, 'tray_manager') and self.tray_manager and self.tray_manager.tray_icon:
                            if update_info:
                                self.tray_manager.tray_icon.showMessage(
                                    "PCLink Update Available",
                                    f"Version {update_info['version']} is available for download.",
                                    QSystemTrayIcon.Information,
                                    5000
                                )
                            else:
                                self.tray_manager.tray_icon.showMessage(
                                    "PCLink Updates",
                                    "You are running the latest version.",
                                    QSystemTrayIcon.Information,
                                    3000
                                )
                    except Exception as e:
                        log.warning(f"Failed to show update notification: {e}")
                
                QTimer.singleShot(0, show_notification)
            
            if hasattr(self, 'update_checker'):
                self.update_checker.check_for_updates_async(handle_result)
            else:
                log.warning("Update checker not available")
                
        except Exception as e:
            log.error(f"Failed to check for updates: {e}", exc_info=True)

    def quit_application(self):
        """Quit application with proper cleanup."""
        log.info("Shutting down PCLink.")
        try:
            # Stop server
            if self.controller is not None:
                self.controller.stop_server()
            
            # Hide tray icon
            if hasattr(self, 'tray_manager') and self.tray_manager:
                self.tray_manager.hide()
            
            # Close main window if exists
            if hasattr(self, 'main_window') and self.main_window:
                self.main_window.close()
            
            # Quit application
            QApplication.quit()
            
        except Exception as e:
            log.error(f"Error during application shutdown: {e}", exc_info=True)
            # Force quit if normal shutdown fails
            QApplication.quit()


class MainWindow(QMainWindow):
    def __init__(self, existing_controller=None, from_headless=False, create_tray=True):
        super().__init__()
        self.hide()  # Hide window during setup to prevent flicker
        self.from_headless = from_headless
        self.create_tray = create_tray

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
        
        # Use existing controller if provided, otherwise create new one
        if existing_controller:
            self.controller = existing_controller
            self.controller.window = self  # Update controller's window reference
        else:
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

        # Only setup tray icon if requested (not for background GUI)
        if self.create_tray:
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
        self.open_log_action = QAction(self)

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
        self.open_log_action.setText("Open Log File")
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
            log.info(f"QR payload generated: {len(payload_str)} characters")
        except Exception as e:
            log.error(f"Failed to fetch QR payload: {e}")
            self.qr_label.setText(self.tr("qr_error_text"))
            self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return

        # Create QR code with better error correction for mobile scanning
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,  # Medium error correction
            box_size=10,
            border=4,
        )
        qr.add_data(payload_str)
        qr.make(fit=True)
        matrix = qr.get_matrix()

        label_size = self.qr_label.size()
        pixmap = QPixmap(label_size)
        
        # Use white background instead of transparent for better scanning
        pixmap.fill(Qt.GlobalColor.white)

        with QPainter(pixmap) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            module_count = len(matrix)
            if module_count == 0: 
                log.warning("QR code matrix is empty")
                return

            # Calculate module size with padding
            available_size = min(label_size.width(), label_size.height()) - 20  # 20px padding
            module_size = available_size / module_count
            offset_x = (label_size.width() - (module_size * module_count)) / 2
            offset_y = (label_size.height() - (module_size * module_count)) / 2

            # Draw white background for QR code area
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(
                int(offset_x - 10), int(offset_y - 10),
                int(module_size * module_count + 20), int(module_size * module_count + 20)
            )

            # Draw black QR code modules
            painter.setBrush(QColor("#000000"))
            for y, row in enumerate(matrix):
                for x, module in enumerate(row):
                    if module:
                        painter.drawRect(
                            int(offset_x + x * module_size), 
                            int(offset_y + y * module_size),
                            int(module_size) + 1, 
                            int(module_size) + 1,
                        )
        
        self.qr_label.setText("")
        self.qr_label.setPixmap(pixmap)
        log.info("QR code generated successfully")

    def setup_tray_icon(self):
        """Setup tray icon using unified tray manager."""
        try:
            singleton = PCLinkSingleton()
            
            # If coming from headless mode, reuse the tray manager
            if self.from_headless and singleton.get_tray_manager():
                self.tray_manager = singleton.get_tray_manager()
                self.tray_manager.parent_app = self
                # Update menu for GUI mode
                self._update_tray_for_gui_mode()
            else:
                # Create new tray manager for normal GUI startup
                self.tray_manager = UnifiedTrayManager(self)
                singleton.set_tray_manager(self.tray_manager)
                self.tray_manager.setup_tray_icon(self, mode="gui")
                
        except Exception as e:
            log.error(f"Failed to setup tray icon: {e}", exc_info=True)
    
    def _update_tray_for_gui_mode(self):
        """Update tray menu for GUI mode when transitioning from headless."""
        try:
            if self.tray_manager and self.tray_manager.tray_icon:
                # Update existing menu actions
                if 'show_gui' in self.tray_manager.menu_actions:
                    self.tray_manager.menu_actions['show_gui'].setText("Hide PCLink")
                    # Disconnect old signal and connect new one
                    try:
                        self.tray_manager.menu_actions['show_gui'].triggered.disconnect()
                    except:
                        pass  # Ignore if no connections exist
                    self.tray_manager.menu_actions['show_gui'].triggered.connect(self._toggle_window_visibility)
                
                # Update parent app reference for tray manager
                self.tray_manager.parent_app = self
                
                log.info("Tray menu updated for GUI mode")
        except Exception as e:
            log.error(f"Failed to update tray for GUI mode: {e}", exc_info=True)
    
    def _toggle_window_visibility(self):
        """Toggle window visibility."""
        try:
            if self.isVisible() and not self.isMinimized():
                self.hide()
                if 'show_gui' in self.tray_manager.menu_actions:
                    self.tray_manager.menu_actions['show_gui'].setText("Show PCLink")
            else:
                if self.isMinimized():
                    self.showNormal()
                else:
                    self.show()
                self.activateWindow()
                if 'show_gui' in self.tray_manager.menu_actions:
                    self.tray_manager.menu_actions['show_gui'].setText("Hide PCLink")
        except Exception as e:
            log.error(f"Failed to toggle window visibility: {e}", exc_info=True)

    def show_window(self):
        """Toggle window visibility."""
        try:
            if self.isVisible() and not self.isMinimized():
                # Window is visible, so hide it
                self.hide()
            else:
                # Window is hidden or minimized, so show it
                if self.isMinimized():
                    self.showNormal()
                else:
                    self.show()
                self.activateWindow()
            
            # Update tray action text
            self._update_tray_visibility_action()
        except Exception as e:
            log.error(f"Failed to toggle window visibility: {e}", exc_info=True)

    def showEvent(self, event):
        """Override showEvent to update tray menu."""
        super().showEvent(event)
        self._update_tray_visibility_action()

    def hideEvent(self, event):
        """Override hideEvent to update tray menu."""
        super().hideEvent(event)
        self._update_tray_visibility_action()
    
    def _update_tray_visibility_action(self):
        """Update tray menu action text based on window visibility."""
        try:
            if hasattr(self, 'tray_manager') and self.tray_manager:
                if 'show_gui' in self.tray_manager.menu_actions:
                    action = self.tray_manager.menu_actions['show_gui']
                    if self.isVisible() and not self.isMinimized():
                        action.setText("Hide PCLink")
                    else:
                        action.setText("Show PCLink")
        except Exception as e:
            log.warning(f"Failed to update tray visibility action: {e}")

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
                try:
                    self.tray_icon.showMessage(
                        "PCLink Update Available",
                        f"Version {update_info['version']} is available for download.",
                        QSystemTrayIcon.Information,
                        5000
                    )
                except Exception as tray_error:
                    log.warning(f"Failed to show tray notification: {tray_error}")
    
    def handle_no_update_signal(self):
        """Handle no update available signal (runs in main thread)."""
        QMessageBox.information(
            self,
            self.tr("no_updates_title"),
            self.tr("no_updates_msg")
        )

    def restart_server(self):
        """Restart server from GUI mode."""
        try:
            log.info("Restarting server from GUI mode")
            if self.controller:
                self.controller.toggle_server_state()
            else:
                log.error("No controller available for server restart")
        except Exception as e:
            log.error(f"Failed to restart server from GUI: {e}", exc_info=True)

    def quit_application(self):
        log.info("Shutting down PCLink from GUI.")
        self.controller.stop_server()
        if hasattr(self, 'tray_manager') and self.tray_manager:
            self.tray_manager.hide()
        elif self.tray_icon: 
            self.tray_icon.hide()
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

        # Enhanced startup mode detection for PyInstaller compatibility
        is_startup_mode = detect_startup_mode()
        
        # Log startup information for debugging
        if getattr(sys, "frozen", False):
            log.info(f"Running as PyInstaller executable: {sys.executable}")
            log.info(f"Command line arguments: {sys.argv}")
        
        # Check for existing instance (system-wide singleton pattern)
        singleton = PCLinkSingleton()
        
        if not singleton.acquire_lock():
            log.warning("Another PCLink instance is already running, exiting")
            if not is_startup_mode:
                # Try to show existing instance (if possible)
                try:
                    QMessageBox.information(None, "PCLink", "PCLink is already running. Check the system tray.")
                except:
                    pass
            return 0
        
        # Always create HeadlessApp for unified tray system and background GUI
        main_component = HeadlessApp()
        singleton.set_instance(main_component)
        
        # Store whether to show GUI after server starts
        main_component.show_gui_after_start = not is_startup_mode

        log.info(f"PCLink started {'in headless mode' if is_startup_mode else 'with GUI'}.")
        
        try:
            exit_code = app.exec()
            log.info(f"Application exiting with code {exit_code}.")
            return exit_code
        finally:
            # Always release the system lock when exiting
            singleton.release_lock()

    except Exception as e:
        log.critical("A fatal error occurred during application startup.", exc_info=True)
        
        # For PyInstaller executables, also try to show a message box
        try:
            QMessageBox.critical(None, "Fatal Error", f"PCLink failed to start:\n{e}")
        except:
            # If Qt fails, at least log to a file
            try:
                error_file = Path.home() / "AppData" / "Roaming" / "PCLink" / "startup_error.log"
                error_file.parent.mkdir(parents=True, exist_ok=True)
                with open(error_file, "a", encoding="utf-8") as f:
                    import datetime
                    f.write(f"\n{datetime.datetime.now()}: PCLink startup failed: {e}\n")
            except:
                pass
        
        return 1

def detect_startup_mode():
    """Enhanced startup mode detection for better PyInstaller compatibility."""
    # Check command line arguments
    if "--startup" in sys.argv:
        return True
    
    # For PyInstaller executables, also check if we're being run from Windows startup
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        try:
            # Check if the current process was started by Windows (common startup scenario)
            import psutil
            current_process = psutil.Process()
            parent_process = current_process.parent()
            
            # If parent is explorer.exe or winlogon.exe, likely startup
            if parent_process and parent_process.name().lower() in ['explorer.exe', 'winlogon.exe']:
                log.info("Detected startup via Windows system process")
                return True
                
        except (ImportError, Exception):
            # psutil not available or other error, fall back to other checks
            pass
    
    # Check environment variables that might indicate startup
    import os
    if os.environ.get('PCLINK_STARTUP_MODE') == '1':
        return True
    
    return False


if __name__ == "__main__":
    sys.exit(main())