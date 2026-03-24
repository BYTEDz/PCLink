# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core.config import config_manager
from ...core.extension_manager import ExtensionManager

log = logging.getLogger(__name__)
router = APIRouter()


class ServiceToggle(BaseModel):
    name: str
    enabled: bool


@router.get("/")
async def get_services():
    """Returns the list of all services and their current status."""
    services = config_manager.get("services", {})

    # Enrich with descriptions and icons for the UI
    service_info = {
        "files_browse": {
            "title": "File Browser",
            "icon": "folder",
            "description": "Browse system files and view thumbnails.",
        },
        "files_download": {
            "title": "File Download",
            "icon": "download",
            "description": "Download files to the connected device.",
        },
        "files_upload": {
            "title": "File Upload",
            "icon": "upload",
            "description": "Upload files from the connected device.",
        },
        "files_delete": {
            "title": "File Deletion",
            "icon": "trash-2",
            "description": "Delete files and folders on the system.",
        },
        "processes": {
            "title": "Processes",
            "icon": "activity",
            "description": "View and manage running system processes.",
        },
        "power": {
            "title": "Power Control",
            "icon": "power",
            "description": "Shutdown, restart, or lock the system.",
        },
        "info": {
            "title": "System Status",
            "icon": "info",
            "description": "Monitor battery and hardware status.",
        },
        "mouse": {
            "title": "Remote Mouse",
            "icon": "mouse-pointer",
            "description": "Control system cursor and clicks.",
        },
        "keyboard": {
            "title": "Remote Type",
            "icon": "type",
            "description": "Send keyboard inputs and shortcuts.",
        },
        "media": {
            "title": "Media Control",
            "icon": "play-circle",
            "description": "Control playback and see media info.",
        },
        "volume": {
            "title": "System Volume",
            "icon": "volume-2",
            "description": "Adjust master volume and mute status.",
        },
        "terminal": {
            "title": "Terminal",
            "icon": "terminal",
            "description": "Direct shell access (High Risk).",
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
        "apps": {
            "title": "Applications",
            "icon": "grid",
            "description": "View and launch installed applications.",
        },
        "clipboard": {
            "title": "Clipboard",
            "icon": "clipboard",
            "description": "Read and write system clipboard.",
        },
        "screenshot": {
            "title": "Screen Capture",
            "icon": "camera",
            "description": "Capture system screen snapshots.",
        },
        "command": {
            "title": "Shell Command",
            "icon": "hash",
            "description": "Run detached shell commands.",
        },
        "wol": {
            "title": "Wake-on-LAN",
            "icon": "wifi",
            "description": "Check WOL status and MAC address.",
        },
    }

    result = []
    for name, enabled in services.items():
        info = service_info.get(
            name, {"title": name.capitalize(), "icon": "box", "description": ""}
        )
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
    services = config_manager.get("services", {}).copy()
    if payload.name not in services:
        raise HTTPException(
            status_code=404, detail=f"Service '{payload.name}' not found."
        )

    services[payload.name] = payload.enabled
    config_manager.set("services", services)

    log.info(
        f"Service '{payload.name}' has been {'enabled' if payload.enabled else 'disabled'} via Web UI."
    )

    # Special handling for extensions
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

    # Broadcast to all mobile devices
    if hasattr(request.app.state, "mobile_manager"):
        from ..services.discovery_service import DiscoveryService

        await request.app.state.mobile_manager.broadcast(
            {
                "type": "UPDATE_STATE",
                "services": services,
                "server_id": DiscoveryService.generate_server_id(),
            }
        )

    return {"status": "success", "service": payload.name, "enabled": payload.enabled}
