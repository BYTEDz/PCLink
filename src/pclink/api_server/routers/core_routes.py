# src/pclink/api_server/routers/core_routes.py
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from fastapi import (
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from ...core import constants
from ...core.device_manager import device_manager
from ...core.utils import get_cert_fingerprint
from ...services import input_service
from ...services.transfer_service import (
    DOWNLOAD_SESSION_DIR,
    TEMP_UPLOAD_DIR,
    transfer_service,
)
from ..ws_manager import ConnectionManager, mobile_manager, ui_manager
from .dependencies import (
    MOBILE_API,
    WEB_AUTH,
    verify_mobile_api_enabled,
    verify_web_session,
)
from .transfers import cleanup_stale_sessions, restore_sessions_startup

log = logging.getLogger(__name__)


class AnnouncePayload(BaseModel):
    name: str
    local_ip: Optional[str] = None
    platform: Optional[str] = None
    client_version: Optional[str] = None
    device_id: Optional[str] = None


class QrPayload(BaseModel):
    protocol: str
    ip: str
    port: int
    certFingerprint: Optional[str] = None


class PairingRequestPayload(BaseModel):
    device_name: str
    device_id: Optional[str] = None
    device_fingerprint: Optional[str] = None
    client_version: Optional[str] = None
    platform: Optional[str] = None
    hardware_id: Optional[str] = None


def handle_mouse_command(data: Dict[str, Any], device_permissions: List[str] = None):
    # Permission Check
    if device_permissions is not None and "mouse" not in device_permissions:
        return

    if not input_service.is_available():
        log.warning("Mouse command ignored - No input backend available")
        return

    action = data.get("action")
    try:
        if action == "move":
            input_service.mouse_move(data.get("dx", 0), data.get("dy", 0))
        elif action == "click":
            input_service.mouse_click(data.get("button", "left"), data.get("clicks", 1))
        elif action == "double_click":
            input_service.mouse_click(data.get("button", "left"), 2)
        elif action == "scroll":
            input_service.mouse_scroll(data.get("dx", 0), data.get("dy", 0))
    except Exception as e:
        log.error(f"Error executing mouse command '{action}': {e}")


def handle_keyboard_command(data: Dict[str, Any], device_permissions: List[str] = None):
    # Permission Check
    if device_permissions is not None and "keyboard" not in device_permissions:
        return

    if not input_service.is_available():
        log.warning("Keyboard command ignored - No input backend available")
        return

    try:
        if text := data.get("text"):
            input_service.keyboard_type(text)
        elif key_str := data.get("key"):
            modifiers = data.get("modifiers", [])
            input_service.keyboard_press_key(key_str, modifiers)
    except Exception as e:
        log.error(f"Error executing keyboard command: {e}")


def mount_core_routes(
    app,
    controller,
    connected_devices,
    allow_insecure_shell,
    pairing_events,
    pairing_results,
    extension_manager,
):
    @app.on_event("startup")
    async def startup_event():
        try:
            result = await restore_sessions_startup()
            log.info(
                f"Session restoration: {result['restored_uploads']} uploads, {result['restored_downloads']} downloads"
            )

            async def periodic_cleanup():
                while True:
                    await asyncio.sleep(3600)
                    try:
                        from ...core.config import config_manager

                        threshold = config_manager.get("transfer_cleanup_threshold", 7)
                        await cleanup_stale_sessions(days=threshold)
                    except Exception as e:
                        log.error(f"Periodic cleanup failed: {e}")

            asyncio.create_task(periodic_cleanup())

        except Exception as e:
            log.error(f"Failed to restore sessions on startup: {e}")

        asyncio.create_task(broadcast_updates_task(mobile_manager, app.state))

        # Clear extension crash counter on successful startup
        extension_manager.mark_startup_success()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
        await websocket.accept()

        if not token:
            await websocket.close(code=1008, reason="Missing API Key")
            return

        device = device_manager.get_device_by_api_key(token)
        if not (device and device.is_approved):
            await websocket.close(code=1008, reason="Invalid Device Token")
            return

        device_manager.update_device_ip(device.device_id, websocket.client.host)
        device_manager.update_device_last_seen(device.device_id)
        device_id = device.device_id
        permissions = device.permissions

        await mobile_manager.connect(websocket, device_id)

        # Initial push: Sync all feature states and permissions
        from ...core.config import config_manager
        from ...services.discovery_service import DiscoveryService

        await websocket.send_json(
            {
                "type": "SYNC_STATE",
                "services": config_manager.get("services", {}),
                "permissions": permissions,
                "server_id": DiscoveryService.generate_server_id(),
            }
        )
        try:
            while True:
                data = await websocket.receive_json()
                from ...core.config import config_manager

                services = config_manager.get("services", {})
                msg_type = data.get("type")

                # REFRESH PERMISSIONS (Safety for real-time revocation)
                device = device_manager.get_device_by_id(device_id)
                if not (device and device.is_approved):
                    log.warning(
                        f"Closing WebSocket for revoked/unapproved device: {device_id}"
                    )
                    await websocket.close(code=4003, reason="DEVICE_REVOKED")
                    break
                permissions = device.permissions

                # MAP TYPE TO SERVICE
                type_service_map = {
                    "mouse_control": "mouse",
                    "keyboard_control": "keyboard",
                    "media_control": "media",
                    "file_operation": "files_browse",
                    "macros": "macros",
                    "apps": "apps",
                }

                required_service = type_service_map.get(msg_type)

                # GOLDEN RULE: Global override Check
                if required_service and not services.get(required_service, True):
                    log.warning(
                        f"WebSocket command '{msg_type}' blocked - global service '{required_service}' is OFF"
                    )
                    continue

                if msg_type == "mouse_control":
                    handle_mouse_command(data, permissions)
                elif msg_type == "keyboard_control":
                    handle_keyboard_command(data, permissions)
                elif msg_type == "media_control" and "media" in permissions:
                    from ...services.media_service import media_service

                    action = data.get("action")
                    if action == "play_pause":
                        media_service.play_pause()
                    elif action == "next":
                        media_service.next_track()
                    elif action == "previous":
                        media_service.previous_track()
                    elif action == "volume_up":
                        media_service.volume_up()
                    elif action == "volume_down":
                        media_service.volume_down()
        except (WebSocketDisconnect, OSError):
            pass
        except (json.JSONDecodeError, KeyError):
            pass
        finally:
            mobile_manager.disconnect(websocket)

    @app.websocket("/ws/ui")
    async def websocket_ui_endpoint(websocket: WebSocket):
        try:
            await verify_web_session(websocket)
        except HTTPException:
            await websocket.close(code=4001, reason="Authentication failed")
            return

        await ui_manager.connect(websocket)
        log.info("Web UI client connected to WebSocket.")

        try:
            is_enabled = (
                getattr(controller, "mobile_api_enabled", False)
                if controller
                else False
            )
            initial_status = "running" if is_enabled else "stopped"
            await websocket.send_json(
                {"type": "server_status", "status": initial_status}
            )
        except Exception as e:
            log.error(f"Failed to send initial status to UI client: {e}")

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "approve_pair":
                    pid = data.get("pairing_id")
                    if pid and pid in pairing_events:
                        if pid in pairing_results:
                            pairing_results[pid]["approved"] = True
                        pairing_events[pid].set()
                        await websocket.send_json(
                            {
                                "type": "notification",
                                "data": {
                                    "title": "Pairing Approved",
                                    "message": "Device approved",
                                },
                            }
                        )

                elif msg_type == "deny_pair":
                    pid = data.get("pairing_id")
                    if pid and pid in pairing_events:
                        pairing_events[pid].set()  # Approved defaults to False
                        await websocket.send_json(
                            {
                                "type": "notification",
                                "data": {
                                    "title": "Pairing Denied",
                                    "message": "Device pairing request denied",
                                },
                            }
                        )

        except (WebSocketDisconnect, OSError):
            log.info("Web UI client disconnected from WebSocket.")
        except json.JSONDecodeError:
            pass
        finally:
            ui_manager.disconnect(websocket)

    @app.get("/ui/pairing/list", dependencies=[WEB_AUTH])
    async def list_pending_pairings():
        """List all currently pending pairing requests."""
        pending = []
        for pid, data in pairing_results.items():
            dev = data.get("device")
            if dev:
                pending.append(
                    {
                        "pairing_id": pid,
                        "device_name": dev.device_name,
                        "device_id": dev.device_id,
                        "platform": dev.platform,
                        "ip": dev.current_ip,
                    }
                )
        return {"requests": pending}

    @app.post("/pairing/request", dependencies=[Depends(verify_mobile_api_enabled)])
    async def request_pairing(payload: PairingRequestPayload, request: Request):
        """Initiate device pairing sequence."""
        pairing_id = str(uuid.uuid4())
        try:
            event = asyncio.Event()
            pairing_events[pairing_id] = event
            client_ip = request.client.host if request.client else "unknown"
            device_id = payload.device_id or str(uuid.uuid4())
            if not payload.device_name or not payload.device_name.strip():
                raise HTTPException(status_code=400, detail="Device name is required.")

            # --- Duplicate Detection & Cleanup ---
            try:
                existing_devices = device_manager.get_all_devices()
                new_hardware_id = payload.hardware_id or ""

                for existing in existing_devices:
                    match_found = False

                    if (
                        new_hardware_id
                        and existing.hardware_id == new_hardware_id
                        and existing.device_id != device_id
                    ):
                        match_found = True

                    elif (
                        not new_hardware_id
                        and existing.device_name == payload.device_name
                        and existing.platform == payload.platform
                        and existing.device_id != device_id
                    ):
                        match_found = True

                    if match_found:
                        log.info(
                            f"Cleanup: Revoking duplicate device entry: {existing.device_name} ({existing.device_id})"
                        )
                        device_manager.revoke_device(existing.device_id)
                        await mobile_manager.disconnect_device(existing.device_id)

            except Exception as e:
                log.warning(f"Error during duplicate device cleanup: {e}")
            # -------------------------------------

            device = device_manager.register_device(
                device_id=device_id,
                device_name=payload.device_name,
                device_fingerprint=payload.device_fingerprint or "",
                platform=payload.platform or "",
                client_version=payload.client_version or "",
                current_ip=client_ip,
                hardware_id=payload.hardware_id or "",
            )
            pairing_results[pairing_id] = {"device": device, "approved": False}

            pairing_notification = {
                "type": "pairing_request",
                "data": {
                    "pairing_id": pairing_id,
                    "device_name": payload.device_name,
                    "device_id": device_id,
                    "ip": client_ip,
                    "platform": payload.platform,
                    "client_version": payload.client_version,
                },
            }
            await mobile_manager.broadcast(pairing_notification)
            await ui_manager.broadcast(pairing_notification)
            try:
                await asyncio.wait_for(event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=408, detail="Pairing request timed out."
                )
            if pairing_results.get(pairing_id, {}).get("approved", False):
                device_manager.approve_device(device.device_id)
                fingerprint = get_cert_fingerprint(constants.CERT_FILE)
                return {
                    "api_key": device.api_key,
                    "cert_fingerprint": fingerprint,
                    "device_id": device.device_id,
                }
            else:
                device_manager.revoke_device(device.device_id)
                raise HTTPException(
                    status_code=403, detail="Pairing request denied by user."
                )
        finally:
            pairing_events.pop(pairing_id, None)
            pairing_results.pop(pairing_id, None)

    @app.get("/")
    def read_root():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/ui/")

    @app.get("/heartbeat", dependencies=MOBILE_API)
    async def heartbeat():
        """Unified authenticated heartbeat endpoint."""
        from ...services.discovery_service import DiscoveryService

        return {
            "status": "ok",
            "time": time.time(),
            "server_id": DiscoveryService.generate_server_id(),
        }

    @app.get("/status")
    async def server_status():
        import sys

        from ...core.version import __version__
        from ...services.discovery_service import DiscoveryService

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
            "port": app.state.host_port if hasattr(app.state, "host_port") else 38080,
            "platform": sys.platform,
        }

    from .auth import router as auth_router

    app.include_router(auth_router)

    @app.get("/ui/devices", dependencies=[WEB_AUTH])
    async def get_connected_devices():
        devices = []
        for device in device_manager.get_all_devices():
            if device.is_approved:
                # FIX: Map DB columns to Frontend keys
                devices.append(
                    {
                        "id": device.device_id,
                        "name": device.device_name,
                        "ip": device.current_ip,
                        "platform": device.platform,
                        "client_version": device.client_version,
                        "last_seen": device.last_seen.isoformat(),
                        "permissions": ",".join(device.permissions),
                    }
                )
        for ip, info in connected_devices.items():
            if not any(d["ip"] == ip for d in devices):
                devices.append(
                    {
                        "id": ip,
                        "name": info.get("name", "Unknown Device"),
                        "ip": ip,
                        "platform": info.get("platform", "Unknown"),
                        "last_seen": time.strftime(
                            "%Y-%m-%dT%H:%M:%S",
                            time.localtime(info.get("last_seen", 0)),
                        ),
                        "client_version": info.get("client_version", "Unknown"),
                        "permissions": "",
                    }
                )
        return {"devices": devices}

    @app.post("/ui/devices/remove-all", dependencies=[WEB_AUTH])
    async def remove_all_devices():
        try:
            removed_count = 0
            for device in device_manager.get_all_devices():
                if device.is_approved:
                    device_manager.revoke_device(device.device_id)
                    await mobile_manager.disconnect_device(device.device_id)
                    removed_count += 1
            connected_devices.clear()
            log.info(f"Removed {removed_count} devices via web UI")
            return {"status": "success", "removed_count": removed_count}
        except Exception as e:
            log.error(f"Failed to remove all devices: {e}")
            raise HTTPException(status_code=500, detail="Failed to remove devices")

    @app.post("/ui/devices/revoke", dependencies=[WEB_AUTH])
    async def revoke_single_device(
        device_id: str = Query(
            ..., description="The ID of the device to revoke access for"
        ),
    ):
        """Revoke device access and purge caches."""
        try:
            device = device_manager.get_device_by_id(device_id)
            device_ip = device.current_ip if device else None

            if device_manager.revoke_device(device_id):
                await mobile_manager.disconnect_device(device_id)
                removed_from_cache = 0
                for ip, data in list(connected_devices.items()):
                    cached_id = data.get("device_id")
                    if cached_id == device_id:
                        del connected_devices[ip]
                        removed_from_cache += 1
                        continue
                    if device_ip and ip == device_ip and not cached_id:
                        del connected_devices[ip]
                        removed_from_cache += 1

                log.info(f"Device {device_id} revoked via web UI.")
                return {"status": "success", "message": "Device access revoked"}

            raise HTTPException(status_code=404, detail="Device not found")
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"Failed to revoke device {device_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/ui/devices/ban", dependencies=[WEB_AUTH])
    async def ban_device_permanently(
        device_id: str = Query(...), reason: str = Query("Manual ban")
    ):
        """Revoke a device and permanently ban its hardware ID from re-pairing."""
        try:
            device = device_manager.get_device_by_id(device_id)
            if not device:
                raise HTTPException(status_code=404, detail="Device not found")

            hardware_id = device.hardware_id
            if not hardware_id:
                # Fallback: just revoke if no hardware ID
                device_manager.revoke_device(device_id)
                await mobile_manager.disconnect_device(device_id)
                return {
                    "status": "success",
                    "message": "Device revoked, but could not ban: No Hardware ID available.",
                }

            if device_manager.ban_hardware(hardware_id, reason):
                await mobile_manager.disconnect_device(device_id)
                return {
                    "status": "success",
                    "message": f"Device {device.device_name} and hardware ID {hardware_id} banned permanently.",
                }

            return {"status": "error", "message": "Failed to ban device."}
        except Exception as e:
            log.error(f"Failed to ban device {device_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/ui/devices/blacklist", dependencies=[WEB_AUTH])
    async def get_banned_list():
        """List all permanently banned hardware IDs."""
        return {"blacklist": device_manager.get_blacklist()}

    @app.post("/ui/devices/unban", dependencies=[WEB_AUTH])
    async def unban_hardware_id(hardware_id: str = Query(...)):
        """Remove a hardware ID from the blacklist."""
        if device_manager.unban_hardware(hardware_id):
            return {
                "status": "success",
                "message": f"Hardware ID {hardware_id} unbanned.",
            }
        raise HTTPException(
            status_code=404, detail="Hardware ID not found in blacklist."
        )

    @app.get("/updates/check")
    async def check_for_updates():
        """Query GitHub for latest release metadata."""
        try:
            import requests

            from ...core.version import __version__

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
            else:
                return {
                    "update_available": False,
                    "error": "Failed to check for updates",
                }
        except Exception as e:
            log.error(f"Update check failed: {e}")
            return {"update_available": False, "error": str(e)}

    @app.post("/notifications/show", dependencies=[WEB_AUTH])
    async def show_system_notification(request: Request):
        try:
            data = await request.json()
            title = data.get("title", "PCLink")
            message = data.get("message", "")
            if hasattr(app.state, "tray_manager") and app.state.tray_manager:
                app.state.tray_manager.show_notification(title, message)
                return {"status": "success", "message": "Notification sent"}
            else:
                return {
                    "status": "error",
                    "message": "System notifications not available",
                }
        except Exception as e:
            log.error(f"Failed to show system notification: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/settings/save", dependencies=[WEB_AUTH])
    async def save_server_settings(request: Request):
        """Persist global server configuration."""
        try:
            data = await request.json()
            from ...core.config import config_manager

            if "auto_start" in data:
                auto_start_enabled = data["auto_start"]
                if controller and hasattr(controller, "handle_startup_change"):
                    try:
                        controller.handle_startup_change(auto_start_enabled)
                        log.info(
                            f"Auto-start {'enabled' if auto_start_enabled else 'disabled'} via web UI"
                        )
                    except Exception as e:
                        log.error(f"Failed to update startup setting: {e}")
                        raise HTTPException(status_code=500, detail=str(e))
                else:
                    config_manager.set("auto_start", auto_start_enabled)

            if "allow_terminal_access" in data:
                terminal_access = data["allow_terminal_access"]
                config_manager.set("allow_terminal_access", terminal_access)
            if "allow_extensions" in data:
                extensions_enabled = data["allow_extensions"]
                config_manager.set("allow_extensions", extensions_enabled)
                if extensions_enabled:
                    extension_manager.load_all_extensions()
                else:
                    extension_manager.unload_all_extensions()
            if "allow_insecure_shell" in data:
                config_manager.set("allow_insecure_shell", data["allow_insecure_shell"])

            if "notifications" in data:
                current_notifications = config_manager.get("notifications", {}).copy()
                current_notifications.update(data["notifications"])
                config_manager.set("notifications", current_notifications)

            log.info(f"Server settings updated via web UI: {data}")
            return {"status": "success", "message": "Settings saved successfully"}
        except HTTPException as he:
            raise he
        except Exception as e:
            log.error(f"Failed to save settings: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/settings/load", dependencies=[WEB_AUTH])
    async def load_server_settings():
        try:
            from ...core.config import config_manager

            auto_start_status = config_manager.get("auto_start", False)
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
                "allow_terminal_access": config_manager.get(
                    "allow_terminal_access", False
                ),
                "allow_extensions": config_manager.get("allow_extensions", False),
                "allow_insecure_shell": config_manager.get(
                    "allow_insecure_shell", False
                ),
                "notifications": config_manager.get("notifications", {}),
            }
        except Exception as e:
            log.error(f"Failed to load settings: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/logs", dependencies=[WEB_AUTH])
    async def get_server_logs():
        try:
            log_file = constants.APP_DATA_PATH / "pclink.log"
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    recent_lines = lines[-100:] if len(lines) > 100 else lines
                    return {"logs": "".join(recent_lines), "lines": len(recent_lines)}
            else:
                return {"logs": "No log file found", "lines": 0}
        except Exception as e:
            return {"logs": f"Error reading logs: {str(e)}", "lines": 0}

    @app.post("/logs/clear", dependencies=[WEB_AUTH])
    async def clear_server_logs():
        try:
            log_file = constants.APP_DATA_PATH / "pclink.log"
            if log_file.exists():
                with open(log_file, "w") as f:
                    f.write("")
                    log.info("Server logs cleared via web UI")
                return {"status": "success", "message": "Logs cleared"}
            else:
                return {"status": "error", "message": "No log file found"}
        except Exception as e:
            return {"status": "error", "message": f"Error clearing logs: {str(e)}"}

    @app.get("/qr-payload", response_model=QrPayload)
    async def get_qr_payload():
        fingerprint = get_cert_fingerprint(constants.CERT_FILE)
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
        except Exception:
            try:
                local_ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                local_ip = "127.0.0.1"

        # Security: Pair required. Master key sharing disabled.
        return QrPayload(
            protocol="https",
            ip=local_ip,
            port=app.state.host_port,
            certFingerprint=fingerprint,
        )

    @app.post("/pairing/approve")
    async def approve_pairing(request: Request):
        data = await request.json()
        pairing_id = data.get("pairing_id")
        approved = data.get("approved", False)
        if pairing_id in pairing_results:
            pairing_results[pairing_id]["approved"] = approved
            pairing_results[pairing_id]["user_decided"] = True
            if event := pairing_events.get(pairing_id):
                event.set()
            return {"status": "success", "approved": approved}
        else:
            raise HTTPException(status_code=404, detail="Pairing request not found")

    @app.post("/pairing/deny")
    async def deny_pairing(request: Request):
        data = await request.json()
        pairing_id = data.get("pairing_id")
        if pairing_id in pairing_results:
            pairing_results[pairing_id]["approved"] = False
            pairing_results[pairing_id]["user_decided"] = True
            if event := pairing_events.get(pairing_id):
                event.set()
            return {"status": "success", "approved": False}
        else:
            raise HTTPException(status_code=404, detail="Pairing request not found")

    @app.post("/pairing/request")
    async def pairing_request(payload: PairingRequestPayload, request: Request):
        """Handle incoming pairing requests from mobile devices."""
        client_ip = request.client.host
        pairing_id = str(uuid.uuid4())

        # 1. Create a future/event to wait for user approval
        pairing_events[pairing_id] = asyncio.Event()
        pairing_results[pairing_id] = {
            "approved": False,
            "user_decided": False,
            "device_name": payload.device_name,
            "ip": client_ip,
            "platform": payload.platform,
        }

        # 2. Notify Web UI
        await ui_manager.broadcast(
            {
                "type": "pairing_request",
                "data": {
                    "pairing_id": pairing_id,
                    "device_name": payload.device_name,
                    "ip": client_ip,
                    "platform": payload.platform,
                    "hardware_id": payload.hardware_id,
                },
            }
        )

        # 3. Wait for approval (timeout after 60s)
        try:
            await asyncio.wait_for(pairing_events[pairing_id].wait(), timeout=60.0)
            if pairing_results[pairing_id]["approved"]:
                # 4. Generate device-specific token
                device_id = payload.device_id or str(uuid.uuid4())
                device = device_manager.register_device(
                    device_id=device_id,
                    device_name=payload.device_name,
                    device_fingerprint=payload.device_fingerprint or "",
                    platform=payload.platform or "",
                    client_version=payload.client_version or "",
                    current_ip=client_ip,
                    hardware_id=payload.hardware_id or "",
                )

                # Approve immediately since user just clicked 'Approve' in Web UI
                device_manager.approve_device(device_id)

                return {
                    "status": "approved",
                    "api_key": device.api_key,
                    "cert_fingerprint": get_cert_fingerprint(constants.CERT_FILE),
                }
            else:
                raise HTTPException(
                    status_code=403, detail="Pairing request denied by user."
                )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=408, detail="Pairing request timed out. Please try again."
            )
        finally:
            if pairing_id in pairing_events:
                del pairing_events[pairing_id]
            if pairing_id in pairing_results:
                del pairing_results[pairing_id]

    @app.post("/announce", dependencies=MOBILE_API)
    async def announce_device(request: Request, payload: AnnouncePayload):
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
            log.info(f"New device connected: {payload.name} ({client_ip})")
            notification_payload = {
                "type": "notification",
                "data": {
                    "title": "Device Connected",
                    "message": f"{payload.name} ({client_ip}) has connected.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }
            await mobile_manager.broadcast(notification_payload)
            await ui_manager.broadcast(notification_payload)
        return {"status": "announced"}

    @app.post("/server/start", dependencies=[WEB_AUTH])
    async def start_server():
        try:
            if controller and hasattr(controller, "start_server"):
                await ui_manager.broadcast(
                    {"type": "server_status", "status": "starting"}
                )
                controller.start_server()
                await asyncio.sleep(1)
                await ui_manager.broadcast(
                    {"type": "server_status", "status": "running"}
                )
                return {"status": "success", "message": "Server starting"}
            raise HTTPException(
                status_code=500, detail="Server controller not available"
            )
        except Exception as e:
            log.error(f"Failed to start server: {e}")
            await ui_manager.broadcast({"type": "server_status", "status": "stopped"})
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/server/stop", dependencies=[WEB_AUTH])
    async def stop_server():
        try:
            if controller and hasattr(controller, "stop_server"):
                await ui_manager.broadcast(
                    {"type": "server_status", "status": "stopping"}
                )
                controller.stop_server()
                await asyncio.sleep(1)
                await ui_manager.broadcast(
                    {"type": "server_status", "status": "stopped"}
                )
                return {"status": "success", "message": "Server stopping"}
            raise HTTPException(
                status_code=500, detail="Server controller not available"
            )
        except Exception as e:
            log.error(f"Failed to stop server: {e}")
            await ui_manager.broadcast({"type": "server_status", "status": "running"})
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/server/restart", dependencies=[WEB_AUTH])
    async def restart_server():
        try:
            if (
                controller
                and hasattr(controller, "stop_server")
                and hasattr(controller, "start_server")
            ):
                await ui_manager.broadcast(
                    {"type": "server_status", "status": "restarting"}
                )

                async def delayed_restart():
                    controller.stop_server()
                    await asyncio.sleep(2)
                    controller.start_server()
                    await asyncio.sleep(1)
                    await ui_manager.broadcast(
                        {"type": "server_status", "status": "running"}
                    )

                asyncio.create_task(delayed_restart())
                return {"status": "success", "message": "Server restarting"}
            raise HTTPException(
                status_code=500, detail="Server controller not available"
            )
        except Exception as e:
            log.error(f"Failed to restart server: {e}")
            await ui_manager.broadcast({"type": "server_status", "status": "running"})
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/debug/performance")
    async def debug_performance():
        import time

        import psutil

        ACTIVE_UPLOADS = transfer_service.active_uploads
        ACTIVE_DOWNLOADS = transfer_service.active_downloads
        TRANSFER_LOCKS = transfer_service.transfer_locks

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
            "active_uploads_memory": len(ACTIVE_UPLOADS),
            "active_downloads_memory": len(ACTIVE_DOWNLOADS),
            "persisted_uploads_disk": persisted_uploads,
            "persisted_downloads_disk": persisted_downloads,
            "transfer_locks": len(TRANSFER_LOCKS),
        }

    @app.post("/server/shutdown", dependencies=[WEB_AUTH])
    async def shutdown_server():
        try:
            log.info("Shutdown endpoint called via web UI")
            await ui_manager.broadcast(
                {"type": "server_status", "status": "shutting_down"}
            )

            def do_shutdown():
                try:
                    log.info("Executing shutdown sequence...")
                    if controller and hasattr(controller, "stop_server_completely"):
                        log.info("Stopping server completely...")
                        controller.stop_server_completely()
                    else:
                        log.warning(
                            "Controller not available or missing stop_server_completely method"
                        )
                finally:
                    log.info("Forcing application exit...")
                    import os

                    os._exit(0)

            import threading

            log.info("Starting shutdown timer...")
            threading.Timer(0.5, do_shutdown).start()
            return {"status": "success", "message": "Server shutting down"}
        except Exception as e:
            log.error(f"Failed to shutdown server: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/transfers/cleanup/status", dependencies=[WEB_AUTH])
    async def get_transfer_cleanup_status():
        try:
            from ...core.config import config_manager

            threshold = config_manager.get("transfer_cleanup_threshold", 7)
            current_time = time.time()
            threshold_seconds = threshold * 24 * 60 * 60

            stale_uploads = 0
            for meta in TEMP_UPLOAD_DIR.glob("*.meta"):
                if current_time - meta.stat().st_mtime > threshold_seconds:
                    stale_uploads += 1

            stale_downloads = 0
            for sess in DOWNLOAD_SESSION_DIR.glob("*.json"):
                if current_time - sess.stat().st_mtime > threshold_seconds:
                    stale_downloads += 1

            return {
                "threshold_days": threshold,
                "stale_uploads": stale_uploads,
                "stale_downloads": stale_downloads,
                "total_stale": stale_uploads + stale_downloads,
            }
        except Exception as e:
            log.error(f"Failed to get cleanup status: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/transfers/cleanup/execute", dependencies=[WEB_AUTH])
    async def execute_transfer_cleanup():
        try:
            from ...core.config import config_manager

            threshold = config_manager.get("transfer_cleanup_threshold", 7)
            result = await cleanup_stale_sessions(days=threshold)
            return {"status": "success", "cleaned": result}
        except Exception as e:
            log.error(f"Manual cleanup failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.patch("/transfers/cleanup/config", dependencies=[WEB_AUTH])
    async def update_transfer_cleanup_config(request: Request):
        try:
            data = await request.json()
            threshold = data.get("threshold")
            if threshold is None or not isinstance(threshold, int) or threshold < 0:
                raise HTTPException(status_code=400, detail="Invalid threshold value")

            from ...core.config import config_manager

            config_manager.set("transfer_cleanup_threshold", threshold)
            return {"status": "success", "threshold": threshold}
        except Exception as e:
            log.error(f"Failed to update cleanup config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/extensions/{extension_id}/approve", dependencies=[WEB_AUTH])
    async def approve_extension(extension_id: str):
        try:
            from ...core.config import config_manager

            if not config_manager.get("allow_extensions", False):
                raise HTTPException(
                    status_code=403,
                    detail="Extension system is disabled globally. Enable it in settings to approve extensions.",
                )

            # 1. Update manifest to remove security flag and enable
            manifest_path = (
                extension_manager.extensions_path / extension_id / "extension.yaml"
            )
            if not manifest_path.exists():
                raise HTTPException(status_code=404, detail="Extension not found")

            import yaml

            with open(manifest_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            config["enabled"] = True
            config["security_consent_needed"] = False

            with open(manifest_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f)

            # 2. Load it
            if extension_manager.load_extension(extension_id):
                log.info(f"Extension {extension_id} approved and enabled.")
                return {
                    "status": "success",
                    "message": "Extension approved and enabled",
                }
            else:
                raise HTTPException(
                    status_code=500, detail="Failed to load extension after approval"
                )
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"Failed to approve extension {extension_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))


async def broadcast_updates_task(manager: ConnectionManager, state: Any):
    from ...core.config import config_manager
    from ...services import media_service, system_service

    while True:
        try:
            if not manager.active_connections:
                await asyncio.sleep(5)
                continue

            # Prepare internal data structure
            from ...core.config import config_manager

            services = config_manager.get("services", {})
            from ...services.discovery_service import DiscoveryService

            update_data = {
                "type": "UPDATE_STATE",
                "services": services,
                "server_id": DiscoveryService.generate_server_id(),
            }

            # Check services for system info
            if services.get("info", True):
                update_data["system"] = await system_service.get_system_info()
                update_data["system"]["allow_insecure_shell"] = (
                    state.allow_insecure_shell
                )
            else:
                # Basic info only even if service is disabled
                import platform

                from ...core.version import __version__

                update_data["system"] = {
                    "version": __version__,
                    "platform": platform.system(),
                    "allow_insecure_shell": state.allow_insecure_shell,
                }

            # Check services for media info
            if services.get("media", True):
                update_data["media"] = await media_service.get_media_info()
            else:
                update_data["media"] = {"status": "Service disabled"}

            payload = {"type": "update", "data": update_data}
            await manager.broadcast(payload)
        except Exception as e:
            log.error(f"Error in broadcast task: {e}")
        await asyncio.sleep(1)
