# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import Dict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..core.config import config_manager
from ..core.extension_manager import ExtensionManager

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
        "files": {"title": "File Management", "icon": "file-text", "description": "Browse, upload, and download files."},
        "system": {"title": "System Control", "icon": "cpu", "description": "Manage processes, applications, and system power."},
        "info": {"title": "System Info", "icon": "info", "description": "Retrieve hardware and software info. (Basic version info is always shared for connectivity)"},
        "input": {"title": "Remote Input", "icon": "mouse-pointer", "description": "Remote control of mouse and keyboard."},
        "media": {"title": "Media Control", "icon": "play-circle", "description": "Control media playback and streaming."},
        "terminal": {"title": "Remote Terminal", "icon": "terminal", "description": "Direct shell access to your system."},
        "macros": {"title": "Macros", "icon": "command", "description": "Automate repetitive tasks with custom macros."},
        "extensions": {"title": "Extensions", "icon": "package", "description": "Third-party extension system functionality."},
        "applications": {"title": "Applications", "icon": "grid", "description": "View and launch installed system applications."},
        "utils": {"title": "Utility Tools", "icon": "tool", "description": "Screen capture and clipboard management."},
    }
    
    result = []
    for name, enabled in services.items():
        info = service_info.get(name, {"title": name.capitalize(), "icon": "box", "description": ""})
        result.append({
            "id": name,
            "title": info["title"],
            "icon": info["icon"],
            "description": info["description"],
            "enabled": enabled
        })
    
    return {"services": result}

@router.post("/toggle")
async def toggle_service(payload: ServiceToggle):
    """Enables or disables a specific service."""
    services = config_manager.get("services", {}).copy()
    if payload.name not in services:
        raise HTTPException(status_code=404, detail=f"Service '{payload.name}' not found.")
    
    services[payload.name] = payload.enabled
    config_manager.set("services", services)
    
    log.info(f"Service '{payload.name}' has been {'enabled' if payload.enabled else 'disabled'} via Web UI.")
    
    # Special handling for extensions
    if payload.name == "extensions":
        ext_manager = ExtensionManager()
        if payload.enabled:
            log.info("Extensions enabled via services center: Loading all extensions...")
            ext_manager.load_all_extensions()
        else:
            log.info("Extensions disabled via services center: Unloading all extensions...")
            ext_manager.unload_all_extensions()
            
    return {"status": "success", "service": payload.name, "enabled": payload.enabled}
