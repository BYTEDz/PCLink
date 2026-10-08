# src/pclink/api_server/routers/applications.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...services.app_service import app_service

log = logging.getLogger(__name__)
router = APIRouter()


class Application(BaseModel):
    name: str
    command: str
    icon_path: Optional[str] = None
    is_custom: bool = False


class AppLaunchPayload(BaseModel):
    command: str


@router.get("", response_model=List[Application])
async def get_applications(force_refresh: bool = False):
    apps = await app_service.get_applications(force_refresh)
    return [Application(**a) for a in apps]


@router.post("/launch")
async def launch_application(payload: AppLaunchPayload):
    if not payload.command:
        raise HTTPException(status_code=400, detail="Empty command")
    await app_service.launch(payload.command)
    return {"status": "success"}


@router.get("/icon")
@router.get("/icon/")
async def get_application_icon(
    path: str = Query(...),
    token: Optional[str] = Query(None),
):
    if not path or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid path")

    log.debug(f"[AppsIcon] Request for: '{path}' (has_token: {bool(token)})")

    icon = await app_service.resolve_icon(path)
    if icon and os.path.exists(icon):
        lower = icon.lower()
        if lower.endswith(".svg"):
            media_type = "image/svg+xml"
        elif lower.endswith(".ico"):
            media_type = "image/x-icon"
        elif lower.endswith(".bmp"):
            media_type = "image/bmp"
        elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
            media_type = "image/jpeg"
        else:
            media_type = "image/png"

        return FileResponse(
            icon,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=604800"},
        )

    log.debug(f"[AppsIcon] 404: Icon not found for: '{path}'")
    raise HTTPException(status_code=404, detail="Icon not found")
