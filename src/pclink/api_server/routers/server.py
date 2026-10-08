# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import hmac
import logging
import secrets
import sys
import time
from typing import Any, Dict, List, Optional

from pclink.core.capabilities import resolve_server_capabilities
import psutil
import requests
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ...core import constants
from ...core.config import config_manager
from ...core.extension_manager import ExtensionManager
from ...core.logging import memory_log_handler
from ...core.utils import get_available_ips, get_cert_fingerprint
from ...core.version import __version__
from ...services.discovery_service import DiscoveryService
from ...services.pairing_service import pairing_service
from ...services.transfer_service import (
    DOWNLOAD_SESSION_DIR,
    TEMP_UPLOAD_DIR,
    transfer_service,
)
from ..ws_manager import ui_manager
from .dependencies import WEB_AUTH
from .transfers import cleanup_stale_sessions

log = logging.getLogger(__name__)
_ = gettext.gettext

mgmt_router = APIRouter(tags=["Server Management"])
core_router = APIRouter(tags=["Server Core"])

# Ephemeral physical claim session store with 3-minute TTL
_active_claim_session: Dict[str, Any] = {"secret": None, "expires_at": 0.0}


class QrPayload(BaseModel):
    protocol: str
    ip: str
    port: int
    certFingerprint: Optional[str] = None
    availableIps: List[str] = []
    serverId: Optional[str] = None
    claimSecret: Optional[str] = None
    remoteAccessUrl: Optional[str] = None


class RemoteAccessActivatePayload(BaseModel):
    token: str
    hostname: str
    claim_secret: Optional[str] = None


class AnnouncePayload(BaseModel):
    name: str
    local_ip: Optional[str] = None
    platform: Optional[str] = None
    client_version: Optional[str] = None
    device_id: Optional[str] = None


@mgmt_router.get("/status")
async def server_status(request: Request):
    controller = getattr(request.app.state, "controller", None)
    mobile_api_enabled = (
        getattr(controller, "mobile_api_enabled", False) if controller else False
    )
    ext_manager = getattr(request.app.state, "extension_manager", None)
    is_safe_mode = getattr(ext_manager, "safe_mode", False) if ext_manager else False

    return {
        "status": "running",
        "server_running": mobile_api_enabled,
        "web_ui_running": True,
        "mobile_api_enabled": mobile_api_enabled,
        "version": __version__,
        "safe_mode": is_safe_mode,
        "capabilities": resolve_server_capabilities(),
        "server_id": DiscoveryService.generate_server_id(),
        "port": getattr(request.app.state, "host_port", 38080),
        "platform": sys.platform,
        "start_time": getattr(controller, "start_time", time.time()),
    }


@core_router.get("/heartbeat")
async def heartbeat():
    return {"status": "alive", "timestamp": time.time()}


@core_router.get("/qr-payload", response_model=QrPayload)
async def get_qr_payload(request: Request):
    fingerprint = get_cert_fingerprint(constants.CERT_FILE)
    available_ips = get_available_ips()
    primary_ip = available_ips[0] if available_ips else "127.0.0.1"
    server_id = DiscoveryService.generate_server_id()

    # Generate single-use claim secret valid for 3 minutes
    claim_secret = secrets.token_hex(32)
    _active_claim_session["secret"] = claim_secret
    _active_claim_session["expires_at"] = time.time() + 180.0

    return QrPayload(
        protocol="https",
        ip=primary_ip,
        port=getattr(request.app.state, "host_port", 38080),
        certFingerprint=fingerprint,
        availableIps=available_ips,
        serverId=server_id,
        claimSecret=claim_secret,
        relayUrl=config_manager.get("remote_access_url", ""),
    )


