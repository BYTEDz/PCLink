# src/pclink/api_server/routers/server.py
import asyncio
import logging
import socket
import sys
import time
from typing import Optional

import psutil
import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core import constants
from ...core.config import config_manager
from ...core.utils import get_cert_fingerprint
from ...core.version import __version__
from ...services.discovery_service import DiscoveryService
from ...services.transfer_service import (
    DOWNLOAD_SESSION_DIR,
    TEMP_UPLOAD_DIR,
    transfer_service,
)
from ..ws_manager import ui_manager
from .dependencies import WEB_AUTH
from .transfers import cleanup_stale_sessions

log = logging.getLogger(__name__)
mgmt_router = APIRouter(tags=["Server Management"])
core_router = APIRouter(tags=["Server Core"])


class QrPayload(BaseModel):
    protocol: str
    ip: str
    port: int
    certFingerprint: Optional[str] = None


class AnnouncePayload(BaseModel):
    name: str
    local_ip: Optional[str] = None
    platform: Optional[str] = None
    client_version: Optional[str] = None
    device_id: Optional[str] = None


@mgmt_router.get("/status")
async def server_status(request: Request):
    """Retrieve current server state, version, and unique identity."""
    controller = getattr(request.app.state, "controller", None)
    mobile_api_enabled = (
        getattr(controller, "mobile_api_enabled", False) if controller else False
    )

    return {
        "status": "running",
        "server_running": mobile_api_enabled,
        "web_ui_running": True,
        "mobile_api_enabled": mobile_api_enabled,
        "version": __version__,
        "server_id": DiscoveryService.generate_server_id(),
        "port": getattr(request.app.state, "host_port", 38080),
        "platform": sys.platform,
    }


@core_router.get("/heartbeat")
async def heartbeat():
    """Lightweight check to confirm the API is responsive."""
    return {"status": "alive", "timestamp": time.time()}


@core_router.get("/qr-payload", response_model=QrPayload)
async def get_qr_payload(request: Request):
    """Generate the payload for the connection QR code."""
    fingerprint = get_cert_fingerprint(constants.CERT_FILE)

    # Attempt to find the best local IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
    except Exception:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"

    return QrPayload(
        protocol="https",
        ip=local_ip,
        port=getattr(request.app.state, "host_port", 38080),
        certFingerprint=fingerprint,
    )


@core_router.get("/updates/check")
async def check_for_updates():
    """Query the latest version info from GitHub."""
    try:
        response = requests.get(
            "https://api.github.com/repos/BYTEDz/pclink/releases/latest", timeout=10
        )
        if response.status_code == 200:
            release_data = response.json()
            latest_version = release_data.get("tag_name", "").lstrip("v")
            current_version = __version__

            def version_tuple(v):
                return tuple(map(int, (v.split("."))))

            try:
                update_available = version_tuple(latest_version) > version_tuple(
                    current_version
                )
            except ValueError:
                update_available = False

            return {
                "update_available": update_available,
                "current_version": current_version,
                "latest_version": latest_version,
                "download_url": release_data.get("html_url"),
                "release_notes": release_data.get("body", "")[:500],
            }
        return {"update_available": False, "error": "Failed to check for updates"}
    except Exception as e:
        log.error(f"Update check failed: {e}")
        return {"update_available": False, "error": str(e)}


@mgmt_router.post("/notifications/show", dependencies=[WEB_AUTH])
async def show_system_notification(request: Request):
    """Trigger a desktop notification via the tray manager."""
    try:
        data = await request.json()
        title = data.get("title", "PCLink")
        message = data.get("message", "")
        tray_manager = getattr(request.app.state, "tray_manager", None)

        if tray_manager:
            tray_manager.show_notification(title, message)
            return {"status": "success", "message": "Notification sent"}
        return {"status": "error", "message": "System notifications not available"}
    except Exception as e:
        log.error(f"Failed to show system notification: {e}")
        return {"status": "error", "message": str(e)}


@mgmt_router.get("/settings/load", dependencies=[WEB_AUTH])
async def load_server_settings(request: Request):
    """Fetch global configuration for the Web UI."""
    try:
        auto_start_status = config_manager.get("auto_start", False)
        controller = getattr(request.app.state, "controller", None)

        if controller and hasattr(controller, "startup_manager"):
            try:
                real_status = controller.startup_manager.is_enabled()
                if real_status != auto_start_status:
                    config_manager.set("auto_start", real_status)
                    auto_start_status = real_status
            except Exception as e:
                log.error(f"Failed to verify startup status: {e}")

        return {
            "auto_start": auto_start_status,
            "allow_terminal_access": config_manager.get("allow_terminal_access", False),
            "allow_extensions": config_manager.get("allow_extensions", False),
            "allow_insecure_shell": config_manager.get("allow_insecure_shell", False),
            "notifications": config_manager.get("notifications", {}),
            "server_port": config_manager.get("server_port", 38080),
            "theme": config_manager.get("theme", "system"),
        }
    except Exception as e:
        log.error(f"Failed to load settings: {e}")
        return {"status": "error", "message": str(e)}


