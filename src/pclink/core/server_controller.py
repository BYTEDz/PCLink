# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import json
import logging
import socket
import sys
import threading
import time
import traceback
import webbrowser

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse

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

CRASH_TOMBSTONE_FILE = constants.APP_DATA_PATH / ".last_crash.json"


def create_control_api(controller, shutdown_callback):
    """Creates the FastAPI application for the internal control API."""
    control_app = FastAPI()
    router = APIRouter()

    @router.get("/status")
    def get_status():
        return controller.get_status()

    @router.get("/crash-info")
    def get_crash_info():
        return controller.get_crash_info()

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

    @router.get("/relay-status")
    def get_relay_status():
        from ..services.tunnel_service import tunnel_service

        return tunnel_service.get_status()

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

        # Crash diagnostic state
        self.main_server_crashed = False
        self.main_server_error = None
        self.main_server_traceback = None
        self.last_crash_tombstone = self._load_last_crash_tombstone()
        self.tray_manager = None

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

    def _load_last_crash_tombstone(self):
        """Loads historical crash tombstone from disk if present."""
        if CRASH_TOMBSTONE_FILE.exists():
            try:
                return json.loads(CRASH_TOMBSTONE_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                log.debug(f"Failed reading crash tombstone: {e}")
        return None

    def _write_crash_tombstone(self, error: str, tb: str):
        """Persists crash details to disk so CLI and mobile clients can inspect post-mortem."""
        tombstone = {
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": str(error),
            "traceback": str(tb),
            "port": self.get_port(),
        }
        self.last_crash_tombstone = tombstone
        try:
            CRASH_TOMBSTONE_FILE.write_text(
                json.dumps(tombstone, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.error(f"Failed to persist crash tombstone: {e}")

    def _clear_crash_tombstone(self):
        """Cleans up the persisted crash tombstone once stability is confirmed."""
        if CRASH_TOMBSTONE_FILE.exists():
            try:
                CRASH_TOMBSTONE_FILE.unlink()
                self.last_crash_tombstone = None
            except OSError:
                pass

    def get_crash_info(self):
        """Returns active in-memory crash data or disk-persisted post-mortem report."""
        if self.main_server_crashed:
            return {
                "crashed": True,
                "active_crash": True,
                "error": self.main_server_error,
                "traceback": self.main_server_traceback,
                "port": self.get_port(),
            }
        if self.last_crash_tombstone:
            return {
                "crashed": False,
                "active_crash": False,
                "historical_crash": True,
                "error": self.last_crash_tombstone.get("error"),
                "traceback": self.last_crash_tombstone.get("traceback"),
                "timestamp": self.last_crash_tombstone.get("timestamp"),
                "timestamp_iso": self.last_crash_tombstone.get("timestamp_iso"),
            }
        return {"crashed": False, "active_crash": False, "historical_crash": False}

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
        from ..services.tunnel_service import tunnel_service

        tunnel_info = tunnel_service.get_status()
        is_tunnel_active = tunnel_info.get("status") == "active"
        has_token = bool(config_manager.get("remote_access_token", ""))
        is_enabled = config_manager.get("enable_remote_access", True)

        if not has_token:
            relay_state = "unlinked"
        elif not is_enabled:
            relay_state = "paused"
        elif is_tunnel_active:
            relay_state = "active"
        else:
            relay_state = "offline"

        raw_url = config_manager.get("remote_access_url", "")
        # Compact masked hostname (e.g. relay-53c2...bytedz.com)
        masked_host = None
        if raw_url:
            host_clean = (
                raw_url.replace("https://", "").replace("http://", "").rstrip("/")
            )
            if len(host_clean) > 20:
                masked_host = f"{host_clean[:14]}...{host_clean[-10:]}"
            else:
                masked_host = host_clean

        return {
            "status": self.status,
            "port": self.get_port(),
            "mobile_api_enabled": self.mobile_api_enabled,
            "remote_access_state": relay_state,
            "remote_access_host": masked_host,
            "crashed": self.main_server_crashed,
            "error": self.main_server_error,
            "has_tombstone": self.last_crash_tombstone is not None,
        }

    def get_port(self):
        return config_manager.get("server_port", 38080)

    def get_web_ui_url(self):
        return f"https://localhost:{self.get_port()}/"

    def get_qr_data(self):
        """Get QR code data as a JSON string for CLI display."""
        try:
            import json
            import secrets
            from ..api_server.routers.server import _active_claim_session
            from ..services.discovery_service import DiscoveryService

            fingerprint = get_cert_fingerprint(constants.CERT_FILE)
            available_ips = get_available_ips()
            primary_ip = available_ips[0] if available_ips else "127.0.0.1"
            server_id = DiscoveryService.generate_server_id()

            claim_secret = secrets.token_hex(32)
            _active_claim_session["secret"] = claim_secret
            _active_claim_session["expires_at"] = time.time() + 180.0

            payload = {
                "protocol": "https",
                "ip": primary_ip,
                "port": self.get_port(),
                "certFingerprint": fingerprint,
                "availableIps": available_ips,
                "serverId": server_id,
                "claimSecret": claim_secret,
                "relayUrl": config_manager.get("remote_access_url", ""),
            }
            return json.dumps(payload)
        except Exception as e:
            log.error(f"Failed to generate QR data: {e}")
            return None

    def start_relay_tunnel(self):
        """Spawns automated Cloudflare Tunnel if credentials exist."""
        relay_enabled = config_manager.get("enable_remote_access", True)
        stored_token = config_manager.get("remote_access_token", "")

        if not relay_enabled or not stored_token:
            return

        from ..services.tunnel_service import tunnel_service

        def _run_starter():
            asyncio.run(tunnel_service.start())

        threading.Thread(
            target=_run_starter, daemon=True, name="pclink-tunnel-init"
        ).start()

    def stop_relay_tunnel(self):
        """Shuts down active Cloudflare Tunnel process cleanly."""
        from ..services.tunnel_service import tunnel_service

        try:
            tunnel_service.stop()
        except Exception as e:
            log.error(f"Tunnel termination error: {e}")

    def start(self):
        self.status = "starting"
        self.main_server_crashed = False
        self.main_server_error = None
        self.main_server_traceback = None

        control_app = create_control_api(self, self.shutdown)
        self.control_api_thread = threading.Thread(
            target=self._run_control_server, args=(control_app,), daemon=True
        )
        self.control_api_thread.start()

        self.main_api_thread = threading.Thread(
            target=self._run_main_server, daemon=True, name="pclink-main-api"
        )
        self.main_api_thread.start()

        # Pre-warm Cloudflare Tunnel binary asynchronously on startup
        from ..services.tunnel_service import tunnel_service

        tunnel_service.prewarm_binary_background()

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
        """Monitors main thread liveliness, network reachability, discovery, and performs self-healing."""
        last_reported_status = "healthy"
        last_pressure_log_time = 0

        while self._watchdog_running:
            try:
                time.sleep(15)

                # 1. Thread Health Check: Main API Thread Supervisor
                if self.status == "running" and not self.main_server_crashed:
                    if not (self.main_api_thread and self.main_api_thread.is_alive()):
                        crash_msg = (
                            "Main server thread terminated unexpectedly during runtime"
                        )
                        log.error(f"Watchdog: {crash_msg}! Flagging crashed state...")
                        self.main_server_crashed = True
                        self.status = "crashed"
                        self.main_server_error = crash_msg
                        self._write_crash_tombstone(
                            crash_msg, "Thread terminated without clean exit"
                        )

                        if self.tray_manager:
                            self.tray_manager.notify_server_crashed(crash_msg)

                # 2. Health Check: Discovery Beacon Thread
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

                # 3. Automated Non-Destructive Self-Healing Check
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

                # 4. Cloudflare WAN Relay Tunnel Watchdog & Self-Healing
                from ..services.tunnel_service import tunnel_service

                try:
                    asyncio.run(tunnel_service.check_and_heal())
                except Exception as e:
                    log.debug(
                        _("Watchdog: Tunnel check error: {error}").format(error=e)
                    )

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

        self.start_relay_tunnel()
        log.info("Mobile API is now enabled.")

    def stop_mobile_api(self):
        if self.discovery_service:
            self.discovery_service.stop()
            self.discovery_service = None
        self.stop_relay_tunnel()
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
        self.stop_relay_tunnel()
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

        try:
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
            self.main_server_crashed = False
            self.main_server_error = None
            self.main_server_traceback = None
            self.main_api_server.run()
        except Exception as e:
            tb = traceback.format_exc()
            self.main_server_crashed = True
            self.main_server_error = str(e)
            self.main_server_traceback = tb
            self.status = "crashed"
            log.error(f"FATAL: Main server thread crashed: {e}\n{tb}")

            # Persist tombstone for post-mortem analysis across reboots
            self._write_crash_tombstone(str(e), tb)

            if self.tray_manager:
                self.tray_manager.notify_server_crashed(str(e))

            # Spin up emergency recovery web server on port 38080
            self._run_emergency_rescue_server(str(e), tb)

    def _run_emergency_rescue_server(self, error_str: str, tb_str: str):
        """Spins up a lightweight emergency recovery portal on port 38080 with port collision protection."""
        rescue_app = FastAPI()

        @rescue_app.get("/{full_path:path}", response_class=HTMLResponse)
        def rescue_page():
            escaped_error = error_str.replace("<", "&lt;").replace(">", "&gt;")
            escaped_tb = tb_str.replace("<", "&lt;").replace(">", "&gt;")

            html_content = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>PCLink Recovery Center</title>
                <style>
                    body {{ font-family: system-ui, -apple-system, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 24px; display: flex; justify-content: center; }}
                    .container {{ max-width: 800px; width: 100%; }}
                    .card {{ background-color: #1e293b; border-radius: 16px; border: 1px solid #334155; padding: 28px; box-shadow: 0 10px 25px rgba(0,0,0,0.4); }}
                    .badge {{ display: inline-flex; align-items: center; background-color: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); padding: 4px 10px; border-radius: 9999px; font-weight: 700; font-size: 12px; margin-bottom: 16px; }}
                    h1 {{ margin: 0 0 8px 0; font-size: 24px; display: flex; align-items: center; gap: 10px; }}
                    p.desc {{ color: #94a3b8; font-size: 14px; margin: 0 0 20px 0; line-height: 1.5; }}
                    .error-box {{ background-color: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 14px; border-radius: 6px; font-family: monospace; font-size: 13px; color: #fca5a5; margin-bottom: 20px; word-break: break-all; }}
                    details {{ background-color: #0f172a; border-radius: 8px; border: 1px solid #334155; margin-bottom: 24px; }}
                    summary {{ padding: 12px 16px; cursor: pointer; font-size: 13px; font-weight: 600; color: #cbd5e1; user-select: none; }}
                    pre {{ margin: 0; padding: 16px; overflow-x: auto; font-family: monospace; font-size: 12px; color: #94a3b8; line-height: 1.4; border-top: 1px solid #334155; }}
                    .actions {{ display: flex; gap: 12px; }}
                    button.restart {{ background-color: #3b82f6; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 8px; font-size: 14px; }}
                    button.restart:hover {{ background-color: #2563eb; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <div class="badge">SERVER INSTABILITY DETECTED</div>
                        <h1>⚠️ PCLink Server Crash Recovery</h1>
                        <p class="desc">The main server failed during startup or initialization. The background control watchdog intercepted the crash and preserved this recovery portal.</p>

                        <div class="error-box">
                            <strong>Cause:</strong> {escaped_error}
                        </div>

                        <details>
                            <summary>View Complete Python Traceback</summary>
                            <pre>{escaped_tb}</pre>
                        </details>

                        <div class="actions">
                            <button class="restart" onclick="restartServer()">
                                <span>↻</span> Restart PCLink Server
                            </button>
                        </div>
                    </div>
                </div>
                <script>
                    function restartServer() {{
                        const btn = document.querySelector('button.restart');
                        btn.disabled = true;
                        btn.innerText = 'Restarting...';
                        fetch('http://127.0.0.1:{constants.CONTROL_PORT}/restart', {{ method: 'POST' }})
                            .then(() => setTimeout(() => window.location.reload(), 3000))
                            .catch(() => setTimeout(() => window.location.reload(), 3000));
                    }}
                </script>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)

        try:
            config = uvicorn.Config(
                app=rescue_app,
                host="0.0.0.0",
                port=self.get_port(),
                log_level="warning",
                ssl_keyfile=str(constants.KEY_FILE),
                ssl_certfile=str(constants.CERT_FILE),
                loop="asyncio",
            )
            self.main_api_server = uvicorn.Server(config)
            self.main_api_server.run()
        except OSError as bind_err:
            log.critical(
                f"Emergency rescue server failed to bind port {self.get_port()} (Port Conflict): {bind_err}. "
                f"Control API remains online on port {constants.CONTROL_PORT}."
            )

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