@core_router.post("/relay/activate")
async def activate_remote_access_tunnel(
    request: Request, payload: RemoteAccessActivatePayload
):
    """
    Zero-config out-of-band activation endpoint.
    Accepts EITHER:
    1. Valid authenticated & approved device API Key (Paired Wi-Fi route).
    2. Valid ephemeral physical claim_secret (QR scan route).
    """
    is_authorized = False

    # Route A: Authenticated paired device (LAN auto-discovery or on-demand re-handshake)
    from .dependencies import extract_token

    token = extract_token(request)
    if token:
        from ...core.device_manager import device_manager

        device = device_manager.get_device_by_api_key(token)
        if device and device.is_approved:
            is_authorized = True
            log.info(
                f"Remote Access tunnel activation authorized via paired device '{device.device_name}'"
            )

    # Route B: Physical QR claim secret (Initial pairing route)
    if not is_authorized and payload.claim_secret:
        now = time.time()
        stored_secret = _active_claim_session.get("secret")
        expires_at = _active_claim_session.get("expires_at", 0.0)

        if stored_secret and now <= expires_at:
            if hmac.compare_digest(stored_secret, payload.claim_secret):
                is_authorized = True
                _active_claim_session["secret"] = None
                _active_claim_session["expires_at"] = 0.0
                log.info(
                    "Remote Access tunnel activation authorized via QR claim secret"
                )

    if not is_authorized:
        raise HTTPException(
            status_code=403,
            detail=_(
                "Unauthorized: Valid claim secret or paired device authentication required"
            ),
        )

    from ...services.tunnel_service import tunnel_service

    success = await tunnel_service.activate_with_token(payload.token, payload.hostname)
    if not success:
        raise HTTPException(
            status_code=500, detail=_("Failed to activate tunnel process")
        )

    full_url = f"https://{payload.hostname.replace('https://', '').rstrip('/')}"
    try:
        from ..ws_manager import mobile_manager, ui_manager

        update_msg = {
            "type": "UPDATE_STATE",
            "relay_url": full_url,
            "remote_access_url": full_url,
        }
        asyncio.create_task(mobile_manager.broadcast(update_msg))
        asyncio.create_task(ui_manager.broadcast(update_msg))
    except Exception:
        pass

    return {
        "status": "activated",
        "hostname": payload.hostname,
        "message": _("Remote Access activated successfully"),
    }


@core_router.post("/relay/unlink")
@mgmt_router.post("/ui/relay/unlink")
async def unlink_remote_access_endpoint(request: Request):
    """
    Stops the tunnel and purges saved remote credentials from local configuration.
    Accepts either an active browser session or an authorized paired mobile device.
    """
    from .dependencies import extract_token, verify_web_session

    is_authorized = False

    token = extract_token(request)
    if token:
        from ...core.device_manager import device_manager

        device = device_manager.get_device_by_api_key(token)
        if device and device.is_approved:
            is_authorized = True

    if not is_authorized:
        try:
            if await verify_web_session(request):
                is_authorized = True
        except Exception:
            pass

    if not is_authorized:
        raise HTTPException(status_code=403, detail="Unauthorized")

    from ...services.tunnel_service import tunnel_service

    tunnel_service.unlink_credentials(reason="Explicit client unlink request")

    return {"status": "success", "message": _("Remote Access credentials cleared")}


@mgmt_router.get("/ui/relay/status", dependencies=[WEB_AUTH])
async def get_ui_remote_access_status():
    """Returns runtime telemetry, active URL, token existence, and configuration state of the Remote Access tunnel."""
    from ...services.tunnel_service import tunnel_service

    status = tunnel_service.get_status()
    status["enabled"] = config_manager.get("enable_remote_access", True)
    status["relay_url"] = config_manager.get("remote_access_url", "")
    status["server_port"] = config_manager.get("server_port", 38080)
    status["has_token"] = bool(config_manager.get("remote_access_token", ""))
    return status