@mgmt_router.post("/settings/save", dependencies=[WEB_AUTH])
async def save_server_settings(request: Request):
    """Update global configuration and handle side-effects."""
    try:
        data = await request.json()
        controller = getattr(request.app.state, "controller", None)

        if "auto_start" in data:
            auto_start_enabled = data["auto_start"]
            if controller and hasattr(controller, "handle_startup_change"):
                try:
                    controller.handle_startup_change(auto_start_enabled)
                except Exception as e:
                    log.error(f"Failed to update startup setting: {e}")
                    raise HTTPException(status_code=500, detail=str(e))
            else:
                config_manager.set("auto_start", auto_start_enabled)

        if "allow_terminal_access" in data:
            config_manager.set("allow_terminal_access", data["allow_terminal_access"])

        if "allow_extensions" in data:
            extensions_enabled = data["allow_extensions"]
            config_manager.set("allow_extensions", extensions_enabled)
            # Notify extension manager if available
            from ...services.extension_service import extension_service

            if extensions_enabled:
                extension_service.manager.load_all_extensions()
            else:
                extension_service.manager.unload_all_extensions()

        if "notifications" in data:
            current_notifications = config_manager.get("notifications", {}).copy()
            current_notifications.update(data["notifications"])
            config_manager.set("notifications", current_notifications)

        if "theme" in data:
            config_manager.set("theme", data["theme"])

        if "server_port" in data:
            config_manager.set("server_port", data["server_port"])

        log.info(f"Server settings updated: {list(data.keys())}")
        return {"status": "success", "message": "Settings saved successfully"}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to save settings: {e}")
        return {"status": "error", "message": str(e)}


@mgmt_router.get("/logs", dependencies=[WEB_AUTH])
async def get_server_logs():
    """Retrieve the last 100 lines of the application log."""
    try:
        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                recent_lines = lines[-100:] if len(lines) > 100 else lines
                return {"logs": "".join(recent_lines), "lines": len(recent_lines)}
        return {"logs": "No log file found", "lines": 0}
    except Exception as e:
        return {"logs": f"Error reading logs: {str(e)}", "lines": 0}


@mgmt_router.post("/logs/clear", dependencies=[WEB_AUTH])
async def clear_server_logs():
    """Truncate the application log file."""
    try:
        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            with open(log_file, "w") as f:
                f.write("")
            log.info("Server logs cleared via web UI")
            return {"status": "success", "message": "Logs cleared"}
        return {"status": "error", "message": "No log file found"}
    except Exception as e:
        return {"status": "error", "message": f"Error clearing logs: {str(e)}"}


@mgmt_router.post("/server/start", dependencies=[WEB_AUTH])
async def start_server(request: Request):
    """Instruct the controller to activate the server profile."""
    controller = getattr(request.app.state, "controller", None)
    if not controller:
        raise HTTPException(status_code=500, detail="Controller missing")

    try:
        await ui_manager.broadcast({"type": "server_status", "status": "starting"})
        if hasattr(controller, "start_server"):
            controller.start_server()
        await asyncio.sleep(1)
        await ui_manager.broadcast({"type": "server_status", "status": "running"})
        return {"status": "success"}
    except Exception as e:
        log.error(f"Failed to start server: {e}")
        await ui_manager.broadcast({"type": "server_status", "status": "stopped"})
        raise HTTPException(status_code=500, detail=str(e))


@mgmt_router.post("/server/stop", dependencies=[WEB_AUTH])
async def stop_server(request: Request):
    """Instruct the controller to deactivate the server profile."""
    controller = getattr(request.app.state, "controller", None)
    if not controller:
        raise HTTPException(status_code=500, detail="Controller missing")

    try:
        await ui_manager.broadcast({"type": "server_status", "status": "stopping"})
        if hasattr(controller, "stop_server"):
            controller.stop_server()
        await asyncio.sleep(1)
        await ui_manager.broadcast({"type": "server_status", "status": "stopped"})
        return {"status": "success"}
    except Exception as e:
        log.error(f"Failed to stop server: {e}")
        await ui_manager.broadcast({"type": "server_status", "status": "running"})
        raise HTTPException(status_code=500, detail=str(e))


