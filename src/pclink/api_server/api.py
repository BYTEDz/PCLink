# src/pclink/api_server/api.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
from typing import Any, Dict

from fastapi import (
    FastAPI,
    HTTPException,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from ..core.device_manager import device_manager
from ..core.extension_manager import ExtensionManager
from ..web_ui.router import create_web_ui_router
from .routers.applications import router as applications_router
from .routers.extensions import mgmt_router, runtime_router

# --- API Router Imports ---
from .routers.file_browser import router as file_browser_router
from .routers.info import router as info_router
from .routers.input import router as input_router
from .routers.macros import router as macro_router
from .routers.media import router as media_router
from .routers.media_streaming import router as media_streaming_router
from .routers.phone_files import router as phone_file_router
from .routers.processes import router as process_manager_router
from .routers.services_management import router as services_router
from .routers.system import router as system_router
from .routers.terminal import create_terminal_router

# UPDATED: Import from the new transfers package
from .routers.transfers import (
    download_router,
    upload_router,
)
from .routers.utils import router as utils_router

log = logging.getLogger(__name__)


# --- Pydantic Models ---

# --- Pairing State ---
pairing_events: Dict[str, asyncio.Event] = {}
pairing_results: Dict[str, dict] = {}

# --- WebSocket Command Handlers ---


# --- FastAPI App Factory ---
def create_api_app(
    controller_instance, connected_devices: Dict, allow_insecure_shell: bool
) -> FastAPI:
    app = FastAPI(
        title="PCLink API",
        version="8.9.5",
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=lambda route: (
            f"{route.tags[0]}-{route.name}" if route.tags else route.name
        ),
    )

    from .ws_manager import mobile_manager, ui_manager

    # Expose managers to state for access in routers
    app.state.mobile_manager = mobile_manager
    app.state.ui_manager = ui_manager

    controller = controller_instance
    app.state.controller = controller_instance

    from .routers.dependencies import (
        MOBILE_API,
        WEB_AUTH,
    )

    # Validation dependencies are now imported from .routers.dependencies
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    terminal_router = create_terminal_router()

    try:
        web_ui_router = create_web_ui_router(app)
        app.include_router(web_ui_router, prefix="/ui")
        log.info("Web UI enabled at /ui/")
    except Exception as e:
        log.warning(f"Web UI could not be loaded: {e}")
        error_str = str(e)

        @app.get("/ui/")
        async def web_ui_fallback():
            return {"message": "Web UI not available", "error": error_str}

    # --- Service Management ---
    app.include_router(
        services_router,
        prefix="/ui/services",
        tags=["Services"],
        dependencies=[WEB_AUTH],
    )

    @app.get("/ui/services/list", dependencies=[WEB_AUTH])
    async def list_services_states():
        from ..core.config import config_manager

        return {"services": config_manager.get("services", {})}

    @app.get("/settings/defaults/permissions", dependencies=[WEB_AUTH])
    async def get_default_permissions():
        from ..core.config import config_manager

        return {"permissions": config_manager.get("default_device_permissions", [])}

    @app.post("/settings/defaults/permissions", dependencies=[WEB_AUTH])
    async def update_default_permissions(payload: Dict[str, Any]):
        from ..core.config import config_manager

        perms = payload.get("permissions", [])
        config_manager.set("default_device_permissions", perms)
        return {"status": "success"}

    # --- NEW: Device Permission Management ---
    @app.post("/devices/{device_id}/permissions", dependencies=[WEB_AUTH])
    async def update_device_permissions(device_id: str, payload: Dict[str, Any]):
        """Update specific permission node for a device."""
        perm = payload.get("permission")
        enabled = payload.get("enabled", False)

        device = device_manager.get_device_by_id(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        current_perms = set(device.permissions)
        if enabled:
            current_perms.add(perm)
        else:
            current_perms.discard(perm)

        device.permissions = list(current_perms)
        device_manager._save_device(device)

        log.info(f"Updated permissions for {device.device_name}: {perm}={enabled}")

        # Proactively notify the device via WebSocket
        from ..core.config import config_manager

        await mobile_manager.send_to_device(
            device_id,
            {
                "type": "UPDATE_STATE",
                "services": config_manager.get("services", {}),
                "permissions": device.permissions,
            },
        )

        return {"status": "success", "permissions": device.permissions}

    # --- Register Routers (ORDER MATTERS) ---
    app.include_router(
        upload_router, prefix="/files/upload", tags=["Uploads"], dependencies=MOBILE_API
    )
    app.include_router(
        download_router,
        prefix="/files/download",
        tags=["Downloads"],
        dependencies=MOBILE_API,
    )
    app.include_router(
        file_browser_router, prefix="/files", tags=["Files"], dependencies=MOBILE_API
    )
    app.include_router(
        phone_file_router,
        prefix="/phone/files",
        tags=["Phone Files"],
        dependencies=MOBILE_API,
    )

    app.include_router(
        system_router, prefix="/system", tags=["System"], dependencies=MOBILE_API
    )
    app.include_router(
        media_streaming_router,
        prefix="/files",
        tags=["Streaming"],
        dependencies=MOBILE_API,
    )
    app.include_router(
        process_manager_router,
        prefix="/system",
        tags=["Processes"],
        dependencies=MOBILE_API,
    )
    app.include_router(
        info_router, prefix="/info", tags=["Info"], dependencies=MOBILE_API
    )
    app.include_router(
        input_router, prefix="/input", tags=["Input"], dependencies=MOBILE_API
    )
    app.include_router(
        media_router, prefix="/media", tags=["Media"], dependencies=MOBILE_API
    )
    app.include_router(
        utils_router, prefix="/utils", tags=["Utils"], dependencies=MOBILE_API
    )
    app.include_router(terminal_router, prefix="/terminal", tags=["Terminal"])
    app.include_router(
        macro_router, prefix="/macro", tags=["Macros"], dependencies=MOBILE_API
    )
    app.include_router(
        applications_router,
        prefix="/applications",
        tags=["Apps"],
        dependencies=MOBILE_API,
    )

    # --- Extension System ---
    extension_manager = ExtensionManager()

    # Enable dynamic mounting for extensions loaded now or later
    extension_manager.app = app

    # Extension management (accessible by mobile app)
    app.include_router(mgmt_router, prefix="/api/extensions", dependencies=MOBILE_API)

    # Extension runtime (UI/Static) - Authenticated unique per extension ID
    app.include_router(runtime_router, prefix="/extensions", dependencies=MOBILE_API)

    # Load all enabled extensions at startup
    extension_manager.load_all_extensions()

    app.state.allow_insecure_shell = allow_insecure_shell

    from .middleware import setup_app_middleware

    setup_app_middleware(app, extension_manager)

    from .routers.core_routes import mount_core_routes

    mount_core_routes(
        app,
        controller,
        connected_devices,
        allow_insecure_shell,
        pairing_events,
        pairing_results,
        extension_manager,
    )

    return app
