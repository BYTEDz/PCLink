# src/pclink/api_server/routers/websocket_routes.py
import asyncio
import logging
import platform
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ...core.config import config_manager
from ...core.device_manager import device_manager
from ...services import input_service
from ..ws_manager import mobile_manager, ui_manager
from .dependencies import verify_web_session

log = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])

AUTH_CHECK_INTERVAL = 5.0  # seconds


async def handle_mouse_command(data: Dict[str, Any], permissions: List[str]):
    if "mouse" not in permissions or not input_service.is_available():
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
        log.error(f"Mouse command '{action}' failed: {e}")


async def handle_keyboard_command(data: Dict[str, Any], permissions: List[str]):
    if "keyboard" not in permissions or not input_service.is_available():
        return

    try:
        if text := data.get("text"):
            # Typing strings can block; offload to thread
            await asyncio.to_thread(input_service.keyboard_type, text)
        elif key := data.get("key"):
            input_service.keyboard_press(key)
    except Exception as e:
        log.error(f"Keyboard command failed: {e}")


@router.websocket("/ws")
async def mobile_websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    """Main communication channel for mobile devices."""
    await websocket.accept()

    if not token:
        return await websocket.close(code=1008, reason="MISSING_TOKEN")

    device = device_manager.get_device_by_api_key(token)
    if not (device and device.is_approved):
        return await websocket.close(code=1008, reason="INVALID_OR_REVOKED_TOKEN")

    device_id = device.device_id
    device_manager.update_device_ip(device_id, websocket.client.host)
    device_manager.update_device_last_seen(device_id)

    await mobile_manager.connect(websocket, device_id)

    from ...services.discovery_service import DiscoveryService
    from ...services.media_service import media_service

    # Local state caching to prevent DB/Config hits on every high-freq packet
    permissions = device.permissions
    services = config_manager.get("services", {})
    last_auth_check = time.time()

    await websocket.send_json(
        {
            "type": "SYNC_STATE",
            "services": services,
            "permissions": permissions,
            "server_id": DiscoveryService.generate_server_id(),
        }
    )

    type_service_map = {
        "mouse_control": "mouse",
        "keyboard_control": "keyboard",
        "media_control": "media",
        "file_operation": "files_browse",
        "macros": "macros",
        "apps": "apps",
    }

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            now = time.time()

            # 1. Periodic Real-time Permission Verification
            if now - last_auth_check > AUTH_CHECK_INTERVAL:
                current_device = device_manager.get_device_by_id(device_id)
                if not (current_device and current_device.is_approved):
                    log.warning(f"Closing WS for revoked device: {device_id}")
                    await websocket.close(code=4003, reason="DEVICE_REVOKED")
                    break

                permissions = current_device.permissions
                services = config_manager.get("services", {})
                last_auth_check = now

            # 2. Global Check
            required_service = type_service_map.get(msg_type)
            if required_service and not services.get(required_service, True):
                continue

            # 3. Safe Command Execution
            try:
                if msg_type == "mouse_control":
                    await handle_mouse_command(data, permissions)
                elif msg_type == "keyboard_control":
                    await handle_keyboard_command(data, permissions)
                elif msg_type == "media_control" and "media" in permissions:
                    action = data.get("action")
                    if action == "play_pause":
                        await asyncio.to_thread(media_service.play_pause)
                    elif action == "next":
                        await asyncio.to_thread(media_service.next_track)
                    elif action == "previous":
                        await asyncio.to_thread(media_service.previous_track)
                    elif action == "volume_up":
                        await asyncio.to_thread(media_service.volume_up)
                    elif action == "volume_down":
                        await asyncio.to_thread(media_service.volume_down)
            except Exception as e:
                log.error(f"Error processing {msg_type}: {e}", exc_info=True)

    except (WebSocketDisconnect, OSError):
        log.debug(f"Device {device_id} disconnected normally.")
    finally:
        mobile_manager.disconnect(websocket)


@router.websocket("/ws/ui")
async def web_ui_websocket_endpoint(websocket: WebSocket):
    """Real-time update channel for the Browser Web UI."""
    try:
        await verify_web_session(websocket)
    except HTTPException:
        return await websocket.close(code=4001, reason="AUTH_FAILED")

    await ui_manager.connect(websocket)
    app_state = websocket.app.state

    controller = getattr(app_state, "controller", None)
    is_running = (
        getattr(controller, "mobile_api_enabled", False) if controller else False
    )

    await websocket.send_json(
        {"type": "server_status", "status": "running" if is_running else "stopped"}
    )

    try:
        results = getattr(app_state, "pairing_results", {})
        events = getattr(app_state, "pairing_events", {})

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type in ("approve_pair", "deny_pair"):
                pid = data.get("pairing_id")
                if pid and pid in events:
                    if msg_type == "approve_pair" and pid in results:
                        results[pid]["approved"] = True
                    events[pid].set()

    except (WebSocketDisconnect, OSError):
        pass
    finally:
        ui_manager.disconnect(websocket)


async def broadcast_updates_task(manager, state):
    """Background task to push periodic system state updates to connected clients."""
    from ...services import media_service, system_service
    from ...services.discovery_service import DiscoveryService

    while True:
        try:
            if not manager.active_connections:
                await asyncio.sleep(2)
                continue

            services = config_manager.get("services", {})
            update_data = {
                "type": "UPDATE_STATE",
                "services": services,
                "server_id": DiscoveryService.generate_server_id(),
            }

            if services.get("info", True):
                update_data["system"] = await system_service.get_system_info()
            else:
                version = (
                    getattr(getattr(state, "controller", None), "version", "unknown")
                    if hasattr(state, "controller")
                    else "unknown"
                )
                update_data["system"] = {
                    "version": version,
                    "platform": platform.system(),
                }

            if services.get("media", True):
                update_data["media"] = await media_service.get_media_info()

            await manager.broadcast({"type": "update", "data": update_data})
        except Exception as e:
            log.error(f"Broadcast task error: {e}")

        await asyncio.sleep(1)
