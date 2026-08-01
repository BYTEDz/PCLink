# src/pclink/api_server/api.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import logging
import shutil
import time
from typing import Any, Dict

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .routers.applications import router as applications_router
from .routers.extensions import mgmt_router, runtime_router

# --- API Router Imports ---
from .routers.file_browser import router as file_browser_router
from .routers.input import router as input_router
from .routers.macros import router as macro_router
from .routers.media import router as media_router
from .routers.phone_files import router as phone_file_router
from .routers.services_management import router as services_router
from .routers.system import info_router, system_router
from .routers.terminal import create_terminal_router

from .routers.transfers import (
    download_router,
    upload_router,
)
from .routers.utils import router as utils_router
from ..services.pairing_service import pairing_service
from ..core.validators import PCLinkError, SecurityError

log = logging.getLogger(__name__)
_ = gettext.gettext


# --- FastAPI App Factory ---
def create_api_app(controller_instance, connected_devices: Dict) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
        from ..services.system_service import system_service
        from .ws_manager import mobile_manager, ui_manager

        asyncio.create_task(system_service.start_background_collection())
        asyncio.create_task(
            broadcast_updates_task(mobile_manager, ui_manager, app.state)
        )

        # Reset extension crash counter
        app.state.extension_manager.mark_startup_success()

        # Non-blocking extension loader
        async def background_extension_loader():
            log.info(_("Initiating background loading for server extensions..."))
            start_t = time.time()
            await asyncio.to_thread(app.state.extension_manager.load_all_extensions)
            dur = round(time.time() - start_t, 2)
            log.info(_("Extensions loaded in background in {} seconds.").format(dur))

        asyncio.create_task(background_extension_loader())

        yield

    app = FastAPI(
        title="PCLink API",
        version="4.6.1",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        generate_unique_id_function=lambda route: (
            f"{route.tags[0]}-{route.name}" if route.tags else route.name
        ),
    )

    # --- Global Exception Handlers ---
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def not_found_error_handler(request: Request, exc: FileNotFoundError):
        return JSONResponse(
            status_code=404, content={"detail": _("File or directory not found")}
        )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError):
        return JSONResponse(status_code=403, content={"detail": _("Permission denied")})

    @app.exception_handler(FileExistsError)
    async def file_exists_error_handler(request: Request, exc: FileExistsError):
        return JSONResponse(
            status_code=409, content={"detail": _("Target already exists")}
        )

    @app.exception_handler(NotADirectoryError)
    async def not_a_dir_error_handler(request: Request, exc: NotADirectoryError):
        return JSONResponse(
            status_code=400, content={"detail": _("Target is not a directory")}
        )

    @app.exception_handler(shutil.SameFileError)
    async def same_file_error_handler(request: Request, exc: shutil.SameFileError):
        return JSONResponse(status_code=409, content={"detail": "SOURCE_IS_DEST"})

    @app.exception_handler(PCLinkError)
    async def pclink_error_handler(request: Request, exc: PCLinkError):
        status_code = 403 if isinstance(exc, SecurityError) else 400
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    from .ws_manager import mobile_manager, ui_manager
    from ..core.device_manager import device_manager
    from ..core.share_manager import share_manager
    from ..core.web_auth import web_auth_manager
    from ..core.config import config_manager

    # Register managers and core services on app state
    app.state.mobile_manager = mobile_manager
    app.state.ui_manager = ui_manager
    app.state.connected_devices = connected_devices
    app.state.pairing_events = pairing_service.pairing_events
    app.state.pairing_results = pairing_service.pairing_results
    app.state.pairing_service = pairing_service
    app.state.device_manager = device_manager
    app.state.share_manager = share_manager
    app.state.web_auth_manager = web_auth_manager
    app.state.config_manager = config_manager
    app.state.controller = controller_instance
    app.state.host_port = getattr(controller_instance, "port", 38080)
    from .routers.dependencies import MOBILE_API, WEB_AUTH

    # Extension System (Initialize Early for State Setup)
    from ..core.extension_manager import ExtensionManager

    extension_manager = ExtensionManager()
    extension_manager.app = app
    app.state.extension_manager = extension_manager

    # Hardened CORS Middleware: Restrict cross-origin access to local/LAN IP addresses with credential support
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Router Registration
    app.include_router(
        services_router,
        prefix="/ui/services",
        tags=["Services"],
        dependencies=[WEB_AUTH],
    )

    @app.get("/")
    def root():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/ui/")

    # Modularized Routers
    from .routers.auth import router as auth_router
    from .routers.devices import router as devices_router, get_connected_devices
    from .routers.pairing import (
        mgmt_router as pairing_mgmt,
        mobile_router as pairing_mobile,
    )
    from .routers.repair import router as repair_router
    from .routers.server import core_router as server_core, mgmt_router as server_mgmt
    from .routers.websocket_routes import router as ws_router

    app.include_router(auth_router)
    app.include_router(server_core)
    app.include_router(server_mgmt)

    app.include_router(devices_router)
    app.include_router(pairing_mgmt)
    app.include_router(pairing_mobile)
    app.include_router(repair_router, prefix="/ui/repair", dependencies=[WEB_AUTH])

    @app.get("/ui/devices", dependencies=[WEB_AUTH])
    async def ui_devices_alias(
        request: Request,
        include_unapproved: bool = Query(False),
    ):
        return await get_connected_devices(
            request, include_unapproved=include_unapproved
        )

    @app.get("/settings/defaults/permissions", dependencies=[WEB_AUTH])
    async def ui_default_perms_alias():
        from .routers.devices import get_default_permissions

        return await get_default_permissions()

    @app.post("/settings/defaults/permissions", dependencies=[WEB_AUTH])
    async def ui_update_default_perms_alias(payload: Dict[str, Any]):
        from .routers.devices import update_default_permissions

        return await update_default_permissions(payload)

    app.include_router(ws_router)

    @app.get("/ui/services/list", dependencies=[WEB_AUTH])
    async def list_services_states():
        return {"services": config_manager.get("services", {})}

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

    from .routers.desktop_streaming import router as desktop_streaming_router

    app.include_router(desktop_streaming_router)

    try:
        from ..web_ui.router import create_web_ui_router

        web_ui_router = create_web_ui_router(app)
        app.include_router(web_ui_router, prefix="/ui")
    except Exception as e:
        log.warning(f"Web UI failed to load: {e}")

    app.include_router(mgmt_router, prefix="/api/extensions", dependencies=MOBILE_API)
    app.include_router(runtime_router, prefix="/extensions", dependencies=MOBILE_API)
    app.include_router(mgmt_router, prefix="/ui/extensions", dependencies=[WEB_AUTH])

    from .middleware import setup_app_middleware

    setup_app_middleware(app, extension_manager)

    return app
