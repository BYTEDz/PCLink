# src/pclink/api_server/routers/dependencies.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
from typing import Optional, Union

from fastapi import Depends, Header, HTTPException, Query, Request, WebSocket

from ...core.device_manager import Device, device_manager
from ...core.share_manager import share_manager
from ...core.web_auth import web_auth_manager

log = logging.getLogger(__name__)
_ = gettext.gettext


def extract_token(
    conn: Union[Request, WebSocket],
    x_api_key: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """Centralized helper to extract device API key/token from headers, query parameters, or cookies."""
    if x_api_key:
        return x_api_key
    if token:
        return token
    if hasattr(conn, "query_params"):
        query_key = (
            conn.query_params.get("token")
            or conn.query_params.get("x-api-key")
            or conn.query_params.get("api_key")
        )
        if query_key:
            return query_key
    if hasattr(conn, "headers"):
        header_key = conn.headers.get("X-API-Key") or conn.headers.get("x-api-key")
        if header_key:
            return header_key
    if hasattr(conn, "cookies"):
        cookie_key = conn.cookies.get("pclink_device_token")
        if cookie_key:
            return cookie_key
    return None


async def verify_web_session(request: Request) -> bool:
    """Verifies active web admin session or internal CLI access."""
    # 1. Check for Internal/CLI authentication (only from localhost)
    if request.client and request.client.host in ("127.0.0.1", "::1"):
        if request.headers.get("X-Internal-Auth") == "true":
            return True

    # 2. Check for traditional session tokens
    session_token = request.cookies.get("pclink_session") or request.headers.get(
        "X-Session-Token"
    )
    if not session_token:
        raise HTTPException(status_code=401, detail=_("No session token"))

    client_ip = request.client.host if request.client else None
    if not web_auth_manager.validate_session(session_token, client_ip):
        raise HTTPException(status_code=401, detail=_("Invalid or expired session"))
    return True


WEB_AUTH = Depends(verify_web_session)


async def get_authenticated_device(
    request: Request,
    x_api_key: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> Device:
    """Core dependency returning the authenticated and approved Device instance."""
    key = extract_token(request, x_api_key, token)
    if not key:
        raise HTTPException(status_code=401, detail=_("Missing API Key"))

    device = device_manager.get_device_by_api_key(key)
    if device and device.is_approved:
        if request.client:
            client_ip = request.client.host
            if device.current_ip != client_ip:
                device_manager.update_device_ip(device.device_id, client_ip)
            else:
                device_manager.update_device_last_seen(device.device_id)
        return device

    raise HTTPException(status_code=403, detail="DEVICE_REVOKED")


async def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> bool:
    """Dependency verifying API key or active web session for general endpoints."""
    # Bypass for file downloads with valid share tokens
    if request.url.path.startswith("/files/download"):
        req_path = request.query_params.get("path")
        req_token = extract_token(request, x_api_key, token)
        if (
            req_token
            and req_path
            and share_manager.validate_share_token(req_token, req_path)
        ):
            return True

    key = extract_token(request, x_api_key, token)
    if key:
        device = device_manager.get_device_by_api_key(key)
        if device and device.is_approved:
            if request.client:
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

    raise HTTPException(status_code=403, detail=_("Missing Token or session"))


def verify_mobile_api_enabled(request: Request) -> bool:
    """Verifies that Mobile API server connectivity is active."""
    controller = getattr(request.app.state, "controller", None)
    if not (
        controller
        and hasattr(controller, "mobile_api_enabled")
        and controller.mobile_api_enabled
    ):
        log.warning(
            "Mobile API endpoint accessed but API is disabled. (Setup not complete?)"
        )
        raise HTTPException(
            status_code=503, detail=_("Mobile API is currently disabled.")
        )
    return True


MOBILE_API = [Depends(verify_api_key), Depends(verify_mobile_api_enabled)]
