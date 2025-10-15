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
import sys
import time
import threading
import signal

from .core.config import config_manager
from .core.controller import Controller
from .core.system_tray import SystemTrayManager
from .core.setup_guide import should_show_setup_guide, show_setup_guide
from .core.update_checker import UpdateChecker

log = logging.getLogger(__name__)


def run_headless_server():
    """
    Run PCLink server without Qt GUI (fallback for systems with Qt issues).
    """
    import signal
    import time
    from .core.controller import Controller
    
    log.info("Starting PCLink in pure headless mode (no Qt)")
    
    # Create a minimal controller without Qt dependencies
    class MinimalHeadless:
        def __init__(self):
            self.server_status = "stopped"
            
        def update_server_status(self, status):
            self.server_status = status
            log.info(f"Server status: {status}")
            
        def update_device_list(self, devices):
            log.info(f"Connected devices: {len(devices)}")
            for device in devices:
                log.info(f"  - {device.get('name', 'Unknown')}")
    
    headless_app = MinimalHeadless()
    controller = Controller(headless_app)
    
    # Handle shutdown gracefully
    def signal_handler(signum, frame):
        log.info("Received shutdown signal, stopping server...")
        controller.stop_server()
        exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start the server
    controller.start_server()
    
    log.info("PCLink headless server started. Press Ctrl+C to stop.")
    log.info("Note: Install Qt dependencies for full GUI experience:")
    log.info("  sudo apt install libxcb-cursor0 libxcb-xinerama0")
    
    try:
        # Keep the server running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        controller.stop_server()
        return 0


class HeadlessApp:
    """
    Manages the application in headless mode, providing a tray icon for control.
    Web-first version without Qt dependencies.
    """
    def __init__(self):
        self.server_status = "stopped"
        self.main_window = None  # Not used in web-first mode
        self.running = True
        self.check_thread = None
        
        self.controller = Controller(self)
        self.update_checker = UpdateChecker()
        self.tray_manager = SystemTrayManager(self)
        self.tray_manager.setup_menu(mode="headless")
        
        self._server_startup_attempts = 0
        # Check every 1.5 seconds, so 10 attempts give 15 seconds total for startup
        self._MAX_SERVER_STARTUP_ATTEMPTS = 10 
        
        self.start_server()
        
        # Try to show tray, but don't fail if it doesn't work
        # Initialize tray with retry mechanism for boot startup
        self._init_tray_with_retry()

    def start_server(self):
        """Starts the API server and monitors its status."""
        log.info("Headless mode: Attempting to start server.")
        self.server_status = "starting"
        self.tray_manager.update_status(self.server_status)
        self._server_startup_attempts = 0 # Reset attempts
        
        self.controller.start_server()
        
        # Start server status checking in a separate thread
        if self.check_thread and self.check_thread.is_alive():
            return  # Already checking
            
        self.check_thread = threading.Thread(target=self._check_server_loop, daemon=True)
        self.check_thread.start()

    def _check_server_loop(self):
        """Periodically checks if the server has started successfully."""
        while self.running and self._server_startup_attempts < self._MAX_SERVER_STARTUP_ATTEMPTS:
            time.sleep(1.5)  # Check every 1.5 seconds
            self._server_startup_attempts += 1
            
            if self.controller.is_server_running():
                self.on_server_started()
                return
            elif not self.controller.is_server_starting():
                # Server thread is dead
                log.warning(f"Server failed to start after {self._server_startup_attempts} attempts.")
                self.on_server_failed()
                return
                
        if self._server_startup_attempts >= self._MAX_SERVER_STARTUP_ATTEMPTS:
            log.warning(f"Server timed out after {self._server_startup_attempts} attempts.")
            self.on_server_failed()
    
    def check_server_status(self):
        """Legacy method for compatibility"""
        # This method is kept for compatibility but not used in web-first mode
        pass

    def on_server_started(self):
        """Handles successful server startup."""
        log.info("Server started successfully in headless mode.")
        self.server_status = "running"
        self.tray_manager.update_status(self.server_status, self.controller.get_port())
        
        if config_manager.get("show_startup_notification", True):
            try:
                self.tray_manager.show_message("PCLink Server", "Server is running.")
            except Exception as e:
                log.debug(f"Could not show startup notification: {e}")
                # Don't let notification errors crash the server startup

    def on_server_failed(self):
        """Handles server startup failure."""
        log.error("Server failed to start in headless mode.")
        self.server_status = "error"
        self.tray_manager.update_status(self.server_status)
        try:
            self.tray_manager.show_message("PCLink Server Error", "Could not start server.")
        except Exception as e:
            log.debug(f"Could not show error notification: {e}")

    def restart_server(self):
        """Restarts the server."""
        log.info("Restarting server from tray menu.")
        self.controller.stop_server()
        self.server_status = "stopped"
        self.tray_manager.update_status(self.server_status)
        
        # Restart after a short delay
        def delayed_start():
            time.sleep(1.0)
            if self.running:
                self.start_server()
        
        restart_thread = threading.Thread(target=delayed_start, daemon=True)
        restart_thread.start()

    def show_main_gui(self):
        """Web-first mode - open web UI instead of Qt GUI."""
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
        self.controller.stop_server_completely()  # Use complete stop when quitting
        self.tray_manager.hide()
        sys.exit(0)
    
    def shutdown(self):
        """Shutdown method for API compatibility"""
        self.quit_application()
    
    def _init_tray_with_retry(self):
        """Initialize system tray with retry mechanism for boot startup scenarios"""
        max_attempts = 10
        retry_delay = 2  # seconds
        
        def try_init_tray(attempt=1):
            try:
                if self.tray_manager.is_tray_available():
                    self.tray_manager.show()
                    log.info("System tray initialized successfully")
                    
                    if sys.platform.startswith('linux'):
                        log.info("💡 Linux tray tips:")
                        log.info("   • Right-click tray icon for menu")
                        log.info("   • If menu doesn't work, use web UI: https://localhost:8000/ui/")
                        log.info("   • Or use keyboard shortcuts: Ctrl+C to stop")
                    return True
                else:
                    if attempt < max_attempts:
                        log.info(f"System tray not available yet (attempt {attempt}/{max_attempts}), retrying in {retry_delay}s...")
                        threading.Timer(retry_delay, lambda: try_init_tray(attempt + 1)).start()
                    else:
                        log.info("System tray not available - running in background mode")
                        log.info("Access PCLink via web UI: https://localhost:8000/ui/")
                    return False
                    
            except Exception as e:
                if attempt < max_attempts:
                    log.warning(f"Failed to initialize system tray (attempt {attempt}/{max_attempts}): {e}")
                    log.info(f"Retrying in {retry_delay} seconds...")
                    threading.Timer(retry_delay, lambda: try_init_tray(attempt + 1)).start()
                else:
                    log.warning(f"Failed to initialize system tray after {max_attempts} attempts: {e}")
                    log.info("Running without system tray - use web UI for control")
                    
                    if sys.platform.startswith('linux'):
                        log.info("🔧 Linux tray troubleshooting:")
                        log.info("   • Install: sudo apt install gir1.2-appindicator3-0.1")
                        log.info("   • Or use web UI: https://localhost:8000/ui/")
                return False
        
        # Start the first attempt
        try_init_tray()
    
    def run(self):
        """Main run loop for the headless application."""
        log.info("Starting PCLink headless mode...")
        
        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            log.info(f"Received signal {signum}, shutting down...")
            self.quit_application()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            # Keep the main thread alive
            while self.running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            log.info("Keyboard interrupt received, shutting down...")
            self.quit_application()
        
        return 0