# filename: src/pclink/core/controller.py
import asyncio
import logging
import os
import socket
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import uvicorn

# PCLink is now web-first - Qt components removed

from ..api_server.api import create_api_app, pairing_events, pairing_results
from ..api_server.discovery import DiscoveryService
from . import constants
from .config import config_manager
from .device_manager import device_manager
from .state import emit_device_list_updated, emit_pairing_request, add_device_callback, add_pairing_callback, connected_devices, controller
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
        self.mobile_api_enabled = False  # Controls whether mobile API endpoints are active - start as False
        
        # Sync startup state with config on initialization
        self._sync_startup_state()

    def is_server_running(self):
        return self.uvicorn_server and self.uvicorn_server.started

    def is_server_starting(self):
        return self.server_thread and self.server_thread.is_alive()

    def get_port(self):
        return getattr(self.window, 'api_port', config_manager.get('server_port'))

    def connect_signals(self):
        """Connects GUI element signals to controller methods (Qt mode only)."""
        if self._signals_connected:
            return
        
        w = self.window
        
        # Only connect Qt signals if the elements exist
        if hasattr(w, 'server_toggle_button'):
            w.server_toggle_button.clicked.connect(self.toggle_server_state)
        if hasattr(w, 'copy_ip_btn'):
            w.copy_ip_btn.clicked.connect(lambda: self.copy_to_clipboard(w.ip_address_combo.currentText()))
        if hasattr(w, 'copy_port_btn'):
            w.copy_port_btn.clicked.connect(lambda: self.copy_to_clipboard(w.port_entry.text()))
        if hasattr(w, 'copy_key_btn'):
            w.copy_key_btn.clicked.connect(lambda: self.copy_to_clipboard(w.api_key_entry.text()))
        if hasattr(w, 'ip_address_combo'):
            w.ip_address_combo.currentIndexChanged.connect(w.generate_qr_code)

        # Set up callbacks for device and pairing updates
        if hasattr(w, 'update_device_list_ui'):
            add_device_callback(w.update_device_list_ui)
        add_pairing_callback(self.handle_pairing_request)

        # Connect menu actions if they exist
        if hasattr(w, 'exit_action'):
            w.exit_action.triggered.connect(w.quit_application)
        if hasattr(w, 'restart_admin_action'):
            w.restart_admin_action.triggered.connect(self.handle_restart_as_admin)
        if hasattr(w, 'change_port_action'):
            w.change_port_action.triggered.connect(self.change_port_ui)
        if hasattr(w, 'update_key_action'):
            w.update_key_action.triggered.connect(self.update_api_key_ui)
        if hasattr(w, 'startup_action'):
            w.startup_action.toggled.connect(self.handle_startup_change)
        if hasattr(w, 'minimize_action'):
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

        # Web-only mode - pairing handled via web UI
        log.info(f"Pairing request from '{device_info}' - handled via web UI")
        accepted = True  # Web UI will handle the actual approval/denial
        
        pairing_results[pairing_id] = {"approved": accepted, "user_decided": True}
        log.info(f"Pairing request for '{device_info}' {'accepted' if accepted else 'denied'}.")

        if event := pairing_events.get(pairing_id):
            event.set()

    def start_server(self):
        if hasattr(self.window, "server_toggle_button"):
            self.window.server_toggle_button.setEnabled(False)
            self.window.status_indicator.set_color("#ffc107")

        # Enable mobile API
        self.mobile_api_enabled = True

        # Auto-fix Linux networking issues
        if sys.platform.startswith('linux'):
            self._auto_fix_linux_networking()

        # Start discovery service for mobile devices (always needed for mobile API)
        if not self.discovery_service:
            hostname = socket.gethostname()
            self.discovery_service = DiscoveryService(self.get_port(), hostname)
            self.discovery_service.start()
            log.info("Discovery service started for mobile API")

        # Start server if not already running (only needed in GUI mode)
        if not self.is_server_running():
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            log.info("Starting new server thread")
        else:
            log.info("Server already running, mobile API enabled")

        if hasattr(self.window, "server_check_timer"):
            self.window.server_check_timer.start(100)
        
        # Notify tray of server state change
        if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
            self.window.tray_manager.update_server_status("running")
            
        log.info("Mobile API server started")

    def stop_server(self):
        """Stop the mobile API server while keeping web UI accessible"""
        # Stop discovery service (mobile device discovery)
        if self.discovery_service:
            self.discovery_service.stop()
            self.discovery_service = None
        
        # Disable mobile API endpoints
        self.mobile_api_enabled = False
        
        # Clear connected devices
        connected_devices.clear()
        emit_device_list_updated()
        
        # Update UI state
        if hasattr(self.window, "is_server_running"):
            self.window.is_server_running = False
            self.update_ui_for_server_state()
        
        # Notify tray of server state change
        if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
            self.window.tray_manager.update_server_status("stopped")
        
        log.info("Mobile API server stopped (Web UI remains accessible)")
    
    def stop_server_completely(self):
        """Completely stop both mobile API and web UI server"""
        if self.discovery_service:
            self.discovery_service.stop()
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        
        self.uvicorn_server = None
        self.server_thread = None
        self.discovery_service = None
        self.mobile_api_enabled = False
        
        # Notify tray of server state change
        if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
            self.window.tray_manager.update_server_status("stopped")

        if hasattr(self.window, "is_server_running"):
            self.window.is_server_running = False
            connected_devices.clear()
            emit_device_list_updated()
            self.update_ui_for_server_state()
        log.info("Server stopped completely.")

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

            # Set controller reference for API access
            controller = self
            
            app = create_api_app(
                api_key,
                controller,  # Pass controller instead of signal emitter
                connected_devices,
                allow_insecure_shell=config_manager.get("allow_insecure_shell")
            )

            # The IP from the combo box is primarily for the QR code.
            # In headless mode, we can use a placeholder as the QR code is not visible.
            host_ip_combo = getattr(self.window, 'ip_address_combo', None)
            app.state.host_ip = host_ip_combo.currentText() if host_ip_combo else "0.0.0.0"
            app.state.host_port = self.get_port()
            app.state.api_key = api_key
            
            # Store tray manager reference for system notifications
            if hasattr(self.window, 'tray_manager'):
                app.state.tray_manager = self.window.tray_manager
            
            # Configure uvicorn for frozen builds
            is_frozen = getattr(sys, "frozen", False)
            uvicorn_config = {
                "app": app, 
                "host": "0.0.0.0", 
                "port": self.get_port(), 
                "log_level": "warning" if is_frozen else "info",  # Reduce log noise in exe
                "ssl_keyfile": str(constants.KEY_FILE), 
                "ssl_certfile": str(constants.CERT_FILE),
                "access_log": not is_frozen,  # Disable access log in exe
                "use_colors": not is_frozen,  # Disable colors in exe
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
        """Check if server has started - web-only version"""
        if not self.is_server_starting():
            if hasattr(self.window, 'server_check_timer'):
                self.window.server_check_timer.stop()
            if not self.is_server_running():
                log.error("The server failed to start. See logs for details.")
                if hasattr(self.window, 'is_server_running'):
                    self.window.is_server_running = False
                self.update_ui_for_server_state()
            return
        
        if self.is_server_running():
            if hasattr(self.window, 'server_check_timer'):
                self.window.server_check_timer.stop()
            log.info("Server has started successfully.")
            if hasattr(self.window, 'is_server_running'):
                self.window.is_server_running = True
            self.update_ui_for_server_state()

    def update_ui_for_server_state(self):
        """Update UI state - web-only version with minimal Qt dependencies"""
        w = self.window
        if not hasattr(w, "status_indicator"): 
            return

        is_running = getattr(w, 'is_server_running', False)
        
        # Only update Qt elements if they exist
        if hasattr(w, 'server_toggle_button'):
            w.server_toggle_button.setEnabled(True)
        if hasattr(w, 'status_indicator'):
            w.status_indicator.set_color("#28a745" if is_running else "#6c757d")
        if hasattr(w, 'status_label'):
            w.status_label.setText(w.tr(f"server_{'running' if is_running else 'stopped'}_status"))

        if is_running:
            if hasattr(w, 'protocol_label'):
                w.protocol_label.setText(w.tr("protocol_https_secure"))
            if hasattr(w, 'server_toggle_button'):
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
        """Restart server - web-only version"""
        if hasattr(self.window, 'is_server_running') and self.window.is_server_running:
            log.info("Restarting server due to configuration change...")
            self.stop_server()
            # Use threading instead of QTimer
            import threading
            def delayed_start():
                import time
                time.sleep(0.5)
                self.start_server()
            threading.Thread(target=delayed_start, daemon=True).start()

    def handle_startup_change(self, checked: bool):
        try:
            exe = Path(sys.executable)
            app_path = str(exe)
            if exe.name.lower() == "python.exe":
                 app_path = f'"{exe}" -m pclink'
            
            if checked:
                self.startup_manager.add(constants.APP_NAME, Path(app_path))
            else:
                self.startup_manager.remove(constants.APP_NAME)
        except Exception as e:
            log.error(f"Could not modify startup settings: {e}")

    def _sync_startup_state(self):
        """Sync the actual startup state with the config setting."""
        try:
            auto_start_enabled = config_manager.get("auto_start", False)
            is_currently_enabled = self.startup_manager.is_enabled(constants.APP_NAME)
            
            # If config says enabled but startup is not actually enabled, enable it
            if auto_start_enabled and not is_currently_enabled:
                import sys
                from pathlib import Path
                
                if getattr(sys, "frozen", False):
                    app_path = Path(sys.executable)
                else:
                    app_path = Path(sys.executable)
                
                self.startup_manager.add(constants.APP_NAME, app_path)
                log.info("Startup enabled to match config setting")
                
            # If config says disabled but startup is enabled, disable it
            elif not auto_start_enabled and is_currently_enabled:
                self.startup_manager.remove(constants.APP_NAME)
                log.info("Startup disabled to match config setting")
                
        except Exception as e:
            log.error(f"Failed to sync startup state: {e}")

    def handle_minimize_change(self, checked: bool):
        config_manager.set("minimize_to_tray", checked)
        self.window.minimize_to_tray = checked

    def handle_allow_insecure_shell_change(self, checked: bool):
        """Handle insecure shell setting change - web-only version"""
        if checked:
            log.warning("Insecure shell access enabled - this reduces security!")
        config_manager.set("allow_insecure_shell", checked)
        self._prompt_for_server_restart()

    def handle_startup_notification_change(self, checked: bool):
        config_manager.set("show_startup_notification", checked)

    def handle_restart_as_admin(self):
        self.stop_server()
        restart_as_admin()

    def update_api_key_ui(self):
        """Regenerate API key - web-only version"""
        log.info("Regenerating API key...")
        new_key = str(uuid.uuid4())
        save_config_value(constants.API_KEY_FILE, new_key)
        if hasattr(self.window, 'api_key'):
            self.window.api_key = new_key
        if hasattr(self.window, 'api_key_entry'):
            self.window.api_key_entry.setText(new_key)
        self._prompt_for_server_restart()

    def change_port_ui(self, new_port: int = None):
        """Change server port - web-only version"""
        if new_port is None:
            log.warning("Port change requested but no port specified")
            return
        
        if new_port != self.get_port():
            log.info(f"Changing server port to {new_port}")
            config_manager.set("server_port", new_port)
            if hasattr(self.window, 'api_port'):
                self.window.api_port = new_port
            if hasattr(self.window, 'port_entry'):
                self.window.port_entry.setText(str(new_port))
            self._prompt_for_server_restart()

    def copy_to_clipboard(self, text: str):
        import pyperclip
        pyperclip.copy(text)

    def prune_and_update_devices(self):
        if self.window.is_server_running and device_manager.prune_devices():
            emit_device_list_updated()

    def handle_check_updates_change(self, checked: bool):
        config_manager.set("check_updates_on_startup", checked)
        self.window.check_updates_on_startup = checked

    def _auto_fix_linux_networking(self):
        """Auto-fix common Linux networking issues"""
        try:
            import subprocess
            import os
            
            log.info("Auto-fixing Linux networking issues...")
            
            # Check and fix firewall rules
            self._fix_linux_firewall()
            
            # Ensure user has network permissions
            self._fix_linux_permissions()
            
            # Test and fix network interfaces
            self._fix_linux_interfaces()
            
        except Exception as e:
            log.warning(f"Auto-fix failed, but continuing: {e}")

    def _fix_linux_firewall(self):
        """Fix Linux firewall rules for PCLink"""
        try:
            # Check UFW first
            result = subprocess.run(['which', 'ufw'], capture_output=True)
            if result.returncode == 0:
                # Check if UFW is active
                result = subprocess.run(['ufw', 'status'], capture_output=True, text=True)
                if result.returncode == 0 and 'Status: active' in result.stdout:
                    # Check if PCLink rules exist
                    if '38099/udp' not in result.stdout:
                        log.info("Adding UFW rule for PCLink discovery...")
                        subprocess.run(['ufw', 'allow', '38099/udp'], capture_output=True)
                    if '8000' not in result.stdout:
                        log.info("Adding UFW rule for PCLink API...")
                        subprocess.run(['ufw', 'allow', '8000:8010/tcp'], capture_output=True)
        except Exception as e:
            log.debug(f"Firewall auto-fix skipped: {e}")

    def _fix_linux_permissions(self):
        """Fix Linux user permissions for networking"""
        try:
            import pwd
            import grp
            
            # Check if netdev group exists and add user to it
            try:
                netdev_group = grp.getgrnam('netdev')
                current_user = pwd.getpwuid(os.getuid()).pw_name
                
                # Check if user is in netdev group
                user_groups = [g.gr_name for g in grp.getgrall() if current_user in g.gr_mem]
                if 'netdev' not in user_groups:
                    log.info("User needs to be added to netdev group for better network access")
                    # We can't add user to group without sudo, but we can log it
                    
            except KeyError:
                pass  # netdev group doesn't exist
                
        except Exception as e:
            log.debug(f"Permission auto-fix skipped: {e}")

    def _fix_linux_interfaces(self):
        """Fix Linux network interface issues"""
        try:
            # Test if we can create UDP broadcast socket
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Try to bind to discovery port
            try:
                test_sock.bind(('', 38099))
                test_sock.close()
                log.info("Network interface test passed")
            except OSError as e:
                if e.errno == 98:  # Address in use
                    log.info("Discovery port in use (PCLink may already be running)")
                else:
                    log.warning(f"Network binding issue: {e}")
                test_sock.close()
                
        except Exception as e:
            log.warning(f"Network interface test failed: {e}")

    def show_discovery_troubleshoot(self):
        # Discovery troubleshooting is now handled via web UI
        log.info("Discovery troubleshooting available in web UI settings")

    def open_log_file(self):
        import webbrowser
        import os
        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            # Open log file with default system application
            if os.name == 'nt':  # Windows
                os.startfile(str(log_file))
            elif os.name == 'posix':  # macOS and Linux
                webbrowser.open(f'file://{log_file}')
        else:
            log.warning(f"Log file does not exist at: {log_file}")
            
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

    def shutdown(self):
        """Shutdown the entire PCLink application"""
        log.info("Shutting down PCLink application...")
        
        try:
            # Stop all services
            self.stop_server_completely()
            
            # Close any open resources
            if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
                self.window.tray_manager.hide()
            
            # Exit the application
            import sys
            sys.exit(0)
            
        except Exception as e:
            log.error(f"Error during shutdown: {e}")
            # Force exit if graceful shutdown fails
            import sys
            sys.exit(1)