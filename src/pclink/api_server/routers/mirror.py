from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Request,
    HTTPException,
    Depends,
)
from ...services.mirror_service import mirror_service
from .dependencies import verify_api_key, verify_web_session

router = APIRouter(prefix="/mirror", tags=["mirroring"])


@router.post("/start", dependencies=[Depends(verify_api_key)])
async def start_mirror(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    output_mode = body.get("outputMode", "rtp")
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

    success = await mirror_service.start_engine(
        client_host=client_host,
        encoder=encoder,
        width=width,
        height=height,
        fps=fps,
        bitrate=bitrate,
        audio=audio,
    )
    if success:
        return {"success": True, "host": client_host, "encoder": encoder}
    raise HTTPException(status_code=500, detail="Failed to start mirror engine")


@router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_mirror():
    await mirror_service.stop_engine()
    return {"success": True}


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_status():
    return {
        "active": mirror_service.process is not None
        and mirror_service.process.returncode is None,
        "engine": "ferrumcast",
    }


@router.get("/diagnostics", dependencies=[Depends(verify_api_key)])
async def get_diagnostics():
    return await mirror_service.diagnose_system()


@router.post("/reset-portal", dependencies=[Depends(verify_api_key)])
async def reset_portal():
    success = mirror_service.reset_portal_token()
    return {"success": success}


@router.websocket("/ws")
async def mirror_websocket(websocket: WebSocket):
    # Securely verify WebSocket connection during handshake
    try:
        await verify_web_session(websocket)
    except HTTPException:
        # Fallback to query param token for mobile/app clients
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

    mirror_service.subscribe(send_to_ws)

    try:
        while True:
            data = await websocket.receive_json()
            await mirror_service.send_command(data)
    except WebSocketDisconnect:
        pass
    finally:
        mirror_service.unsubscribe(send_to_ws)
