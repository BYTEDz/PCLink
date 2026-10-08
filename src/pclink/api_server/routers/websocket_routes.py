# src/pclink/api_server/routers/websocket_routes.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import json
import logging
import platform
import struct
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ...core.config import config_manager
from ...core.device_manager import device_manager
from ...core.logging import log_telemetry_event
from ...services import input_service
from ..ws_manager import mobile_manager, ui_manager
from .dependencies import verify_web_session

log = logging.getLogger(__name__)
_ = gettext.gettext
router = APIRouter(tags=["WebSocket"])

AUTH_CHECK_INTERVAL = 30.0  # seconds


def handle_mouse_command_fast(data: Dict[str, Any], permissions: List[str]):
    """Direct non-blocking execution for mouse movement and button states."""
    if "input" not in permissions or not input_service.is_available():
        return

    action = data.get("action")
    try:
        if action == "move":
            input_service.mouse_move(data.get("dx", 0), data.get("dy", 0))
        elif action == "scroll":
            input_service.mouse_scroll(data.get("dx", 0), data.get("dy", 0))
        elif action == "click":
            input_service.mouse_click(
                data.get("button", "left"),
                data.get("clicks", 1),
            )
        elif action == "double_click":
            input_service.mouse_click(data.get("button", "left"), 2)
        elif action in ("down", "button_down"):
            input_service.mouse_down(data.get("button", "left"))
        elif action in ("up", "button_up"):
            input_service.mouse_up(data.get("button", "left"))
    except Exception as e:
        log.error(f"Mouse command '{action}' failed: {e}")


async def handle_keyboard_command(data: Dict[str, Any], permissions: List[str]):
    if "input" not in permissions or not input_service.is_available():
        log.warning(
            f"Keyboard command rejected: permissions={permissions}, available={input_service.is_available()}"
        )
        return

    try:
        action = data.get("action")
        scan_code = data.get("scan_code")
        if scan_code is not None:
            await asyncio.to_thread(
                input_service.raw_key, int(scan_code), action == "down"
            )
            return

        key = data.get("key")
        modifiers = data.get("modifiers", [])

        if action == "down" and key:
            await asyncio.to_thread(input_service.key_down, key, modifiers)
        elif action == "up" and key:
            await asyncio.to_thread(input_service.key_up, key, modifiers)
        elif text := data.get("text"):
            await asyncio.to_thread(input_service.keyboard_type, text)
        elif key:
            await asyncio.to_thread(input_service.keyboard_press_key, key, modifiers)
    except Exception as e:
        log.error(f"Keyboard command failed: {e}", exc_info=True)


