# src/pclink/headless.py
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
import signal
import sys
import threading
import time

from .core.config import config_manager
from .core.controller import Controller
from .core.system_tray import SystemTrayManager
from .core.update_checker import UpdateChecker

log = logging.getLogger(__name__)


class HeadlessApp:
    """
    Manages the application in headless mode, providing a tray icon for control.
    """
    def __init__(self):
        self.running = True
        self.controller = Controller(self)
        self.update_checker = UpdateChecker()
        self.tray_manager = SystemTrayManager(self)
        self.tray_manager.setup_menu(mode="headless")
        
        # Start the server using the controller's secure startup logic.
        self.controller.start_server()
        
        # Initialize the system tray icon with a retry mechanism for boot scenarios.
        self._init_tray_with_retry()

    def restart_server(self):
        """Restarts the server via the controller."""
        log.info("Restarting server from tray menu.")
        
        def delayed_restart():
            self.controller.stop_server()
            time.sleep(1.0)
            if self.running:
                self.controller.start_server()
        
        threading.Thread(target=delayed_restart, daemon=True).start()

    def open_web_ui(self):
        """Opens the web UI in the default browser."""
        log.info("Opening web UI in browser...")
        import webbrowser
        port = self.controller.get_port()
        web_url = f"https://localhost:{port}/ui/"
        
        try:
            webbrowser.open(web_url)
            self.tray_manager.show_message(
                "PCLink Web UI", 
                f"Opening web interface at {web_url}"
            )
        except Exception as e:
            log.error(f"Failed to open web UI: {e}")
            self.tray_manager.show_message(
                "PCLink Web UI", 
                f"Please open {web_url} in your browser"
            )

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
        self.running = False
        self.controller.stop_server_completely()
        self.tray_manager.hide()
        sys.exit(0)
    
    def shutdown(self):
        """Provides a consistent shutdown method name."""
        self.quit_application()
    
    def _init_tray_with_retry(self):
        """Initializes the system tray with a retry mechanism."""
        max_attempts = 10
        retry_delay = 2  # seconds
        
        def try_init_tray(attempt=1):
            try:
                if self.tray_manager.is_tray_available():
                    self.tray_manager.show()
                    log.info("System tray initialized successfully.")
                    return True
                else:
                    if attempt < max_attempts:
                        log.info(f"System tray not available yet (attempt {attempt}/{max_attempts}), retrying in {retry_delay}s...")
                        threading.Timer(retry_delay, lambda: try_init_tray(attempt + 1)).start()
                    else:
                        log.warning("System tray not available. PCLink is running in the background.")
                        log.info(f"Access PCLink via the web UI: https://localhost:{self.controller.get_port()}/ui/")
                    return False
            except Exception as e:
                if attempt < max_attempts:
                    log.warning(f"Failed to initialize system tray (attempt {attempt}/{max_attempts}): {e}")
                    threading.Timer(retry_delay, lambda: try_init_tray(attempt + 1)).start()
                else:
                    log.error(f"Failed to initialize system tray after {max_attempts} attempts: {e}")
                    log.info("Running without system tray. Use the web UI for control.")
                return False
        
        try_init_tray()
    
    def run(self):
        """Main run loop for the headless application."""
        log.info("Starting PCLink headless application.")
        
        def signal_handler(signum, frame):
            log.info(f"Received signal {signum}, shutting down...")
            self.quit_application()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Keyboard interrupt received, shutting down...")
            self.quit_application()
        
        return 0