# src/pclink/api_server/middleware.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core.config import config_manager
from ..core.device_manager import device_manager
from ..core.share_manager import share_manager
from ..core.validators import ValidationError
from .routers.dependencies import extract_token

log = logging.getLogger(__name__)

# --- Configuration for Permissions ---
SERVICE_PERMISSION_MAP = {
    "/files/upload": "files_write",
    "/files/delete": "files_write",
    "/files/compress": "files_write",
    "/files/extract": "files_write",
    "/files/create-folder": "files_write",
    "/files/rename": "files_write",
    "/files/batch-rename": "files_write",
    "/files/paste": "files_write",
    "/files/browse": "files_read",
    "/files/thumbnail": "files_read",
    "/files/download": "files_read",
    "/files/media-info": "files_read",
    "/files/stream": "files_read",
    "/files": "files_read",
    "/phone/files": "files_read",
    "/system/processes": "processes",
    "/system/power": "power",
    "/system/volume": "media",
    "/system": "power",
    "/info": "info",
    "/input": "input",
    "/media": "media",
    "/terminal": "terminal",
    "/macro": "macros",
    "/applications": "apps",
    "/utils/clipboard": "input",
    "/utils/screenshot": "screenshot",
    "/utils/command": "terminal",
    "/utils": "input",
    "/api/extensions": "extensions",
    "/extensions": "extensions",
    "/desktop-streaming": "desktop_streaming",
}


async def upload_optimization_middleware(request: Request, call_next):
    if request.url.path.startswith("/files/upload/"):
        response = await call_next(request)
        response.headers["content-encoding"] = "identity"
        return response
    return await call_next(request)


async def service_enforcement_middleware(request: Request, call_next):
    path = request.url.path

    # 1. Whitelist Core Endpoints (Always Allowed - includes Wake-on-LAN)
    whitelist = [
        "/heartbeat",
        "/auth/check",
        "/auth/login",
        "/status",
        "/qr-payload",
        "/system/wake-on-lan",
    ]
    if (
        any(path.startswith(p) for p in whitelist)
        or (path.startswith("/ui") and not path.startswith("/ui/services"))
        or path.startswith("/static")
    ):
        return await call_next(request)

    # 2. Identify Target Service
    target_service = None
    for prefix, name in SERVICE_PERMISSION_MAP.items():
        if path.startswith(prefix):
            target_service = name
            break

    if target_service:
        global_services = config_manager.get("services", {})
        if not global_services.get(target_service, True):
            log.warning(
                f"Blocking request to globally disabled service '{target_service}': {path}"
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"The '{target_service}' service is currently disabled globally.",
                    "service": target_service,
                    "action": "ENABLE_SERVICE_IN_UI",
                },
            )

        token = extract_token(request)

        session_token = request.cookies.get("pclink_session") or request.headers.get(
            "X-Session-Token"
        )
        is_admin = False
        if session_token:
            from ..core.web_auth import web_auth_manager

            client_ip = request.client.host if request.client else None
            if web_auth_manager.validate_session(session_token, client_ip):
                is_admin = True

        if is_admin:
            return await call_next(request)

        if token:
            if path.startswith("/files/download"):
                req_path = request.query_params.get("path")
                if req_path and share_manager.validate_share_token(token, req_path):
                    return await call_next(request)

            try:
                device = device_manager.get_device_by_api_key(token)
                if device:
                    if target_service not in device.permissions:
                        log.warning(
                            f"Device '{device.device_name}' ({device.device_id}) denied access to '{target_service}'"
                        )
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": "PERMISSION_DENIED",
                                "required": target_service,
                            },
                        )
                    return await call_next(request)
            except ValidationError:
                pass

        return JSONResponse(
            status_code=403,
            content={"detail": "AUTHENTICATION_REQUIRED", "service": target_service},
        )

    return await call_next(request)


def create_extension_middleware(extension_manager: Any):
    async def extension_runtime_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/extensions/") and not path.startswith("/api/extensions"):
            parts = path.split("/")
            if len(parts) > 2:
                extension_id = parts[2]
                is_active = (
                    extension_manager.get_extension(extension_id) is not None
                    or extension_id in extension_manager.isolated_processes
                )
                if not is_active:
                    manifest_path = (
                        extension_manager.extensions_path
                        / extension_id
                        / "extension.yaml"
                    )
                    if manifest_path.exists():
                        try:
                            import yaml

                            with open(manifest_path, "r", encoding="utf-8") as f:
                                config = yaml.safe_load(f)
                            if config.get("enabled", True):
                                extension_manager.failed_extensions.pop(
                                    extension_id, None
                                )
                                if extension_manager.load_extension(extension_id):
                                    return await call_next(request)
                        except Exception as e:
                            log.error(
                                f"Failed to hot-load extension {extension_id} on request: {e}"
                            )

                    if not path.endswith("/icon"):
                        log.warning(
                            f"Blocking request to disabled or unknown extension: {extension_id} (Path: {path})"
                        )
                    return JSONResponse(
                        status_code=404,
                        content={"detail": f"Extension '{extension_id}' Not Found"},
                    )
        return await call_next(request)

    return extension_runtime_middleware


def setup_app_middleware(app: Any, extension_manager: Any):
    app.middleware("http")(create_extension_middleware(extension_manager))
    app.middleware("http")(service_enforcement_middleware)
    app.middleware("http")(upload_optimization_middleware)