@mgmt_router.get("/ui/relay/ping", dependencies=[WEB_AUTH])
async def ping_ui_remote_access():
    """Server-side edge latency probe that avoids browser cross-origin (CORS) blocks."""
    from ...services.tunnel_service import tunnel_service

    if not tunnel_service.is_running():
        return {"status": "offline", "latency_ms": None}

    relay_url = config_manager.get("remote_access_url", "").strip()
    if not relay_url:
        return {"status": "unconfigured", "latency_ms": None}

    clean_url = f"{relay_url.rstrip('/')}/heartbeat"

    def _probe():
        start = time.perf_counter()
        try:
            resp = requests.get(
                clean_url,
                timeout=4.0,
                headers={"User-Agent": "PCLink-Server/1.0"},
            )
            latency = int((time.perf_counter() - start) * 1000)
            return resp.status_code, latency
        except Exception as e:
            log.debug(f"Relay ping probe error: {e}")
            return None, None

    status_code, latency = await asyncio.to_thread(_probe)
    if status_code == 200:
        return {"status": "online", "latency_ms": latency}
    elif status_code == 530:
        return {"status": "paused", "latency_ms": None}
    elif status_code in (404, 410):
        return {"status": "unlinked", "latency_ms": None}
    else:
        # If the tunnel daemon process has confirmed edge connection, report online
        if tunnel_service._tunnel_status == "active":
            return {"status": "online", "latency_ms": None}
        return {"status": "offline", "latency_ms": None}


@mgmt_router.post("/ui/relay/toggle", dependencies=[WEB_AUTH])
async def toggle_ui_remote_access(request: Request):
    """Enables or terminates the Remote Access tunnel process on demand."""
    data = await request.json()
    enabled = bool(data.get("enabled", False))
    config_manager.set("enable_remote_access", enabled)

    controller = getattr(request.app.state, "controller", None)
    if controller:
        if enabled:
            controller.start_relay_tunnel()
        else:
            controller.stop_relay_tunnel()

    return {"status": "success", "enabled": enabled}


@mgmt_router.post("/ui/relay/reconnect", dependencies=[WEB_AUTH])
async def reconnect_ui_remote_access(request: Request):
    """Restarts the tunnel engine and re-verifies ingress."""
    controller = getattr(request.app.state, "controller", None)
    if controller:
        controller.stop_relay_tunnel()
        await asyncio.sleep(1.0)
        controller.start_relay_tunnel()
        return {"status": "success", "message": _("Remote Access reconnect initiated")}
    raise HTTPException(status_code=500, detail=_("Server controller unavailable"))


@core_router.get("/updates/check")
async def check_for_updates():
    """Non-blocking update check with short timeout to prevent event loop stalls on offline networks."""

    def _fetch_release_info():
        return requests.get(
            "https://api.github.com/repos/BYTEDz/pclink/releases/latest",
            timeout=3.0,
            headers={"User-Agent": "PCLink-Server"},
        )

    try:
        response = await asyncio.to_thread(_fetch_release_info)
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
        log.debug(f"Offline or unreachable network during update check: {e}")
        return {"update_available": False, "offline": True, "error": str(e)}


@mgmt_router.post("/notifications/show", dependencies=[WEB_AUTH])
async def show_system_notification(request: Request):
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
            "enable_remote_access": config_manager.get("enable_remote_access", True),
            "remote_access_url": config_manager.get("remote_access_url", ""),
        }
    except Exception as e:
        log.error(f"Failed to load settings: {e}")
        return {"status": "error", "message": str(e)}


@mgmt_router.post("/settings/save", dependencies=[WEB_AUTH])
async def save_server_settings(request: Request):
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
            ext_manager = ExtensionManager()
            if extensions_enabled:
                ext_manager.load_all_extensions()
            else:
                ext_manager.unload_all_extensions()

        if "notifications" in data:
            current_notifications = config_manager.get("notifications", {}).copy()
            current_notifications.update(data["notifications"])
            config_manager.set("notifications", current_notifications)

        if "theme" in data:
            config_manager.set("theme", data["theme"])

        if "server_port" in data:
            config_manager.set("server_port", data["server_port"])

        if "bridge_enabled" in data:
            config_manager.set("bridge_enabled", data["bridge_enabled"])

        if "enable_remote_access" in data:
            config_manager.set("enable_remote_access", data["enable_remote_access"])

        log.info(f"Server settings updated: {list(data.keys())}")
        return {"status": "success", "message": "Settings saved successfully"}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to save settings: {e}")
        return {"status": "error", "message": str(e)}


