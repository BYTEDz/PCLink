# src/pclink/api_server/routers/desktop_streaming.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from ...services.desktop_streaming_service import desktop_streaming_service
from .dependencies import extract_token, verify_api_key, verify_web_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/desktop-streaming", tags=["desktop_streaming"])


def _process_mouse_input(data: dict):
    """Parses MOUSE_INPUT payloads sent from FerrumViewer Android app and executes them via kernel uinput."""
    from ...services.input_service import input_service

    action = data.get("action")
    if not action and "type" in data and data.get("type") == "MOUSE_INPUT":
        action = data.get("action")

    if not action:
        return False

    if action == "move":
        dx = data.get("x") or data.get("dx") or 0.0
        dy = data.get("y") or data.get("dy") or 0.0
        input_service.mouse_move(dx, dy)
        return True
    elif action in ("click", "double_click"):
        btn = data.get("button", "left")
        clicks = 2 if action == "double_click" else 1
        input_service.mouse_click(btn, clicks)
        return True
    elif action in ("button_down", "button_up"):
        btn = data.get("button", "left")
        input_service.mouse_click(btn, 1)
        return True
    elif action == "scroll":
        dx = data.get("delta_x") or data.get("dx") or 0.0
        dy = data.get("delta_y") or data.get("dy") or 0.0
        input_service.mouse_scroll(dx, dy)
        return True

    return False


@router.post("/start", dependencies=[Depends(verify_api_key)])
async def start_desktop_streaming(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    output_mode = body.get("outputMode", "rtp")

    if output_mode == "webrtc":
        client_host = None
    else:
        client_host = body.get("udpHost") or request.client.host

    srtp_key = None
    if body.get("srtp"):
        import secrets

        srtp_key = secrets.token_hex(30)

    success = await desktop_streaming_service.start_engine(
        client_host=client_host, srtp_key=srtp_key, **body
    )
    if success:
        res = {
            "success": True,
            "host": client_host,
            "encoder": body.get("encoder", "auto"),
        }
        if srtp_key:
            res["srtp_key"] = srtp_key
        return res
    raise HTTPException(status_code=500, detail="Failed to start mirror engine")


@router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_desktop_streaming():
    await desktop_streaming_service.stop_engine()
    return {"success": True}


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_status():
    return {
        "active": desktop_streaming_service.process is not None
        and desktop_streaming_service.process.returncode is None,
        "engine": "ferrumcast",
        "srtp_key": desktop_streaming_service.srtp_key,
    }


@router.get("/diagnostics", dependencies=[Depends(verify_api_key)])
async def get_diagnostics():
    return await desktop_streaming_service.diagnose_system()


@router.post("/reset-portal", dependencies=[Depends(verify_api_key)])
async def reset_portal():
    success = desktop_streaming_service.reset_portal_token()
    return {"success": success}


@router.post("/input/engine", dependencies=[Depends(verify_api_key)])
async def send_engine_input(request: Request):
    try:
        body = await request.json()
        if _process_mouse_input(body):
            return {"success": True}

        await desktop_streaming_service.send_command(body)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws")
async def desktop_streaming_websocket(websocket: WebSocket):
    try:
        await verify_web_session(websocket)
    except HTTPException:
        token = extract_token(websocket)
        if token:
            from ...core.device_manager import device_manager

            device = device_manager.get_device_by_api_key(token)
            if not (device and device.is_approved):
                return await websocket.close(code=4001, reason="AUTH_FAILED")
        else:
            return await websocket.close(code=4001, reason="AUTH_FAILED")

    await websocket.accept()

    async def send_to_ws(msg):
        try:
            await asyncio.wait_for(websocket.send_json(msg), timeout=1.0)
        except (asyncio.TimeoutError, Exception):
            pass

    desktop_streaming_service.subscribe(send_to_ws)

    try:
        while True:
            data = await websocket.receive_json()
            if not _process_mouse_input(data):
                await desktop_streaming_service.send_command(data)
    except WebSocketDisconnect:
        pass
    finally:
        remaining = desktop_streaming_service.unsubscribe(send_to_ws)
        if remaining == 0:
            await desktop_streaming_service.stop_engine()