@router.websocket("/ws")
async def mobile_websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    """Main communication channel for mobile devices supporting dual-format (binary + JSON) frames."""
    await websocket.accept()

    client_host = websocket.client.host if websocket.client else "unknown"

    if not token:
        log_telemetry_event(
            "websocket",
            "connection_rejected",
            {"ip": client_host, "reason": "Missing token"},
            level=logging.WARNING,
        )
        return await websocket.close(code=1008, reason="MISSING_TOKEN")

    device = device_manager.get_device_by_api_key(token)
    if not (device and device.is_approved):
        log_telemetry_event(
            "websocket",
            "connection_rejected",
            {"ip": client_host, "reason": "Invalid or revoked token"},
            level=logging.WARNING,
        )
        return await websocket.close(code=1008, reason="INVALID_OR_REVOKED_TOKEN")

    device_id = device.device_id
    device_manager.update_device_ip(device_id, client_host)
    device_manager.update_device_last_seen(device_id)

    await mobile_manager.connect(websocket, device_id)
    log_telemetry_event(
        "websocket",
        "device_connected",
        {"device_id": device_id, "device_name": device.device_name, "ip": client_host},
    )

    # Broadcast device connection event to active Web UI clients for immediate reactivity
    asyncio.create_task(ui_manager.broadcast({"type": "devices_changed"}))

    from ...services.discovery_service import DiscoveryService
    from ...services.media_service import media_service

    permissions = device.permissions
    services = config_manager.get("services", {})
    last_auth_check = time.time()

    from ...services.system_service import system_service

    ext_manager = getattr(websocket.app.state, "extension_manager", None)
    is_safe_mode = getattr(ext_manager, "safe_mode", False) if ext_manager else False

    await websocket.send_json(
        {
            "type": "SYNC_STATE",
            "services": services,
            "permissions": permissions,
            "server_id": DiscoveryService.generate_server_id(),
            "remote_access_url": config_manager.get("remote_access_url", ""),
            "safe_mode": is_safe_mode,
        }
    )

    if services.get("info", True):
        await websocket.send_json(
            {
                "type": "telemetry_history",
                "data": system_service.get_telemetry_history(),
            }
        )

    type_service_map = {
        "mouse_control": "input",
        "keyboard_control": "input",
        "media_control": "media",
        "file_operation": "files_read",
        "macros": "macros",
        "apps": "apps",
    }

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            now = time.time()
            if now - last_auth_check > AUTH_CHECK_INTERVAL:
                current_device = device_manager.get_device_by_id(device_id)
                if not (current_device and current_device.is_approved):
                    log_telemetry_event(
                        "websocket",
                        "device_revoked_disconnect",
                        {"device_id": device_id},
                        level=logging.WARNING,
                    )
                    await websocket.close(code=4003, reason="DEVICE_REVOKED")
                    break

                permissions = current_device.permissions
                services = config_manager.get("services", {})
                last_auth_check = now

            # --- Binary Frame Fast-Path ---
            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                if not services.get("input", True) or "input" not in permissions:
                    continue

                if len(raw_bytes) >= 1:
                    cmd_type = raw_bytes[0]
                    if cmd_type == 0x01 and len(raw_bytes) >= 5:  # MOUSE_MOVE
                        dx, dy = struct.unpack(">hh", raw_bytes[1:5])
                        input_service.mouse_move(dx, dy)
                        continue
                    elif cmd_type == 0x02 and len(raw_bytes) >= 5:  # MOUSE_SCROLL
                        dx, dy = struct.unpack(">hh", raw_bytes[1:5])
                        input_service.mouse_scroll(dx, dy)
                        continue
                    elif cmd_type == 0x03 and len(raw_bytes) >= 3:  # MOUSE_BUTTON
                        btn_code = raw_bytes[1]
                        btn_action = raw_bytes[2]
                        btn_name = {1: "left", 2: "right", 3: "middle"}.get(
                            btn_code, "left"
                        )
                        if btn_action == 1:
                            input_service.mouse_down(btn_name)
                        elif btn_action == 0:
                            input_service.mouse_up(btn_name)
                        elif btn_action == 2:
                            input_service.mouse_click(btn_name, 1)
                        continue
                    elif cmd_type == 0x04 and len(raw_bytes) >= 4:  # KEY_RAW
                        scan_code, action_val = struct.unpack(">HB", raw_bytes[1:4])
                        input_service.raw_key(scan_code, action_val == 1)
                        continue

            # --- JSON Text Frame Fallback ---
            if "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_type = data.get("type")
                required_service = type_service_map.get(msg_type)
                if required_service and not services.get(required_service, True):
                    continue

                try:
                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif msg_type == "mouse_control":
                        handle_mouse_command_fast(data, permissions)
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
                    elif msg_type == "FORCE_KEYFRAME":
                        from ...services.desktop_streaming_service import (
                            desktop_streaming_service,
                        )

                        await desktop_streaming_service.send_command(
                            {"type": "FORCE_KEYFRAME"}
                        )
                except Exception as e:
                    log.error(f"Error processing {msg_type}: {e}", exc_info=True)

    except (WebSocketDisconnect, RuntimeError, OSError, asyncio.CancelledError) as e:
        log_telemetry_event(
            "websocket",
            "device_disconnected",
            {"device_id": device_id, "reason": str(e)},
        )
    finally:
        mobile_manager.disconnect(websocket)

        from ...services.desktop_streaming_service import desktop_streaming_service

        asyncio.create_task(desktop_streaming_service.stop_engine())
        # Broadcast device disconnection event to active Web UI clients for immediate reactivity
        asyncio.create_task(ui_manager.broadcast({"type": "devices_changed"}))


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
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_type = data.get("type")
                if msg_type in ("approve_pair", "deny_pair"):
                    pid = data.get("pairing_id")
                    if pid and pid in events:
                        if msg_type == "approve_pair" and pid in results:
                            results[pid]["approved"] = True
                        events[pid].set()

    except (WebSocketDisconnect, RuntimeError, OSError, asyncio.CancelledError):
        pass
    finally:
        ui_manager.disconnect(websocket)


async def broadcast_updates_task(mobile_mgr, ui_mgr, state):
    """Background task to push periodic system state updates to connected mobile and Web UI clients."""
    from ...services import media_service, system_service
    from ...services.discovery_service import DiscoveryService

    while True:
        try:
            if not mobile_mgr.active_connections and not ui_mgr.active_connections:
                await asyncio.sleep(2)
                continue

            services = config_manager.get("services", {})
            ext_manager = getattr(state, "extension_manager", None)
            is_safe_mode = (
                getattr(ext_manager, "safe_mode", False) if ext_manager else False
            )

            update_data = {
                "type": "UPDATE_STATE",
                "services": services,
                "server_id": DiscoveryService.generate_server_id(),
                "remote_access_url": config_manager.get("remote_access_url", ""),
                "safe_mode": is_safe_mode,
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

            msg = {"type": "update", "data": update_data}
            if mobile_mgr.active_connections:
                await mobile_mgr.broadcast(msg)
            if ui_mgr.active_connections:
                await ui_mgr.broadcast(msg)
        except Exception as e:
            log.error(f"Broadcast task error: {e}")

        await asyncio.sleep(1)
