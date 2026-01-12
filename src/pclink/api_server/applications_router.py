# src/pclink/api_server/applications_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import platform
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services.app_service import app_service

log = logging.getLogger(__name__)
router = APIRouter()

class Application(BaseModel):
    name: str; command: str; icon_path: Optional[str] = None; is_custom: bool = False

class AppLaunchPayload(BaseModel): command: str

@router.get("", response_model=List[Application])
async def get_applications(force_refresh: bool = False):
    apps = await app_service.get_applications(force_refresh)
    return [Application(**a) for a in apps]

@router.post("/launch")
async def launch_application(payload: AppLaunchPayload):
    if not payload.command: raise HTTPException(400, "Empty command")
    try:
        await app_service.launch(payload.command)
        return {"status": "success"}
    except Exception as e:
        log.error(f"Launch failed: {e}")
        raise HTTPException(500, str(e))

@router.get("/icon")
async def get_application_icon(path: str):
    if not path or ".." in path: raise HTTPException(400, "Invalid path")
    
    if platform.system() == "Linux":
        icon = app_service.find_linux_icon(path)
        if icon: return FileResponse(icon)
        
    raise HTTPException(404, "Icon not found")