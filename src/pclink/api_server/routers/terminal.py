# src/pclink/api_server/routers/terminal.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
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
        return terminal_service.get_available_shells()

    @router.delete(
        "/sessions/{session_id}", dependencies=[Depends(verify_mobile_api_enabled)]
    )
    async def delete_session(
        session_id: str, device: Any = Depends(get_authenticated_terminal_device)
    ):
        """Explicitly terminates a session when user removes it from UI."""
        await terminal_service.kill_session(session_id)
        return {"status": "success", "session_id": session_id}

    @router.websocket("/ws")
    async def terminal_websocket(
        websocket: WebSocket,
        token: str = Query(None),
        session_id: str = Query("default"),
        shell: str = Query(None),
    ):
        try:
            device = await get_authenticated_terminal_device(
                websocket=websocket, token=token
            )
        except HTTPException as e:
            log.warning(
                f"Terminal connection rejected from {websocket.client}: {e.detail}"
            )
            # Use 1008 (Policy Violation) strictly for 403 Forbidden; use 1011 (Internal Error) for 500
            close_code = 1008 if e.status_code == status.HTTP_403_FORBIDDEN else 1011
            await websocket.close(code=close_code, reason=e.detail)
            return

        await websocket.accept()
        log.info(
            f"Terminal attached for '{device.device_name}' [Session: {session_id}]"
        )

        try:
            shells_info = terminal_service.get_available_shells()
            default_shell = shells_info.get("default", "cmd")
            requested_shell = (shell or default_shell).lower()

            if (
                requested_shell != "cmd"
                and requested_shell not in shells_info["shells"]
            ):
                requested_shell = default_shell

            await terminal_service.handle_client_connection(
                websocket=websocket,
                session_id=session_id,
                shell_type=requested_shell,
            )

        except WebSocketDisconnect:
            log.info(
                f"Terminal disconnected for device '{device.device_name}' [Session: {session_id}]"
            )
        except Exception as e:
            log.error(f"Terminal error for '{device.device_name}': {e}", exc_info=True)
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    return router
