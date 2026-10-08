# src/pclink/api_server/routers/services_management.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core.config import DEFAULT_SETTINGS, config_manager
from ...core.extension_manager import ExtensionManager

log = logging.getLogger(__name__)
router = APIRouter()

SERVICE_INFO = {
    "files_read": {
        "title": "File Access (Read)",
        "icon": "folder",
        "description": "Browse system files and download contents.",
    },
    "files_write": {
        "title": "File Access (Write)",
        "icon": "edit-3",
        "description": "Upload, rename, move, and delete files.",
    },
    "input": {
        "title": "Remote Input & Clipboard",
        "icon": "mouse-pointer",
        "description": "Control cursor, keyboard typing, and sync clipboard.",
    },
    "media": {
        "title": "Media & Volume Control",
        "icon": "play-circle",
        "description": "Control media playback and system master volume.",
    },
    "apps": {
        "title": "Applications",
        "icon": "grid",
        "description": "View and launch installed applications.",
    },
    "processes": {
        "title": "Processes",
        "icon": "activity",
        "description": "View and manage running system processes.",
    },
    "power": {
        "title": "Power Control",
        "icon": "power",
        "description": "Shutdown, restart, sleep, or lock the system.",
    },
    "info": {
        "title": "System Status",
        "icon": "info",
        "description": "Monitor battery and hardware status.",
    },
    "screenshot": {
        "title": "Screen Capture",
        "icon": "camera",
        "description": "Capture system screen snapshots.",
    },
    "macros": {
        "title": "Macros",
        "icon": "zap",
        "description": "Execute automated task scripts.",
    },
    "extensions": {
        "title": "Extensions",
        "icon": "package",
        "description": "Manage and run server extensions.",
    },
    "desktop_streaming": {
        "title": "Desktop Streaming",
        "icon": "monitor",
        "description": "Stream device screen to connected device.",
    },
    "terminal": {
        "title": "Terminal & Shell",
        "icon": "terminal",
        "description": "Direct shell and terminal access (High Risk).",
    },
}


class ServiceToggle(BaseModel):
    name: str
    enabled: bool


@router.get("/")
async def get_services():
    """Returns the list of all 13 canonical services and their current status."""
    services = DEFAULT_SETTINGS["services"].copy()
    services.update(config_manager.get("services", {}))

    result = []
    # Always iterate over SERVICE_INFO to guarantee all 13 canonical permissions are returned
    for name, info in SERVICE_INFO.items():
        enabled = services.get(name, DEFAULT_SETTINGS["services"].get(name, True))
        result.append(
            {
                "id": name,
                "title": info["title"],
                "icon": info["icon"],
                "description": info["description"],
                "enabled": enabled,
            }
        )

    return {"services": result}


@router.post("/toggle")
async def toggle_service(payload: ServiceToggle, request: Request):
    """Enables or disables a specific service."""
    services = DEFAULT_SETTINGS["services"].copy()
    services.update(config_manager.get("services", {}))

    if payload.name not in SERVICE_INFO and payload.name not in services:
        raise HTTPException(
            status_code=404, detail=f"Service '{payload.name}' not found."
        )

    services[payload.name] = payload.enabled
    config_manager.set("services", services)

    log.info(
        f"Service '{payload.name}' has been {'enabled' if payload.enabled else 'disabled'} via Web UI."
    )

    if payload.name == "extensions":
        ext_manager = ExtensionManager()
        if payload.enabled:
            log.info(
                "Extensions enabled via services center: Loading all extensions..."
            )
            ext_manager.load_all_extensions()
        else:
            log.info(
                "Extensions disabled via services center: Unloading all extensions..."
            )
            ext_manager.unload_all_extensions()

    elif payload.name == "desktop_streaming" and not payload.enabled:
        from ...services.desktop_streaming_service import desktop_streaming_service

        log.info(
            "Desktop streaming disabled via kill switch: Killing mirror engine and freeing encoders..."
        )
        await desktop_streaming_service.stop_engine()

    elif payload.name == "terminal" and not payload.enabled:
        from ...services.terminal_service import terminal_service

        log.info(
            "Terminal disabled via kill switch: Terminating all active shell processes..."
        )
        await terminal_service.terminate_all_sessions()

    elif payload.name == "input" and not payload.enabled:
        from ...services.adb_hub_service import adb_hub_service

        log.info("Remote input disabled via kill switch: Stopping OTG hub...")
        await adb_hub_service.stop()

    if hasattr(request.app.state, "mobile_manager"):
        from ...services.discovery_service import DiscoveryService

        await request.app.state.mobile_manager.broadcast(
            {
                "type": "UPDATE_STATE",
                "services": services,
                "server_id": DiscoveryService.generate_server_id(),
            }
        )

    return {"status": "success", "service": payload.name, "enabled": payload.enabled}
