# src/pclink/api_server/terminal.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import platform
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..core.config import config_manager
from ..services.terminal_service import terminal_service
from ..core.validators import validate_api_key
from ..core.device_manager import device_manager

log = logging.getLogger(__name__)

def create_terminal_router(api_key: str) -> APIRouter:
    router = APIRouter()

    def _authenticate(token: str) -> bool:
        if not token: return False
        # Check main API key
        try:
            if validate_api_key(token) == api_key: return True
        except Exception: pass
        # Check device API keys
        try:
            device = device_manager.get_device_by_api_key(token)
            if device and device.is_approved:
                device_manager.update_device_last_seen(device.device_id)
                return True
        except Exception: pass
        return False

    @router.get("/shells")
    async def get_available_shells(token: str = Query(None)):
        if not _authenticate(token):
            return {"error": "Invalid API Key"}
        return terminal_service.get_available_shells()

    @router.websocket("/ws")
    async def terminal_websocket(websocket: WebSocket, token: str = Query(None)):
        if not _authenticate(token):
            await websocket.close(code=1008, reason="Unauthorized")
            return

        if not config_manager.get("allow_terminal_access", False):
            await websocket.close(code=4002, reason="Terminal access disabled")
            return

        await websocket.accept()
        log.info(f"Terminal session started for {websocket.client}")

        try:
            if platform.system() == "Windows":
                shell = websocket.query_params.get("shell", "cmd").lower()
                await terminal_service.run_windows_terminal(websocket, shell)
            else:
                await terminal_service.run_unix_terminal(websocket)
        except WebSocketDisconnect:
            log.info("Terminal disconnected")
        except Exception as e:
            log.error(f"Terminal error: {e}")
            try: await websocket.send_text(f"\r\n[PCLink Error] {e}\r\n")
            except Exception: pass
        finally:
            try: await websocket.close()
            except Exception: pass

    return router