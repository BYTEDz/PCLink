# src/pclink/api_server/api.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

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
def create_api_app(controller_instance, connected_devices: Dict) -> FastAPI:
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
    app.state.connected_devices = connected_devices
    app.state.pairing_events = pairing_events
    app.state.pairing_results = pairing_results
    app.state.controller = controller_instance
    app.state.host_port = getattr(controller_instance, "port", 38080)
    from .routers.dependencies import MOBILE_API, WEB_AUTH

    # 5. Extension System (Initialize Early for Startup Tasks)
    from ..core.extension_manager import ExtensionManager

    extension_manager = ExtensionManager()
    extension_manager.app = app
    app.state.extension_manager = extension_manager

    # 1. Startup Logic (Restoration & Cleanup)
    @app.on_event("startup")
    async def startup_event():
        from .routers.transfers import (
            cleanup_stale_sessions,
            restore_sessions_startup,
        )

        try:
            result = await restore_sessions_startup()
            log.info(
                f"Session restoration: {result['restored_uploads']} up, {result['restored_downloads']} down"
            )

            async def periodic_cleanup():
                from ..core.config import config_manager

                while True:
                    await asyncio.sleep(3600)
                    try:
                        th = config_manager.get("transfer_cleanup_threshold", 7)
                        await cleanup_stale_sessions(days=th)
                    except Exception as e:
                        log.error(f"Cleanup failed: {e}")

            asyncio.create_task(periodic_cleanup())
        except Exception as e:
            log.error(f"Startup restoration failed: {e}")

        # Start WebSocket Broadcast Task
        from .routers.websocket_routes import broadcast_updates_task

        asyncio.create_task(broadcast_updates_task(mobile_manager, app.state))

        # Reset extension crash counter
        extension_manager.mark_startup_success()

    # 2. Global Middleware
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # 3. Router Registration
    # - Services & Settings
    app.include_router(
        services_router,
        prefix="/ui/services",
        tags=["Services"],
        dependencies=[WEB_AUTH],
    )

    # - UI/Static Root Redirect
    @app.get("/")
    def root():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/ui/")

    # - NEW: Modularized Routers
    from .routers.auth import router as auth_router
    from .routers.devices import router as devices_router, get_connected_devices
    from .routers.pairing import (
        mgmt_router as pairing_mgmt,
        mobile_router as pairing_mobile,
    )
    from .routers.server import core_router as server_core, mgmt_router as server_mgmt
    from .routers.websocket_routes import router as ws_router

    # Root Level (Match UI Expectations)
    app.include_router(auth_router)  # /auth/...
    app.include_router(server_core)  # /heartbeat, /announce...
    app.include_router(server_mgmt)  # /status, /logs, /ui/pairing/list...

    # UI Prefixed
    app.include_router(devices_router)  # /ui/devices/...
    app.include_router(pairing_mgmt)  # /ui/pairing/...
    app.include_router(pairing_mobile)  # /pairing/...

    # Aliases for UI Compatibility (Force /ui/devices without slash)
    @app.get("/ui/devices", dependencies=[WEB_AUTH])
    async def ui_devices_alias(request: Request):
        return await get_connected_devices(request)

    @app.get("/settings/defaults/permissions", dependencies=[WEB_AUTH])
    async def ui_default_perms_alias():
        from .routers.devices import get_default_permissions

        return await get_default_permissions()

    @app.post("/settings/defaults/permissions", dependencies=[WEB_AUTH])
    async def ui_update_default_perms_alias(payload: Dict[str, Any]):
        from .routers.devices import update_default_permissions

        return await update_default_permissions(payload)

    app.include_router(ws_router)  # /ws, /ws/ui

    # - Services Support
    @app.get("/ui/services/list", dependencies=[WEB_AUTH])
    async def list_services_states():
        from ..core.config import config_manager

        return {"services": config_manager.get("services", {})}

    # - Core Domain Routers
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
    app.include_router(create_terminal_router(), prefix="/terminal", tags=["Terminal"])
    app.include_router(
        macro_router, prefix="/macro", tags=["Macros"], dependencies=MOBILE_API
    )
    app.include_router(
        applications_router,
        prefix="/applications",
        tags=["Apps"],
        dependencies=MOBILE_API,
    )

    # 4. Web UI & Extensions
    try:
        from ..web_ui.router import create_web_ui_router

        web_ui_router = create_web_ui_router(app)
        app.include_router(web_ui_router, prefix="/ui")
    except Exception as e:
        log.warning(f"Web UI failed to load: {e}")

    # 5. Extension Loading
    extension_manager.load_all_extensions()

    app.include_router(mgmt_router, prefix="/api/extensions", dependencies=MOBILE_API)
    app.include_router(runtime_router, prefix="/extensions", dependencies=MOBILE_API)
    app.include_router(mgmt_router, prefix="/ui/extensions", dependencies=[WEB_AUTH])

    from .middleware import setup_app_middleware

    setup_app_middleware(app, extension_manager)

    return app
