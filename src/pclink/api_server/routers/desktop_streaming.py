from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Request,
    HTTPException,
    Depends,
)
from ...services.desktop_streaming_service import desktop_streaming_service
from .dependencies import verify_api_key, verify_web_session

router = APIRouter(prefix="/desktop-streaming", tags=["desktop_streaming"])


@router.post("/start", dependencies=[Depends(verify_api_key)])
async def start_desktop_streaming(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    output_mode = body.get("outputMode", "rtp")

    # WebRTC pipelines handle transport allocation dynamically via ICE negotiation.
    # Conversely, standard RTP streaming requires a static destination host to route
    # unicast UDP media packets immediately.
    if output_mode == "webrtc":
        client_host = None
    else:
        client_host = body.get("udpHost") or request.client.host

    encoder = body.get("encoder", "auto")
    width = body.get("width")
    height = body.get("height")
    fps = body.get("fps")
    bitrate = body.get("bitrate", 4000)
    audio = body.get("audio", True)
    gdi = body.get("gdi", False)

    success = await desktop_streaming_service.start_engine(
        client_host=client_host,
        encoder=encoder,
        width=width,
        height=height,
        fps=fps,
        bitrate=bitrate,
        audio=audio,
        gdi=gdi,
    )
    if success:
        return {"success": True, "host": client_host, "encoder": encoder}
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
    }


@router.get("/diagnostics", dependencies=[Depends(verify_api_key)])
async def get_diagnostics():
    return await desktop_streaming_service.diagnose_system()


@router.post("/reset-portal", dependencies=[Depends(verify_api_key)])
async def reset_portal():
    success = desktop_streaming_service.reset_portal_token()
    return {"success": success}


@router.websocket("/ws")
async def desktop_streaming_websocket(websocket: WebSocket):
    try:
        # Validate the connection using the active web session state.
        # This serves as the primary authentication path for browser-based clients.
        await verify_web_session(websocket)
    except HTTPException:
        # Fallback to query-string token authentication for native clients (e.g., mobile apps).
        # Since standard WebSocket handshakes on native clients do not consistently support custom headers,
        # tokens are accepted as query parameters and validated against the device registry.
        token = websocket.query_params.get("token")
        if token:
            from ...core.device_manager import device_manager

            device = device_manager.get_device_by_api_key(token)
            if not (device and device.is_approved):
                return await websocket.close(code=4001, reason="AUTH_FAILED")
        else:
            return await websocket.close(code=4001, reason="AUTH_FAILED")

    await websocket.accept()

    async def send_to_ws(msg):
        await websocket.send_json(msg)

    # Bind the connection lifecycle to the mirror service's pub-sub dispatcher
    # to receive real-time engine telemetry, local SDP generation events, and ICE candidates.
    desktop_streaming_service.subscribe(send_to_ws)

    try:
        while True:
            data = await websocket.receive_json()
            await desktop_streaming_service.send_command(data)
    except WebSocketDisconnect:
        pass
    finally:
        desktop_streaming_service.unsubscribe(send_to_ws)
