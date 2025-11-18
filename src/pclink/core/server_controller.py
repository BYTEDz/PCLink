# src/pclink/core/server_controller.py
import logging
import socket
import sys
import threading
import time
import uuid
import webbrowser

import uvicorn

from ..api_server.api import create_api_app
from ..api_server.control_api import create_control_api
from ..api_server.discovery import DiscoveryService
from . import constants
from .config import config_manager
from .state import connected_devices
from .utils import DummyTty
from .web_auth import web_auth_manager

log = logging.getLogger(__name__)

CONTROL_PORT = 9876


class ServerController:
    """Manages the lifecycle of all PCLink server components."""

    def __init__(self, shutdown_callback=None):
        self.main_api_server = None
        self.main_api_thread = None
        self.control_api_server = None
        self.control_api_thread = None
        self.discovery_service = None
        self.mobile_api_enabled = False
        self._shutdown_callback = shutdown_callback
        self.status = "stopped"

    def get_status(self):
        return {"status": self.status, "port": self.get_port(), "mobile_api_enabled": self.mobile_api_enabled}

    def get_port(self):
        return config_manager.get('server_port')

    def get_web_ui_url(self):
        return f'https://localhost:{self.get_port()}/'

    def get_qr_data(self):
        """Get QR code data as a JSON string for CLI display."""
        if not self.main_api_server or not hasattr(self.main_api_server.config.app.state, 'api_key'):
            return None
        try:
            import json
            from .utils import get_cert_fingerprint
            
            api_key = self.main_api_server.config.app.state.api_key
            fingerprint = get_cert_fingerprint(constants.CERT_FILE)
            
            # Get local IP - use the same method as the API endpoint
            try:
                # Create a socket to determine the local IP used for external connections
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                try:
                    local_ip = socket.gethostbyname(socket.gethostname())
                except Exception:
                    local_ip = "127.0.0.1"
            
            payload = {
                "protocol": "https",
                "ip": local_ip,
                "port": self.get_port(),
                "apiKey": api_key,
                "certFingerprint": fingerprint
            }
            return json.dumps(payload)
        except Exception as e:
            log.error(f"Failed to generate QR data: {e}")
            return None

    def start(self):
        self.status = "starting"
        
        control_app = create_control_api(self, self.shutdown)
        self.control_api_thread = threading.Thread(
            target=self._run_control_server,
            args=(control_app,),
            daemon=True
        )
        self.control_api_thread.start()
        
        self.main_api_thread = threading.Thread(target=self._run_main_server, daemon=True)
        self.main_api_thread.start()

        if web_auth_manager.is_setup_completed():
            self.activate_secure_mode()
        else:
            log.warning("WebUI setup not complete. Mobile API and discovery are disabled.")
        
        self.status = "running"
        log.info("ServerController started successfully.")

    def activate_secure_mode(self):
        log.info("Activating secure mode...")
        self.mobile_api_enabled = True
        if not self.discovery_service:
            hostname = socket.gethostname()
            self.discovery_service = DiscoveryService(self.get_port(), hostname)
            self.discovery_service.start()
            log.info("Discovery service started.")
        log.info("Mobile API is now enabled.")

    def stop_mobile_api(self):
        if self.discovery_service:
            self.discovery_service.stop()
            self.discovery_service = None
        self.mobile_api_enabled = False
        connected_devices.clear()
        log.info("Mobile API has been stopped.")

    def start_mobile_api(self):
        if web_auth_manager.is_setup_completed():
            self.activate_secure_mode()

    def restart(self):
        log.info("Restarting PCLink server...")
        self.stop_services()
        time.sleep(1)
        self.start()

    def stop_services(self):
        self.status = "stopping"
        if self.discovery_service:
            self.discovery_service.stop()
        if self.main_api_server:
            self.main_api_server.should_exit = True
        if self.main_api_thread:
            self.main_api_thread.join(timeout=2.0)
        self.main_api_server = None
        self.main_api_thread = None
        self.mobile_api_enabled = False
        connected_devices.clear()
        self.status = "stopped"
        log.info("All main services stopped.")
        
    def shutdown(self):
        log.info("Shutdown requested.")
        self.stop_services()
        if self.control_api_server:
            self.control_api_server.should_exit = True
        if self.control_api_thread:
            self.control_api_thread.join(timeout=2.0)
        
        if self._shutdown_callback:
            self._shutdown_callback()
        log.info("ServerController has shut down.")

    def open_web_ui(self):
        webbrowser.open(self.get_web_ui_url())

    def _run_main_server(self):
        if sys.stdout is None: sys.stdout = DummyTty()
        if sys.stderr is None: sys.stderr = DummyTty()

        if constants.API_KEY_FILE.exists():
            api_key = constants.API_KEY_FILE.read_text().strip()
        else:
            api_key = str(uuid.uuid4())
            constants.API_KEY_FILE.write_text(api_key)
            log.info("Generated new API key for first run")
        
        app = create_api_app(
            api_key,
            self,
            connected_devices,
            allow_insecure_shell=config_manager.get("allow_insecure_shell")
        )
        app.state.host_port = self.get_port()
        app.state.api_key = api_key
        
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=self.get_port(),
            log_level="warning",
            ssl_keyfile=str(constants.KEY_FILE),
            ssl_certfile=str(constants.CERT_FILE),
        )
        self.main_api_server = uvicorn.Server(config)
        self.main_api_server.run()

    def _run_control_server(self, app):
        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=CONTROL_PORT,
            log_level="warning",
        )
        self.control_api_server = uvicorn.Server(config)
        self.control_api_server.run()