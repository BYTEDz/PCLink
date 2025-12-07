# src/pclink/core/controller.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import uvicorn

from ..api_server.api import create_api_app
from ..api_server.discovery import DiscoveryService
from . import constants
from .config import config_manager
from .device_manager import device_manager
from .state import connected_devices
from .utils import (DummyTty, get_startup_manager, restart_as_admin,
                    save_config_value)
from .web_auth import web_auth_manager

log = logging.getLogger(__name__)


class Controller:
    """Handles the application's core logic and orchestrates UI interactions."""

    def __init__(self, main_window):
        self.window = main_window
        self.discovery_service = None
        self.uvicorn_server = None
        self.server_thread = None
        self.startup_manager = get_startup_manager()
        self.mobile_api_enabled = False  # Start disabled until setup is complete.
        
        self._sync_startup_state()

    def is_server_running(self):
        return self.uvicorn_server and self.uvicorn_server.started

    def is_server_starting(self):
        return self.server_thread and self.server_thread.is_alive()

    def get_port(self):
        return getattr(self.window, 'api_port', config_manager.get('server_port'))

    def start_server(self):
        """
        Starts the core web server. The mobile API and discovery service are
        only enabled after the initial password setup is complete.
        """
        # Always start the Uvicorn server for the WebUI.
        if not self.is_server_running():
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            log.info("Starting Uvicorn server for WebUI.")
        else:
            log.info("Uvicorn server is already running.")
            
        # Only enable the mobile API (secure mode) if setup is completed.
        if web_auth_manager.is_setup_completed():
            self.activate_secure_mode()
        else:
            log.warning("WebUI setup not complete. Mobile API and discovery are disabled.")
            if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
                self.window.tray_manager.update_server_status("Setup Required")

    def activate_secure_mode(self):
        """Activates the mobile API and discovery service after setup is complete."""
        log.info("Password setup complete. Activating secure mode...")
        self.mobile_api_enabled = True

        if sys.platform.startswith('linux'):
            self._auto_fix_linux_networking()

        if not self.discovery_service:
            hostname = socket.gethostname()
            self.discovery_service = DiscoveryService(self.get_port(), hostname)
            self.discovery_service.start()
            log.info("Discovery service started for mobile API.")

        if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
            self.window.tray_manager.update_server_status("running")
            
        log.info("Mobile API is now enabled.")

    def stop_server(self):
        """Disables the mobile API and discovery, but keeps the WebUI running."""
        if self.discovery_service:
            self.discovery_service.stop()
            self.discovery_service = None
        
        self.mobile_api_enabled = False
        connected_devices.clear()
        
        if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
            self.window.tray_manager.update_server_status("stopped")
        
        log.info("Mobile API server stopped (Web UI remains accessible).")
    
    def stop_server_completely(self):
        """Completely stops the entire Uvicorn server."""
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
        
        if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
            self.window.tray_manager.update_server_status("stopped")

        connected_devices.clear()
        log.info("Server stopped completely.")

    def _run_server(self):
        if sys.stdout is None: sys.stdout = DummyTty()
        if sys.stderr is None: sys.stderr = DummyTty()

        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        try:
            api_key = getattr(self.window, 'api_key', None)
            if api_key is None:
                if constants.API_KEY_FILE.exists():
                    api_key = constants.API_KEY_FILE.read_text().strip()
                else:
                    api_key = str(uuid.uuid4())
                    save_config_value(constants.API_KEY_FILE, api_key)
                    log.info("Generated new API key for first run")
            
            app = create_api_app(
                api_key,
                self, # Pass controller instance
                connected_devices,
                allow_insecure_shell=config_manager.get("allow_insecure_shell")
            )

            app.state.host_port = self.get_port()
            app.state.api_key = api_key
            
            if hasattr(self.window, 'tray_manager'):
                app.state.tray_manager = self.window.tray_manager
            
            is_frozen = getattr(sys, "frozen", False)
            uvicorn_config = {
                "app": app, 
                "host": "0.0.0.0", 
                "port": self.get_port(), 
                "log_level": "warning" if is_frozen else "info",
                "ssl_keyfile": str(constants.KEY_FILE), 
                "ssl_certfile": str(constants.CERT_FILE),
                "access_log": not is_frozen,
                "use_colors": not is_frozen,
                "workers": 1,
                "ws_ping_interval": 20,
                "ws_ping_timeout": 20,
                # Performance optimizations for file uploads
                "timeout_keep_alive": 60,  # Keep connections alive longer
                "h11_max_incomplete_event_size": 64 * 1024 * 1024,  # 64MB for large uploads
            }

            config = uvicorn.Config(**uvicorn_config)
            self.uvicorn_server = uvicorn.Server(config)
            self.uvicorn_server.run()
        except Exception:
            log.critical("Server failed to run", exc_info=True)

    def _prompt_for_server_restart(self):
        if self.is_server_running():
            log.info("Restarting server due to configuration change...")
            self.stop_server()
            
            def delayed_start():
                time.sleep(0.5)
                self.start_server()
            threading.Thread(target=delayed_start, daemon=True).start()

    def handle_startup_change(self, checked: bool):
        try:
            if getattr(sys, "frozen", False):
                app_path = str(Path(sys.executable))
            else:
                app_path = f'"{sys.executable}" -m pclink'
            
            if checked:
                self.startup_manager.add(constants.APP_NAME, app_path)
            else:
                self.startup_manager.remove(constants.APP_NAME)
        except Exception as e:
            log.error(f"Could not modify startup settings: {e}")

    def _sync_startup_state(self):
        try:
            auto_start_enabled = config_manager.get("auto_start", False)
            
            # If auto_start is DISABLED in config, ensure it's removed
            if not auto_start_enabled:
                self.startup_manager.remove(constants.APP_NAME)
                return

            # Only add if enabled in config but missing in system
            is_currently_enabled = self.startup_manager.is_enabled(constants.APP_NAME)
            if auto_start_enabled and not is_currently_enabled:
                if getattr(sys, "frozen", False):
                    app_path = str(Path(sys.executable))
                else:
                    app_path = f'"{sys.executable}" -m pclink'
                
                self.startup_manager.add(constants.APP_NAME, app_path)
                log.info("Startup enabled to match config setting")
                
        except Exception as e:
            log.error(f"Failed to sync startup state: {e}")

    def handle_minimize_change(self, checked: bool):
        config_manager.set("minimize_to_tray", checked)
        self.window.minimize_to_tray = checked

    def handle_allow_insecure_shell_change(self, checked: bool):
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
        log.info("Regenerating API key...")
        new_key = str(uuid.uuid4())
        save_config_value(constants.API_KEY_FILE, new_key)
        if hasattr(self.window, 'api_key'):
            self.window.api_key = new_key
        self._prompt_for_server_restart()

    def change_port_ui(self, new_port: int = None):
        if new_port is None:
            log.warning("Port change requested but no port specified")
            return
        
        if new_port != self.get_port():
            log.info(f"Changing server port to {new_port}")
            config_manager.set("server_port", new_port)
            if hasattr(self.window, 'api_port'):
                self.window.api_port = new_port
            self._prompt_for_server_restart()

    def prune_and_update_devices(self):
        device_manager.prune_devices()

    def handle_check_updates_change(self, checked: bool):
        config_manager.set("check_updates_on_startup", checked)
        self.window.check_updates_on_startup = checked

    def _auto_fix_linux_networking(self):
        try:
            log.info("Auto-fixing Linux networking issues...")
            self._fix_linux_firewall()
            self._fix_linux_permissions()
            self._fix_linux_interfaces()
        except Exception as e:
            log.warning(f"Auto-fix failed, but continuing: {e}")

    def _fix_linux_firewall(self):
        try:
            result = subprocess.run(['which', 'ufw'], capture_output=True)
            if result.returncode == 0:
                result = subprocess.run(['ufw', 'status'], capture_output=True, text=True)
                if result.returncode == 0 and 'Status: active' in result.stdout:
                    if '38099/udp' not in result.stdout:
                        log.info("Adding UFW rule for PCLink discovery...")
                        subprocess.run(['ufw', 'allow', '38099/udp'], capture_output=True)
                    if '38080' not in result.stdout:
                        log.info("Adding UFW rule for PCLink API...")
                        subprocess.run(['ufw', 'allow', '38080:38090/tcp'], capture_output=True)
        except Exception as e:
            log.debug(f"Firewall auto-fix skipped: {e}")

    def _fix_linux_permissions(self):
        try:
            import pwd
            import grp
            try:
                netdev_group = grp.getgrnam('netdev')
                current_user = pwd.getpwuid(os.getuid()).pw_name
                user_groups = [g.gr_name for g in grp.getgrall() if current_user in g.gr_mem]
                if 'netdev' not in user_groups:
                    log.info("User needs to be added to netdev group for better network access")
            except KeyError:
                pass
        except Exception as e:
            log.debug(f"Permission auto-fix skipped: {e}")

    def _fix_linux_interfaces(self):
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                test_sock.bind(('', 38099))
                test_sock.close()
                log.info("Network interface test passed")
            except OSError as e:
                if e.errno == 98:
                    log.info("Discovery port in use (PCLink may already be running)")
                else:
                    log.warning(f"Network binding issue: {e}")
                test_sock.close()
        except Exception as e:
            log.warning(f"Network interface test failed: {e}")

    def show_discovery_troubleshoot(self):
        log.info("Discovery troubleshooting available in web UI settings")

    def open_log_file(self):
        import webbrowser
        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            if os.name == 'nt':
                os.startfile(str(log_file))
            elif os.name == 'posix':
                webbrowser.open(f'file://{log_file}')
        else:
            log.warning(f"Log file does not exist at: {log_file}")
            
    def get_qr_payload(self):
        if not self.is_server_running(): return None
        try:
            import requests
            protocol = "https"
            url = f"{protocol}://127.0.0.1:{self.get_port()}/qr-payload"
            headers = {"x-api-key": getattr(self.window, 'api_key', '')}
            with requests.packages.urllib3.warnings.catch_warnings():
                requests.packages.urllib3.disable_warnings()
                response = requests.get(url, headers=headers, verify=False, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"Failed to fetch QR payload: {e}")
            return None

    def get_qr_data(self):
        """Get QR code data as a JSON string for CLI display."""
        payload = self.get_qr_payload()
        if payload:
            import json
            return json.dumps(payload)
        return None

    def get_web_ui_url(self):
        """Get the Web UI URL."""
        protocol = "https" if self.is_server_running() else "http"
        return f"{protocol}://127.0.0.1:{self.get_port()}/ui/"

    def shutdown(self):
        """Shutdown the entire PCLink application"""
        log.info("Shutting down PCLink application...")
        try:
            self.stop_server_completely()
            if hasattr(self.window, 'tray_manager') and self.window.tray_manager:
                self.window.tray_manager.hide()
            sys.exit(0)
        except Exception as e:
            log.error(f"Error during shutdown: {e}")
            sys.exit(1)