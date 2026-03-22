# src/pclink/api_server/routers/websocket_routes.py
import asyncio
import logging
import platform
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ...core.config import config_manager
from ...core.device_manager import device_manager
from ...services import input_service
from ..ws_manager import mobile_manager, ui_manager
from .dependencies import verify_web_session

log = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


def handle_mouse_command(data: Dict[str, Any], device_permissions: List[str] = None):
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
    if device_permissions is not None and "keyboard" not in device_permissions:
        return
    if not input_service.is_available():
        log.warning("Keyboard command ignored - No input backend available")
        return

    try:
        if text := data.get("text"):
            input_service.keyboard_type(text)
        elif key := data.get("key"):
            input_service.keyboard_press(key)
    except Exception as e:
        log.error(f"Error executing keyboard command: {e}")


@router.websocket("/ws")
async def mobile_websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    """Main communication channel for mobile devices."""
    await websocket.accept()

    if not token:
        await websocket.close(code=1008, reason="MISSING_TOKEN")
        return

    device = device_manager.get_device_by_api_key(token)
    if not (device and device.is_approved):
        await websocket.close(code=1008, reason="INVALID_OR_REVOKED_TOKEN")
        return

    device_id = device.device_id
    device_manager.update_device_ip(device_id, websocket.client.host)
    device_manager.update_device_last_seen(device_id)

    await mobile_manager.connect(websocket, device_id)

    # Initial Sync
    from ...services.discovery_service import DiscoveryService

    await websocket.send_json(
        {
            "type": "SYNC_STATE",
            "services": config_manager.get("services", {}),
            "permissions": device.permissions,
            "server_id": DiscoveryService.generate_server_id(),
        }
    )

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # 1. Real-time Permission Verification
            current_device = device_manager.get_device_by_id(device_id)
            if not (current_device and current_device.is_approved):
                log.warning(f"Closing WS for revoked device: {device_id}")
                await websocket.close(code=4003, reason="DEVICE_REVOKED")
                break

            permissions = current_device.permissions
            services = config_manager.get("services", {})

            # 2. Service mapping & Global Check
            type_service_map = {
                "mouse_control": "mouse",
                "keyboard_control": "keyboard",
                "media_control": "media",
                "file_operation": "files_browse",
                "macros": "macros",
                "apps": "apps",
            }
            required_service = type_service_map.get(msg_type)
            if required_service and not services.get(required_service, True):
                log.debug(f"Blocked {msg_type} - service disabled")
                continue

            # 3. Command Execution
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
    finally:
        mobile_manager.disconnect(websocket)


@router.websocket("/ws/ui")
async def web_ui_websocket_endpoint(websocket: WebSocket):
    """Real-time update channel for the Browser Web UI."""
    try:
        await verify_web_session(websocket)
    except HTTPException:
        await websocket.close(code=4001, reason="AUTH_FAILED")
        return

    await ui_manager.connect(websocket)

    # Send initial status
    controller = getattr(websocket.app.state, "controller", None)
    is_running = (
        getattr(controller, "mobile_api_enabled", False) if controller else False
    )
    await websocket.send_json(
        {"type": "server_status", "status": "running" if is_running else "stopped"}
    )

    try:
        results = getattr(websocket.app.state, "pairing_results", {})
        events = getattr(websocket.app.state, "pairing_events", {})

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # UI-triggered pairing responses
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
                await asyncio.sleep(5)
                continue

            services = config_manager.get("services", {})
            update_data = {
                "type": "UPDATE_STATE",
                "services": services,
                "server_id": DiscoveryService.generate_server_id(),
            }

            # Gather System Metrics
            if services.get("info", True):
                update_data["system"] = await system_service.get_system_info()
            else:
                update_data["system"] = {
                    "version": getattr(state, "controller", None).version
                    if hasattr(state, "controller")
                    else "unknown",
                    "platform": platform.system(),
                }

            # Gather Media Metadata
            if services.get("media", True):
                update_data["media"] = await media_service.get_media_info()

            await manager.broadcast({"type": "update", "data": update_data})
        except Exception as e:
            log.error(f"Broadcast task error: {e}")
        await asyncio.sleep(1)