@mgmt_router.post("/server/restart", dependencies=[WEB_AUTH])
async def restart_server(request: Request):
    """Perform a sequenced stop and subsequent start of the server."""
    controller = getattr(request.app.state, "controller", None)
    if not controller:
        raise HTTPException(status_code=500, detail="Controller missing")

    try:
        await ui_manager.broadcast({"type": "server_status", "status": "restarting"})

        async def delayed_restart():
            if hasattr(controller, "stop_server"):
                controller.stop_server()
            await asyncio.sleep(2)
            if hasattr(controller, "start_server"):
                controller.start_server()
            await asyncio.sleep(1)
            await ui_manager.broadcast({"type": "server_status", "status": "running"})

        asyncio.create_task(delayed_restart())
        return {"status": "success", "message": "Server restarting"}
    except Exception as e:
        log.error(f"Failed to restart: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mgmt_router.post("/server/shutdown", dependencies=[WEB_AUTH])
async def shutdown_server(request: Request):
    """Completely terminate the application process."""
    controller = getattr(request.app.state, "controller", None)
    log.warning("Shutdown triggered via web UI")

    try:
        await ui_manager.broadcast({"type": "server_status", "status": "shutting_down"})

        def do_shutdown():
            try:
                if controller and hasattr(controller, "stop_server_completely"):
                    controller.stop_server_completely()
            finally:
                import os

                os._exit(0)

        import threading

        threading.Timer(0.5, do_shutdown).start()
        return {"status": "success", "message": "Shutting down..."}
    except Exception as e:
        log.error(f"Shutdown failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mgmt_router.get("/debug/performance")
async def debug_performance():
    """Retrieve system and transfer performance metrics."""
    process = psutil.Process()
    persisted_uploads = len(list(TEMP_UPLOAD_DIR.glob("*.meta")))
    persisted_downloads = len(list(DOWNLOAD_SESSION_DIR.glob("*.json")))

    return {
        "cpu_percent": process.cpu_percent(),
        "memory_mb": process.memory_info().rss / 1024 / 1024,
        "open_files": len(process.open_files()),
        "connections": len(process.connections()),
        "threads": process.num_threads(),
        "server_time": time.time(),
        "active_uploads_memory": len(transfer_service.active_uploads),
        "active_downloads_memory": len(transfer_service.active_downloads),
        "persisted_uploads_disk": persisted_uploads,
        "persisted_downloads_disk": persisted_downloads,
        "transfer_locks": len(transfer_service.transfer_locks),
    }


@mgmt_router.get("/transfers/cleanup/status", dependencies=[WEB_AUTH])
async def get_transfer_cleanup_status():
    """Analyze stale transfer data that is eligible for cleanup."""
    try:
        threshold = config_manager.get("transfer_cleanup_threshold", 7)
        now = time.time()
        threshold_sec = threshold * 24 * 60 * 60

        stale_up = sum(
            1
            for f in TEMP_UPLOAD_DIR.glob("*.meta")
            if now - f.stat().st_mtime > threshold_sec
        )
        stale_dn = sum(
            1
            for f in DOWNLOAD_SESSION_DIR.glob("*.json")
            if now - f.stat().st_mtime > threshold_sec
        )

        return {
            "threshold_days": threshold,
            "stale_uploads": stale_up,
            "stale_downloads": stale_dn,
            "total_stale": stale_up + stale_dn,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@mgmt_router.post("/transfers/cleanup/execute", dependencies=[WEB_AUTH])
async def execute_transfer_cleanup():
    """Manually trigger cleanup of stale transfer sessions."""
    threshold = config_manager.get("transfer_cleanup_threshold", 7)
    count = await cleanup_stale_sessions(days=threshold)
    return {"status": "success", "cleaned": count}


@mgmt_router.post("/transfers/cleanup/config", dependencies=[WEB_AUTH])
async def update_transfer_cleanup_config(request: Request):
    """Update the aging threshold for transfer cleanup."""
    data = await request.json()
    threshold = data.get("threshold")
    if threshold is None or not isinstance(threshold, int) or threshold < 0:
        raise HTTPException(status_code=400, detail="Invalid threshold")

    config_manager.set("transfer_cleanup_threshold", threshold)
    return {"status": "success", "threshold": threshold}


@mgmt_router.get("/ui/pairing/list")
async def list_pending_pairings(request: Request):
    """List all currently pending pairing requests."""
    results = getattr(request.app.state, "pairing_results", {})
    pending = []
    for pid, data in results.items():
        pending.append(
            {
                "pairing_id": pid,
                "device_name": data.get("device_name"),
                "ip": data.get("ip"),
                "platform": data.get("platform"),
            }
        )
    return {"requests": pending}


@core_router.post("/announce")
async def announce_device(request: Request, payload: AnnouncePayload):
    """Legacy endpoint for mobile devices to announce their presence."""
    connected_devices = getattr(request.app.state, "connected_devices", {})
    client_ip = request.client.host
    is_new = client_ip not in connected_devices

    connected_devices[client_ip] = {
        "last_seen": time.time(),
        "name": payload.name,
        "ip": client_ip,
        "platform": payload.platform,
        "client_version": payload.client_version,
        "device_id": payload.device_id,
    }

    if is_new:
        log.info(f"Device announced: {payload.name} ({client_ip})")

    return {"status": "announced"}
