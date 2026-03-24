import logging
import platform
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect

from ...core.config import config_manager
from ...core.device_manager import device_manager
from ...services.terminal_service import terminal_service

log = logging.getLogger(__name__)


def create_terminal_router() -> APIRouter:
    router = APIRouter()

    def _get_authenticated_device(
        conn: Any, token: Optional[str] = None
    ) -> Optional[Any]:
        # 1. Extraction (Checks query param, then headers, then cookies)
        tk = (
            token
            or conn.headers.get("X-API-Key")
            or conn.cookies.get("pclink_device_token")
        )
        if not tk:
            return None

        # 2. Lookup
        try:
            device = device_manager.get_device_by_api_key(tk)
            if device and device.is_approved:
                device_manager.update_device_last_seen(device.device_id)
                return device
        except Exception:
            pass
        return None

    from .dependencies import verify_api_key, verify_mobile_api_enabled

    @router.get(
        "/shells",
        dependencies=[Depends(verify_api_key), Depends(verify_mobile_api_enabled)],
    )
    async def get_available_shells(request: Request, token: str = Query(None)):
        device = _get_authenticated_device(request, token)
        if not device:
            return {"error": "Unauthorized"}

        # Global Check
        services = config_manager.get("services", {})
        if not services.get("terminal", True):
            return {"error": "GLOBAL_DISABLED"}

        # Per-Device Check
        if "terminal" not in device.permissions:
            return {"error": "PERMISSION_DENIED"}

        return terminal_service.get_available_shells()

    @router.websocket("/ws")
    async def terminal_websocket(websocket: WebSocket, token: str = Query(None)):
        await websocket.accept()

        device = _get_authenticated_device(websocket, token)
        if not device:
            log.warning(
                f"Terminal connection rejected: Invalid or missing token from {websocket.client}"
            )
            await websocket.close(code=1008, reason="Unauthorized")
            return

        # 1. Global Kill Switch Check
        services = config_manager.get("services", {})
        if not services.get("terminal", True):
            log.warning("Terminal connection rejected: Service disabled globally")
            await websocket.close(code=4002, reason="Terminal globally disabled")
            return

        # 2. Per-Device Permission Check
        if "terminal" not in device.permissions:
            log.warning(
                f"Terminal access DENIED for device '{device.device_name}' ({device.device_id}). Permissions: {device.permissions}"
            )
            await websocket.close(code=4003, reason="PERMISSION_DENIED")
            return

        log.info(f"Terminal access granted for device '{device.device_name}'")
        log.info(f"Terminal session started for {websocket.client}")

        try:
            shell = websocket.query_params.get("shell", "cmd").lower()
            if platform.system() == "Windows":
                await terminal_service.run_windows_terminal(websocket, shell)
            else:
                await terminal_service.run_unix_terminal(websocket, shell)
        except WebSocketDisconnect:
            log.info("Terminal disconnected")
        except Exception as e:
            log.error(f"Terminal error: {e}")
            try:
                await websocket.send_text(f"\r\n[PCLink Error] {e}\r\n")
            except Exception:
                pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    return router
