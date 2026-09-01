# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
import socket
import sys
import threading
import time
import webbrowser

import uvicorn
from fastapi import APIRouter, FastAPI

from ..api_server.api import create_api_app
from ..services.discovery_service import DiscoveryService
from . import constants
from .config import config_manager
from .startup import StartupManager
from .state import connected_devices
from .utils import DummyTty, get_available_ips, get_cert_fingerprint
from .web_auth import web_auth_manager

log = logging.getLogger(__name__)
_ = gettext.gettext


def create_control_api(controller, shutdown_callback):
    """Creates the FastAPI application for the internal control API."""
    control_app = FastAPI()
    router = APIRouter()

    @router.get("/status")
    def get_status():
        return controller.get_status()

    @router.post("/stop")
    def stop_server():
        controller.shutdown()
        return {"message": _("PCLink is shutting down.")}

    @router.post("/restart")
    def restart_server():
        controller.restart()
        return {"message": _("PCLink is restarting.")}

    @router.get("/web-url")
    def get_web_url():
        return {"url": controller.get_web_ui_url()}

    @router.get("/qr-data")
    def get_qr_data():
        """Get QR code data for pairing."""
        qr_data = controller.get_qr_data()
        if qr_data:
            return {"qr_data": qr_data}
        return {"error": _("QR data not available")}

    control_app.include_router(router)
    return control_app


class ServerController:
    """Manages the lifecycle, background watchdog, and self-healing of all PCLink server components."""

    def __init__(self, shutdown_callback=None):
        self.main_api_server = None
        self.main_api_thread = None
        self.control_api_server = None
        self.control_api_thread = None
        self.discovery_service = None
        self.mobile_api_enabled = False
        self._shutdown_callback = shutdown_callback
        self.status = "stopped"
        self.start_time = time.time()

        self._watchdog_thread = None
        self._watchdog_running = False

        self.startup_manager = StartupManager()
        self._sync_startup_config()

    def _sync_startup_config(self):
        """Ensure config.json matches OS startup state."""
        try:
            is_enabled_os = self.startup_manager.is_enabled()
            if config_manager.get("auto_start") != is_enabled_os:
                log.info(f"Syncing auto_start config with OS state: {is_enabled_os}")
                config_manager.set("auto_start", is_enabled_os)
        except Exception as e:
            log.warning(f"Failed to sync startup config: {e}")

    def handle_startup_change(self, enable: bool):
        """Called by API or CLI to toggle startup at OS level."""
        success = False
        if enable:
            success = self.startup_manager.enable()
        else:
            success = self.startup_manager.disable()

        if success:
            config_manager.set("auto_start", enable)
            return True
        else:
            raise Exception(_("Failed to change startup settings in Operating System"))

    def get_status(self):
        return {
            "status": self.status,
            "port": self.get_port(),
            "mobile_api_enabled": self.mobile_api_enabled,
        }

    def get_port(self):
        return config_manager.get("server_port")

    def get_web_ui_url(self):
        return f"https://localhost:{self.get_port()}/"

    def get_qr_data(self):
        """Get QR code data as a JSON string for CLI display."""
        try:
            import json

            fingerprint = get_cert_fingerprint(constants.CERT_FILE)
            available_ips = get_available_ips()
            primary_ip = available_ips[0] if available_ips else "127.0.0.1"

            payload = {
                "protocol": "https",
                "ip": primary_ip,
                "port": self.get_port(),
                "certFingerprint": fingerprint,
            }
            return json.dumps(payload)
        except Exception as e:
            log.error(f"Failed to generate QR data: {e}")
            return None

    def start(self):
        self.status = "starting"

        control_app = create_control_api(self, self.shutdown)
        self.control_api_thread = threading.Thread(
            target=self._run_control_server, args=(control_app,), daemon=True
        )
        self.control_api_thread.start()

        self.main_api_thread = threading.Thread(
            target=self._run_main_server, daemon=True
        )
        self.main_api_thread.start()

        if web_auth_manager.is_setup_completed():
            self.activate_secure_mode()
        else:
            log.warning(
                "WebUI setup not complete. Mobile API and discovery are disabled."
            )

        self._start_watchdog()
        self.status = "running"
        log.info("ServerController started successfully.")

    def _start_watchdog(self):
        """Starts the background self-healing watchdog thread."""
        if not self._watchdog_running:
            self._watchdog_running = True
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True, name="pclink-watchdog"
            )
            self._watchdog_thread.start()
            log.info("Self-healing watchdog thread active.")

    def _watchdog_loop(self):
        """Monitors network reachability, discovery beacon status, and performs self-healing."""
        last_reported_status = "healthy"
        last_pressure_log_time = 0

        while self._watchdog_running:
            try:
                time.sleep(15)

                # 1. Health Check: Discovery Beacon Thread
                if self.mobile_api_enabled and self.discovery_service:
                    if not (
                        self.discovery_service._thread
                        and self.discovery_service._thread.is_alive()
                    ):
                        log.warning(
                            _(
                                "Watchdog: Discovery beacon thread died. Restarting discovery service..."
                            )
                        )
                        hostname = socket.gethostname()
                        self.discovery_service = DiscoveryService(
                            self.get_port(), hostname
                        )
                        self.discovery_service.start()

                # 2. Automated Non-Destructive Self-Healing Check
                from ..services.repair_service import repair_service

                analysis = repair_service.detect_instability_causes()
                current_status = analysis.get("overall_status", "healthy")
                now = time.time()

                if current_status in ("warning", "critical"):
                    causes = analysis.get("detected_causes", [])
                    cause_details = (
                        "; ".join(
                            [
                                f"{c.get('title', _('Unknown'))}: {c.get('description', '').rstrip('.')}"
                                for c in causes
                            ]
                        )
                        if causes
                        else _("Unknown cause")
                    )

                    if (
                        current_status != last_reported_status
                        or (now - last_pressure_log_time) > 300
                    ):
                        log.warning(
                            _(
                                "Watchdog: Server pressure detected [{status}]. Cause(s): {causes}. Initiating auto-heal..."
                            ).format(
                                status=current_status.upper(),
                                causes=cause_details,
                            )
                        )
                        last_pressure_log_time = now
                        last_reported_status = current_status

                        repair_service.auto_heal()
                else:
                    if last_reported_status in ("warning", "critical"):
                        log.info(
                            _(
                                "Watchdog: Server pressure resolved. System status is back to normal."
                            )
                        )
                    last_reported_status = "healthy"

            except Exception as e:
                log.debug(f"Watchdog loop iteration exception: {e}")

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

    def start_server(self):
        self.start_mobile_api()

    def stop_server(self):
        self.stop_mobile_api()

    def stop_server_completely(self):
        self.shutdown()

    def restart(self):
        log.info("Restarting PCLink server...")
        self.stop_services()
        time.sleep(1)
        self.start()

    def stop_services(self):
        self.status = "stopping"
        self._watchdog_running = False
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
        if sys.stdout is None:
            sys.stdout = DummyTty()
        if sys.stderr is None:
            sys.stderr = DummyTty()

        app = create_api_app(self, connected_devices)
        app.state.host_port = self.get_port()

        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=self.get_port(),
            log_level="warning",
            ssl_keyfile=str(constants.KEY_FILE),
            ssl_certfile=str(constants.CERT_FILE),
            loop="asyncio",
        )
        self.main_api_server = uvicorn.Server(config)
        self.main_api_server.run()

    def _run_control_server(self, app):
        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=constants.CONTROL_PORT,
            log_level="warning",
            loop="asyncio",
        )
        self.control_api_server = uvicorn.Server(config)
        self.control_api_server.run()
