# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import re
import urllib.parse
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from ..core.config import config_manager
from ..core.device_manager import device_manager
from ..core.e2ee import decrypt_payload, derive_e2ee_key, encrypt_payload
from ..core.extension_db import extension_db
from ..core.share_manager import share_manager
from ..core.validators import ValidationError
from .routers.dependencies import extract_token

log = logging.getLogger(__name__)

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

# Endpoints strictly blocked from receiving traffic over WAN relays
WAN_BLOCKED_PREFIXES = (
    "/pairing",
    "/relay/activate",
    "/qr-payload",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/factory-reset",
    "/open-data-dir",
    "/desktop-streaming",
    "/audio",
    "/system/wake-on-lan",
)

# Endpoints permitted in plaintext over WAN (unauthenticated probes, chunk streams, raw PTY WebSockets, static assets)
WAN_PLAINTEXT_WHITELIST = (
    "/heartbeat",
    "/status",
    "/files/download/chunk/",
    "/terminal",
    "/static",
    "/favicon.ico",
)

# Regex matching strictly static extension UI templates and assets:
# e.g., /extensions/<id>/ui, /extensions/<id>/widget/<id>, /extensions/<id>/icon, /extensions/sdk/*
_EXTENSION_STATIC_ASSET_REGEX = re.compile(
    r"^/extensions/(?:sdk/[^/]+|[^/]+/(?:ui|widget/[^/]+|icon))(?:/.*)?$"
)


def _is_wan_plaintext_allowed(method: str, path: str) -> bool:
    """
    Strictly permits only read-only static probes, application icons, and extension runtime/worker requests over WAN.
    All broker RPCs (/broker/) and admin mutations are strictly rejected unless protected by X-PCLink-E2EE.
    """
    if any(path.startswith(w) for w in WAN_PLAINTEXT_WHITELIST):
        return True

    if method in ("GET", "OPTIONS"):
        # Allow streaming application icons in plaintext
        if path.startswith("/api/applications/icon") or path.startswith(
            "/applications/icon"
        ):
            return True

        # Strictly block broker RPCs (must be E2EE)
        if "/broker/" in path or path.startswith("/extensions/broker"):
            return False

        # Allow extension runtime UI, static assets, and isolated worker GET/OPTIONS requests
        if path.startswith("/extensions/"):
            return True

        return False

    return False


async def upload_optimization_middleware(request: Request, call_next):
    if request.url.path.startswith("/files/upload/"):
        response = await call_next(request)
        response.headers["content-encoding"] = "identity"
        return response
    return await call_next(request)


