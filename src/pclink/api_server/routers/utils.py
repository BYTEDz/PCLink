# src/pclink/api_server/routers/utils.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from ...services.utility_service import utility_service

log = logging.getLogger(__name__)
router = APIRouter()


class ClipboardModel(BaseModel):
    text: str


class CommandModel(BaseModel):
    command: str


@router.post("/command")
async def run_command(payload: CommandModel):
    """Executes a shell command on the server."""
    if not payload.command:
        raise ValueError("Command cannot be empty.")
    await utility_service.run_command_detached(payload.command)
    return {"status": "command sent"}


@router.post("/clipboard")
async def set_clipboard(payload: ClipboardModel):
    """Sets the system clipboard text."""
    await utility_service.set_clipboard(payload.text)
    return {"status": "Clipboard updated"}


@router.get("/clipboard")
async def get_clipboard():
    """Gets the system clipboard text."""
    return {"text": await utility_service.get_clipboard()}


@router.get("/screenshot")
async def get_screenshot(
    max_width: Optional[int] = Query(None, ge=100, le=7680),
    max_height: Optional[int] = Query(None, ge=100, le=4320),
    quality: int = Query(80, ge=10, le=100),
    format: str = Query("webp", regex="^(webp|jpeg|jpg|png)$"),
    monitor: int = Query(1, ge=0, le=32),
):
    """Captures and returns a screenshot with optional custom sizing and compression."""
    fmt = format.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    try:
        data = await utility_service.get_screenshot(
            max_width=max_width,
            max_height=max_height,
            quality=quality,
            format=fmt,
            monitor=monitor,
        )
        return Response(content=data, media_type=f"image/{fmt}")
    except ImportError:
        raise HTTPException(
            status_code=500, detail="Required libraries (PIL) not available."
        )
    except Exception as e:
        log.error(f"Screenshot capture failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to capture screenshot.")
