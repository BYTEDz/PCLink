# src/pclink/api_server/routers/terminal.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
import platform
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from ...core.config import config_manager
from ...core.device_manager import device_manager
from ...services.terminal_service import terminal_service
from .dependencies import extract_token, verify_mobile_api_enabled

log = logging.getLogger(__name__)
_ = gettext.gettext

# --- Dependencies ---


async def get_authenticated_terminal_device(
    request: Request = None, websocket: WebSocket = None, token: str = Query(None)
) -> Any:
    """Consolidated dependency to authenticate and authorize terminal access."""
    conn = request or websocket
    tk = extract_token(conn, token=token)

    if not tk:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_("Missing authentication token"),
        )

    try:
        device = device_manager.get_device_by_api_key(tk)
        if not device or not device.is_approved:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_("Invalid or revoked token"),
            )

        # 1. Global Kill Switch Check
        services = config_manager.get("services", {})
        if not services.get("terminal", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_("Terminal service globally disabled"),
            )

        # 2. Per-Device Permission Check
        if "terminal" not in device.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_("Terminal permission denied for device"),
            )

        device_manager.update_device_last_seen(device.device_id)
        return device

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Terminal auth error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_("Internal server error"),
        )


def create_terminal_router() -> APIRouter:
    router = APIRouter()

    @router.get("/shells", dependencies=[Depends(verify_mobile_api_enabled)])
    async def get_available_shells(
        device: Any = Depends(get_authenticated_terminal_device),
    ):
        """Returns HTTP 200 only if fully authorized, otherwise Depends() throws 401/403."""
        return terminal_service.get_available_shells()

    @router.websocket("/ws")
    async def terminal_websocket(websocket: WebSocket, token: str = Query(None)):
        # 1. Authenticate BEFORE accepting the connection
        try:
            device = await get_authenticated_terminal_device(
                websocket=websocket, token=token
            )
        except HTTPException as e:
            log.warning(
                f"Terminal connection rejected from {websocket.client}: {e.detail}"
            )
            await websocket.close(code=1008, reason=e.detail)
            return

        # 2. Connection Approved -> Now we accept
        await websocket.accept()
        log.info(
            f"Terminal access granted for device '{device.device_name}' ({websocket.client})"
        )

        try:
            shells_info = terminal_service.get_available_shells()
            default_shell = shells_info.get("default", "bash")
            requested_shell = websocket.query_params.get("shell", default_shell).lower()

            # Security: Validation of shell choice
            if (
                requested_shell != "cmd"
                and requested_shell not in shells_info["shells"]
            ):
                log.warning(f"Rejecting unsupported shell: {requested_shell}")
                await websocket.send_text(
                    _("\r\n[PCLink] Error: Unsupported shell '{shell}'.\r\n").format(
                        shell=requested_shell
                    )
                )
                await websocket.close(code=4003)
                return

            if platform.system() == "Windows":
                await terminal_service.run_windows_terminal(websocket, requested_shell)
            else:
                await terminal_service.run_unix_terminal(websocket, requested_shell)

        except WebSocketDisconnect:
            log.info(f"Terminal disconnected for device '{device.device_name}'")
        except Exception as e:
            log.error(f"Terminal error for '{device.device_name}': {e}", exc_info=True)
            try:
                await websocket.send_text(
                    _("\r\n[PCLink Error] {error}\r\n").format(error=e)
                )
            except Exception:
                pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    return router