async def e2ee_payload_middleware(request: Request, call_next):
    """
    Transparently decrypts incoming request payloads and encrypts outgoing responses
    when X-PCLink-E2EE: gcm-v1 is present. Enforces zero-trust on Cloudflare WAN tunnels.
    """
    path = request.url.path
    is_wan_relay = "cf-ray" in request.headers or "cf-connecting-ip" in request.headers
    has_e2ee = (
        request.headers.get("X-PCLink-E2EE") == "gcm-v1"
        or request.headers.get("x-pclink-e2ee") == "gcm-v1"
    )

    # 1. Reject LAN-only endpoints arriving over the WAN relay
    if is_wan_relay and any(path.startswith(prefix) for prefix in WAN_BLOCKED_PREFIXES):
        log.warning(f"BLOCKED: LAN-only endpoint accessed over WAN relay: {path}")
        return JSONResponse(
            status_code=403,
            content={"detail": "ENDPOINT_FORBIDDEN_OVER_WAN"},
        )

    # 2. Enforce Zero-Trust: All WAN requests (mutations and confidential GET queries) must be E2EE
    if is_wan_relay and not has_e2ee:
        if not _is_wan_plaintext_allowed(request.method, path):
            log.warning(
                f"BLOCKED: Plaintext request received over WAN tunnel without E2EE: {request.method} {path}"
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "E2EE_REQUIRED_OVER_WAN"},
            )

    if not has_e2ee:
        return await call_next(request)

    token = extract_token(request)
    if not token:
        return await call_next(request)

    device = device_manager.get_device_by_api_key(token)
    if not device:
        return await call_next(request)

    aes_key = derive_e2ee_key(device.api_key)

    # 3. Decrypt incoming body if present
    body_bytes = await request.body()
    if body_bytes:
        try:
            decrypted_body = decrypt_payload(body_bytes, aes_key)

            # Re-bind the ASGI stream so Pydantic and route handlers read the decrypted data
            async def receive():
                return {
                    "type": "http.request",
                    "body": decrypted_body,
                    "more_body": False,
                }

            request._receive = receive
            request._body = decrypted_body

            # Check if decrypted payload is JSON or raw binary (for file chunks)
            is_json = False
            stripped = decrypted_body.strip()
            if stripped and (stripped[:1] in (b"{", b"[") or stripped == b"null"):
                is_json = True

            raw_headers = list(request.scope.get("headers", []))
            new_headers = []
            for k, v in raw_headers:
                k_lower = k.lower()
                if k_lower == b"content-type":
                    if is_json:
                        new_headers.append(
                            (b"content-type", b"application/json; charset=utf-8")
                        )
                    else:
                        new_headers.append(
                            (b"content-type", b"application/octet-stream")
                        )
                elif k_lower == b"content-length":
                    new_headers.append(
                        (b"content-length", str(len(decrypted_body)).encode("ascii"))
                    )
                else:
                    new_headers.append((k, v))
            request.scope["headers"] = new_headers

        except Exception as e:
            log.error(f"E2EE Decryption failure on {path}: {e}")
            return JSONResponse(
                status_code=400,
                content={"detail": "E2EE_DECRYPTION_FAILED"},
            )

    # 4. Call route handler
    response = await call_next(request)

    # 5. Encrypt response body if returning content
    if response.status_code < 400 and hasattr(response, "body") and response.body:
        try:
            encrypted_content = encrypt_payload(response.body, aes_key)
            headers = dict(response.headers)
            headers["X-PCLink-E2EE"] = "gcm-v1"
            headers["Content-Length"] = str(len(encrypted_content))
            headers["Content-Type"] = "application/octet-stream"

            return Response(
                content=encrypted_content,
                status_code=response.status_code,
                headers=headers,
                media_type="application/octet-stream",
            )
        except Exception as e:
            log.error(f"E2EE Response encryption failure on {path}: {e}")
            return response

    return response


async def service_enforcement_middleware(request: Request, call_next):
    path = request.url.path

    whitelist = [
        "/heartbeat",
        "/auth/check",
        "/auth/login",
        "/status",
        "/qr-payload",
        "/system/wake-on-lan",
        "/favicon.ico",
        "/extensions/sdk",
        "/extensions/theme",
    ]
    if (
        any(path.startswith(p) for p in whitelist)
        or (path.startswith("/ui") and not path.startswith("/ui/services"))
        or path.startswith("/static")
    ):
        return await call_next(request)

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
                raw_identifier = parts[2]
                extension_id = urllib.parse.unquote(raw_identifier)

                if extension_id in ("sdk", "theme"):
                    return await call_next(request)

                if not extension_manager.is_extension_active(extension_id):
                    manifest = extension_manager.get_manifest(extension_id)
                    if manifest:
                        target_id = manifest.get("id") or extension_id
                        state = extension_db.get_state(target_id)
                        if state is None or (
                            state.get("enabled", True)
                            and not state.get("quarantined", False)
                        ):
                            extension_manager.failed_extensions.pop(target_id, None)
                            if extension_manager.load_extension(target_id):
                                return await call_next(request)

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
    app.middleware("http")(e2ee_payload_middleware)
    app.middleware("http")(upload_optimization_middleware)