@mgmt_router.get("/logs", dependencies=[WEB_AUTH])
async def get_server_logs(
    level: Optional[str] = Query(
        None, description="Exact severity level (INFO, WARNING, ERROR, DEBUG)"
    ),
    min_level: Optional[str] = Query(
        None, description="Minimum severity level threshold"
    ),
    search: Optional[str] = Query(None, description="Search keyword filter"),
    limit: int = Query(200, ge=1, le=1000, description="Max entries to return"),
):
    try:
        entries = memory_log_handler.get_logs(
            level=level, min_level=min_level, search=search, limit=limit
        )

        if entries:
            formatted_text = "\n".join([e["message"] for e in entries])
            return {
                "logs": formatted_text,
                "lines": len(entries),
                "structured": entries,
            }

        if memory_log_handler.buffer:
            filter_desc = level or min_level or "ALL"
            msg = f"--- No log records matching level '{filter_desc}'"
            if search:
                msg += f" and search '{search}'"
            msg += " ---"
            return {"logs": msg, "lines": 0, "structured": []}

        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            filtered = []
            target_lvl = (level or min_level or "").upper()
            search_str = (search or "").lower()

            for line in lines:
                if target_lvl and f" - {target_lvl} " not in line.upper():
                    continue
                if search_str and search_str not in line.lower():
                    continue
                filtered.append(line)

            recent = filtered[-limit:] if len(filtered) > limit else filtered
            if recent:
                return {
                    "logs": "".join(recent),
                    "lines": len(recent),
                    "structured": [],
                }

        filter_desc = level or min_level or "ALL"
        return {
            "logs": f"--- No log records found for filter '{filter_desc}' ---",
            "lines": 0,
            "structured": [],
        }
    except Exception as e:
        return {"logs": f"Error reading logs: {str(e)}", "lines": 0, "structured": []}


@mgmt_router.post("/logs/clear", dependencies=[WEB_AUTH])
async def clear_server_logs():
    try:
        memory_log_handler.buffer.clear()

        log_file = constants.APP_DATA_PATH / "pclink.log"
        if log_file.exists():
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("")
            log.info("Server logs cleared via web UI")
            return {"status": "success", "message": "Logs cleared"}
        return {"status": "success", "message": "In-memory logs cleared"}
    except Exception as e:
        return {"status": "error", "message": f"Error clearing logs: {str(e)}"}


@mgmt_router.post("/server/start", dependencies=[WEB_AUTH])
async def start_server(request: Request):
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
    threshold = config_manager.get("transfer_cleanup_threshold", 7)
    count = await cleanup_stale_sessions(days=threshold)
    return {"status": "success", "cleaned": count}


@mgmt_router.post("/transfers/cleanup/config", dependencies=[WEB_AUTH])
async def update_transfer_cleanup_config(request: Request):
    data = await request.json()
    threshold = data.get("threshold")
    if threshold is None or not isinstance(threshold, int) or threshold < 0:
        raise HTTPException(status_code=400, detail="Invalid threshold")

    config_manager.set("transfer_cleanup_threshold", threshold)
    return {"status": "success", "threshold": threshold}


@mgmt_router.get("/ui/pairing/list")
async def list_pending_pairings(request: Request):
    return {"requests": pairing_service.get_pending_requests()}


@core_router.post("/announce")
async def announce_device(request: Request, payload: AnnouncePayload):
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


@mgmt_router.post("/open-data-dir")
async def open_data_dir(request: Request):
    is_wan_relay = "cf-ray" in request.headers or "cf-connecting-ip" in request.headers
    client_ip = request.client.host if request.client else None

    if is_wan_relay or client_ip not in ("127.0.0.1", "::1", "localhost"):
        log.warning(
            f"BLOCKED: Remote attempt to open data directory from {client_ip} (CF: {is_wan_relay})"
        )
        raise HTTPException(
            status_code=403,
            detail=_("WAN access denied: endpoint is restricted to local host"),
        )

    from ...core.utils import open_directory

    open_directory(constants.APP_DATA_PATH)
    return {"status": "success", "path": str(constants.APP_DATA_PATH)}
