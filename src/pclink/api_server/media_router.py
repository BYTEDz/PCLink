# src/pclink/api_server/media_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import time
from enum import Enum
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services import media_service

router = APIRouter()
log = logging.getLogger(__name__)


class MediaStatus(str, Enum):
    NO_SESSION = "no_session"
    INACTIVE = "inactive"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"


class MediaInfoResponse(BaseModel):
    status: MediaStatus = Field(..., description="The current playback status.")
    control_level: Literal["full", "basic"] = Field(..., description="The level of control available.")
    title: Optional[str] = None
    artist: Optional[str] = None
    album_title: Optional[str] = None
    duration_sec: int = 0
    position_sec: int = 0
    server_timestamp: float = Field(..., description="The UTC timestamp when the media info was captured.")
    is_shuffle_active: Optional[bool] = None
    repeat_mode: Optional[str] = None
    source_app: Optional[str] = None


class MediaActionModel(BaseModel):
    action: str


class SeekModel(BaseModel):
    position_sec: int


@router.get("/", response_model=MediaInfoResponse)
async def get_media_info() -> MediaInfoResponse:
    """Provides information about the currently playing media."""
    data = await media_service.get_media_info()
    
    status_str = data.get("status", "STOPPED").upper()
    try:
        status_enum = MediaStatus(status_str.lower())
    except ValueError:
        status_enum = MediaStatus.STOPPED

    return MediaInfoResponse(
        status=status_enum,
        control_level=data.get("control_level", "basic"),
        title=data.get("title"),
        artist=data.get("artist"),
        album_title=data.get("album_title"),
        duration_sec=data.get("duration_sec", 0),
        position_sec=data.get("position_sec", 0),
        server_timestamp=time.time(),
        is_shuffle_active=data.get("is_shuffle_active"),
        repeat_mode=data.get("repeat_mode"),
        source_app=data.get("source_app")
    )


@router.post("/command", response_model=MediaInfoResponse)
async def media_command(payload: MediaActionModel) -> MediaInfoResponse:
    """Executes a media control command."""
    await media_service.media_command(payload.action)
    return await get_media_info()


@router.post("/seek", response_model=MediaInfoResponse)
async def seek_media_position(payload: SeekModel) -> MediaInfoResponse:
    """Seeks to a specific position in the media."""
    await media_service.seek_media(payload.position_sec)
    return await get_media_info()