# src/pclink/api_server/routers/dependencies.py
import logging

from fastapi import Depends, Header, HTTPException, Query, Request

from ...core.device_manager import device_manager
from ...core.web_auth import web_auth_manager

log = logging.getLogger(__name__)


async def verify_web_session(request: Request):
    session_token = request.cookies.get("pclink_session")
    if not session_token:
        session_token = request.headers.get("X-Session-Token")
    if not session_token:
        raise HTTPException(status_code=401, detail="No session token")

    client_ip = request.client.host if request.client else None
    if not web_auth_manager.validate_session(session_token, client_ip):
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return True


WEB_AUTH = Depends(verify_web_session)


async def verify_api_key(
    x_api_key: str = Header(None), token: str = Query(None), request: Request = None
):
    key = x_api_key or token
    if not key and request:
        key = request.cookies.get("pclink_device_token")

    if key:
        device = device_manager.get_device_by_api_key(key)
        if device and device.is_approved:
            if request and request.client:
                client_ip = request.client.host
                if device.current_ip != client_ip:
                    device_manager.update_device_ip(device.device_id, client_ip)
                else:
                    device_manager.update_device_last_seen(device.device_id)
            return True
        raise HTTPException(status_code=403, detail="DEVICE_REVOKED")

    try:
        if await verify_web_session(request):
            return True
    except HTTPException:
        pass

    raise HTTPException(status_code=403, detail="Missing Token or session")


def verify_mobile_api_enabled(request: Request):
    # safely fetch controller from app state
    controller = getattr(request.app.state, "controller", None)
    if not (
        controller
        and hasattr(controller, "mobile_api_enabled")
        and controller.mobile_api_enabled
    ):
        log.warning(
            "Mobile API endpoint accessed but API is disabled. (Setup not complete?)"
        )
        raise HTTPException(status_code=503, detail="Mobile API is currently disabled.")
    return True


MOBILE_API = [Depends(verify_api_key), Depends(verify_mobile_api_enabled)]
