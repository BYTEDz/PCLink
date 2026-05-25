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

    # --- Core params ---
    encoder = body.get("encoder", "auto")
    width = body.get("width")
    height = body.get("height")
    fps = body.get("fps")
    bitrate = body.get("bitrate", 4000)
    audio = body.get("audio", True)
    gdi = body.get("gdi", False)

    # --- Encoder speed/quality ---
    speed_preset = body.get("speedPreset", "ultrafast")
    tune = body.get("tune", "zerolatency")
    nvenc_preset = body.get("nvencPreset", "p4")
    nvenc_tune = body.get("nvencTune", "ultra-low-latency")
    vaapi_target_usage = body.get("vaapiTargetUsage", 1)
    qsv_target_usage = body.get("qsvTargetUsage", 7)

    # --- Rate control ---
    rc_mode = body.get("rcMode", "cbr")
    cqp_value = body.get("cqpValue", 26)

    # --- GOP ---
    key_int_max = body.get("keyIntMax", 60)

    # --- B/ref frames ---
    bframes = body.get("bframes", 0)
    ref_frames = body.get("refFrames", 1)

    # --- Pipeline / network ---
    rtp_mtu = body.get("rtpMtu", 1200)
    queue_max_time_ns = body.get("queueMaxTimeNs", 0)
    queue_max_buffers = body.get("queueMaxBuffers", 2)
    aggregate_mode = body.get("aggregateMode", "zero-latency")
    udp_buffer_size = body.get("udpBufferSize", 2097152)

    # --- Source ---
    show_cursor = body.get("showCursor", True)
    colorimetry = body.get("colorimetry", "bt709")

    success = await desktop_streaming_service.start_engine(
        client_host=client_host,
        encoder=encoder,
        width=width,
        height=height,
        fps=fps,
        bitrate=bitrate,
        audio=audio,
        gdi=gdi,
        speed_preset=speed_preset,
        tune=tune,
        nvenc_preset=nvenc_preset,
        nvenc_tune=nvenc_tune,
        vaapi_target_usage=vaapi_target_usage,
        qsv_target_usage=qsv_target_usage,
        rc_mode=rc_mode,
        cqp_value=cqp_value,
        key_int_max=key_int_max,
        bframes=bframes,
        ref_frames=ref_frames,
        rtp_mtu=rtp_mtu,
        queue_max_time_ns=queue_max_time_ns,
        queue_max_buffers=queue_max_buffers,
        aggregate_mode=aggregate_mode,
        udp_buffer_size=udp_buffer_size,
        show_cursor=show_cursor,
        colorimetry=colorimetry,
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
        remaining = desktop_streaming_service.unsubscribe(send_to_ws)
        if remaining == 0:
            # Stop the engine if no clients are left to prevent it from blocking the server
            # especially on Windows where zombie engines can cause IPC locks.
            await desktop_streaming_service.stop_engine()
