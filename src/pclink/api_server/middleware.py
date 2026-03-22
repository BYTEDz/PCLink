# src/pclink/api_server/middleware.py
import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core.config import config_manager
from ..core.device_manager import device_manager
from ..core.validators import ValidationError

log = logging.getLogger(__name__)

# --- Configuration for Permissions ---
SERVICE_PERMISSION_MAP = {
    "/files/browse": "files_browse",
    "/files/thumbnail": "files_browse",
    "/files/download": "files_download",
    "/files/upload": "files_upload",
    "/files/delete": "files_delete",
    "/files": "files_browse",
    "/phone/files": "files_browse",
    "/system/processes": "processes",
    "/system/power": "power",
    "/system/volume": "volume",
    "/system/wake-on-lan": "wol",
    "/system": "power",
    "/info": "info",
    "/input/mouse": "mouse",
    "/input/keyboard": "keyboard",
    "/input": "mouse",
    "/media": "media",
    "/terminal": "terminal",
    "/macro": "macros",
    "/applications": "apps",
    "/utils/clipboard": "clipboard",
    "/utils/screenshot": "screenshot",
    "/utils/command": "command",
    "/utils": "utils",
    "/api/extensions": "extensions",
    "/extensions": "extensions",
}


async def upload_optimization_middleware(request: Request, call_next):
    if request.url.path.startswith("/files/upload/"):
        response = await call_next(request)
        response.headers["content-encoding"] = "identity"
        return response
    return await call_next(request)


async def service_enforcement_middleware(request: Request, call_next):
    path = request.url.path

    # 1. Whitelist Core Endpoints (Always Allowed)
    whitelist = [
        "/heartbeat",
        "/auth/check",
        "/auth/login",
        "/status",
        "/qr-payload",
    ]
    if (
        any(path == p for p in whitelist)
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
        # --- GLOBAL SERVICE CHECK ---
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

        # --- IDENTITY EXTRACTION ---
        # 1. Check for device token (headers, query, or cookie)
        token = (
            request.headers.get("X-API-Key")
            or request.query_params.get("token")
            or request.cookies.get("pclink_device_token")
        )

        # 2. Check for web admin session
        session_token = request.cookies.get("pclink_session") or request.headers.get(
            "X-Session-Token"
        )
        is_admin = False
        if session_token:
            from ..core.web_auth import web_auth_manager

            client_ip = request.client.host if request.client else None
            if web_auth_manager.validate_session(session_token, client_ip):
                is_admin = True

        # --- PERMISSION ENFORCEMENT ---
        if is_admin:
            # Admin session bypasses device-specific permission checks
            return await call_next(request)

        if token:
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
                    # Permission granted
                    return await call_next(request)
            except ValidationError:
                pass

        # If we reached here, it's a service request with no valid identity (neither admin nor device)
        # We block it since these services REQUIRE a valid identity.
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
                if not extension_manager.get_extension(extension_id):
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
                                log.info(
                                    f"Hot-loading requested extension on-demand: {extension_id}"
                                )
                                extension_manager.failed_extensions.pop(
                                    extension_id, None
                                )
                                if extension_manager.load_extension(extension_id):
                                    return await call_next(request)
                        except Exception as e:
                            log.error(
                                f"Failed to hot-load extension {extension_id} on request: {e}"
                            )

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
